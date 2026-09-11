"""影片庫的規則：誰看得到、誰刪得掉、一筆上傳要記下什麼。

View 層只負責把 request 拆開，判斷與寫入都在這裡，跟 analytics.recording
的分工一樣。
"""

import base64
import binascii
import logging
import os
from collections import Counter
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

from core.models import Role
from core.permissions import athlete_ids_visible_to
from video.models import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    TrainingVideo,
    VideoKind,
    VideoNote,
)

logger = logging.getLogger(__name__)

#: 縮圖是前端用 canvas 擷的第一格，寬度壓到 640 以內，通常只有幾十 KB。
MAX_POSTER_BYTES = 2 * 1024 * 1024


class VideoError(Exception):
    """使用者看得懂的錯誤——view 直接把訊息丟進 messages。"""


# --------------------------------------------------------------- 查詢與權限


def visible_videos(user, athlete=None):
    """這個人看得到的影片。運動員只有自己的，教練有旗下的，管理員全部。"""
    qs = (
        TrainingVideo.objects.select_related(
            "athlete__user", "uploaded_by", "record__item", "activity"
        )
        .annotate(note_count=Count("notes"))
        .filter(athlete_id__in=athlete_ids_visible_to(user))
    )
    if athlete is not None:
        qs = qs.filter(athlete=athlete)
    return qs


def get_video(user, pk):
    video = visible_videos(user).filter(pk=pk).first()
    if video is None:
        raise VideoError(_("找不到這條影片，或你沒有權限看。"))
    return video


def may_delete(user, video):
    """自己傳的片自己刪得掉；教練與管理員刪得掉旗下運動員的片。"""
    if user.is_superuser or user.role in (Role.COACH, Role.ADMIN):
        return True
    return video.uploaded_by_id == user.id


def may_annotate(user, video):
    """看得到就批註得了——運動員也常自己標「這裡卡住」給教練看。"""
    return video.athlete_id in set(athlete_ids_visible_to(user))


# --------------------------------------------------------------- 搜尋

#: 搜尋欄下面最多列幾個熱搜詞。再多就佔掉一整行，掃過去反而找不到。
HOT_TERM_LIMIT = 8


def search_videos(videos, query):
    """在已經取出來的清單上比對關鍵字。

    一個運動員的片通常幾十條，整批都在手上了，再回資料庫做 icontains 不划算。
    比對標題、說明、類別名稱、綁到的項目，還有日期——打「2026-09」就篩得出九月。
    """
    needle = (query or "").strip().casefold()
    if not needle:
        return list(videos)
    return [v for v in videos if needle in _haystack(v)]


def _haystack(video):
    bits = [
        video.title,
        video.note,
        str(video.get_kind_display()),
        video.linked_label,
        video.date.isoformat(),
    ]
    return " ".join(b for b in bits if b).casefold()


def hot_terms(videos, limit=HOT_TERM_LIMIT):
    """熱搜詞：這批片綁到的項目名稱，出現次數多的排前面。

    不寫死「100 米」這類字眼——每隊練的東西不一樣，讓資料自己長出來；
    練跳遠的隊伍看到的就會是跳遠的項目。
    """
    counts = Counter()
    for video in videos:
        name = ""
        if video.record_id:
            name = video.record.item.name
        elif video.activity_id:
            name = video.activity.name
        if name:
            counts[name.strip()] += 1
    return [name for name, _n in counts.most_common(limit)]


# --------------------------------------------------------------- 上傳


def check_filename(filename):
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise VideoError(
            _("只收 %(v0)s 這幾種格式（你傳的是 .%(v1)s）。")
            % {"v0": "、".join(ALLOWED_EXTENSIONS), "v1": ext or "?"}
        )
    return ext


def check_size(size):
    if size and size > MAX_UPLOAD_BYTES:
        raise VideoError(
            _("影片太大了（%(v0)s MB），單檔上限 %(v1)s MB。請剪短一點或降低畫質再傳。")
            % {"v0": int(size / 1024 / 1024), "v1": int(MAX_UPLOAD_BYTES / 1024 / 1024)}
        )


def _decimal(raw, places="0.01"):
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw)).quantize(Decimal(places))
    except (InvalidOperation, ValueError):
        return None


def _int(raw):
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _poster_file(data_url):
    """把前端 canvas 擷下來的 data URL 轉成可以存的檔案。

    這只是張封面圖，讓影片庫不要整排黑框——跟動作分析無關。
    """
    if not data_url or "," not in data_url:
        return None
    header, _sep, payload = data_url.partition(",")
    if "image/jpeg" not in header and "image/png" not in header:
        return None
    try:
        raw = base64.b64decode(payload)
    except (binascii.Error, ValueError):
        return None
    if not raw or len(raw) > MAX_POSTER_BYTES:
        return None
    return ContentFile(raw, name="poster.jpg")


def save_video(user, athlete, data, upload=None):
    """建立一筆影片紀錄。

    `upload` 是經 Django 上傳的檔案（本機開發）；R2 開著時檔案已經由瀏覽器
    直傳上去了，這裡只會拿到 data["remote_key"]。兩條路只能走一條。
    """
    remote_key = (data.get("remote_key") or "").strip()
    if upload is None and not remote_key:
        raise VideoError(_("沒有收到影片檔，請重新選一次。"))

    if upload is not None:
        check_filename(upload.name)
        check_size(upload.size)
        size = upload.size
    else:
        check_filename(remote_key)
        size = _int(data.get("size_bytes")) or 0
        check_size(size)

    kind = data.get("kind")
    if kind not in VideoKind.values:
        kind = VideoKind.STRENGTH

    video = TrainingVideo(
        athlete=athlete,
        date=data.get("date") or date_cls.today(),
        kind=kind,
        title=(data.get("title") or "").strip()[:120],
        note=(data.get("note") or "").strip(),
        remote_key=remote_key,
        duration_sec=_decimal(data.get("duration_sec")),
        size_bytes=size,
        width=_int(data.get("width")),
        height=_int(data.get("height")),
        uploaded_by=user,
    )
    _attach_links(video, athlete, data)
    if upload is not None:
        video.file = upload
    poster = _poster_file(data.get("poster"))
    if poster is not None:
        video.poster = poster
    video.save()
    return video


def _attach_links(video, athlete, data):
    """選擇性關聯：id 對不上或不是這位運動員的，就當作沒填，不要報錯。"""
    from analytics.models import MetricRecord
    from training.models import SessionActivity

    record_id = _int(data.get("record"))
    if record_id:
        video.record = MetricRecord.objects.filter(pk=record_id, athlete=athlete).first()

    activity_id = _int(data.get("activity"))
    if activity_id:
        video.activity = SessionActivity.objects.filter(
            pk=activity_id, session__athlete=athlete
        ).first()


def delete_video(user, video):
    if not may_delete(user, video):
        raise VideoError(_("這條影片不是你上傳的，只有上傳者或教練刪得掉。"))
    video.drop_file()
    video.delete()


# --------------------------------------------------------------- 批註


#: 分析工具存進批註的東西。前端送什麼進來都要當作不可信，逐項洗過再存。
TOOL_KINDS = ("timing", "steps", "draw")
SHAPE_TYPES = ("line", "angle", "hline", "vline", "free")
MAX_TAPS = 400          # 400 步夠記完一趟 400 米
MAX_SHAPES = 60
MAX_POINTS = 300        # 自由手繪一筆的點數上限


def add_note(user, video, at_sec, body, end_sec=None, data=None):
    """加一條批註。

    `end_sec` 有值代表量的是一段時間（A→B）；`data` 是分析工具的量測結果，
    格式見 `_clean_data`。兩個都留空就是單純釘在某一秒的文字批註。
    """
    if not may_annotate(user, video):
        raise VideoError(_("你沒有權限在這條影片上批註。"))
    body = (body or "").strip()
    if not body:
        raise VideoError(_("批註不能是空的。"))
    at = _decimal(at_sec)
    if at is None or at < 0:
        at = Decimal("0.00")

    end = _decimal(end_sec)
    if end is not None and end < at:
        at, end = end, at          # 使用者先標了 B 才標 A，換過來就好

    return VideoNote.objects.create(
        video=video, at_sec=at, end_sec=end, body=body,
        data=_clean_data(data), author=user,
    )


def _clean_data(raw):
    """把前端送來的量測資料洗乾淨。

    座標一律存成 0～1 的比例而不是像素，這樣同一條線在手機與電腦上、
    在不同解析度的影片上都畫在同一個位置。
    """
    if not isinstance(raw, dict):
        return {}
    kind = raw.get("kind")
    if kind not in TOOL_KINDS:
        return {}
    out = {"kind": kind}

    if kind == "steps":
        taps = [t for t in (_float(v) for v in _as_list(raw.get("taps"))) if t is not None]
        out["taps"] = [round(t, 3) for t in taps[:MAX_TAPS]]
    elif kind == "timing":
        distance = _float(raw.get("distance_m"))
        if distance and 0 < distance <= 10000:
            out["distance_m"] = round(distance, 2)

    shapes = []
    for shape in _as_list(raw.get("shapes"))[:MAX_SHAPES]:
        cleaned = _clean_shape(shape)
        if cleaned:
            shapes.append(cleaned)
    if shapes:
        out["shapes"] = shapes
    return out


def _clean_shape(shape):
    if not isinstance(shape, dict):
        return None
    kind = shape.get("t")
    if kind not in SHAPE_TYPES:
        return None
    points = []
    for point in _as_list(shape.get("p"))[:MAX_POINTS]:
        pair = _as_list(point)
        if len(pair) != 2:
            continue
        x, y = _float(pair[0]), _float(pair[1])
        if x is None or y is None:
            continue
        # 夾在畫面內：超出範圍的點畫出去只會變成看不見的線
        points.append([round(min(max(x, 0.0), 1.0), 4), round(min(max(y, 0.0), 1.0), 4)])
    if not points:
        return None
    return {"t": kind, "p": points}


def _as_list(value):
    return value if isinstance(value, list) else []


def _float(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    # NaN / inf 進了 JSONField 會讓之後讀出來的頁面直接壞掉
    return value if value == value and abs(value) != float("inf") else None


def delete_note(user, note):
    """自己寫的批註自己刪；教練與管理員可以刪任何一條。"""
    if not (
        user.is_superuser
        or user.role in (Role.COACH, Role.ADMIN)
        or note.author_id == user.id
    ):
        raise VideoError(_("這條批註不是你寫的。"))
    note.delete()


# --------------------------------------------------------------- 關聯選單


def link_choices(athlete, on_date):
    """上傳表單上「這條片對應哪一項」的選單內容。

    只撈當天的，因為片幾乎都是當天拍的；真要綁別天的，存好之後在詳情頁再改。
    """
    from analytics.models import MetricRecord
    from training.models import SessionActivity

    records = (
        MetricRecord.objects.select_related("item")
        .filter(athlete=athlete, date=on_date)
        .order_by("item__name", "set_no", "id")
    )
    activities = (
        SessionActivity.objects.select_related("session")
        .filter(session__athlete=athlete, session__date=on_date)
        .order_by("block", "order", "id")
    )
    return {
        "records": [(r.id, _record_label(r)) for r in records],
        "activities": [(a.id, f"[{a.get_block_display()}] {a.name}") for a in activities],
    }


def _record_label(record):
    bits = [record.item.name]
    if record.set_label:
        bits.append(str(record.set_label))
    if record.value is not None:
        bits.append(f"{record.value}{record.item.unit}")
    elif record.weight_kg is not None:
        bits.append(f"{record.weight_kg}kg")
    return " · ".join(bits)

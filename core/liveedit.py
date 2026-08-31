"""可直接點格子改內容的欄位登錄表（inline edit）。

一個地方定義「哪些欄位可以在畫面上按下去改」、「值要怎麼轉」、「誰改得動」，
HTML 前端（core.views.inline_edit）和之後要接的 API 都走同一份規則，
才不會出現某一頁擋得住、另一頁擋不住的情況。

權限的骨幹只有兩條：
  1. 看不到這名運動員的資料 → 什麼都不能改（沿用 athlete_ids_visible_to）。
  2. 不是自己寫的東西 → 不能改（管理員例外，要有人收得了爛攤子）。
"""

from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from core.models import Role, SessionStatus, SessionType, program_type_choices
from core.permissions import athlete_ids_visible_to
from planning.models import SessionNote, TrainingSession
from training.models import BlockType, SessionActivity, StrengthSet, TrackSet


class EditDenied(Exception):
    """使用者沒有權限改這一格。"""


class EditError(Exception):
    """值本身不合法。"""


# ------------------------------------------------------------------ 值的轉換


def _text(value, max_length=None):
    value = (value or "").strip()
    if max_length and len(value) > max_length:
        raise EditError(f"最多 {max_length} 個字。")
    return value


def _int(value, low=None, high=None, allow_blank=False):
    value = (value or "").strip()
    if not value:
        if allow_blank:
            return None
        raise EditError("要填一個數字。")
    try:
        number = int(float(value))
    except ValueError:
        raise EditError(f"「{value}」不是數字。")
    if low is not None and number < low:
        raise EditError(f"不能小於 {low}。")
    if high is not None and number > high:
        raise EditError(f"不能大於 {high}。")
    return number


def _decimal(value, allow_blank=True):
    value = (value or "").strip()
    if not value:
        if allow_blank:
            return None
        raise EditError("要填一個數字。")
    try:
        return Decimal(value)
    except InvalidOperation:
        raise EditError(f"「{value}」不是數字。")


def _date(value):
    value = (value or "").strip()
    if not value:
        raise EditError("要選一個日期。")
    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        raise EditError("日期格式要是 YYYY-MM-DD。")


def _choice(value, choices):
    value = (value or "").strip()
    valid = {v for v, _ in choices}
    if value not in valid:
        raise EditError("不認得的選項。")
    return value


# --------------------------------------------------------------- 欄位定義


class Field:
    """一個可編輯欄位：怎麼轉值、用什麼控制項編輯、誰有資格改。"""

    def __init__(self, kind="text", label="", coerce=None, choices=None, owner="writer"):
        self.kind = kind          # text / textarea / number / date / select / rating
        self.label = label
        self.coerce = coerce or (lambda v: _text(v))
        self.choices = choices or []
        self.owner = owner        # writer / athlete / coach

    def clean(self, raw):
        return self.coerce(raw)


SLOT_CHOICES = [("AM", "上午"), ("PM", "下午")]


SESSION_FIELDS = {
    "title": Field("text", "課表名稱", lambda v: _text(v, 150)),
    "description": Field("textarea", "課表概要", lambda v: _text(v)),
    "date": Field("date", "日期", _date),
    "time_slot": Field("select", "時段", lambda v: _choice(v, SLOT_CHOICES), SLOT_CHOICES),
    "session_type": Field(
        "select",
        "類別",
        lambda v: _choice(v, list(SessionType.choices)),
        program_type_choices(),
    ),
    "planned_duration_min": Field("number", "計劃時長", lambda v: _int(v, 0, 600)),
    "actual_duration_min": Field(
        "number", "實際時長", lambda v: _int(v, 0, 600, allow_blank=True), owner="athlete"
    ),
    "session_rpe": Field(
        "number", "課後 RPE", lambda v: _int(v, 1, 10, allow_blank=True), owner="athlete"
    ),
    "completion_pct": Field("number", "完成度", lambda v: _int(v, 0, 100), owner="athlete"),
    "status": Field(
        "select",
        "狀態",
        lambda v: _choice(v, SessionStatus.choices),
        list(SessionStatus.choices),
        owner="athlete",
    ),
    "satisfaction": Field(
        "rating", "訓練滿意度", lambda v: _int(v, 1, 5, allow_blank=True), owner="athlete"
    ),
    "athlete_feedback": Field("textarea", "運動員反饋", lambda v: _text(v), owner="athlete"),
    "coach_comment": Field("textarea", "教練評語", lambda v: _text(v), owner="coach"),
}

ACTIVITY_FIELDS = {
    "name": Field("text", "活動名稱", lambda v: _text(v, 120)),
    "block": Field(
        "select", "區塊", lambda v: _choice(v, BlockType.choices), list(BlockType.choices)
    ),
    "order": Field("number", "排序", lambda v: _int(v, 1, 99)),
    "sets": Field("text", "組數", lambda v: _text(v, 30)),
    "reps": Field("text", "次數", lambda v: _text(v, 30)),
    "distance": Field("text", "距離", lambda v: _text(v, 30)),
    "weight": Field("text", "重量", lambda v: _text(v, 40)),
    "intensity": Field("text", "強度", lambda v: _text(v, 40)),
    "rest": Field("text", "休息時間", lambda v: _text(v, 80)),
    "key_points": Field("textarea", "訓練要點", lambda v: _text(v)),
    "note": Field("textarea", "當日備注", lambda v: _text(v)),
    "satisfaction": Field("rating", "滿意度", lambda v: _int(v, 1, 5, allow_blank=True)),
}

NOTE_FIELDS = {"body": Field("textarea", "內容", lambda v: _text(v))}

TRACKSET_FIELDS = {
    "description": Field("text", "內容", lambda v: _text(v, 150)),
    "distance_m": Field("number", "距離 (m)", lambda v: _int(v, 0, 100000)),
    "reps": Field("number", "趟數", lambda v: _int(v, 1, 200)),
    "sets": Field("number", "組數", lambda v: _int(v, 1, 200)),
    "target_time_sec": Field("number", "目標時間", _decimal),
    "actual_time_sec": Field("number", "實際時間", _decimal, owner="athlete"),
    "rest_between_reps_sec": Field("number", "趟間休息", lambda v: _int(v, 0, 36000)),
    "rest_between_sets_sec": Field("number", "組間休息", lambda v: _int(v, 0, 36000)),
    "intensity_pct": Field("number", "強度 %", _decimal),
    "rpe": Field("number", "RPE", lambda v: _int(v, 1, 10, allow_blank=True), owner="athlete"),
    "technical_focus": Field("textarea", "技術重點", lambda v: _text(v)),
}

STRENGTHSET_FIELDS = {
    "set_number": Field("number", "第幾組", lambda v: _int(v, 1, 99)),
    "reps": Field("number", "次數", lambda v: _int(v, 0, 999)),
    "weight_kg": Field("number", "重量 (kg)", lambda v: _decimal(v, allow_blank=False)),
    "target_1rm_pct": Field("number", "目標 %1RM", _decimal),
    "rest_sec": Field("number", "組間休息", lambda v: _int(v, 0, 36000)),
    "rir": Field("number", "RIR", lambda v: _int(v, 0, 10, allow_blank=True), owner="athlete"),
    "rpe": Field("number", "RPE", lambda v: _int(v, 1, 10, allow_blank=True), owner="athlete"),
    "note": Field("text", "備註", lambda v: _text(v, 150)),
}

#: data-edit="<key>:<pk>:<field>" 裡的 <key> 對應表
REGISTRY = {
    "session": (TrainingSession, SESSION_FIELDS),
    "activity": (SessionActivity, ACTIVITY_FIELDS),
    "note": (SessionNote, NOTE_FIELDS),
    "trackset": (TrackSet, TRACKSET_FIELDS),
    "strengthset": (StrengthSet, STRENGTHSET_FIELDS),
}


# ------------------------------------------------------------------- 權限


def session_of(obj):
    """任何一個可編輯物件都掛在某一堂課底下。"""
    if isinstance(obj, TrainingSession):
        return obj
    return obj.session


def is_admin(user):
    return bool(user.is_superuser or user.role == Role.ADMIN)


def writer_of(obj):
    """誰「寫下」了這筆資料。"""
    for attr in ("created_by", "author"):
        writer = getattr(obj, attr, None)
        if writer is not None:
            return writer
    if isinstance(obj, TrainingSession):
        # 舊資料沒有 created_by：派發教練優先，否則算運動員自訂
        if obj.assigned_by and obj.assigned_by.user_id:
            return obj.assigned_by.user
        return obj.athlete.user
    return writer_of(session_of(obj))


def key_for(obj):
    for key, (model, _fields) in REGISTRY.items():
        if isinstance(obj, model):
            return key
    return ""


def _coaches_this(session, user):
    """這名教練帶不帶得動這堂課（帶這名運動員、或是派發者）。"""
    if session.assigned_by and session.assigned_by.user_id == user.id:
        return True
    coach = session.athlete.coach
    return coach is not None and coach.user_id == user.id


def can_edit(obj, user, field_name=None):
    """這個人能不能改這一格。field_name 留空就是問「這筆資料整體」。"""
    if not user.is_authenticated:
        return False

    session = session_of(obj)
    if session.athlete_id not in set(athlete_ids_visible_to(user)):
        return False
    if is_admin(user):
        return True

    spec = None
    if field_name:
        _model, fields = REGISTRY.get(key_for(obj), (None, {}))
        spec = fields.get(field_name)

    owner = spec.owner if spec else "writer"
    if owner == "athlete":
        # 練的人自己填的欄位（RPE、實際時長、滿意度、反饋…）
        return session.athlete.user_id == user.id
    if owner == "coach":
        return user.role == Role.COACH and _coaches_this(session, user)

    # 預設：只有寫下這筆的人改得動
    writer = writer_of(obj)
    return writer is not None and writer.id == user.id


def can_delete(obj, user):
    """刪一整筆（活動、記事）的規則跟「改自己寫的東西」一樣。"""
    if not user.is_authenticated:
        return False
    if session_of(obj).athlete_id not in set(athlete_ids_visible_to(user)):
        return False
    if is_admin(user):
        return True
    writer = writer_of(obj)
    return writer is not None and writer.id == user.id


# ------------------------------------------------------------------ 套用


def apply_edit(user, key, pk, field_name, raw_value):
    """把一格的新值寫進去，回傳 (物件, 顯示字串)。"""
    if key not in REGISTRY:
        raise EditError("不認得的欄位群組。")
    model, fields = REGISTRY[key]
    if field_name not in fields:
        raise EditError(f"「{field_name}」不是可編輯欄位。")

    try:
        obj = model.objects.get(pk=pk)
    except model.DoesNotExist:
        raise EditError("這筆資料已經不在了，重新整理看看。")

    if not can_edit(obj, user, field_name):
        raise EditDenied(deny_reason(obj, user, fields[field_name]))

    value = fields[field_name].clean(raw_value)
    setattr(obj, field_name, value)
    try:
        obj.full_clean(exclude=[f.name for f in obj._meta.fields if f.name != field_name])
    except ValidationError as exc:
        raise EditError("；".join(m for msgs in exc.message_dict.values() for m in msgs))

    obj.save()
    _after_save(obj, field_name)
    return obj, display_value(obj, field_name)


def deny_reason(obj, user, spec):
    if spec is not None and spec.owner == "athlete":
        return "這一格由運動員本人填寫。"
    if spec is not None and spec.owner == "coach":
        return "這一格由教練填寫。"
    writer = writer_of(obj)
    who = (writer.get_full_name() or writer.username) if writer else "其他人"
    return f"這是 {who} 寫下的內容，只有本人（或管理員）能改。"


def _after_save(obj, field_name):
    """改完之後要跟著動的東西：換日期要重掛週計劃、動到負荷要重算。"""
    session = session_of(obj)

    if isinstance(obj, TrainingSession) and field_name == "date":
        from core.views import _microcycle_for

        micro = _microcycle_for(session.athlete, session.date)
        if micro != session.microcycle:
            session.microcycle = micro
            session.save(update_fields=["microcycle", "updated_at"])

    if field_name in {"session_rpe", "actual_duration_min", "date", "status"}:
        from analytics import services as an

        try:
            an.rebuild_daily_load(session.athlete, session.date)
            an.rebuild_weekly_summary(session.athlete, an.monday_of(session.date))
        except Exception:  # 重算失敗不該讓使用者剛才的編輯跟著失敗
            pass

    if session.microcycle_id:
        session.microcycle.recalculate_actual_load()


def display_value(obj, field_name):
    """回寫給畫面用的顯示字串（空值統一顯示成 —）。"""
    getter = getattr(obj, f"get_{field_name}_display", None)
    value = getter() if getter else getattr(obj, field_name)
    if value in (None, ""):
        return "—"
    if isinstance(value, date_cls):
        return value.isoformat()
    return str(value)

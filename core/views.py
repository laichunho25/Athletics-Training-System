"""HTML 前端 views（與 DRF API 並存，共用 services 層）。"""

import calendar as pycalendar
import json
import logging
import re
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Max, Min, Q, Value
from django.utils import timezone, translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.db.models.functions import Coalesce, Greatest
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils.translation import gettext_lazy as _

from accounts.body_brands import BRAND_PRESETS, GENERIC, detect_brand, form_presets
from accounts.body_import import parse_body_composition
from accounts.models import AthleteProfile, BodyMetricLog, CoachProfile, Event, User
from analytics import body_strength as bs
from analytics import dimensions as dim
from analytics import services as an
from analytics.models import (
    STRENGTH_UNITS,
    MetricCategory,
    MetricDomain,
    MetricItem,
    MetricRecord,
    TrackMethod,
    TrainingStatus,
    block_choices,
    domain_pairs_for_session_type,
    domains_for_session_type,
    ensure_builtin_items,
    item_for_name,
    metric_category_for_activity,
    pinned_items,
    rename_item,
    session_types_for_domain,
    set_item_unit,
    toggle_pin,
    track_item_for,
    track_method_choices,
)
from analytics.recording import (
    RecordError,
    create_records,
    edit_message,
    ensure_item_for_activity,
    move_record,
    plan_distance,
    resequence,
    session_domain_tables,
    session_records,
    update_records,
)
from core import i18n as core_i18n
from core import liveedit
from core.athlete_context import athlete_switcher, current_athlete, remember, remembered_id
from core.glossary import all_terms, as_groups
from core.models import (
    PHASE_GUIDE,
    AthleteStatus,
    PhaseType,
    Role,
    SessionStatus,
    SessionType,
    program_type_choices,
)
from core.permissions import athlete_ids_visible_to
from injury import services as inj
from injury.models import (
    TRAINING_MODE_GUIDE,
    DayAction,
    Injury,
    PainLog,
    TrainingMode,
    TreatmentEffect,
    TreatmentLog,
    TreatmentStage,
    TreatmentType,
)
from nutrition import services as nu
from nutrition import vision as nuvision
from nutrition.models import (
    MealLog,
    MealType,
    NutritionGoal,
    NutritionTarget,
    RecoveryLog,
    RecoveryMethod,
)
from planning.models import (
    Competition,
    CompetitionLevel,
    Macrocycle,
    Microcycle,
    Phase,
    NoteKind,
    SessionNote,
    ProjectAssignment,
    TrainingSession,
    project_athletes,
    projects_for,
    weeks_between,
)
from programs.models import Application, Project
from programs.services import ImportError_ as ProgramImportError
from programs.services import annotate_matches, find_existing_athlete, import_application
from training.models import (
    ActivityCategory,
    ActivityDefinition,
    BlockProgram,
    BlockProgramItem,
    BlockType,
    Discipline,
    Exercise,
    LibraryStatus,
    MovementKind,
    SessionActivity,
    SportType,
)
from training.library import (
    can_edit,
    ensure_activity_library,
    library_catalog,
    is_library_admin,
    library_groups,
    library_tree,
    pending_submissions,
    visible_definitions,
)
from video import services as vsvc
from video import storage as vstorage
from video.models import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    VideoKind,
    VideoNote,
    make_key,
)

logger = logging.getLogger(__name__)


def jdump(value):
    """圖表資料轉 JSON；夾在裡面的翻譯字串一律當成文字處理。"""
    return json.dumps(value, default=str)


#: 「多項目一起分析」一次最多放幾個項目——圖上超過這個數量就看不出東西了，
#: 也順便擋掉手改網址塞一大串 items 的情況。
MULTI_ITEM_LIMIT = 8

def csrf_failure(request, reason=""):
    """CSRF 檢查失敗時的說明頁（settings.CSRF_FAILURE_VIEW）。

    最常見的情境是登入頁在分頁裡放了太久、或瀏覽器留著舊網域的 csrftoken，
    第一次送出就被擋掉——重新整理拿一個新 token 就會過。
    預設的 403 頁講的是英文的 CSRF 術語，使用者只會看到「死 error」，
    所以這裡換成看得懂的指示，並把原因寫進 log 方便追。
    """
    logger.warning("CSRF 檢查失敗：%s（path=%s）", reason, request.path)
    return render(
        request,
        "web/csrf_failure.html",
        {"reason": reason, "retry_to": request.path},
        status=403,
    )


def healthz(request):
    """Render 健康檢查端點：不碰資料庫、不強制轉 https，永遠回 200。"""
    return HttpResponse("ok", content_type="text/plain")


@require_POST
def set_language(request):
    """切換介面語言。

    登入的人存回帳號（換裝置也跟著走），未登入的人只存 cookie。
    兩邊都寫 cookie，登出之後畫面也不會突然跳回另一種語言。
    """
    lang = core_i18n.supported(request.POST.get("language"))
    nxt = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/"
    if not url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        nxt = "/"
    response = redirect(nxt)
    if lang:
        if request.user.is_authenticated:
            User.objects.filter(pk=request.user.pk).update(language=lang)
        translation.activate(lang)
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            lang,
            max_age=settings.LANGUAGE_COOKIE_AGE,
            samesite="Lax",
        )
    return response


RISK_CSS = {
    "OPTIMAL": ("b-green", "c-green"),
    "UNDER": ("b-blue", "c-blue"),
    "ELEVATED": ("b-yellow", "c-yellow"),
    "HIGH": ("b-red", "c-red"),
    "INSUFFICIENT": ("b-dim", "c-dim"),
}


def _current_athlete(request):
    """目前檢視的運動員（?athlete= → session 記住的 → 名單第一位）。

    實作搬到 core.athlete_context，樣板外框（頂欄切換器、側欄連結）用的是同一份，
    所以換頁一定跟著同一位人。
    """
    return current_athlete(request)


def _athlete_switcher(request):
    """教練用的運動員切換清單。"""
    return athlete_switcher(request)


def landing(request):
    """公開首頁——不需登入，介紹 ATM 的紀錄與分析能力，並提供短跑術語表與登入入口。"""
    return render(
        request,
        "site/landing.html",
        {"glossary": as_groups(), "glossary_count": len(all_terms())},
    )


@login_required
def home(request):
    """登入後的分流入口（/app/）。"""
    if request.user.role == Role.COACH:
        return redirect("web:athlete_list")
    return redirect("web:dashboard")


# ------------------------------------------------------------------ 儀表板


@login_required
def dashboard(request):
    if (
        request.user.role == Role.COACH
        and not request.GET.get("athlete")
        and remembered_id(request) is None
    ):
        # 教練第一次進來先看列表挑人；挑過之後直接回到上一位的狀態總覽
        return redirect("web:athlete_list")

    athlete = _current_athlete(request)
    if athlete is None:
        return render(request, "web/no_athlete.html", {"page": "dashboard"})

    d = an.athlete_dashboard(athlete)
    acwr = d["acwr"]
    badge, color = RISK_CSS[acwr["risk_flag"]]

    week_start = an.monday_of(date.today())
    week_sessions = TrainingSession.objects.filter(
        athlete=athlete, date__gte=week_start, date__lte=week_start + timedelta(days=6)
    ).order_by("date", "time_slot")

    prog = an.weekly_load_progression(athlete, 8)

    macro = athlete.macrocycles.filter(is_active=True).first()

    return render(
        request,
        "web/dashboard.html",
        {
            "page": "dashboard",
            "athlete": athlete,
            "athletes": _athlete_switcher(request),
            # 「距離目標賽事 / 目前分期」兩張卡片的編輯用資料
            "macro": macro,
            "phases": macro.phases.all() if macro else [],
            "competitions": athlete_competitions(athlete).filter(
                date__gte=date.today() - timedelta(days=30)
            ),
            # 熱身賽要挑「為了哪一場重要比賽而備戰」，所以只列重要比賽
            "key_competitions": athlete_competitions(athlete).filter(
                is_warmup=False, date__gte=date.today()
            ),
            "competition_levels": CompetitionLevel.choices,
            "phase_types": PhaseType.choices,
            "can_edit_plan": _can_edit_plan(request.user, athlete),
            "today_iso": date.today().isoformat(),
            "d": d,
            "acwr": acwr,
            "acwr_badge": badge,
            "acwr_color": color,
            "readiness": d["readiness"],
            "week_sessions": week_sessions,
            "week_start": week_start,
            "chart_labels": jdump([p["label"] for p in prog]),
            "chart_load": jdump([p["total_load"] for p in prog]),
            "chart_acwr": jdump([p["acwr"] for p in prog]),
            "injuries": athlete.active_injuries,
            **_body_context(athlete),
        },
    )


# ------------------------------------------------------------ 體組成 / 體測

#: 體組成表單上可以填的數值欄位 → 是不是整數
BODY_NUMBER_FIELDS = {
    "weight_kg": False,
    "body_fat_pct": False,
    "muscle_mass_kg": False,
    "muscle_mass_index": True,
    "bmi": False,
    "muscle_quality_score": True,
    "visceral_fat_level": False,
    "bone_mass_kg": False,
    "body_water_pct": False,
    "bmr_kcal": True,
    "metabolic_age": True,
    # InBody / HOWBODY 報告紙才有的項目
    "body_fat_mass_kg": False,
    "fat_free_mass_kg": False,
    "tbw_liters": False,
    "protein_kg": False,
    "mineral_kg": False,
    "whr": False,
    "ecw_tbw": False,
    "score": True,
    "muscle_arm_r": False,
    "muscle_arm_l": False,
    "muscle_leg_r": False,
    "muscle_leg_l": False,
    "muscle_trunk": False,
    "fat_arm_r": False,
    "fat_arm_l": False,
    "fat_leg_r": False,
    "fat_leg_l": False,
    "fat_trunk": False,
    "mq_arm_r": True,
    "mq_arm_l": True,
    "mq_leg_r": True,
    "mq_leg_l": True,
    "resting_hr": True,
    "hrv": True,
}

#: 走勢圖上畫哪幾條線：(欄位, 圖例, 顏色, 用哪一個 y 軸)
BODY_CHART_SERIES = [
    ("weight_kg", _("體重 (kg)"), "#ff6b35", "y"),
    ("muscle_mass_kg", _("肌肉量 (kg)"), "#3fb950", "y"),
    ("body_fat_pct", _("體脂肪率 (%)"), "#58a6ff", "y1"),
    ("body_water_pct", _("體水分率 (%)"), "#a371f7", "y1"),
]

#: 「與上一次比較」要看的欄位：(欄位, 中文, 小數位, 變多算不算好事)
BODY_DELTA_FIELDS = [
    ("weight_kg", _("體重"), 1, None),
    ("body_fat_pct", _("體脂肪率"), 1, False),
    ("muscle_mass_kg", _("肌肉量"), 2, True),
    ("visceral_fat_level", _("內臟脂肪等級"), 1, False),
]


def _body_context(athlete):
    """狀態總覽頁「一般資料 + 體組成」區塊的資料。"""
    history = list(athlete.body_metrics.order_by("-date")[:24])
    latest = history[0] if history else None
    previous = history[1] if len(history) > 1 else None

    # 走勢圖由舊排到新；缺值留 None，讓 Chart.js 用 spanGaps 接起來
    rows = list(reversed(history))
    chart = {
        "labels": jdump([r.date.strftime("%m/%d") for r in rows]),
        "series": jdump(
            [
                {
                    "label": label,
                    "color": color,
                    "axis": axis,
                    "data": [
                        float(getattr(r, field)) if getattr(r, field) is not None else None
                        for r in rows
                    ],
                }
                for field, label, color, axis in BODY_CHART_SERIES
                if any(getattr(r, field) is not None for r in rows)
            ]
        ),
    }

    return {
        "body_latest": latest,
        "body_previous": previous,
        "body_deltas": _body_deltas(latest, previous),
        "body_history": history,
        "body_chart": chart,
        "body_today_iso": date.today().isoformat(),
        "body_brand_presets": jdump(form_presets()),
        "body_brand_choices": [(key, str(p["name"])) for key, p in BRAND_PRESETS.items()],
        "body_brand_default": latest.brand if latest and latest.brand else GENERIC,
    }


def _body_deltas(latest, previous):
    """最新一筆跟上一筆的差；沒有上一筆就沒得比。"""
    if latest is None or previous is None:
        return []
    rows = []
    for field, label, digits, higher_is_better in BODY_DELTA_FIELDS:
        now, before = getattr(latest, field), getattr(previous, field)
        if now is None or before is None:
            continue
        diff = round(float(now) - float(before), digits)
        if higher_is_better is None or diff == 0:
            color = "c-dim"
        else:
            color = "c-green" if (diff > 0) == higher_is_better else "c-red"
        rows.append(
            {
                "label": label,
                "diff": f"{diff:+.{digits}f}",
                "color": color,
                "since": previous.date,
            }
        )
    return rows


def _body_value(raw, as_int):
    """表單上的一格：留空＝None，填了就必須是數字。"""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError(_("「%(v0)s」不是有效的數字。") % {"v0": text})
    return int(number.to_integral_value()) if as_int else number


def _body_date(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def _body_save(request, athlete):
    """手動輸入一筆體組成紀錄（同一天再存一次＝覆蓋原本那筆）。"""
    on_date = _body_date(request.POST.get("date")) or date.today()
    values = {
        field: _body_value(request.POST.get(field), as_int)
        for field, as_int in BODY_NUMBER_FIELDS.items()
    }
    if values["weight_kg"] is None:
        raise ValueError(_("體重是必填的。"))
    values["device"] = request.POST.get("device", "").strip()[:40]
    brand = (request.POST.get("brand") or "").strip().upper()
    if brand not in BRAND_PRESETS:
        # 使用者直接打品牌名（"inbody 570"）也認；認不出就當通用
        brand = detect_brand(brand) or detect_brand(values["device"]) or GENERIC
    values["brand"] = brand
    values["mba_rating"] = request.POST.get("mba_rating", "").strip()[:20]
    values["note"] = request.POST.get("note", "").strip()
    values["measured_at"] = request.POST.get("measured_at") or None
    values["source"] = BodyMetricLog.Source.MANUAL
    values["source_file"] = ""
    # 那個牌子沒有印的項目表單上是收起來的，別留下上一次量測的舊值
    for field in BRAND_PRESETS[brand]["hidden"]:
        values[field] = None if field != "mba_rating" else ""

    _unused, created = BodyMetricLog.objects.update_or_create(
        athlete=athlete, date=on_date, defaults=values
    )
    if created:
        messages.success(request, _("已新增 %(date)s 的體組成紀錄。") % {"date": on_date})
    else:
        messages.success(request, _("已更新 %(date)s 的體組成紀錄。") % {"date": on_date})


def _body_store(request, athlete, text, label, source_file="", on_date=None):
    """把解析出來的體組成資料寫進去（檔案匯入與貼上文字共用）。"""
    records, unknown = parse_body_composition(text, default_date=on_date or date.today())
    if not records:
        raise ValueError(
            _("%(v0)s裡找不到可用的體組成資料（至少要有體重）。可以用磅的 App 匯出 CSV，或把「項目 數值」一行一項貼進來。") % {"v0": label}
        )

    created = updated = 0
    for record in records:
        record_date = record.pop("date")
        if on_date is not None:
            record_date = on_date
        record["source"] = BodyMetricLog.Source.IMPORT
        record["source_file"] = source_file[:120]
        _unused, was_created = BodyMetricLog.objects.update_or_create(
            athlete=athlete, date=record_date, defaults=record
        )
        created += was_created
        updated += not was_created

    parts = []
    if created:
        parts.append(_("新增 %(v0)s 筆") % {"v0": created})
    if updated:
        parts.append(_("更新 %(v0)s 筆") % {"v0": updated})
    messages.success(request, _("已從%(v0)s%(v1)s體組成紀錄。") % {"v0": label, "v1": '、'.join(parts)})
    if unknown:
        messages.warning(request, _("有幾個項目看不懂、已略過：") + "、".join(unknown[:8]))


def _body_import(request, athlete):
    """上傳體組成磅匯出的檔案，直接更新最新的身體狀態。"""
    upload = request.FILES.get("file")
    if upload is None:
        raise ValueError(_("請先選一個檔案。"))
    if upload.size > 2 * 1024 * 1024:
        raise ValueError(_("檔案太大了（上限 2 MB）。"))

    raw = upload.read()
    for encoding in ("utf-8-sig", "utf-16", "big5", "cp950", "gbk"):
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise ValueError(_("讀不懂這個檔案的編碼，請另存成 UTF-8 的 CSV。"))

    _body_store(request, athlete, text, f"「{upload.name}」", source_file=upload.name)


def _body_paste(request, athlete):
    """把磅 App／截圖辨識出來的文字直接貼進來。

    手機把截圖的文字複製出來（iOS 實時文字、Android Google Lens）之後貼上，
    等於用圖片匯入，但辨識交給手機做，準確度比自己跑 OCR 高。
    """
    text = request.POST.get("text", "").strip()
    if not text:
        raise ValueError(_("請先把磅上的文字貼進來。"))
    if len(text) > 20000:
        raise ValueError(_("貼進來的文字太長了（上限 2 萬字）。"))

    # 貼上的內容常常沒有日期（App 的日期在另一個畫面），所以讓使用者自己指定
    on_date = _body_date(request.POST.get("date")) if request.POST.get("date") else None
    _body_store(request, athlete, text, _("貼上的文字"), source_file="貼上文字", on_date=on_date)


@login_required
@require_POST
def athlete_body_metric(request, pk):
    """狀態總覽頁的體組成區塊：手動輸入、檔案匯入、刪除一筆。"""
    athlete = get_object_or_404(AthleteProfile, pk=pk)
    if athlete.id not in set(athlete_ids_visible_to(request.user)):
        raise Http404(_("看不到這名運動員。"))

    back = f"{reverse('web:dashboard')}?athlete={athlete.id}"
    if not _can_edit_plan(request.user, athlete):
        messages.error(request, _("只有這名運動員本人、他的教練或管理員可以改體組成紀錄。"))
        return redirect(back)

    action = request.POST.get("action")
    try:
        if action == "save":
            _body_save(request, athlete)
        elif action == "import":
            _body_import(request, athlete)
        elif action == "paste":
            _body_paste(request, athlete)
        elif action == "delete":
            deleted, _unused = BodyMetricLog.objects.filter(
                athlete=athlete, pk=request.POST.get("log_id")
            ).delete()
            messages.success(request, _("已刪除該筆體組成紀錄。") if deleted else _("找不到那筆紀錄。"))
        else:
            messages.error(request, _("不認得的動作。"))
    except ValueError as exc:
        messages.error(request, _("沒有存起來：%(v0)s") % {"v0": exc})
    return redirect(back)


@login_required
def coach_dashboard(request):
    if request.user.role == Role.ATHLETE:
        return redirect("web:dashboard")
    coach = getattr(request.user, "coach_profile", None)
    if coach is None:
        athletes = AthleteProfile.objects.filter(id__in=athlete_ids_visible_to(request.user))
        rows = [
            {
                "athlete": a,
                "status": a.get_status_display(),
                **an.acwr_report(a),
                "readiness": an.readiness_score(a)["score"],
                "injuries": a.active_injuries.count(),
                "today_sessions": a.sessions.filter(date=date.today()).count(),
            }
            for a in athletes
        ]
    else:
        data = an.coach_dashboard(coach)
        rows = data["rows"]
        for r in rows:
            r.update(an.acwr_report(r["athlete"]))

    for r in rows:
        r["badge"], r["color"] = RISK_CSS[r["risk_flag"]]

    high_risk = [r for r in rows if r["risk_flag"] == "HIGH"]
    injured = [r for r in rows if r["injuries"]]

    return render(
        request,
        "web/coach_dashboard.html",
        {
            "page": "team",
            "rows": rows,
            "high_risk": high_risk,
            "injured": injured,
            "today": date.today(),
            "total": len(rows),
        },
    )


# -------------------------------------------------------------- 運動員列表

#: 列表可以排序的欄位 → 實際的 order_by（預設方向＝由小到大 / A→Z）
#: 沒有任何紀錄時的替代時間（只用來讓 MAX() 不會變成 NULL）
EPOCH = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)

ATHLETE_SORTS = {
    "name": ["user__first_name", "user__last_name", "user__username"],
    "updated": ["-last_update", "user__username"],
    "project": ["project_title", "user__username"],
    "event": ["primary_event__category", "primary_event__distance_m", "primary_event__code"],
    "age": ["-birth_date"],  # 生日越晚＝年紀越小
    "status": ["status", "-injury_count", "user__username"],
}

#: 表頭與「目前排序」提示用的中文欄名
SORT_LABELS = {
    "name": _("姓名"),
    "updated": _("最後更新"),
    "project": _("計劃"),
    "event": _("主項"),
    "age": _("年紀"),
    "status": _("傷患狀態"),
}

#: 「最後更新」篩選：找最近有動的人，或找久沒人理的人
UPDATED_FILTERS = [
    ("7", _("7 天內有更新")),
    ("30", _("30 天內有更新")),
    ("stale30", _("超過 30 天沒更新")),
    ("stale90", _("超過 90 天沒更新")),
]

#: 傷患狀態欄的篩選選項（除了三種 status，再加一個「身上有未結案傷患」）
INJURY_FILTERS = list(AthleteStatus.choices) + [("HAS_INJURY", _("有未結案傷患"))]


def _flip(ordering):
    return [f[1:] if f.startswith("-") else f"-{f}" for f in ordering]


def _sort_urls(request, sort, direction):
    """每個表頭連到「換成這個欄位排序」的網址，點同一欄再點一次就反向。"""
    urls = {}
    for key in ATHLETE_SORTS:
        params = request.GET.copy()
        params["sort"] = key
        params["dir"] = "desc" if key == sort and direction == "asc" else "asc"
        urls[key] = f"?{params.urlencode()}"
    return urls


def _athlete_scope_note(user):
    """列表看得到誰，直接寫在標題下面，免得以為是資料掉了。"""
    if _is_admin(user):
        return _("管理員：看得到系統內所有運動員")
    if user.role == Role.COACH:
        return _("教練：只看得到直屬與自己負責的計劃裡的運動員")
    return _("運動員：只看得到自己的狀態總覽")


@login_required
def athlete_list(request):
    """運動員列表：先挑人，再進去看那個人的狀態總覽。

    帶搜尋、篩選（計劃／主項／傷患狀態）與排序，資料本身跟總覽頁同一份。
    """
    qs = (
        AthleteProfile.objects.filter(id__in=athlete_ids_visible_to(request.user))
        .select_related("user", "primary_event", "coach__user")
        .prefetch_related("applications__project__coaches__user")
        .annotate(
            injury_count=Count(
                "injuries", filter=~Q(injuries__status="RESOLVED"), distinct=True
            ),
            # 一名運動員可以報多個項目，排序時取字母序最前的那個
            project_title=Min("applications__project__title"),
            # 最後更新＝檔案本身、課表、數據紀錄、傷患紀錄之中最新的那個時間。
            # SQLite 的 MAX() 碰到 NULL 會整個變 NULL，所以先 Coalesce 成很早的時間
            last_update=Greatest(
                F("updated_at"),
                Coalesce(Max("sessions__updated_at"), Value(EPOCH)),
                Coalesce(Max("metric_records__updated_at"), Value(EPOCH)),
                Coalesce(Max("injuries__updated_at"), Value(EPOCH)),
            ),
        )
    )

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__username__icontains=q)
            | Q(primary_event__name_zh__icontains=q)
            | Q(primary_event__code__icontains=q)
            | Q(school_or_club__icontains=q)
            | Q(applications__project__title__icontains=q)
        )

    project = request.GET.get("project", "")
    if project == "none":
        qs = qs.filter(applications__isnull=True)
    elif project:
        qs = qs.filter(applications__project_id=project)

    event = request.GET.get("event", "")
    if event:
        qs = qs.filter(primary_event_id=event)

    injury = request.GET.get("injury", "")
    if injury == "HAS_INJURY":
        qs = qs.filter(injury_count__gt=0)
    elif injury in AthleteStatus.values:
        qs = qs.filter(status=injury)

    updated = request.GET.get("updated", "")
    now = timezone.now()
    if updated in ("7", "30"):
        qs = qs.filter(last_update__gte=now - timedelta(days=int(updated)))
    elif updated.startswith("stale"):
        qs = qs.filter(last_update__lt=now - timedelta(days=int(updated[5:])))

    sort = request.GET.get("sort", "name")
    if sort not in ATHLETE_SORTS:
        sort = "name"
    direction = "desc" if request.GET.get("dir") == "desc" else "asc"
    ordering = ATHLETE_SORTS[sort]
    athletes = list(
        qs.distinct().order_by(*(_flip(ordering) if direction == "desc" else ordering))
    )

    visible_projects = (
        Project.objects.filter(applications__athlete__in=athletes).distinct().order_by("title")
    )
    visible_events = (
        Event.objects.filter(primary_athletes__in=athletes)
        .distinct()
        .order_by("category", "distance_m", "code")
    )

    return render(
        request,
        "web/athlete_list.html",
        {
            "page": "athletes",
            "athletes": athletes,
            "total": len(athletes),
            "q": q,
            "project": project,
            "event": event,
            "injury": injury,
            "updated": updated,
            "sort": sort,
            "sort_label": SORT_LABELS[sort],
            "dir": direction,
            "arrow": "▲" if direction == "asc" else "▼",
            "sort_urls": _sort_urls(request, sort, direction),
            "projects": visible_projects,
            "events": visible_events,
            "injury_filters": INJURY_FILTERS,
            "updated_filters": UPDATED_FILTERS,
            "has_filter": bool(q or project or event or injury or updated),
            "today": date.today(),
            "scope_note": _athlete_scope_note(request.user),
        },
    )


# --------------------------------------------------- 備戰計劃（目標賽事／分期）


def _can_edit_plan(user, athlete):
    """誰改得動這名運動員的目標賽事與分期：本人、他的教練、管理員。"""
    if _is_admin(user):
        return True
    if user.role == Role.COACH:
        if athlete.coach_id is not None and athlete.coach.user_id == user.id:
            return True
        # 由計劃分配過來的教練，同樣改得動這名運動員的備戰計劃
        return Application.objects.filter(
            athlete=athlete, project__coaches__user=user
        ).exists()
    return athlete.user_id == user.id


def _relink_microcycles(macro):
    """大週期的起訖或分期一改，底下的週計劃要跟著對回正確的日期與分期。"""
    for micro in macro.microcycles.all():
        if micro.week_number > macro.total_weeks:
            if not micro.sessions.exists():
                micro.delete()
            continue
        phase = macro.phases.filter(
            week_start__lte=micro.week_number, week_end__gte=micro.week_number
        ).first()
        start = macro.start_date + timedelta(weeks=micro.week_number - 1)
        fields = []
        if micro.phase_id != (phase.id if phase else None):
            micro.phase = phase
            fields.append("phase")
        if micro.start_date != start:
            micro.start_date = start
            fields.append("start_date")
        if phase and not micro.actual_load and micro.planned_load != phase.target_weekly_load:
            micro.planned_load = phase.target_weekly_load
            fields.append("planned_load")
        if fields:
            micro.save(update_fields=fields + ["updated_at"])


def _rebuild_cycle(macro):
    """分期與週計劃都是從大週期算出來的，改完大週期就整份重建。"""
    macro.generate_phases()
    macro.generate_microcycles()
    _relink_microcycles(macro)


def _plan_int(raw, low, high, default):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def athlete_competitions(athlete):
    """這名運動員自己的賽事。

    賽事是一人一份的：別人加的目標賽事不會出現在這裡。athlete 留空的是
    舊資料（欄位加上去之前建的），誰先拿來用就歸誰——見 _save_target。
    """
    return Competition.objects.filter(
        Q(athlete=athlete) | Q(athlete__isnull=True)
    ).order_by("date")


def _save_target(request, athlete):
    """存目標賽事：順便把備戰大週期（起始日、週數、基準負荷）一起定下來。"""
    choice = request.POST.get("competition", "")
    is_warmup = request.POST.get("comp_is_warmup") == "1"
    prep_for = None
    if is_warmup and request.POST.get("comp_prep_for"):
        prep_for = athlete_competitions(athlete).filter(
            pk=request.POST["comp_prep_for"], is_warmup=False
        ).first()
        if prep_for is None:
            raise ValueError(_("找不到要備戰的那一場重要比賽。"))

    if choice == "__new__":
        name = request.POST.get("comp_name", "").strip()
        if not name:
            raise ValueError(_("要填賽事名稱。"))
        try:
            comp_date = date.fromisoformat(request.POST.get("comp_date", ""))
        except ValueError:
            raise ValueError(_("比賽日期格式要是 YYYY-MM-DD。"))
        competition, created = Competition.objects.get_or_create(
            athlete=athlete,
            name=name,
            date=comp_date,
            defaults={
                "venue": request.POST.get("comp_venue", "").strip(),
                "level": request.POST.get("comp_level", "REGIONAL"),
                "is_target": True,
                "is_warmup": is_warmup,
                "prep_for": prep_for,
            },
        )
        if not created:
            competition.is_target = True
            competition.is_warmup = is_warmup
            competition.prep_for = prep_for
            competition.save(
                update_fields=["is_target", "is_warmup", "prep_for", "updated_at"]
            )
    elif choice:
        # 只挑得到自己的賽事；舊資料（athlete 留空的）第一次被選中就歸這名運動員
        competition = athlete_competitions(athlete).filter(pk=choice).first()
        if competition is None:
            raise ValueError(_("找不到這一場賽事。"))
        changed = []
        if competition.athlete_id is None:
            competition.athlete = athlete
            changed.append("athlete")
        if competition.is_warmup != is_warmup:
            competition.is_warmup = is_warmup
            changed.append("is_warmup")
        if competition.prep_for_id != (prep_for.id if prep_for else None):
            competition.prep_for = prep_for
            changed.append("prep_for")
        if changed:
            competition.save(update_fields=changed + ["updated_at"])
    else:
        raise ValueError(_("要選一個目標賽事。"))

    # 熱身賽只是路上的一站：週期要排到它備戰的那一場重要比賽為止
    # 熱身賽沒指定備戰對象時，planning_anchor 就是它自己
    anchor = competition.planning_anchor

    baseline = _plan_int(request.POST.get("baseline_weekly_load"), 100, 20000, 1800)

    raw_start = request.POST.get("start_date", "").strip()
    if raw_start:
        try:
            start = date.fromisoformat(raw_start)
        except ValueError:
            raise ValueError(_("開始日期格式要是 YYYY-MM-DD。"))
        if start > anchor.date:
            raise ValueError(_("備戰開始日期不能晚過比賽日期。"))
        # 填了開始日期就不用自己數週數：由開始日（對齊週一）算到比賽日
        start = an.monday_of(start)
        total_weeks = weeks_between(start, anchor.date)
    else:
        # 沒填就從比賽日往回數，湊成完整的 N 週（由週一開始）
        total_weeks = _plan_int(request.POST.get("total_weeks"), 1, 52, 16)
        start = an.monday_of(anchor.date - timedelta(weeks=total_weeks - 1))

    macro = athlete.macrocycles.filter(is_active=True).first()
    structural = True
    if macro is None:
        macro = Macrocycle(athlete=athlete)
    else:
        structural = (
            macro.start_date != start
            or macro.total_weeks != total_weeks
            or macro.baseline_weekly_load != baseline
            or not macro.phases.exists()
        )

    macro.target_competition = competition
    macro.start_date = start
    macro.total_weeks = total_weeks
    macro.baseline_weekly_load = baseline
    macro.end_date = start + timedelta(weeks=total_weeks, days=-1)
    macro.is_active = True
    macro.save()

    if structural:
        _rebuild_cycle(macro)

    if anchor.id != competition.id:
        messages.success(
            request,
            _("目標賽事已設為熱身賽「%(v0)s」（%(v1)s），週期以重要比賽「%(v2)s」（%(v3)s）計算：%(v4)s 起共 %(v5)s 週。") % {"v0": competition.name, "v1": competition.date, "v2": anchor.name, "v3": anchor.date, "v4": start, "v5": total_weeks},
        )
    else:
        messages.success(
            request,
            _("目標賽事已設為「%(v0)s」（%(v1)s）：%(v2)s 起共 %(v3)s 週，%(v4)s。") % {"v0": competition.name, "v1": competition.date, "v2": start, "v3": total_weeks, "v4": competition.countdown_display},
        )


def _save_phase(request, athlete):
    """存分期：改的是 Phase 本身，日曆、週計劃、負荷分析看到的都會跟著變。"""
    macro = athlete.macrocycles.filter(is_active=True).first()
    if macro is None:
        raise ValueError(_("要先設定目標賽事，才有分期可以改。"))

    if request.POST.get("reset") == "1":
        _rebuild_cycle(macro)
        messages.success(request, _("已依預設模板重建整份分期與週計劃。"))
        return

    phase_id = request.POST.get("phase_id", "")
    phase = macro.phases.filter(pk=phase_id).first() if phase_id else macro.current_phase

    phase_type = request.POST.get("phase_type", "")
    if phase_type not in PhaseType.values:
        raise ValueError(_("不認得的期別。"))

    week_start = _plan_int(request.POST.get("week_start"), 1, macro.total_weeks, 1)
    week_end = _plan_int(request.POST.get("week_end"), 1, macro.total_weeks, macro.total_weeks)
    if week_end < week_start:
        raise ValueError(_("結束週不能早於起始週。"))

    if phase is None:
        phase = Phase(macrocycle=macro)
    phase.phase_type = phase_type
    phase.week_start = week_start
    phase.week_end = week_end
    phase.start_date = macro.start_date + timedelta(weeks=week_start - 1)
    phase.end_date = macro.start_date + timedelta(weeks=week_end, days=-1)
    phase.focus = request.POST.get("focus", "").strip()
    phase.target_weekly_load = _plan_int(
        request.POST.get("target_weekly_load"), 0, 20000, macro.baseline_weekly_load
    )
    phase.save()

    _relink_microcycles(macro)
    messages.success(
        request,
        _("分期已更新為「%(v0)s」（第 %(v1)s–%(v2)s 週，目標週負荷 %(v3)s AU）。") % {"v0": phase.get_phase_type_display(), "v1": week_start, "v2": week_end, "v3": phase.target_weekly_load},
    )


@login_required
@require_POST
def athlete_plan_edit(request, pk):
    """儀表板上「距離目標賽事 / 目前分期」兩張卡片的編輯入口。

    寫進去的是 Competition / Macrocycle / Phase 本身，所以日曆、計劃頁、
    負荷分析拿到的都是同一份資料，改一次到處都會更新。
    """
    athlete = get_object_or_404(AthleteProfile, pk=pk)
    if athlete.id not in set(athlete_ids_visible_to(request.user)):
        raise Http404(_("看不到這名運動員。"))

    back = f"{reverse('web:dashboard')}?athlete={athlete.id}"
    if not _can_edit_plan(request.user, athlete):
        messages.error(request, _("只有這名運動員本人、他的教練或管理員可以改備戰計劃。"))
        return redirect(back)

    action = request.POST.get("action")
    try:
        if action == "set_target":
            _save_target(request, athlete)
        elif action == "set_phase":
            _save_phase(request, athlete)
        else:
            messages.error(request, _("不認得的動作。"))
    except ValueError as exc:
        messages.error(request, _("沒有存起來：%(v0)s") % {"v0": exc})
    return redirect(back)


# ------------------------------------------------------------------ 計劃


def _is_admin(user):
    return user.is_superuser or user.role == Role.ADMIN


def _athlete_row(athlete):
    """計劃頁的一列運動員狀況（跟團隊總覽同一組指標）。"""
    week_start = an.monday_of(date.today())
    row = {
        "athlete": athlete,
        "status": athlete.get_status_display(),
        "readiness": an.readiness_score(athlete)["score"],
        "injuries": athlete.active_injuries.count(),
        "today_sessions": athlete.sessions.filter(date=date.today()).count(),
        "week_sessions": athlete.sessions.filter(
            date__gte=week_start, date__lte=week_start + timedelta(days=6)
        ).count(),
        "last_session": athlete.sessions.order_by("-date").first(),
        **an.acwr_report(athlete),
    }
    row["badge"], row["color"] = RISK_CSS[row["risk_flag"]]
    return row


@login_required
def plan_view(request):
    """計劃總覽。

    管理員：看得到全部報名項目，並且可以把項目分配給教練。
    教練：只看得到被分配到的項目，點進去看項目裡運動員的狀況。
    運動員：看得到自己有報名的項目。
    """
    is_admin = _is_admin(request.user)

    if request.method == "POST":
        if not is_admin:
            messages.error(request, _("只有管理員可以分配項目。"))
            return redirect("web:plan")

        action = request.POST.get("action")
        project = get_object_or_404(Project, pk=request.POST.get("project_id"))

        if action == "assign":
            coach_ids = request.POST.getlist("coach_ids")
            added = 0
            for coach in CoachProfile.objects.filter(id__in=coach_ids):
                _unused, created = ProjectAssignment.objects.update_or_create(
                    project=project,
                    coach=coach,
                    defaults={
                        "is_active": True,
                        "assigned_by": request.user,
                        "note": request.POST.get("note", ""),
                    },
                )
                added += int(created)
            messages.success(
                request, _("已把「%(v0)s」分配給 %(v1)s 位教練（新增 %(v2)s 筆）。") % {"v0": project.title, "v1": len(coach_ids), "v2": added}
            )
        elif action == "unassign":
            ProjectAssignment.objects.filter(
                project=project, coach_id=request.POST.get("coach_id")
            ).delete()
            messages.info(request, _("已取消「%(v0)s」的一筆教練分配。") % {"v0": project.title})
        return redirect("web:plan")

    visible = set(athlete_ids_visible_to(request.user))
    rows = []
    for project in projects_for(request.user).prefetch_related("assignments__coach__user"):
        athletes = list(project_athletes(project))
        mine = [a for a in athletes if a.id in visible]
        rows.append(
            {
                "project": project,
                "assignments": list(project.assignments.all()),
                "athlete_count": len(athletes),
                "my_count": len(mine),
                "injured": sum(1 for a in mine if a.active_injuries.exists()),
                "pending": project.applications.filter(athlete__isnull=True).count(),
            }
        )

    return render(
        request,
        "web/plan.html",
        {
            "page": "plan",
            "rows": rows,
            "is_admin": is_admin,
            "coaches": CoachProfile.objects.select_related("user") if is_admin else [],
            "total_athletes": sum(r["my_count"] for r in rows),
        },
    )


@login_required
def plan_detail(request, pk):
    """單一報名項目：這個項目裡的運動員現在怎麼樣。"""
    project = get_object_or_404(Project, pk=pk)
    if not projects_for(request.user).filter(pk=pk).exists():
        raise Http404(_("這個項目沒有分配給你。"))

    if request.method == "POST":
        if request.POST.get("action") == "bulk_program":
            return _plan_bulk_program(request, project)
        return _plan_detail_import(request, project)

    visible = set(athlete_ids_visible_to(request.user))
    athletes = [a for a in project_athletes(project) if a.id in visible]
    rows = [_athlete_row(a) for a in athletes]
    can_assign = _can_assign_program(request.user, project)

    return render(
        request,
        "web/plan_detail.html",
        {
            "page": "plan",
            "project": project,
            "rows": rows,
            "is_admin": _is_admin(request.user),
            "assignments": project.assignments.select_related("coach__user"),
            "high_risk": [r for r in rows if r["risk_flag"] == "HIGH"],
            "injured": [r for r in rows if r["injuries"]],
            "not_imported": annotate_matches(
                project.applications.filter(athlete__isnull=True)
            ),
            "today": date.today(),
            "can_assign": can_assign,
            "program_types": program_type_choices(),
            "today_iso": date.today().isoformat(),
            "source_sessions": _plan_source_sessions(athletes) if can_assign else [],
            "max_dates": MAX_COPY_DATES,
        },
    )


def _can_assign_program(user, project):
    """誰可以一次過派課給整個項目：管理員，以及被分配到這個項目的教練。"""
    if _is_admin(user):
        return True
    coach = getattr(user, "coach_profile", None)
    if coach is None:
        return False
    return (
        project.assignments.filter(coach=coach, is_active=True).exists()
        or project.coaches.filter(pk=coach.pk).exists()
    )


def _plan_source_sessions(athletes):
    """可以拿來當範本的課表：項目裡運動員近期排過的課，由新到舊。"""
    return (
        TrainingSession.objects.filter(athlete__in=[a.id for a in athletes])
        .select_related("athlete__user")
        .annotate(n_activities=Count("activities"))
        .order_by("-date", "-id")[:PLAN_SOURCE_LIMIT]
    )


def _plan_detail_import(request, project):
    """在計劃頁直接把選取的報名表載入成 ATM 運動員檔案（等同後台的「匯入 ATM」）。"""
    if not _is_admin(request.user):
        messages.error(request, _("只有管理員可以匯入報名表。"))
        return redirect("web:plan_detail", pk=project.pk)

    applications = project.applications.filter(
        athlete__isnull=True, id__in=request.POST.getlist("application_ids")
    )
    if not applications:
        messages.warning(request, _("沒有選取任何未匯入的報名表。"))
        return redirect("web:plan_detail", pk=project.pk)

    created = linked = 0
    for application in applications:
        match = find_existing_athlete(application)
        try:
            import_application(application)
        except ProgramImportError as exc:
            messages.error(request, f"{application.name_en}：{exc}")
            continue
        if match:
            linked += 1
        else:
            created += 1

    if created:
        messages.success(
            request,
            _("已把 %(v0)s 份報名載入「%(v1)s」，帳號密碼為隨機值，請用後台的『重設密碼』給對方。") % {"v0": created, "v1": project.title},
        )
    if linked:
        messages.success(
            request,
            _("其中 %(v0)s 位是已註冊運動員，已把「%(v1)s」加進原有檔案，沿用舊有紀錄，沒有另開帳號。") % {"v0": linked, "v1": project.title}
            if created
            else _("%(v0)s 位已註冊運動員已把「%(v1)s」加進原有檔案，沿用舊有紀錄，沒有另開帳號。") % {"v0": linked, "v1": project.title},
        )
    return redirect("web:plan_detail", pk=project.pk)


#: 「以現有課表為範本」下拉選單最多列幾堂課
PLAN_SOURCE_LIMIT = 50

#: 一次派課最多建幾堂課（運動員數 × 日期數），免得手滑排出幾百堂
MAX_BULK_SESSIONS = 200


def _plan_bulk_program(request, project):
    """把同一個 program（連同課表內容）一次派給項目裡指定的運動員。

    被分配到這個項目的教練和管理員都可以用；每一名選中的運動員、每一個選中的
    日期都會各自建一堂獨立的課，之後誰要改自己那一堂都不影響別人。
    挑了範本課表的話，四區的活動也照抄一份過去（練完才填的東西一概不抄）。
    """
    if not _can_assign_program(request.user, project):
        messages.error(request, _("只有管理員或這個項目的負責教練可以派課。"))
        return redirect("web:plan_detail", pk=project.pk)

    visible = set(athlete_ids_visible_to(request.user))
    picked = set(request.POST.getlist("athlete_ids"))
    in_project = [a for a in project_athletes(project) if a.id in visible]
    athletes = [a for a in in_project if str(a.id) in picked]
    if not athletes:
        messages.error(request, _("請至少選一名運動員。"))
        return redirect("web:plan_detail", pk=project.pk)

    dates, bad = _copy_dates(request)
    if not dates:
        messages.error(request, _("請選至少一個日期。"))
        return redirect("web:plan_detail", pk=project.pk)
    dropped = dates[MAX_COPY_DATES:]
    dates = dates[:MAX_COPY_DATES]

    if len(athletes) * len(dates) > MAX_BULK_SESSIONS:
        messages.error(
            request,
            _("一次最多派 %(v0)s 堂課，現在是 %(v1)s 人 × %(v2)s 天；請分幾次派。")
            % {"v0": MAX_BULK_SESSIONS, "v1": len(athletes), "v2": len(dates)},
        )
        return redirect("web:plan_detail", pk=project.pk)

    source = None
    if request.POST.get("source"):
        source = TrainingSession.objects.filter(
            pk=request.POST["source"], athlete__in=[a.id for a in in_project]
        ).first()
        if source is None:
            messages.warning(request, _("找不到那一堂範本課表，這次只用表格填的內容。"))

    session_type = request.POST.get("session_type") or (
        source.session_type if source else SessionType.TRACK
    )
    if session_type not in DEFAULT_PROGRAM_TITLES:
        messages.error(request, _("不認得的 program 類別。"))
        return redirect("web:plan_detail", pk=project.pk)

    title = request.POST.get("title", "").strip() or (
        source.title if source else DEFAULT_PROGRAM_TITLES[session_type]
    )
    description = request.POST.get("description", "").strip() or (
        source.description if source else ""
    )
    duration = _plan_int(
        request.POST.get("planned_duration_min"),
        10,
        480,
        source.planned_duration_min if source else 90,
    )
    time_slot = request.POST.get("time_slot")
    if time_slot not in ("AM", "PM"):
        time_slot = "PM"

    rows = (
        list(source.activities.select_related("definition").order_by("block", "order", "id"))
        if source and request.POST.get("copy_activities")
        else []
    )

    coach = getattr(request.user, "coach_profile", None)
    created = 0
    for athlete in athletes:
        for on_date in dates:
            session = TrainingSession.objects.create(
                athlete=athlete,
                microcycle=_microcycle_for(athlete, on_date),
                date=on_date,
                time_slot=time_slot,
                session_type=session_type,
                title=title,
                description=description,
                assigned_by=coach,
                created_by=request.user,
                planned_duration_min=duration,
            )
            for row in rows:
                _spawn_activity(
                    request,
                    session,
                    row.block,
                    row.order,
                    row.name,
                    {key: getattr(row, key) for key in ACTIVITY_VALUE_FIELDS},
                    definition=row.definition,
                )
            created += 1

    msg = _("已把「%(v0)s」派給 %(v1)s 名運動員 × %(v2)s 天，共建立 %(v3)s 堂課。") % {
        "v0": title,
        "v1": len(athletes),
        "v2": len(dates),
        "v3": created,
    }
    if rows:
        msg += _("（每堂連同 %(v0)s 項活動）") % {"v0": len(rows)}
    messages.success(request, msg)
    if bad:
        messages.warning(request, _("看不懂這些日期，已跳過：%(v0)s") % {"v0": "、".join(bad)})
    if dropped:
        messages.warning(
            request, _("一次最多複製 %(v0)s 天，其餘的沒有建立。") % {"v0": MAX_COPY_DATES}
        )
    return redirect("web:plan_detail", pk=project.pk)


# ------------------------------------------------------------------ 日曆


DEFAULT_PROGRAM_TITLES = {
    SessionType.TRACK: _("田徑場訓練"),
    SessionType.STRENGTH: _("重量訓練"),
    SessionType.RECOVERY: _("恢復訓練"),
    SessionType.REHAB: _("治療康復"),
    SessionType.COMPETITION: _("比賽"),
    SessionType.OTHER: _("其他安排"),
}


def _microcycle_for(athlete, on_date):
    """找出這一天落在哪個週計劃，找不到就留空（session.microcycle 允許 null）。"""
    return (
        Microcycle.objects.filter(
            macrocycle__athlete=athlete,
            macrocycle__is_active=True,
            start_date__lte=on_date,
            start_date__gte=on_date - timedelta(days=6),
        )
        .order_by("-start_date")
        .first()
    )


@login_required
def calendar_view(request):
    athlete = _current_athlete(request)
    if athlete is None:
        return render(request, "web/no_athlete.html", {"page": "calendar"})

    # ---- 按日期新增 program ----
    if request.method == "POST" and request.POST.get("action") == "add_program":
        session_type = request.POST.get("session_type", SessionType.TRACK)
        if session_type not in DEFAULT_PROGRAM_TITLES:
            messages.error(request, _("不認得的 program 類別。"))
            return redirect(f"{request.path}?athlete={athlete.id}")

        on_date = date.fromisoformat(request.POST["date"])
        coach = getattr(request.user, "coach_profile", None)
        session = TrainingSession.objects.create(
            athlete=athlete,
            microcycle=_microcycle_for(athlete, on_date),
            date=on_date,
            time_slot=request.POST.get("time_slot", "PM"),
            session_type=session_type,
            title=request.POST.get("title", "").strip()
            or DEFAULT_PROGRAM_TITLES[session_type],
            description=request.POST.get("description", ""),
            assigned_by=coach,
            created_by=request.user,
            planned_duration_min=int(request.POST.get("planned_duration_min") or 90),
        )
        messages.success(
            request,
            _("已在 %(v0)s 新增「%(v1)s」（%(v2)s）。") % {"v0": on_date, "v1": session.title, "v2": session.get_session_type_display()},
        )
        return redirect(
            f"{request.path}?athlete={athlete.id}&year={on_date.year}&month={on_date.month}"
        )

    # ---- 把已建立的課表複製到其他日子 ----
    if request.method == "POST" and request.POST.get("action") == "copy_session":
        landed = _copy_session(request, athlete)
        target = landed or date.today()
        return redirect(
            f"{request.path}?athlete={athlete.id}&year={target.year}&month={target.month}"
        )

    ctx = _calendar_context(athlete, request)
    ctx.update(
        {
            "page": "calendar",
            "athlete": athlete,
            "athletes": _athlete_switcher(request),
            "program_types": program_type_choices(),
        }
    )
    return render(request, "web/calendar.html", ctx)


#: 一次最多複製到幾天——手滑貼了一整年進去，不會就這樣建出 365 堂課
MAX_COPY_DATES = 30


def _copy_dates(request):
    """把「日期」欄與「其他日期」欄裡的日子讀出來（重複的只算一次）。"""
    raw = " ".join([request.POST.get("date", ""), request.POST.get("dates", "")])
    dates, bad = [], []
    for part in re.split(r"[\s,、]+", raw):
        if not part:
            continue
        try:
            picked = date.fromisoformat(part)
        except ValueError:
            bad.append(part)
            continue
        if picked not in dates:
            dates.append(picked)
    return dates, bad


def _copy_session(request, athlete):
    """把日曆上一堂已建立的課複製到其他日子，回傳第一個目標日期。

    複製的是課表本身（名稱、課別、概要、時長、四區的活動），
    練完才填的東西（狀態、RPE、實際時長、反饋、評語）一律不抄——
    複製出來的是待練的課，不是別人練過的紀錄。
    """
    source = TrainingSession.objects.filter(
        pk=request.POST.get("session"), athlete=athlete
    ).first()
    if source is None:
        messages.error(request, _("找不到要複製的課表。"))
        return None

    dates, bad = _copy_dates(request)
    if not dates:
        messages.error(request, _("請選至少一個日期。"))
        return None
    dropped = dates[MAX_COPY_DATES:]
    dates = dates[:MAX_COPY_DATES]

    time_slot = request.POST.get("time_slot")
    if time_slot not in ("AM", "PM"):
        time_slot = source.time_slot
    with_activities = bool(request.POST.get("copy_activities"))

    rows = (
        list(source.activities.select_related("definition").order_by("block", "order", "id"))
        if with_activities
        else []
    )

    copied = 0
    for on_date in dates:
        new_session = TrainingSession.objects.create(
            athlete=athlete,
            microcycle=_microcycle_for(athlete, on_date),
            date=on_date,
            time_slot=time_slot,
            session_type=source.session_type,
            title=source.title,
            description=source.description,
            assigned_by=source.assigned_by,
            created_by=request.user,
            planned_duration_min=source.planned_duration_min,
        )
        for row in rows:
            _spawn_activity(
                request,
                new_session,
                row.block,
                row.order,
                row.name,
                {key: getattr(row, key) for key in ACTIVITY_VALUE_FIELDS},
                definition=row.definition,
            )
        copied += 1

    msg = _("已把「%(v0)s」複製到 %(v1)s 天：%(v2)s。") % {
        "v0": source.title,
        "v1": copied,
        "v2": "、".join(d.isoformat() for d in dates),
    }
    if rows:
        msg += _("（連同 %(v0)s 項活動）") % {"v0": len(rows)}
    messages.success(request, msg)
    if bad:
        messages.warning(request, _("看不懂這些日期，已跳過：%(v0)s") % {"v0": "、".join(bad)})
    if dropped:
        messages.warning(
            request, _("一次最多複製 %(v0)s 天，其餘的沒有建立。") % {"v0": MAX_COPY_DATES}
        )
    return dates[0]


def _calendar_context(athlete, request):
    """組出月曆格子。calendar_view 和 calendar_live（輪詢刷新）共用同一份。"""
    today = date.today()
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))

    first = date(year, month, 1)
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    grid_start = first - timedelta(days=first.weekday())
    grid_end = last + timedelta(days=(6 - last.weekday()))

    sessions = list(
        TrainingSession.objects.filter(
            athlete=athlete, date__gte=grid_start, date__lte=grid_end
        ).order_by("date", "time_slot")
    )

    by_day = {}
    for s in sessions:
        by_day.setdefault(s.date, []).append(s)

    # 比賽也要在日曆上看得到：填了比賽日期，那一格就標出來（多天賽事整段都標）
    meets = list(
        athlete_competitions(athlete)
        .filter(date__lte=grid_end)
        .filter(Q(end_date__isnull=True, date__gte=grid_start) | Q(end_date__gte=grid_start))
        .select_related("prep_for")
    )
    meets_by_day = {}
    for m in meets:
        day = m.date
        finish = m.end_date if m.end_date and m.end_date > m.date else m.date
        while day <= finish:
            if grid_start <= day <= grid_end:
                meets_by_day.setdefault(day, []).append(m)
            day += timedelta(days=1)

    weeks, cursor = [], grid_start
    while cursor <= grid_end:
        row = []
        for _unused in range(7):
            row.append(
                {
                    "date": cursor,
                    "in_month": cursor.month == month,
                    "is_today": cursor == today,
                    "sessions": by_day.get(cursor, []),
                    "meets": meets_by_day.get(cursor, []),
                }
            )
            cursor += timedelta(days=1)
        weeks.append(row)

    prev_m = first - timedelta(days=1)
    next_m = last + timedelta(days=1)
    macro = athlete.macrocycles.filter(is_active=True).first()

    return {
        "weeks": weeks,
        "year": year,
        "month": month,
        "month_name": _("%(v0)s 年 %(v1)s 月") % {"v0": year, "v1": month},
        "prev": {"year": prev_m.year, "month": prev_m.month},
        "next": {"year": next_m.year, "month": next_m.month},
        "macro": macro,
        "phases": macro.phases.all() if macro else [],
        "month_load": sum(s.session_load for s in sessions if first <= s.date <= last),
        "month_count": sum(1 for s in sessions if first <= s.date <= last),
        "today_iso": today.isoformat(),
        "cal_version": f"{_stamp(sessions)}|{_stamp(meets)}",
        "can_move": {s.id: liveedit.can_edit(s, request.user, "date") for s in sessions},
    }


def _stamp(objects):
    """一組物件的版本指紋：有人改過任何一筆，字串就會不一樣。"""
    latest = max((o.updated_at for o in objects), default=None)
    return f"{len(objects)}-{int(latest.timestamp() * 1000) if latest else 0}"


@login_required
def session_detail(request, pk):
    session = _visible_session(request, pk)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "complete":
            session.mark_complete(
                duration_min=int(request.POST["actual_duration_min"]),
                rpe=int(request.POST["session_rpe"]),
                completion_pct=int(request.POST.get("completion_pct", 100)),
                feedback=request.POST.get("athlete_feedback", ""),
            )
            satisfaction = request.POST.get("satisfaction", "").strip()
            if satisfaction:
                session.satisfaction = int(satisfaction)
                session.save(update_fields=["satisfaction", "updated_at"])
            messages.success(request, _("已送出訓練後檢討和反饋，本次負荷 %(v0)s AU。") % {"v0": session.session_load})
        elif action == "coach_comment":
            session.coach_comment = request.POST.get("coach_comment", "")
            session.save(update_fields=["coach_comment", "updated_at"])
            messages.success(request, _("已儲存教練評語。"))
        elif action == "modify":
            changes = inj.apply_modifications(session)
            messages.info(request, _("已依傷患調整，共 %(v0)s 項變更。") % {"v0": len(changes)})
        elif action == "add_activity":
            _add_activity(request, session)
        elif action == "new_definition":
            _new_definition(request, session)
        elif action == "delete_activity":
            _delete_row(request, SessionActivity, request.POST.get("id"), _("活動"))
        elif action == "save_program":
            _save_block_program(request, session)
        elif action == "apply_program":
            _apply_block_program(request, session)
        elif action == "delete_program":
            _delete_block_program(request)
        elif action == "add_note":
            _add_note(request, session)
        elif action == "delete_note":
            _delete_row(request, SessionNote, request.POST.get("id"), _("記事"))
        elif action in ("log_activity", "add_record", "edit_record",
                        "delete_record", "move_record"):
            # 課表下半部的「訓練紀錄」——新增一筆紀錄／紀錄明細都在這裡處理
            return _session_record_post(request, session, action)
        return redirect("web:session_detail", pk=pk)

    return render(request, "web/session_detail.html", _session_context(request, session))


def _visible_session(request, pk):
    session = get_object_or_404(
        TrainingSession.objects.select_related(
            "athlete__user", "assigned_by__user", "created_by", "microcycle"
        ),
        pk=pk,
    )
    if session.athlete_id not in set(athlete_ids_visible_to(request.user)):
        raise Http404(_("無權限存取此課表。"))
    # 開了誰的課表，頂欄與側欄就跟著切到誰——不會停在上一個看過的人身上
    remember(request, session.athlete_id)
    return session


def _session_context(request, session):
    """課表頁的完整 context（整頁與輪詢刷新的片段共用同一份）。"""
    blocked, reason = inj.should_block_high_intensity(session.athlete, session.date)
    ensure_activity_library()
    # 課表挑得到的動作 ＝ 運動練習項目庫裡已確認的動作（自己剛加、還在等確認的
    # 也留給本人，不然加了自己也挑不到）
    library = list(visible_definitions(request.user))
    catalog = library_tree(request.user)

    # 活動名稱要中英對照；自己打的名稱對得上活動庫就借它的英文名
    english = {d.name: d.name_en for d in library if d.name_en}

    programs_by_block = _block_programs_by_block(request.user)

    # 每一行活動這堂課已經登了幾組（行末寫「3 組・已填 1」用）
    logged = _activity_record_index(session)
    picked = request.GET.get("log")

    blocks = []
    for value, label, activities in session.activities_by_block():
        blocks.append(
            {
                "value": value,
                "label": label,
                # 這一區存好的 program：挑一個就把整組活動帶進來
                "programs": programs_by_block.get(value, []),
                "activities": [
                    {
                        "a": a,
                        "editable": liveedit.can_edit(a, request.user, "name"),
                        "name_en": (
                            a.definition.name_en if a.definition_id else ""
                        ) or english.get(a.name, ""),
                        # 課表只排課，數字在下面的「訓練紀錄」填——
                        # 這一行排了什麼寫成一句話，數字現況寫在旁邊
                        "plan": a.plan_summary,
                        "logged": logged.get((a.block, a.name)),
                        "picked": str(a.id) == picked,
                    }
                    for a in activities
                ],
            }
        )

    notes = [
        {"n": n, "editable": liveedit.can_edit(n, request.user, "body")}
        for n in session.notes.select_related("author")
    ]

    # 同一位運動員的上／下一課：看完一課可以直接翻，不用先回日曆再點
    same_athlete = TrainingSession.objects.filter(athlete_id=session.athlete_id).exclude(pk=session.pk)
    prev_session = (
        same_athlete.filter(
            Q(date__lt=session.date)
            | Q(date=session.date, time_slot__lt=session.time_slot)
        )
        .order_by("-date", "-time_slot")
        .first()
    )
    next_session = (
        same_athlete.filter(
            Q(date__gt=session.date)
            | Q(date=session.date, time_slot__gt=session.time_slot)
        )
        .order_by("date", "time_slot")
        .first()
    )

    return {
        "page": "session",
        "s": session,
        "prev_session": prev_session,
        "next_session": next_session,
        "blocks": blocks,
        "notes": notes,
        "note_kinds": NoteKind.choices,
        "block_choices": BlockType.choices,
        "library": library,
        # 給前端挑活動時自動帶入預設值用（模板以 json_script 輸出，不會被 HTML 咬到）
        "library_data": [
            dict(
                id=d.id,
                name=d.name,
                name_en=d.name_en,
                block=d.default_block,
                category=d.category,
                **d.defaults_payload(),
            )
            for d in library
        ],
        "activity_groups": library_groups(library),
        # 「先挑田徑、再挑短跑，動作才列出來」——課表與本課數據紀錄共用這一份
        "library_catalog": library_catalog(request.user, library),
        # 新增動作時挑的是項目庫的「運動項目 ＋ 訓練動作種類」，不再是一個平的分類
        "library_disciplines": catalog["disciplines"],
        "library_kinds": catalog["kinds"],
        "track_sets": session.track_sets.all(),
        "strength_sets": session.strength_sets.select_related("exercise"),
        "blocked": blocked,
        "block_reason": reason,
        "is_coach": request.user.role in (Role.COACH, Role.ADMIN),
        "can_edit_plan": liveedit.can_edit(session, request.user, "title"),
        # 跟 _can_log_metrics 同一個門檻（本人或管理員），畫面上看得到的按鈕才按得動
        "can_log": _can_log_metrics(request, session),
        "can_comment": liveedit.can_edit(session, request.user, "coach_comment"),
        "version": session.content_version,
        "session_types": program_type_choices(),
        "status_choices": SessionStatus.choices,
        # 這堂課對應的數據紀錄（跟數據分析頁是同一張表）
        **_session_metric_context(request, session),
    }


# ------------------------------------------------------ 課表上的「訓練紀錄」
#
# 課表的四個區塊只排「今天要做什麼」（活動名稱、訓練要點、當日備注）；
# 所有數字——目標、完成、重量、次數、休息——都在下半部的「訓練紀錄」填：
# 挑一行活動按「登記錄」，就在同一頁新增一筆紀錄、在紀錄明細逐格改。
# 寫進去的是 MetricRecord，跟數據分析看的是同一張表，所以填完那邊立刻看得到。


def _record_domains(session):
    """這堂課登得了哪些範疇（比賽數據／田徑練習訓練紀錄／重量訓練紀錄）。"""
    pairs = domain_pairs_for_session_type(session.session_type)
    return pairs or list(MetricDomain.choices)


def _record_domain(session, raw):
    """挑中的範疇：沒挑或挑了不合這個課別的，就用這個課別的第一個。"""
    allowed = [value for value, _label in _record_domains(session)]
    return raw if raw in allowed else allowed[0]


def _activity_record_index(session):
    """(區塊, 項目名稱) → 這堂課底下已經有幾組／填了幾組。

    課表每一行右邊寫「3 組・已填 1」就靠這一份，不用逐行再查一次資料庫。
    """
    index = {}
    for r in session.metric_records.select_related("item"):
        entry = index.setdefault((r.block, r.item.name), {"sets": 0, "filled": 0})
        entry["sets"] += 1
        if r.value is not None:
            entry["filled"] += 1
    return index


def _session_metric_context(request, session):
    """課表下半部「訓練紀錄」要用的東西。

    挑了哪一行活動（?log=）就把那一行的項目與每一組帶出來；
    沒挑的話只列這堂課已經登過的東西。
    """
    domain = _record_domain(session, request.GET.get("rdomain"))

    # 挑中的那一行活動：新增一筆紀錄與紀錄明細都是針對它
    activity = None
    raw = request.GET.get("log")
    if raw and str(raw).isdecimal():
        activity = session.activities.select_related("definition").filter(pk=raw).first()

    item, records = None, []
    if activity is not None:
        item = MetricItem.objects.filter(domain=domain, name=activity.name).first()
        if item is not None:
            records = session_records(session, item, block=activity.block)

    unit = (item.unit or "").strip().lower() if item else ""
    # 登了記錄的這一項，數據分析裡是不是已經有講同一件事的項目
    # （150m 節奏跑／150m 反覆跑）——有的話就在下面問一句要不要一起分析
    related = an.related_items(session.athlete, item) if item else []
    related_ids = ([item.id] + [r["item"].id for r in related]) if related else []
    return {
        "record_domains": _record_domains(session),
        "record_domain": domain,
        "record_domain_label": dict(MetricDomain.choices)[domain],
        # 挑中的那一行 ＋ 它這堂課的每一組
        "log_activity": activity,
        "log_item": item,
        "log_records": records,
        # 數據分析已經有的相關紀錄（那一句「要不要加在一起分析」的提問）
        "log_related": related,
        "log_related_csv": ",".join(str(i) for i in related_ids[:MULTI_ITEM_LIMIT]),
        "log_filled": sum(1 for r in records if r.value is not None),
        # 「距離」那一格的預設：課表那一行寫的米數，不用再打一次
        "log_distance": plan_distance(activity),
        # 這堂課登過的數據，照範疇分開列（田徑練習訓練紀錄／重量訓練紀錄…）
        "record_tables": session_domain_tables(session),
        "metric_statuses": TrainingStatus.choices,
        "metric_blocks": block_choices(),
        "strength_units": STRENGTH_UNITS,
        # 比賽數據要挑是哪一場，比賽分析才排得出逐場那幾張表
        "record_competitions": (
            athlete_competitions(session.athlete)
            if domain == MetricDomain.COMPETITION
            else []
        ),
        # 單位就是 kg 的項目，數值＝重量，表單不再重複問一次
        "unit_is_weight": unit == "kg",
        "is_track": domain == MetricDomain.TRACK,
        "metric_record_count": session.metric_records.count(),
    }


def _session_record_post(request, session, action):
    """課表頁「訓練紀錄」的送出：登記錄、改紀錄、刪紀錄、換組序。"""
    domain = _record_domain(session, request.POST.get("rdomain"))
    back = f"{reverse('web:session_detail', args=[session.pk])}?rdomain={domain}"
    # 改／刪回來要停在原地：紀錄明細回 #rec，下面那幾張分範疇的表回 #dom-<範疇>
    raw_anchor = request.POST.get("anchor", "")
    anchor = raw_anchor if re.fullmatch(r"[\w-]{1,40}", raw_anchor) else "rec"

    if not _can_log_metrics(request, session):
        messages.error(request, _("只有這名運動員本人（或管理員）能登這堂課的數據。"))
        return redirect(back)

    if action == "log_activity":
        # 課表某一行的「登記錄」：同名的數據項目沒有就開一個，
        # 課表寫了幾組就先開好幾組空白紀錄，練完只要補完成數值
        activity = get_object_or_404(
            session.activities.select_related("definition"), pk=request.POST.get("id")
        )
        try:
            item, opened = ensure_item_for_activity(
                activity, domain, user=request.user
            )
        except RecordError as exc:
            messages.error(request, str(exc))
            return redirect(back)
        if opened:
            messages.success(
                request,
                _("已為「%(v0)s」開好 %(v1)s 組空白紀錄，把完成數值填進去就行。")
                % {"v0": item.display_name, "v1": opened},
            )
        return redirect(f"{back}&log={activity.pk}#rec")

    if action == "add_record":
        item = get_object_or_404(MetricItem, pk=request.POST.get("item_id") or 0)
        activity_id = request.POST.get("log") or ""
        competition = None
        if request.POST.get("competition"):
            competition = athlete_competitions(session.athlete).filter(
                pk=request.POST["competition"]
            ).first()
        try:
            # 一列一組：同一堂課不同組的重量／次數／休息時間都不一樣
            _created, msg = create_records(
                athlete=session.athlete,
                item=item,
                session=session,
                post=request.POST,
                on_date=session.date,
                competition=competition,
            )
        except RecordError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, msg)
        return redirect(f"{back}&log={activity_id}#rec")

    # 以下三個動作都只動得了「這堂課」底下的紀錄，別堂課的碰不到
    mine = MetricRecord.objects.filter(session=session)

    if action == "edit_record":
        editable = list(mine.select_related("item"))
        only = request.POST.get("only") or None
        if only and not any(str(r.pk) == str(only) for r in editable):
            raise Http404(_("無權限修改這筆紀錄。"))
        # 課表頁不給 session_lookup——這裡的紀錄本來就屬於當下這一堂課
        changed, problems = update_records(request.POST, editable, only=only)
        text = edit_message(changed, problems)
        if changed:
            messages.success(request, text)
        else:
            messages.info(request, text)
        return redirect(f"{back}&log={request.POST.get('log', '')}#{anchor}")

    if action == "delete_record":
        record = get_object_or_404(mine, pk=request.POST.get("record_id"))
        item_id, on_date = record.item_id, record.date
        record.delete()
        # 刪掉中間那一組之後，剩下的組號補回 1、2、3…
        resequence(session.athlete_id, item_id, on_date)
        messages.info(request, _("已刪除一筆紀錄。"))
        return redirect(f"{back}&log={request.POST.get('log', '')}#{anchor}")

    # move_record：↑ ↓ 把一組往前／往後挪
    direction = "up" if request.POST.get("up") else "down"
    record = get_object_or_404(mine, pk=request.POST.get(direction))
    if not move_record(record, direction):
        messages.info(
            request,
            _("這一組已經在最前面了。") if direction == "up" else _("這一組已經在最後面了。"),
        )
    return redirect(f"{back}&log={request.POST.get('log', '')}#{anchor}")


def _can_log_metrics(request, session):
    """能不能動這堂課的數據——跟登記 RPE 同一個門檻（本人或管理員）。"""
    return liveedit.can_edit(session, request.user, "session_rpe") or liveedit.is_admin(
        request.user
    )


def _add_activity(request, session):
    """在某一區（熱身 / 正課 / 補充 / 恢復）加活動。

    可以一次加多項：「活動名稱」欄每行一個名字，名字對得上活動庫的就把
    預設組數/次數/休息一起帶進來。這裡只排課、不動數據——
    要記數據的那一行，按行末的「登記錄」，數字在下半部的「訓練紀錄」填。
    """
    block = request.POST.get("block")
    if block not in BlockType.values:
        messages.error(request, _("不認得的課表區塊。"))
        return

    definition = None
    definition_id = request.POST.get("definition")
    if definition_id:
        definition = ActivityDefinition.objects.filter(pk=definition_id).first()

    # 一行一項；用頓號或逗號分隔也接受
    names = [
        part.strip()
        for part in re.split(r"[\n、,]", request.POST.get("name", ""))
        if part.strip()
    ]
    if not names and definition:
        names = [definition.name]
    if not names:
        messages.error(request, _("請挑一個活動，或自己打一個名稱。"))
        return

    single = len(names) == 1
    last = session.activities.filter(block=block).order_by("-order").first()
    order = (last.order + 1) if last else 1

    added = []
    for name in names:
        # 名字對得上活動庫就掛上去（統計用得到），自己打的名字也照樣加得進來
        row_def = definition or _definition_for_name(name)
        defaults = row_def.defaults_payload() if row_def else {}

        def field(key):
            # 一次加多項時，逐項的細節照活動庫的預設值走
            if single:
                return request.POST.get(key, "").strip()
            return defaults.get(key, "")

        SessionActivity.objects.create(
            session=session,
            block=block,
            order=order,
            definition=row_def,
            name=name,
            sets=field("sets"),
            reps=field("reps"),
            distance=field("distance"),
            weight=field("weight"),
            intensity=field("intensity"),
            rest=field("rest"),
            key_points=field("key_points"),
            note=request.POST.get("note", "").strip() if single else "",
            created_by=request.user,
        )
        order += 1
        added.append(name)
        if row_def is not None:
            ActivityDefinition.objects.filter(pk=row_def.pk).update(
                use_count=F("use_count") + 1
            )

    msg = _("已加入 %(v0)s 到%(v1)s。") % {"v0": '、'.join(added), "v1": BlockType(block).label}
    msg += _("（要記這一項的數據，按那一行的「登記錄」）")
    messages.success(request, msg)


def _definition_for_name(name):
    """用中文或英文名字在活動庫裡找一項活動。"""
    return (
        ActivityDefinition.objects.filter(name__iexact=name).first()
        or ActivityDefinition.objects.filter(name_en__iexact=name).first()
    )


def _new_definition(request, session):
    """把一個新的訓練活動寫進名稱庫，之後所有課表都挑得到。"""
    name = request.POST.get("name", "").strip()
    if not name:
        messages.error(request, _("請填活動名稱。"))
        return
    block = request.POST.get("default_block")
    if block not in BlockType.values:
        block = BlockType.WARMUP

    # 動作歸在項目庫的哪個運動項目底下；分類（決定數據分析的範疇）跟著項目走
    discipline = Discipline.objects.filter(pk=request.POST.get("discipline")).first()
    kind = MovementKind.objects.filter(pk=request.POST.get("movement_kind")).first()
    category = request.POST.get("category")
    if discipline is not None:
        category = discipline.activity_category
    if category not in ActivityCategory.values:
        category = ActivityCategory.WARMUP

    definition, created = ActivityDefinition.objects.get_or_create(
        name=name,
        defaults={
            "default_block": block,
            "category": category,
            "discipline": discipline,
            "movement_kind": kind,
            # 加進項目庫的東西要管理員確認過才會公開；管理員自己加的就直接生效
            "status": (
                LibraryStatus.APPROVED
                if is_library_admin(request.user)
                else LibraryStatus.PENDING
            ),
            "name_en": request.POST.get("name_en", "").strip(),
            "default_sets": request.POST.get("sets", "").strip(),
            "default_reps": request.POST.get("reps", "").strip(),
            "default_distance": request.POST.get("distance", "").strip(),
            "default_weight": request.POST.get("weight", "").strip(),
            "default_intensity": request.POST.get("intensity", "").strip(),
            "default_rest": request.POST.get("rest", "").strip(),
            "default_key_points": request.POST.get("key_points", "").strip(),
            "created_by": request.user,
        },
    )
    if created and definition.is_approved:
        messages.success(request, _("已新增訓練活動「%(v0)s」，以後可以直接挑。") % {"v0": name})
    elif created:
        messages.success(
            request,
            _("已把「%(v0)s」送進運動練習項目庫，等管理員確認後所有人都挑得到；在那之前只有你自己看得到。") % {"v0": name},
        )
    else:
        messages.info(request, _("「%(v0)s」已經在活動清單裡了。") % {"v0": name})

    if request.POST.get("also_add"):
        post = request.POST.copy()
        post["definition"] = str(definition.id)
        post["block"] = definition.default_block
        request.POST = post
        _add_activity(request, session)


# ------------------------------------------ 區塊 program（一區內容存起來重用）


ACTIVITY_VALUE_FIELDS = ("sets", "reps", "distance", "weight", "intensity", "rest", "key_points")


def _spawn_activity(request, session, block, order, name, values, definition=None):
    """在課表某一區寫入一列活動（純排課，數據那邊不動）。"""
    return SessionActivity.objects.create(
        session=session,
        block=block,
        order=order,
        definition=definition,
        name=name,
        created_by=request.user,
        **{key: values.get(key, "") for key in ACTIVITY_VALUE_FIELDS},
    )


def visible_block_programs(user):
    """看得到哪些 program：存下來的全隊共用，誰排好的熱身別人都套得到。"""
    return (
        BlockProgram.objects.select_related("created_by")
        .prefetch_related("items")
        .order_by("block", "-use_count", "name")
    )


def _block_programs_by_block(user):
    grouped = {value: [] for value in BlockType.values}
    for program in visible_block_programs(user):
        grouped.setdefault(program.block, []).append(program)
    return grouped


def _save_block_program(request, session):
    """把某一區現在排好的活動存成 program，下一課同一區可以整組套用。"""
    block = request.POST.get("block")
    if block not in BlockType.values:
        messages.error(request, _("不認得的課表區塊。"))
        return

    label = BlockType(block).label
    rows = list(session.activities.filter(block=block).order_by("order", "id"))
    if not rows:
        messages.error(request, _("%(v0)s這一區還沒有活動，先加幾項再存成 program。") % {"v0": label})
        return

    name = (request.POST.get("program_name", "").strip() or f"{session.title} · {label}")[:120]
    program, created = BlockProgram.objects.update_or_create(
        created_by=request.user,
        block=block,
        name=name,
        defaults={
            "session_type": session.session_type,
            "note": request.POST.get("program_note", "").strip()[:200],
        },
    )
    program.items.all().delete()
    BlockProgramItem.objects.bulk_create(
        [
            BlockProgramItem(
                program=program,
                order=i,
                definition=row.definition,
                name=row.name,
                **{key: getattr(row, key) for key in ACTIVITY_VALUE_FIELDS},
            )
            for i, row in enumerate(rows, start=1)
        ]
    )
    if created:
        messages.success(
            request,
            _("已把%(v0)s的 %(v1)s 項活動存成 program「%(v2)s」，下一課在同一區挑它就整組帶進去。")
            % {"v0": label, "v1": len(rows), "v2": program.name},
        )
    else:
        messages.success(
            request,
            _("已更新 program「%(v0)s」，現在是 %(v1)s 項活動。") % {"v0": program.name, "v1": len(rows)},
        )


def _apply_block_program(request, session):
    """把一個存好的 program 整組寫進課表的同一區。"""
    program = (
        visible_block_programs(request.user)
        .filter(pk=request.POST.get("program"))
        .first()
    )
    if program is None:
        messages.error(request, _("找不到這個 program，重新整理看看。"))
        return

    block = program.block
    label = BlockType(block).label
    items = list(program.items.all())
    if not items:
        messages.error(request, _("program「%(v0)s」裡沒有活動。") % {"v0": program.name})
        return

    cleared, kept = 0, 0
    if request.POST.get("replace"):
        for activity in session.activities.filter(block=block):
            if liveedit.can_delete(activity, request.user):
                activity.delete()
                cleared += 1
            else:
                kept += 1

    last = session.activities.filter(block=block).order_by("-order").first()
    order = (last.order + 1) if last else 1
    for item in items:
        _spawn_activity(
            request,
            session,
            block,
            order,
            item.name,
            {key: getattr(item, key) for key in ACTIVITY_VALUE_FIELDS},
            definition=item.definition,
        )
        order += 1

    BlockProgram.objects.filter(pk=program.pk).update(use_count=F("use_count") + 1)

    msg = _("已把 program「%(v0)s」的 %(v1)s 項活動加進%(v2)s。") % {
        "v0": program.name, "v1": len(items), "v2": label}
    if cleared:
        msg += _("（先清掉原有的 %(v0)s 項）") % {"v0": cleared}
    if kept:
        msg += _("（有 %(v0)s 項是別人寫的，清不掉，留在原位）") % {"v0": kept}
    messages.success(request, msg)


def _delete_block_program(request):
    program = BlockProgram.objects.filter(pk=request.POST.get("program")).first()
    if program is None:
        messages.error(request, _("這個 program 已經不在了。"))
        return
    if not (liveedit.is_admin(request.user) or program.created_by_id == request.user.id):
        messages.error(request, _("只有建立者（或管理員）可以刪掉這個 program。"))
        return
    name = program.name
    program.delete()
    messages.success(request, _("已刪除 program「%(v0)s」。") % {"v0": name})


def _add_note(request, session):
    body = request.POST.get("body", "").strip()
    if not body:
        messages.error(request, _("記事不能是空的。"))
        return
    kind = request.POST.get("kind")
    SessionNote.objects.create(
        session=session,
        author=request.user,
        kind=kind if kind in NoteKind.values else NoteKind.NOTE,
        body=body,
    )
    messages.success(request, _("已寫入，同一版面的教練與運動員都看得到。"))


def _delete_row(request, model, pk, label):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        messages.error(request, _("這筆%(v0)s已經不在了。") % {"v0": label})
        return
    if not liveedit.can_delete(obj, request.user):
        messages.error(request, _("只能刪自己寫下的%(v0)s。") % {"v0": label})
        return
    obj.delete()
    messages.success(request, _("已刪除這筆%(v0)s。") % {"v0": label})


# --------------------------------------------------- 點格子即改 / 即時同步


@login_required
@require_POST
def inline_edit(request):
    """畫面上任何一格按下去改完之後的落點。

    body: {"target": "activity:12:reps", "value": "15"}
    回 {"ok": true, "display": "15", …}，前端拿 display 直接寫回那一格。
    """
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": _("看不懂的請求格式。")}, status=400)

    parts = str(payload.get("target", "")).split(":")
    if len(parts) != 3:
        return JsonResponse({"ok": False, "error": _("看不懂要改哪一格。")}, status=400)
    key, pk, field_name = parts

    try:
        obj, display = liveedit.apply_edit(
            request.user, key, pk, field_name, payload.get("value", "")
        )
    except liveedit.EditDenied as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=403)
    except liveedit.EditError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    session = liveedit.session_of(obj)
    return JsonResponse(
        {
            "ok": True,
            "display": display,
            "version": session.content_version,
            "session_load": session.session_load,
            "session_id": session.id,
        }
    )


@login_required
def session_live(request, pk):
    """輪詢用：版本沒變只回 changed=false，變了才把整段課表內容重畫送回去。"""
    session = _visible_session(request, pk)
    version = session.content_version
    if request.GET.get("v") == version:
        return JsonResponse({"changed": False, "version": version})
    html = render_to_string(
        "web/_session_body.html", _session_context(request, session), request=request
    )
    return JsonResponse({"changed": True, "version": version, "html": html})


@login_required
def calendar_live(request):
    """輪詢用：日曆上有人改過（含把課表拖到別的日期）就把整個月的格子送回去。"""
    athlete = _current_athlete(request)
    if athlete is None:
        return JsonResponse({"changed": False, "version": ""})
    ctx = _calendar_context(athlete, request)
    if request.GET.get("v") == ctx["cal_version"]:
        return JsonResponse({"changed": False, "version": ctx["cal_version"]})
    html = render_to_string("web/_calendar_grid.html", ctx, request=request)
    return JsonResponse({"changed": True, "version": ctx["cal_version"], "html": html})


# ------------------------------------------------------------------ 分析


@login_required
def analytics_view(request):
    """數據分析。

    上半部是訓練負荷（沿用 ACWR / Monotony 那套），
    下半部是「接著日曆的 program 做出來的數據紀錄」——分比賽、田徑練習、
    重量三個範疇，每個範疇有內建項目，教練也能自己加項目，
    系統再依這些紀錄自動算趨勢與建議。
    """
    athlete = _current_athlete(request)
    if athlete is None:
        return render(request, "web/no_athlete.html", {"page": "analytics"})

    ensure_builtin_items()
    ensure_activity_library()

    # ---- 新增項目 / 新增紀錄 ----
    if request.method == "POST":
        action = request.POST.get("action")
        back = f"{request.path}?athlete={athlete.id}&domain={request.POST.get('domain', '')}"

        if action == "add_item":
            name = request.POST.get("name", "").strip()
            domain = request.POST.get("domain")
            # 從訓練活動庫挑：名稱、分類、單位都照活動庫帶過來
            definition = None
            if request.POST.get("definition"):
                definition = visible_definitions(request.user).filter(
                    pk=request.POST["definition"]
                ).first()
            if definition is not None and domain in MetricDomain.values:
                item = item_for_name(
                    domain,
                    definition.name,
                    user=request.user,
                    category=metric_category_for_activity(definition.category),
                    name_en=definition.name_en,
                )
                messages.success(request, _("已把「%(v0)s」加進項目清單。") % {"v0": item.display_name})
                return redirect(f"{back}&item={item.id}")

            # 直接打名稱：打得中活動庫的話，英文名與分類照活動庫帶
            match = None
            if name:
                match = (
                    ActivityDefinition.objects.filter(name__iexact=name).first()
                    or ActivityDefinition.objects.filter(name_en__iexact=name).first()
                )
            if not name:
                messages.error(request, _("請填項目名稱。"))
            elif domain not in MetricDomain.values:
                messages.error(request, _("不認得的範疇。"))
            elif "unit" not in request.POST:
                # 只打了名稱（沒展開自訂表單）：單位與方向照範疇的預設值給
                item = item_for_name(
                    domain,
                    match.name if match else name,
                    user=request.user,
                    category=(
                        metric_category_for_activity(match.category) if match else None
                    ),
                    name_en=match.name_en if match else "",
                )
                messages.success(request, _("已把「%(v0)s」加進項目清單。") % {"v0": item.display_name})
                return redirect(f"{back}&item={item.id}")
            else:
                item, created = MetricItem.objects.get_or_create(
                    domain=domain,
                    name=name,
                    defaults={
                        "unit": request.POST.get("unit", "").strip(),
                        "higher_is_better": bool(request.POST.get("higher_is_better")),
                        "name_en": (
                            request.POST.get("name_en", "").strip()
                            or (match.name_en if match else "")
                        ),
                        "category": (
                            request.POST.get("category")
                            if request.POST.get("category") in MetricCategory.values
                            else metric_category_for_activity(match.category)
                            if match
                            else MetricCategory.OTHER
                        ),
                        "created_by": request.user,
                    },
                )
                if created:
                    messages.success(request, _("已新增項目「%(v0)s」。") % {"v0": item.display_name})
                else:
                    messages.info(request, _("「%(v0)s」已經在清單裡了。") % {"v0": item.display_name})
                back += f"&item={item.id}"
            return redirect(back)

        if action == "add_track_item":
            # 田徑練習：距離是多變的，所以先挑方式、再填距離，
            # 合起來就是一個可以追蹤的項目（例：150m 反覆跑）。
            method = request.POST.get("method", "")
            if method not in TrackMethod.values:
                messages.error(request, _("請先挑一個練習方式（節奏跑／反覆跑／起跑…）。"))
                return redirect(f"{request.path}?athlete={athlete.id}&domain=TRACK")
            raw = (request.POST.get("distance_m") or "").strip()
            distance = None
            if raw:
                try:
                    distance = max(1, int(float(raw)))
                except ValueError:
                    messages.error(request, _("距離要填數字（公尺），或留空只記方式。"))
                    return redirect(f"{request.path}?athlete={athlete.id}&domain=TRACK")
            item = track_item_for(method, distance, user=request.user)
            messages.success(
                request,
                _("已把「%(v0)s」加進要追蹤的項目清單，可以開始登數據了。") % {"v0": item.display_name},
            )
            return redirect(
                f"{request.path}?athlete={athlete.id}&domain=TRACK&item={item.id}"
            )

        if action in ("pin_item", "unpin_item"):
            # 「主要必看的訓練項目」＝從下面的項目清單 pin 出來的那幾項。
            # 清單練久了會很長，每天真正要看的就那幾個動作，釘出來才不用每次翻。
            item = get_object_or_404(MetricItem, pk=request.POST.get("item_id"))
            already = athlete.pinned_items.filter(item=item).exists()
            if action == "pin_item" and not already:
                toggle_pin(athlete, item, user=request.user)
                messages.success(
                    request,
                    _("已把「%(v0)s」釘到「主要必看的訓練項目」。") % {"v0": item.display_name},
                )
            elif action == "unpin_item" and already:
                toggle_pin(athlete, item, user=request.user)
                messages.info(request, _("已取消釘選「%(v0)s」。") % {"v0": item.display_name})
            return redirect(f"{back}&item={item.id}")

        if action == "delete_item":
            item = get_object_or_404(MetricItem, pk=request.POST.get("item_id"))
            mine = MetricRecord.objects.filter(athlete=athlete, item=item)
            count = mine.count()
            if count and not request.POST.get("confirm"):
                messages.error(
                    request,
                    _("「%(v0)s」底下還有 %(v1)s 筆紀錄，要先確認才刪得掉。") % {"v0": item.display_name, "v1": count},
                )
                return redirect(f"{back}&item={item.id}")
            if item.is_builtin:
                # 內建項目留著（刪了下次開頁又會補回來），只清這名運動員的紀錄；
                # 沒有紀錄的項目本來就不會出現在清單裡
                mine.delete()
                messages.success(
                    request,
                    _("已清掉「%(v0)s」的 %(v1)s 筆紀錄；這是系統內建項目，重新記錄就會再出現。") % {"v0": item.display_name, "v1": count},
                )
            else:
                item.delete()
                messages.success(
                    request,
                    _("已刪除項目「%(v0)s」") % {"v0": item.display_name}
                    + (_("，連同 %(v0)s 筆紀錄。") % {"v0": count} if count else "。"),
                )
            return redirect(back)

        if action == "rename_item":
            # 田徑練習的項目是照課表的活動名稱開出來的，名字打錯或想寫清楚一點，
            # 不該只能刪掉重記——改名之後紀錄照樣掛在同一個項目底下。
            item = get_object_or_404(MetricItem, pk=request.POST.get("item_id"))
            ok, text = rename_item(
                item, request.POST.get("name", ""), athlete=athlete
            )
            if ok:
                messages.success(request, text)
            else:
                messages.error(request, text)
            return redirect(f"{back}&item={item.id}")

        if action == "item_unit":
            # 重量訓練以 kg 為主，撐時間的動作（平板支撐、懸垂…）可以換成秒
            item = get_object_or_404(MetricItem, pk=request.POST.get("item_id"))
            if set_item_unit(item, request.POST.get("unit", "")):
                messages.success(request, _("「%(v0)s」的單位已改成 %(v1)s。") % {"v0": item.name, "v1": item.unit})
            else:
                messages.info(request, _("單位沒有變動。"))
            return redirect(f"{back}&item={item.id}")

        if action == "add_record":
            # 沒挑項目就登不進去（or 0 是為了空字串也走 404，不要炸掉）
            item = get_object_or_404(MetricItem, pk=request.POST.get("item_id") or 0)
            session_id = request.POST.get("session") or None
            session = None
            if session_id:
                session = TrainingSession.objects.filter(
                    pk=session_id, athlete=athlete
                ).first()
            competition = None
            if request.POST.get("competition"):
                competition = Competition.objects.filter(
                    pk=request.POST["competition"]
                ).first()
            try:
                # 一次可以送多組——同一堂課的不同組，重量／次數／休息時間都不一樣，
                # 所以表單是一列一組，每一列各存成一筆紀錄。
                _created, msg = create_records(
                    athlete=athlete,
                    item=item,
                    session=session,
                    post=request.POST,
                    on_date=request.POST.get("date") or date.today(),
                    competition=competition,
                )
            except RecordError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, msg)
            return redirect(f"{back}&item={item.id}")

        if action == "edit_record":
            # 紀錄明細改完可以一次過確認全部（「儲存全部更改」），
            # 也可以只按某一列的 ✓ 單獨存那一筆（表單多送一個 only=<id>）。
            item_id = request.POST.get("item_id")
            editable = list(
                MetricRecord.objects.filter(athlete=athlete, item_id=item_id)
                .select_related("item")
            )
            only = request.POST.get("only") or None
            if only and not any(str(r.pk) == str(only) for r in editable):
                raise Http404(_("無權限修改這筆紀錄。"))

            def find_session(raw):
                """只認這名運動員自己的課，別人的 program 掛不上去。"""
                return (
                    athlete.sessions.filter(pk=raw).first()
                    if str(raw).isdigit()
                    else None
                )

            changed, problems = update_records(
                request.POST, editable, only=only, session_lookup=find_session
            )
            text = edit_message(changed, problems)
            if changed:
                messages.success(request, text)
            else:
                messages.info(request, text)
            return redirect(f"{back}&item={item_id}")

        if action == "move_record":
            # 紀錄明細裡的 ↑ ↓：把一組往前／往後挪，同一天的組號跟著重排
            # ↑ 與 ↓ 是同一張表單的兩顆送出鍵，按哪一顆就送哪一個欄位
            direction = "up" if request.POST.get("up") else "down"
            record = get_object_or_404(
                MetricRecord, pk=request.POST.get(direction) or request.POST.get("record_id")
            )
            if record.athlete_id != athlete.id:
                raise Http404(_("無權限調整這筆紀錄。"))
            if move_record(record, direction):
                messages.info(
                    request,
                    (
                        _("已把 %(date)s 的這一組往前挪。")
                        if direction == "up"
                        else _("已把 %(date)s 的這一組往後挪。")
                    ) % {"date": record.date},
                )
            else:
                messages.info(request, _("這一組已經在最") + (_("前") if direction == "up" else _("後")) + _("面了。"))
            return redirect(f"{back}&item={record.item_id}#day-{record.date}")

        if action == "delete_record":
            record = get_object_or_404(MetricRecord, pk=request.POST.get("record_id"))
            if record.athlete_id != athlete.id:
                raise Http404(_("無權限刪除這筆紀錄。"))
            item_id = record.item_id
            on_date = record.date
            record.delete()
            # 刪掉中間那一組之後，剩下的組號補回 1、2、3…
            resequence(athlete.id, item_id, on_date)
            messages.info(request, _("已刪除一筆紀錄。"))
            return redirect(f"{back}&item={item_id}")

    # ---- 訓練負荷 ----
    weeks = int(request.GET.get("weeks", 12))
    prog = an.weekly_load_progression(athlete, weeks)
    acwr = an.acwr_report(athlete)
    badge, color = RISK_CSS[acwr["risk_flag"]]
    dist = an.volume_distribution(athlete)
    week_start = an.monday_of(date.today())

    # ---- 數據紀錄 ----
    domain = request.GET.get("domain")
    if domain not in MetricDomain.values:
        domain = MetricDomain.TRACK
    requested_item = request.GET.get("item")
    item = None
    if requested_item:
        item = MetricItem.objects.filter(pk=requested_item, domain=domain).first()

    # 練習／重量：清單只留有紀錄的項目，沒挑出來的不佔版面。
    # 比賽數據不一樣——項目就是那幾個比賽項目，全部列出來直接挑著登。
    is_competition = domain == MetricDomain.COMPETITION
    overview = an.metric_overview(
        athlete,
        domain,
        used_only=not is_competition,
        keep_ids=[item.id] if item else None,
    )
    if item is None:
        with_records = [r["item"] for r in overview if r["count"]]
        item = with_records[0] if with_records else (
            overview[0]["item"] if overview else None
        )
    overview_groups = [] if is_competition else an.overview_by_category(overview)

    # 比賽數據以「一場比賽」為單位分析；其餘範疇看的是最常做的動作
    meets = an.competition_report(athlete) if is_competition else []
    competitions = (
        athlete_competitions(athlete).order_by("-date")[:60] if is_competition else []
    )

    analysis = an.metric_analysis(athlete, item) if item else None

    # 給「這筆數據來自哪一堂 program」的下拉選單。
    # 只列得出對得上這個範疇的課別——重量紀錄不會掛到田徑場的課上去。
    linkable_types = session_types_for_domain(domain)
    recent_sessions = athlete.sessions.filter(
        date__gte=date.today() - timedelta(days=90), session_type__in=linkable_types
    ).order_by("-date")[:60]

    # ---- 整體 / 分年份 / 分時期 比較 ----
    compare_modes = an.compare_modes_for(domain)
    compare = request.GET.get("compare", "all")
    if compare not in {m for m, _unused in compare_modes}:
        compare = "all"
    comparison = an.metric_comparison(athlete, item, compare) if item else None
    # 「主要必看的訓練項目」＝從項目清單釘出來的那幾項；
    # 還沒釘過的人先看「最常做的動作」，右邊的 📌 按一下就變成自己的必看清單。
    pinned = [] if is_competition else pinned_items(athlete, domain)
    pinned_ids = [i.id for i in pinned]
    tops = [] if is_competition else (
        an.movement_stats(athlete, pinned) if pinned else an.top_movements(athlete, domain)
    )
    # ---- 多個項目一起分析 ----
    # 同一個距離不同方式（150m 節奏跑 / 150m 反覆跑）、或相近的重訓動作，
    # 各自看趨勢看不出所以然，勾幾個放在一起才知道哪一種練得起來。
    picked_ids = []
    for raw in request.GET.getlist("items"):
        for part in raw.split(","):
            # isdecimal 而不是 isdigit：上標「²」這種字 isdigit() 是 True，
            # int() 卻會炸；網址是使用者改得到的東西，不能假設它乾淨。
            part = part.strip()
            if part.isdecimal() and int(part) not in picked_ids:
                picked_ids.append(int(part))
    picked_ids = picked_ids[:MULTI_ITEM_LIMIT]
    picked_items = []
    if picked_ids:
        found = {
            obj.id: obj
            for obj in MetricItem.objects.filter(id__in=picked_ids, domain=domain)
        }
        picked_items = [found[i] for i in picked_ids if i in found]

    # 一起分析是「順便看看」的功能，不該讓整頁掛掉：
    # 真的算不出來就把錯誤寫進 log、在畫面上說一句，其餘的欄位照常顯示。
    multi = None
    multi_error = ""
    multi_series = []
    if len(picked_items) > 1:
        try:
            multi = an.multi_item_analysis(athlete, picked_items)
            multi_series = multi["series"]
            jdump(multi_series)      # 先試序列化，壞掉的資料不要留到樣板才炸
        except Exception:                 # noqa: BLE001 - 什麼原因都不該讓這一頁 500
            logger.exception(
                "多項目一起分析失敗：athlete=%s domain=%s items=%s",
                athlete.id, domain, picked_ids,
            )
            multi = None
            multi_series = []
            multi_error = _("這幾個項目一起分析時出了問題，已記錄下來；先分開看各自的趨勢。")

    # 可以勾來一起分析的項目：這個範疇底下有紀錄的都列出來
    multi_choices = [row["item"] for row in overview if row["count"]]

    # ---- 「數據分析已經有相關紀錄，要不要加在一起分析」----
    # 課表上的活動按了「登記錄」就會開出一個同名項目，而清單裡常常已經有一個
    # 講同一件事的項目（150m 節奏跑／150m 反覆跑）。分開看看不出所以然，
    # 所以在項目分析上面問一句；已經在一起分析的時候就不再問。
    related = [] if len(picked_items) > 1 else an.related_items(athlete, item)
    related_csv = ",".join(
        str(i)
        for i in ([item.id] + [r["item"].id for r in related])[:MULTI_ITEM_LIMIT]
    ) if related else ""

    # ---- 體組成 × 重量訓練 ----
    # 脂肪比例、肌肉比例、體重與「每公斤體重舉得起多少」擺在一起看，
    # 再推演體脂降下來／去脂體重加上去之後，比值會變成多少。
    # 這一段只在重量訓練範疇出現——田徑練習那邊看的是跑的數字，
    # 擺體組成只會佔版面，順便也省下這幾個算不便宜的查詢。
    is_strength = domain == MetricDomain.STRENGTH
    body_strength = bs.strength_ratio_report(athlete) if is_strength else bs.empty_report(athlete)
    # 自己填一組假設的體重／體脂，看重訓的數字與該用的訓練重量變成怎樣
    body_whatif = bs.custom_plan(
        body_strength, request.GET.get("wf_weight"), request.GET.get("wf_fat")
    ) if is_strength else None

    # ---- 多面向分析：動作重量 × 肌肉脂肪比例 × 訓練時間 ----
    # 分訓練時期或分年份切開，同一段時間的三件事擺在同一列上比。
    dims = dim.multi_dimension_report(
        athlete, request.GET.get("dmode", "phase")
    ) if is_strength else None

    return render(
        request,
        "web/analytics.html",
        {
            "page": "analytics",
            "athlete": athlete,
            "athletes": _athlete_switcher(request),
            "acwr": acwr,
            "acwr_badge": badge,
            "acwr_color": color,
            "monotony": an.calculate_monotony(athlete, week_start),
            "strain": an.calculate_strain(athlete, week_start),
            "wow": an.week_over_week_change(athlete, week_start),
            "weeks": weeks,
            "labels": jdump([p["label"] for p in prog]),
            "loads": jdump([p["total_load"] for p in prog]),
            "acwrs": jdump([p["acwr"] for p in prog]),
            "monotonies": jdump([p["monotony"] for p in prog]),
            "dist_labels": jdump([d["type"] for d in dist]),
            "dist_values": jdump([d["load"] for d in dist]),
            "dist": dist,
            # 數據紀錄
            "domains": MetricDomain.choices,
            "domain": domain,
            "domain_label": dict(MetricDomain.choices)[domain],
            "overview": overview,
            "overview_groups": overview_groups,
            "is_competition": is_competition,
            "meets": meets,
            "competitions": competitions,
            "metric_categories": MetricCategory.choices,
            # 每一筆紀錄都可以註記當天的狀態（傷害治療期…），分析前先看這一欄
            "metric_statuses": TrainingStatus.choices,
            # 這一組數據放回課表的哪一段（熱身／正課／補充練習／恢復練習）
            "metric_blocks": block_choices(),
            # 重量訓練以 kg 為主，撐時間的動作可以把單位換成秒
            "strength_units": STRENGTH_UNITS,
            # 田徑練習：先挑方式、再填距離
            "track_methods": track_method_choices(),
            "item": item,
            "item_record_count": (
                MetricRecord.objects.filter(athlete=athlete, item=item).count()
                if item
                else 0
            ),
            "analysis": analysis,
            # 單位就是 kg 的項目（背蹲舉 1RM…），數值＝重量，表單不再重複問一次
            "unit_is_weight": bool(item and (item.unit or "").strip().lower() == "kg"),
            # 田徑練習用「強度要求」取代重量欄；重量訓練維持原樣
            "is_track": domain == MetricDomain.TRACK,
            "chart_points": jdump(analysis["points"] if analysis else []),
            "recent_sessions": recent_sessions,
            "linkable_type_labels": [
                dict(SessionType.choices)[t] for t in linkable_types
            ],
            "today_iso": date.today().isoformat(),
            # 主要必看的訓練項目（沒釘過就先給最常做的動作）+ 整體／年份／時期比較
            "tops": tops,
            "pinned_ids": pinned_ids,
            "has_pins": bool(pinned),
            # 多項目一起分析
            "multi": multi,
            "multi_choices": multi_choices,
            "picked_ids": picked_ids,
            "picked_csv": ",".join(str(i) for i in picked_ids),
            "multi_series": jdump(multi_series),
            "multi_error": multi_error,
            # 「已經有相關紀錄，要不要加在一起分析」那一句提問
            "related": related,
            "related_csv": related_csv,
            "compare": comparison["mode"] if comparison else "all",
            "compare_modes": compare_modes,
            "comparison": comparison,
            # 體組成 × 重量訓練比值（只在重量訓練範疇顯示）
            "is_strength": is_strength,
            "body_strength": body_strength,
            # 多面向分析：動作重量 × 體組成 × 訓練時間
            "dims": dims,
            "dim_labels": jdump([g["label"] for g in dims["groups"]] if dims else []),
            "dim_hours": jdump([g["hours"] for g in dims["groups"]] if dims else []),
            "dim_fat": jdump([g["fat_pct"] for g in dims["groups"]] if dims else []),
            "dim_muscle": jdump([g["muscle_pct"] for g in dims["groups"]] if dims else []),
            "dim_per_bw": jdump([g["avg_per_bw"] for g in dims["groups"]] if dims else []),
            "dim_tonnage": jdump([g["tonnage"] for g in dims["groups"]] if dims else []),
            "body_whatif": body_whatif,
            "bs_labels": jdump([p["date"] for p in body_strength["series"]]),
            "bs_per_bw": jdump([p["per_bw"] for p in body_strength["series"]]),
            "bs_fat": jdump([p["fat_pct"] for p in body_strength["series"]]),
            "bs_weight": jdump([p["weight"] for p in body_strength["series"]]),
            "phase_guide": PHASE_GUIDE,
            "cmp_labels": jdump(
                [g["label"] for g in comparison["groups"]] if comparison else []
            ),
            "cmp_best": jdump(
                [g["best"] for g in comparison["groups"]] if comparison else []
            ),
            "cmp_avg": jdump(
                [g["average"] for g in comparison["groups"]] if comparison else []
            ),
            "cmp_count": jdump(
                [g["count"] for g in comparison["groups"]] if comparison else []
            ),
        },
    )


# ------------------------------------------------------------------ 營養


@login_required
def nutrition_view(request):
    athlete = _current_athlete(request)
    if athlete is None:
        return render(request, "web/no_athlete.html", {"page": "nutrition"})

    today = date.today()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "morning":
            RecoveryLog.objects.update_or_create(
                athlete=athlete,
                date=today,
                defaults={
                    "sleep_hours": request.POST.get("sleep_hours") or None,
                    "sleep_quality": request.POST.get("sleep_quality") or None,
                    "soreness_level": request.POST.get("soreness_level") or None,
                    "stress_level": request.POST.get("stress_level") or None,
                    "mood": request.POST.get("mood") or None,
                    "resting_hr": request.POST.get("resting_hr") or None,
                    "water_intake_ml": request.POST.get("water_intake_ml") or 0,
                },
            )
            messages.success(request, _("已儲存今日晨間問卷。"))
        elif action == "recalc":
            nu.calculate_targets(athlete, today, goal=request.POST.get("goal", "MAINTAIN"))
            messages.success(request, _("已重新計算今日營養目標。"))
            # 從數據分析帶過來的自訂目標要留著，不然算完就掉了
            if request.POST.get("goal_weight") or request.POST.get("goal_fat"):
                params = urlencode(
                    {
                        k: request.POST.get(k, "")
                        for k in ("goal_weight", "goal_fat")
                        if request.POST.get(k)
                    }
                )
                return redirect(f"{reverse('web:nutrition')}?{params}#bodygoal")
        elif action == "meal_add":
            _save_meal(request, athlete)
        elif action == "meal_regrams":
            _regrams_meal(request, athlete)
        elif action == "meal_delete":
            meal = get_object_or_404(MealLog, pk=request.POST["meal_id"], athlete=athlete)
            meal.delete()
            messages.success(request, _("已刪除該筆飲食紀錄。"))
        return redirect("web:nutrition")

    target = NutritionTarget.objects.filter(athlete=athlete, date=today).first()
    if target is None:
        target = nu.calculate_targets(athlete, today)

    recovery = RecoveryLog.objects.filter(athlete=athlete, date=today).first()
    week_start = an.monday_of(today)
    compliance = nu.weekly_compliance(athlete, week_start)

    sleep_rows = list(
        RecoveryLog.objects.filter(athlete=athlete, date__gte=today - timedelta(days=13))
        .order_by("date")
        .values("date", "sleep_hours", "soreness_level")
    )

    split = target.macro_kcal_split
    meals = list(MealLog.objects.filter(athlete=athlete, date=today))
    plan = nu.supplement_plan(athlete, today, target=target)
    insight = nu.body_composition_insight(athlete, target=target)
    # 數據分析算出「體脂與體重該往哪走」，這裡翻成今天餐桌上的數字
    body_goal = nu.body_goal_plan(
        athlete,
        target=target,
        custom=(request.GET.get("goal_weight"), request.GET.get("goal_fat")),
    )

    return render(
        request,
        "web/nutrition.html",
        {
            "page": "nutrition",
            "athlete": athlete,
            "athletes": _athlete_switcher(request),
            "t": target,
            "recovery": recovery,
            "readiness": an.readiness_score(athlete),
            "compliance": compliance,
            "methods": RecoveryMethod.objects.all(),
            "supplements": nu.COMMON_SUPPLEMENTS,
            "meals": meals,
            "meal_types": MealType.choices,
            "goals": NutritionGoal.choices,
            "eaten": target.actual_intake(),
            "plan": plan,
            "insight": insight,
            "body_goal": body_goal,
            "photo_ai": nuvision.api_available(),
            "today": today,
            "macro_labels": jdump([_("碳水"), _("蛋白質"), _("脂肪")]),
            "macro_values": jdump([split["carb"], split["protein"], split["fat"]]),
            "sleep_labels": jdump([r["date"].strftime("%m/%d") for r in sleep_rows]),
            "sleep_values": jdump(
                [float(r["sleep_hours"]) if r["sleep_hours"] else None for r in sleep_rows]
            ),
            "soreness_values": jdump([r["soreness_level"] for r in sleep_rows]),
        },
    )


def _save_meal(request, athlete):
    """上傳一餐：有相片就交給辨識，沒有就用文字比對食物字典。"""
    photo = request.FILES.get("photo")
    description = request.POST.get("description", "").strip()
    if not photo and not description:
        messages.warning(request, _("請上傳相片或至少寫下吃了什麼。"))
        return

    image_bytes = photo.read() if photo else None
    if photo:
        photo.seek(0)
    result = nuvision.analyze_meal(
        image_bytes=image_bytes,
        filename=getattr(photo, "name", ""),
        description=description,
        athlete=athlete,
    )
    total = nuvision.totals(result["items"])
    meal = MealLog.objects.create(
        athlete=athlete,
        date=request.POST.get("date") or date.today(),
        meal_type=request.POST.get("meal_type", MealType.LUNCH),
        description=description or result["summary"],
        kcal=total["kcal"],
        carb_g=total["carb_g"],
        protein_g=total["protein_g"],
        fat_g=total["fat_g"],
        fiber_g=total["fiber_g"],
        sodium_mg=total["sodium_mg"],
        photo=photo,
        items=result["items"],
        analysis_source=result["source"],
        analysis_note="\n".join(x for x in (result["summary"], result["assessment"]) if x),
    )
    if result["error"]:
        messages.warning(request, result["error"])
    if meal.kcal:
        messages.success(
            request,
            _("已記錄%(v0)s：%(v1)s kcal（碳水 %(v2)sg／蛋白 %(v3)sg／脂肪 %(v4)sg）。") % {"v0": meal.get_meal_type_display(), "v1": meal.kcal, "v2": meal.carb_g, "v3": meal.protein_g, "v4": meal.fat_g},
        )
    else:
        messages.warning(
            request,
            _("認不出食物，紀錄已建立但營養值是 0——可以在下面直接改份量，或用「白飯 200g、雞胸 150g」這種寫法再試一次。"),
        )


def _regrams_meal(request, athlete):
    """調整某一品項的公克數，其餘營養值按比例重算。"""
    meal = get_object_or_404(MealLog, pk=request.POST["meal_id"], athlete=athlete)
    items = list(meal.items or [])
    keys = ("kcal", "carb_g", "protein_g", "fat_g", "fiber_g", "sodium_mg")
    changed = 0
    for idx, row in enumerate(items):
        raw = request.POST.get(f"grams_{idx}")
        if raw in (None, ""):
            continue
        try:
            grams = max(float(raw), 0)
        except ValueError:
            continue
        old = float(row.get("grams") or 0)
        if not old or abs(grams - old) < 0.5:
            continue
        ratio = grams / old
        row["grams"] = round(grams)
        for k in keys:
            row[k] = round(float(row.get(k) or 0) * ratio, 1)
        changed += 1

    if not changed:
        messages.warning(request, _("份量沒有變動。"))
        return

    total = nuvision.totals(items)
    meal.items = items
    meal.kcal = total["kcal"]
    meal.carb_g = total["carb_g"]
    meal.protein_g = total["protein_g"]
    meal.fat_g = total["fat_g"]
    meal.fiber_g = total["fiber_g"]
    meal.sodium_mg = total["sodium_mg"]
    meal.save(
        update_fields=[
            "items", "kcal", "carb_g", "protein_g", "fat_g",
            "fiber_g", "sodium_mg", "updated_at",
        ]
    )
    messages.success(request, _("已更新 %(v0)s 個品項的份量，總熱量 %(v1)s kcal。") % {"v0": changed, "v1": meal.kcal})


# ------------------------------------------------------------------ 傷患


def _split_training_note(note):
    """訓練備註存成「勾選的現場處置步驟｜自己寫的一句話」，讀回來時拆成兩截。"""
    if "｜" in note:
        picked, free = note.split("｜", 1)
        return [p for p in picked.split("、") if p], free
    return [], note


def _compose_training_note(request):
    """把勾選的處置步驟與自由文字合成一欄；沒勾任何一項就只留文字。"""
    steps = [s for s in request.POST.getlist("care_step") if s]
    free = request.POST.get("training_note", "").strip()
    if not steps:
        return free
    return "、".join(steps) + "｜" + free


def _log_pain(request, athlete, injury, prefix="", quiet=False):
    """寫一筆今日疼痛紀錄。prefix 讓「一次回報全部」用得上同一段邏輯。"""

    def val(name, cast=int, default=None):
        raw = request.POST.get(f"{name}{prefix}")
        if raw in (None, ""):
            return default
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return default

    log, _unused = PainLog.objects.update_or_create(
        injury=injury,
        date=date.today(),
        defaults={
            "pain_before": val("pain_before"),
            "pain_at_rest": val("pain_at_rest", default=0),
            "pain_during_activity": val("pain_during_activity", default=0),
            "pain_after_session": val("pain_after_session"),
            "load_intensity": val("load_intensity"),
            "load_volume": request.POST.get(f"load_volume{prefix}", "")[:120],
            "day_action": request.POST.get(f"day_action{prefix}", ""),
            "swelling": bool(request.POST.get(f"swelling{prefix}")),
            "rom_limited": bool(request.POST.get(f"rom_limited{prefix}")),
            "note": request.POST.get(f"note{prefix}", ""),
        },
    )
    if log.blocks_high_intensity:
        n = 0
        for session in athlete.sessions.filter(date=date.today()):
            n += len(inj.apply_modifications(session))
        messages.warning(
            request,
            _("%(v0)s 疼痛 %(v1)s/10 已超過門檻，今日課表已自動調整（%(v2)s 項變更）。") % {"v0": injury.get_body_part_display(), "v1": log.pain_during_activity, "v2": n},
        )
    elif not quiet:
        messages.success(request, _("已記錄今日疼痛。"))
    return log


@login_required
def injuries_view(request):
    athlete = _current_athlete(request)
    if athlete is None:
        return render(request, "web/no_athlete.html", {"page": "injuries"})

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "new_injury":
            injury = Injury.objects.create(
                athlete=athlete,
                body_part=request.POST["body_part"],
                side=request.POST.get("side", "NA"),
                injury_type=request.POST["injury_type"],
                onset_date=request.POST["onset_date"],
                severity=int(request.POST.get("severity", 1)),
                mechanism=request.POST.get("mechanism", ""),
            )
            inj.sync_athlete_status(athlete)
            messages.success(request, _("已建立傷患紀錄：%(v0)s") % {"v0": injury.get_body_part_display()})
        elif action == "pain_log":
            injury = get_object_or_404(Injury, pk=request.POST["injury_id"], athlete=athlete)
            _log_pain(request, athlete, injury, prefix="")
        elif action == "daily_report":
            # 一次把所有進行中的傷患都回報完，運動員不用一張表填一次。
            done = 0
            for injury in athlete.injuries.all():
                if not injury.is_active:
                    continue
                if request.POST.get(f"pain_during_activity_{injury.id}") in (None, ""):
                    continue
                _log_pain(request, athlete, injury, prefix=f"_{injury.id}", quiet=True)
                done += 1
            if done:
                messages.success(request, _("已回報 %(v0)s 處傷患的今日狀況。") % {"v0": done})
            else:
                messages.warning(request, _("沒有填任何一處的今日疼痛。"))
        elif action == "set_training_mode":
            injury = get_object_or_404(Injury, pk=request.POST["injury_id"], athlete=athlete)
            injury.training_mode = request.POST.get("training_mode", TrainingMode.MODIFIED)
            injury.training_note = _compose_training_note(request)[:200]
            injury.save(update_fields=["training_mode", "training_note", "updated_at"])
            messages.success(
                request,
                _("%(v0)s 今日處理方式：%(v1)s。") % {"v0": injury.get_body_part_display(), "v1": injury.get_training_mode_display()},
            )
        elif action == "rtp_toggle":
            injury = get_object_or_404(Injury, pk=request.POST["injury_id"], athlete=athlete)
            done = {int(x) for x in request.POST.getlist("rtp")}
            injury.rtp_progress = sorted(done)
            injury.save(update_fields=["rtp_progress", "updated_at"])
            rtp = inj.rtp_checklist(injury)
            if rtp["cleared"]:
                messages.success(request, _("RTP 條件全部達標，可與教練確認回歸完整訓練。"))
            else:
                messages.success(
                    request, _("已更新 RTP 進度：%(v0)s/%(v1)s 項達標。") % {"v0": rtp['met'], "v1": rtp['total']}
                )
        elif action == "update_status":
            injury = get_object_or_404(Injury, pk=request.POST["injury_id"], athlete=athlete)
            injury.status = request.POST["status"]
            injury.save(update_fields=["status", "updated_at"])
            inj.sync_athlete_status(athlete)
            messages.success(request, _("已更新狀態為 %(v0)s。") % {"v0": injury.get_status_display()})
        elif action == "set_direction":
            injury = get_object_or_404(Injury, pk=request.POST["injury_id"], athlete=athlete)
            injury.treatment_status = request.POST.get(
                "treatment_status", TreatmentStage.ASSESS
            )
            injury.treatment_direction = request.POST.get("treatment_direction", "")
            injury.next_review_date = request.POST.get("next_review_date") or None
            injury.diagnosis = request.POST.get("diagnosis", injury.diagnosis)
            injury.practitioner = request.POST.get("practitioner", injury.practitioner)
            injury.save(
                update_fields=[
                    "treatment_status",
                    "treatment_direction",
                    "next_review_date",
                    "diagnosis",
                    "practitioner",
                    "updated_at",
                ]
            )
            messages.success(
                request, _("已更新治療方向：%(v0)s。") % {"v0": injury.get_treatment_status_display()}
            )
        elif action == "treatment_log":
            injury = get_object_or_404(Injury, pk=request.POST["injury_id"], athlete=athlete)
            log = TreatmentLog.objects.create(
                injury=injury,
                date=request.POST.get("date") or date.today(),
                treatment_type=request.POST["treatment_type"],
                provider=request.POST.get("provider", ""),
                content=request.POST.get("content", ""),
                effect=int(request.POST.get("effect", TreatmentEffect.SAME)),
                pain_after=request.POST.get("pain_after") or None,
                next_step=request.POST.get("next_step", ""),
                cost_hkd=request.POST.get("cost_hkd") or None,
            )
            messages.success(
                request,
                _("已記錄 %(v0)s 的%(v1)s（%(v2)s）。") % {"v0": log.date, "v1": log.get_treatment_type_display(), "v2": log.get_effect_display()},
            )
        return redirect("web:injuries")

    injuries = list(athlete.injuries.all())
    active = [i for i in injuries if i.is_active]

    detail = []
    for i in active:
        trend = i.pain_trend(28)
        picked, free = _split_training_note(i.training_note)
        detail.append(
            {
                "injury": i,
                "rtp": inj.rtp_checklist(i),
                "direction": inj.suggest_treatment_direction(i),
                "treatments": inj.treatment_summary(i),
                "peace_love": inj.peace_love_guide(i),
                "care_picked": picked,
                "care_free": free,
                "labels": jdump([r["date"].strftime("%m/%d") for r in trend]),
                "rest": jdump([r["pain_at_rest"] for r in trend]),
                "activity": jdump([r["pain_during_activity"] for r in trend]),
                "today_log": i.pain_logs.filter(date=date.today()).first(),
            }
        )
    detail.sort(key=lambda d: -d["injury"].priority)

    team_mode = inj.team_training_mode(active)

    blocked, reason = inj.should_block_high_intensity(athlete)

    return render(
        request,
        "web/injuries.html",
        {
            "page": "injuries",
            "athlete": athlete,
            "athletes": _athlete_switcher(request),
            "injuries": injuries,
            "detail": detail,
            "board": inj.injury_board(active),
            "team_mode": team_mode,
            "team_mode_label": dict(TrainingMode.choices).get(team_mode, ""),
            "team_mode_guide": TRAINING_MODE_GUIDE.get(team_mode, {}),
            "training_modes": TrainingMode.choices,
            "resolved": [i for i in injuries if not i.is_active],
            "blocked": blocked,
            "block_reason": reason,
            "body_parts": Injury._meta.get_field("body_part").choices,
            "sides": Injury._meta.get_field("side").choices,
            "injury_types": Injury._meta.get_field("injury_type").choices,
            "statuses": Injury._meta.get_field("status").choices,
            "treatment_stages": TreatmentStage.choices,
            "treatment_types": TreatmentType.choices,
            "treatment_effects": TreatmentEffect.choices,
            "day_actions": DayAction.choices,
            "today": date.today(),
        },
    )


# ---------------------------------------------------------- 運動練習項目庫


#: 項目庫上「確認 / 退回」按鈕作用在哪一張表
LIBRARY_MODELS = {
    "sport": (SportType, _("運動種類")),
    "discipline": (Discipline, _("運動項目")),
    "kind": (MovementKind, _("訓練動作種類")),
    "activity": (ActivityDefinition, _("動作")),
}


def _library_object(request):
    """把表單送來的 model + id 換成物件（認不得就回 (None, None)）。"""
    model, label = LIBRARY_MODELS.get(request.POST.get("model"), (None, None))
    if model is None:
        return None, None
    return model.objects.filter(pk=request.POST.get("id")).first(), label


@login_required
def library_view(request):
    """運動練習項目庫。

    全站「有哪些動作可以練」的唯一來源：課表挑得到的活動、數據分析追蹤得到
    的項目，都是從這裡出去的。分四層看——運動種類 → 運動項目 →
    訓練動作種類 → 動作，動作底下寫著它在做什麼（動作說明）與預設的
    組數／次數／休息。

    教練、運動員、管理員都可以往裡面加東西，但加進來的先掛「待確認」，
    管理員按確認之後才會永久出現在項目庫、別人才挑得到。
    """
    ensure_activity_library()
    can_approve = is_library_admin(request.user)

    if request.method == "POST":
        action = request.POST.get("action")
        back = (
            f"{request.path}?sport={request.POST.get('sport_id', '')}"
            f"&discipline={request.POST.get('discipline_id', '')}"
        )
        # 自己加的東西自己看得到（掛著「待確認」），但要管理員按過才會公開。
        # 管理員自己加的就直接算確認過，不用再確認自己一次。
        status = LibraryStatus.APPROVED if can_approve else LibraryStatus.PENDING
        pending_note = "" if can_approve else _("，等管理員確認後所有人都看得到")

        if action in ("approve", "reject"):
            if not can_approve:
                messages.error(request, _("只有管理員可以確認項目庫的新增內容。"))
                return redirect(back)
            obj, label = _library_object(request)
            if obj is None:
                messages.error(request, _("找不到要處理的項目。"))
            elif action == "approve":
                obj.status = LibraryStatus.APPROVED
                obj.save(update_fields=["status", "updated_at"])
                messages.success(request, _("已確認%(v0)s「%(v1)s」，現在所有人都看得到。") % {"v0": label, "v1": obj.name})
            else:
                obj.status = LibraryStatus.REJECTED
                obj.save(update_fields=["status", "updated_at"])
                messages.info(request, _("已退回%(v0)s「%(v1)s」。") % {"v0": label, "v1": obj.name})
            return redirect(back)

        if action == "add_sport":
            name = request.POST.get("name", "").strip()
            if not name:
                messages.error(request, _("請填運動種類的名稱。"))
            elif SportType.objects.filter(name=name).exists():
                messages.info(request, _("「%(v0)s」已經在項目庫裡了。") % {"v0": name})
            else:
                SportType.objects.create(
                    name=name,
                    name_en=request.POST.get("name_en", "").strip(),
                    note=request.POST.get("note", "").strip(),
                    status=status,
                    created_by=request.user,
                )
                messages.success(request, _("已加入運動種類「%(v0)s」%(v1)s。") % {"v0": name, "v1": pending_note})
            return redirect(back)

        if action == "add_discipline":
            sport = SportType.objects.filter(pk=request.POST.get("sport")).first()
            name = request.POST.get("name", "").strip()
            category = request.POST.get("activity_category")
            if sport is None:
                messages.error(request, _("請先挑一個運動種類。"))
            elif not name:
                messages.error(request, _("請填運動項目的名稱。"))
            elif Discipline.objects.filter(sport=sport, name=name).exists():
                messages.info(request, _("「%(v0)s · %(v1)s」已經在項目庫裡了。") % {"v0": sport.name, "v1": name})
            else:
                Discipline.objects.create(
                    sport=sport,
                    name=name,
                    name_en=request.POST.get("name_en", "").strip(),
                    note=request.POST.get("note", "").strip(),
                    activity_category=(
                        category
                        if category in ActivityCategory.values
                        else ActivityCategory.WARMUP
                    ),
                    status=status,
                    created_by=request.user,
                )
                messages.success(
                    request, _("已加入運動項目「%(v0)s · %(v1)s」%(v2)s。") % {"v0": sport.name, "v1": name, "v2": pending_note}
                )
            return redirect(back)

        if action == "add_kind":
            name = request.POST.get("name", "").strip()
            if not name:
                messages.error(request, _("請填訓練動作種類的名稱。"))
            elif MovementKind.objects.filter(name=name).exists():
                messages.info(request, _("「%(v0)s」已經在項目庫裡了。") % {"v0": name})
            else:
                MovementKind.objects.create(
                    name=name,
                    name_en=request.POST.get("name_en", "").strip(),
                    note=request.POST.get("note", "").strip(),
                    status=status,
                    created_by=request.user,
                )
                messages.success(request, _("已加入訓練動作種類「%(v0)s」%(v1)s。") % {"v0": name, "v1": pending_note})
            return redirect(back)

        if action == "add_activity":
            name = request.POST.get("name", "").strip()
            discipline = Discipline.objects.filter(
                pk=request.POST.get("discipline")
            ).first()
            kind = MovementKind.objects.filter(pk=request.POST.get("movement_kind")).first()
            block = request.POST.get("default_block")
            if not name:
                messages.error(request, _("請填動作名稱。"))
            elif discipline is None:
                messages.error(request, _("請挑這個動作屬於哪個運動項目。"))
            elif ActivityDefinition.objects.filter(name__iexact=name).exists():
                messages.info(request, _("「%(v0)s」已經在項目庫裡了。") % {"v0": name})
            else:
                ActivityDefinition.objects.create(
                    name=name,
                    name_en=request.POST.get("name_en", "").strip(),
                    note=request.POST.get("note", "").strip(),
                    discipline=discipline,
                    movement_kind=kind,
                    # 分類決定數據分析把它歸到哪個範疇，照運動項目的預設值走
                    category=discipline.activity_category,
                    default_block=(block if block in BlockType.values else BlockType.MAIN),
                    default_sets=request.POST.get("sets", "").strip(),
                    default_reps=request.POST.get("reps", "").strip(),
                    default_distance=request.POST.get("distance", "").strip(),
                    default_weight=request.POST.get("weight", "").strip(),
                    default_intensity=request.POST.get("intensity", "").strip(),
                    default_rest=request.POST.get("rest", "").strip(),
                    default_key_points=request.POST.get("key_points", "").strip(),
                    status=status,
                    created_by=request.user,
                )
                messages.success(request, _("已加入動作「%(v0)s」%(v1)s。") % {"v0": name, "v1": pending_note})
            return redirect(back)

        if action == "edit_activity":
            activity = ActivityDefinition.objects.filter(
                pk=request.POST.get("activity")
            ).first()
            name = request.POST.get("name", "").strip()
            target = Discipline.objects.filter(pk=request.POST.get("discipline")).first()
            if activity is None:
                messages.error(request, _("找不到要修改的動作。"))
            elif not can_edit(request.user, activity):
                messages.error(request, _("只有管理員或當初加這個動作的人可以修改它。"))
            elif not name:
                messages.error(request, _("請填動作名稱。"))
            elif (
                ActivityDefinition.objects.filter(name__iexact=name)
                .exclude(pk=activity.pk)
                .exists()
            ):
                messages.info(request, _("項目庫裡已經有另一個「%(v0)s」了。") % {"v0": name})
            else:
                block = request.POST.get("default_block")
                activity.name = name
                activity.name_en = request.POST.get("name_en", "").strip()
                activity.note = request.POST.get("note", "").strip()
                if target is not None:
                    # 換到別的運動項目，分類跟著新的運動項目走（數據分析靠它分範疇）
                    activity.discipline = target
                    activity.category = target.activity_category
                activity.movement_kind = MovementKind.objects.filter(
                    pk=request.POST.get("movement_kind")
                ).first()
                if block in BlockType.values:
                    activity.default_block = block
                activity.default_sets = request.POST.get("sets", "").strip()
                activity.default_reps = request.POST.get("reps", "").strip()
                activity.default_distance = request.POST.get("distance", "").strip()
                activity.default_weight = request.POST.get("weight", "").strip()
                activity.default_intensity = request.POST.get("intensity", "").strip()
                activity.default_rest = request.POST.get("rest", "").strip()
                activity.default_key_points = request.POST.get("key_points", "").strip()
                activity.save()
                messages.success(request, _("已更新動作「%(v0)s」。") % {"v0": name})
            return redirect(back)

        if action == "edit_node":
            obj, label = _library_object(request)
            name = request.POST.get("name", "").strip()
            dupes = (
                type(obj).objects.exclude(pk=obj.pk).filter(name__iexact=name)
                if obj is not None
                else None
            )
            if isinstance(obj, Discipline):
                # 運動項目的名字只要在同一個運動種類底下不重複就好
                dupes = dupes.filter(sport=obj.sport)
            if obj is None:
                messages.error(request, _("找不到要修改的項目。"))
            elif not can_edit(request.user, obj):
                messages.error(request, _("只有管理員或當初加這一項的人可以修改它。"))
            elif not name:
                messages.error(request, _("請填名稱。"))
            elif dupes.exists():
                messages.info(request, _("項目庫裡已經有另一個「%(v0)s」了。") % {"v0": name})
            else:
                obj.name = name
                obj.name_en = request.POST.get("name_en", "").strip()
                obj.note = request.POST.get("note", "").strip()
                fields = ["name", "name_en", "note", "updated_at"]
                category = request.POST.get("activity_category")
                if isinstance(obj, Discipline) and category in ActivityCategory.values:
                    obj.activity_category = category
                    fields.append("activity_category")
                obj.save(update_fields=fields)
                messages.success(request, _("已更新%(v0)s「%(v1)s」。") % {"v0": label, "v1": name})
            return redirect(back)

        if action in ("add_to_discipline", "remove_from_discipline"):
            activity = ActivityDefinition.objects.filter(
                pk=request.POST.get("activity")
            ).first()
            target = Discipline.objects.select_related("sport").filter(
                pk=request.POST.get("discipline")
            ).first()
            if activity is None or target is None:
                messages.error(request, _("找不到要處理的動作或運動項目。"))
            elif action == "add_to_discipline":
                if target.id == activity.discipline_id:
                    messages.info(
                        request, _("「%(v0)s」本來就在「%(v1)s」底下。") % {"v0": activity.name, "v1": target.full_label}
                    )
                else:
                    # 只是多掛一個位置（不是新東西），不用再等管理員確認
                    activity.extra_disciplines.add(target)
                    messages.success(
                        request,
                        _("已把「%(v0)s」也加進「%(v1)s」，兩邊的清單都挑得到。") % {"v0": activity.name, "v1": target.full_label},
                    )
            else:
                activity.extra_disciplines.remove(target)
                messages.info(
                    request, _("已把「%(v0)s」從「%(v1)s」移走。") % {"v0": activity.name, "v1": target.full_label}
                )
            return redirect(back)

        messages.error(request, _("不認得的操作。"))
        return redirect(back)

    sport = SportType.objects.filter(pk=request.GET.get("sport") or 0).first()
    discipline = (
        Discipline.objects.select_related("sport")
        .filter(pk=request.GET.get("discipline") or 0)
        .first()
    )
    if discipline is not None:
        sport = discipline.sport
    tree = library_tree(request.user, sport=sport, discipline=discipline)
    # 沒挑的話預設展開第一個運動種類，一進來就有東西看
    if sport is None and tree["sports"]:
        sport = tree["sports"][0]["obj"]
        tree = library_tree(request.user, sport=sport, discipline=discipline)

    return render(
        request,
        "web/library.html",
        {
            "page": "library",
            "tree": tree,
            "sport": sport,
            "discipline": discipline,
            "can_approve": can_approve,
            "pending": pending_submissions(request.user),
            "block_choices": BlockType.choices,
            "activity_categories": ActivityCategory.choices,
            "library_count": visible_definitions(request.user).count(),
        },
    )


# ==================================================================== 影片庫
# 上傳的片放哪、誰看得到都在 video.services；這裡只把 request 拆開再轉交。
# 檔案本身不一定經過這幾個 view——R2 開著時瀏覽器直接把片 PUT 上去
# （見 video_sign），Django 只收到一筆 metadata。


@login_required
def video_list(request):
    """影片庫：上傳新片，以及依運動員列出既有的片。"""
    athlete = _current_athlete(request)
    if athlete is None:
        return render(request, "web/no_athlete.html", {"page": "video"})

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "upload":
                video = vsvc.save_video(
                    request.user, athlete, request.POST, upload=request.FILES.get("file")
                )
                messages.success(
                    request, _("已上傳「%(v0)s」。") % {"v0": video.display_title}
                )
                return redirect("web:video_detail", pk=video.pk)
            if action == "delete":
                video = vsvc.get_video(request.user, request.POST.get("video_id"))
                title = video.display_title
                vsvc.delete_video(request.user, video)
                messages.success(request, _("已刪除「%(v0)s」。") % {"v0": title})
            else:
                messages.error(request, _("不認得的操作。"))
        except vsvc.VideoError as exc:
            messages.error(request, str(exc))
        return redirect(f"{reverse('web:video_list')}?athlete={athlete.id}")

    videos = list(vsvc.visible_videos(request.user, athlete=athlete))
    kind = request.GET.get("kind")
    if kind in VideoKind.values:
        videos = [v for v in videos if v.kind == kind]

    today = date.today()
    return render(
        request,
        "web/video.html",
        {
            "page": "video",
            "athlete": athlete,
            "athletes": _athlete_switcher(request),
            "videos": videos,
            "kinds": VideoKind.choices,
            "picked_kind": kind or "",
            "today": today,
            "links": vsvc.link_choices(athlete, today),
            "direct_upload": vstorage.r2_enabled(),
            "max_mb": int(MAX_UPLOAD_BYTES / 1024 / 1024),
            "allowed_ext": ", ".join(f".{e}" for e in ALLOWED_EXTENSIONS),
        },
    )


@login_required
def video_detail(request, pk):
    """單條影片：變速與逐格回放、時間點批註，另可並排比對另一條片。"""
    try:
        video = vsvc.get_video(request.user, pk)
    except vsvc.VideoError as exc:
        messages.error(request, str(exc))
        return redirect("web:video_list")

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "note_add":
                vsvc.add_note(
                    request.user, video, request.POST.get("at_sec"), request.POST.get("body")
                )
                messages.success(request, _("已加上批註。"))
            elif action == "note_delete":
                note = get_object_or_404(VideoNote, pk=request.POST["note_id"], video=video)
                vsvc.delete_note(request.user, note)
                messages.success(request, _("已刪除批註。"))
            elif action == "keeper":
                video.is_keeper = not video.is_keeper
                video.save(update_fields=["is_keeper", "updated_at"])
                messages.success(
                    request,
                    _("已標記為範本，保留期限不會清掉這條片。")
                    if video.is_keeper
                    else _("已取消範本標記。"),
                )
            elif action == "delete":
                vsvc.delete_video(request.user, video)
                messages.success(request, _("已刪除該影片。"))
                return redirect(f"{reverse('web:video_list')}?athlete={video.athlete_id}")
            else:
                messages.error(request, _("不認得的操作。"))
        except vsvc.VideoError as exc:
            messages.error(request, str(exc))
        return redirect("web:video_detail", pk=video.pk)

    # 並排比對：?vs=<另一條片的 id>，只收看得到的片
    other = None
    vs_id = request.GET.get("vs")
    if vs_id:
        other = vsvc.visible_videos(request.user).filter(pk=vs_id).first()

    same_athlete = (
        vsvc.visible_videos(request.user, athlete=video.athlete)
        .exclude(pk=video.pk)
        .order_by("-date", "-id")[:50]
    )
    return render(
        request,
        "web/video_detail.html",
        {
            "page": "video",
            "athlete": video.athlete,
            "video": video,
            "other": other,
            "others": same_athlete,
            "notes": list(video.notes.select_related("author")),
            "can_delete": vsvc.may_delete(request.user, video),
            "can_annotate": vsvc.may_annotate(request.user, video),
        },
    )


@login_required
@require_POST
def video_sign(request):
    """發一個 presigned PUT 網址，讓瀏覽器把影片直接送去 R2。

    沒設 R2 時回 `{"direct": false}`，前端就退回一般的表單上傳——
    本機開發不用開任何雲端帳號也能做完整流程。
    """
    athlete = _current_athlete(request)
    if athlete is None:
        return JsonResponse({"error": str(_("先挑一位運動員。"))}, status=400)

    filename = request.POST.get("filename", "")
    try:
        vsvc.check_filename(filename)
        vsvc.check_size(int(request.POST.get("size_bytes") or 0))
    except vsvc.VideoError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except (TypeError, ValueError):
        return JsonResponse({"error": str(_("檔案大小不正確。"))}, status=400)

    if not vstorage.r2_enabled():
        return JsonResponse({"direct": False})

    key = make_key(athlete.id, filename)
    content_type = request.POST.get("content_type") or "video/mp4"
    url = vstorage.presign_put(key, content_type)
    if not url:
        # 設了 R2 但簽不出來（沒裝 boto3、金鑰錯）——不要卡死，退回表單上傳
        logger.warning("R2 已設定但無法簽發上傳網址，改走 Django 上傳")
        return JsonResponse({"direct": False})
    return JsonResponse({"direct": True, "url": url, "key": key, "content_type": content_type})

"""HTML 前端 views（與 DRF API 並存，共用 services 層）。"""

import calendar as pycalendar
import json
import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import AthleteProfile, CoachProfile, Event
from analytics import services as an
from analytics.models import (
    MetricDomain,
    MetricItem,
    MetricRecord,
    ensure_builtin_items,
)
from core import liveedit
from core.glossary import all_terms, as_groups
from core.models import (
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
    Injury,
    PainLog,
    TreatmentEffect,
    TreatmentLog,
    TreatmentStage,
    TreatmentType,
)
from nutrition import services as nu
from nutrition.models import NutritionTarget, RecoveryLog, RecoveryMethod
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
)
from programs.models import Project
from programs.services import ImportError_ as ProgramImportError
from programs.services import import_application
from training.models import (
    ACTIVITY_FIELDS,
    ActivityDefinition,
    BlockType,
    Exercise,
    SessionActivity,
)

logger = logging.getLogger(__name__)

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


RISK_CSS = {
    "OPTIMAL": ("b-green", "c-green"),
    "UNDER": ("b-blue", "c-blue"),
    "ELEVATED": ("b-yellow", "c-yellow"),
    "HIGH": ("b-red", "c-red"),
    "INSUFFICIENT": ("b-dim", "c-dim"),
}


def _current_athlete(request):
    """
    決定目前檢視的運動員：
    - 運動員 → 自己
    - 教練/管理員 → ?athlete=<id>，未指定則取第一位旗下運動員
    """
    visible = list(athlete_ids_visible_to(request.user))
    if not visible:
        return None
    requested = request.GET.get("athlete")
    if requested and int(requested) in visible:
        return AthleteProfile.objects.select_related("user", "primary_event").get(id=int(requested))
    return (
        AthleteProfile.objects.select_related("user", "primary_event")
        .filter(id__in=visible)
        .first()
    )


def _athlete_switcher(request):
    """教練用的運動員切換清單。"""
    if request.user.role == Role.ATHLETE:
        return []
    return AthleteProfile.objects.select_related("user").filter(
        id__in=athlete_ids_visible_to(request.user)
    )


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
    if request.user.role == Role.COACH and not request.GET.get("athlete"):
        # 教練先看列表挑人，挑完才進到某一位的狀態總覽
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
            "competitions": Competition.objects.filter(
                date__gte=date.today() - timedelta(days=30)
            ).order_by("date"),
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
            "chart_labels": json.dumps([p["label"] for p in prog]),
            "chart_load": json.dumps([p["total_load"] for p in prog]),
            "chart_acwr": json.dumps([p["acwr"] for p in prog]),
            "injuries": athlete.active_injuries,
        },
    )


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
            "page": "dashboard",
            "rows": rows,
            "high_risk": high_risk,
            "injured": injured,
            "today": date.today(),
            "total": len(rows),
        },
    )


# -------------------------------------------------------------- 運動員列表

#: 列表可以排序的欄位 → 實際的 order_by（預設方向＝由小到大 / A→Z）
ATHLETE_SORTS = {
    "name": ["user__first_name", "user__last_name", "user__username"],
    "project": ["application__project__title", "user__username"],
    "event": ["primary_event__category", "primary_event__distance_m", "primary_event__code"],
    "age": ["-birth_date"],  # 生日越晚＝年紀越小
    "status": ["status", "-injury_count", "user__username"],
}

#: 表頭與「目前排序」提示用的中文欄名
SORT_LABELS = {
    "name": "姓名",
    "project": "計劃",
    "event": "主項",
    "age": "年紀",
    "status": "傷患狀態",
}

#: 傷患狀態欄的篩選選項（除了三種 status，再加一個「身上有未結案傷患」）
INJURY_FILTERS = list(AthleteStatus.choices) + [("HAS_INJURY", "有未結案傷患")]


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


@login_required
def athlete_list(request):
    """運動員列表：先挑人，再進去看那個人的狀態總覽。

    帶搜尋、篩選（計劃／主項／傷患狀態）與排序，資料本身跟總覽頁同一份。
    """
    qs = (
        AthleteProfile.objects.filter(id__in=athlete_ids_visible_to(request.user))
        .select_related("user", "primary_event", "coach__user", "application__project")
        .annotate(
            injury_count=Count(
                "injuries", filter=~Q(injuries__status="RESOLVED"), distinct=True
            )
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
            | Q(application__project__title__icontains=q)
        )

    project = request.GET.get("project", "")
    if project == "none":
        qs = qs.filter(application__isnull=True)
    elif project:
        qs = qs.filter(application__project_id=project)

    event = request.GET.get("event", "")
    if event:
        qs = qs.filter(primary_event_id=event)

    injury = request.GET.get("injury", "")
    if injury == "HAS_INJURY":
        qs = qs.filter(injury_count__gt=0)
    elif injury in AthleteStatus.values:
        qs = qs.filter(status=injury)

    sort = request.GET.get("sort", "name")
    if sort not in ATHLETE_SORTS:
        sort = "name"
    direction = "desc" if request.GET.get("dir") == "desc" else "asc"
    ordering = ATHLETE_SORTS[sort]
    athletes = list(qs.order_by(*(_flip(ordering) if direction == "desc" else ordering)))

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
            "sort": sort,
            "sort_label": SORT_LABELS[sort],
            "dir": direction,
            "arrow": "▲" if direction == "asc" else "▼",
            "sort_urls": _sort_urls(request, sort, direction),
            "projects": visible_projects,
            "events": visible_events,
            "injury_filters": INJURY_FILTERS,
            "has_filter": bool(q or project or event or injury),
            "today": date.today(),
        },
    )


# --------------------------------------------------- 備戰計劃（目標賽事／分期）


def _can_edit_plan(user, athlete):
    """誰改得動這名運動員的目標賽事與分期：本人、他的教練、管理員。"""
    if _is_admin(user):
        return True
    if user.role == Role.COACH:
        return athlete.coach_id is not None and athlete.coach.user_id == user.id
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


def _save_target(request, athlete):
    """存目標賽事：順便把備戰大週期（起始日、週數、基準負荷）一起定下來。"""
    choice = request.POST.get("competition", "")
    if choice == "__new__":
        name = request.POST.get("comp_name", "").strip()
        if not name:
            raise ValueError("要填賽事名稱。")
        try:
            comp_date = date.fromisoformat(request.POST.get("comp_date", ""))
        except ValueError:
            raise ValueError("比賽日期格式要是 YYYY-MM-DD。")
        competition, created = Competition.objects.get_or_create(
            name=name,
            date=comp_date,
            defaults={
                "venue": request.POST.get("comp_venue", "").strip(),
                "level": request.POST.get("comp_level", "REGIONAL"),
                "is_target": True,
            },
        )
        if not created and not competition.is_target:
            competition.is_target = True
            competition.save(update_fields=["is_target", "updated_at"])
    elif choice:
        competition = get_object_or_404(Competition, pk=choice)
    else:
        raise ValueError("要選一個目標賽事。")

    total_weeks = _plan_int(request.POST.get("total_weeks"), 1, 52, 16)
    baseline = _plan_int(request.POST.get("baseline_weekly_load"), 100, 20000, 1800)

    raw_start = request.POST.get("start_date", "").strip()
    if raw_start:
        try:
            start = date.fromisoformat(raw_start)
        except ValueError:
            raise ValueError("開始日期格式要是 YYYY-MM-DD。")
    else:
        # 沒填就從比賽日往回數，湊成完整的 N 週（由週一開始）
        start = an.monday_of(competition.date - timedelta(weeks=total_weeks - 1))

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

    messages.success(
        request,
        f"目標賽事已設為「{competition.name}」（{competition.date}）"
        f"：{start} 起共 {total_weeks} 週，{competition.countdown_display}。",
    )


def _save_phase(request, athlete):
    """存分期：改的是 Phase 本身，日曆、週計劃、負荷分析看到的都會跟著變。"""
    macro = athlete.macrocycles.filter(is_active=True).first()
    if macro is None:
        raise ValueError("要先設定目標賽事，才有分期可以改。")

    if request.POST.get("reset") == "1":
        _rebuild_cycle(macro)
        messages.success(request, "已依預設模板重建整份分期與週計劃。")
        return

    phase_id = request.POST.get("phase_id", "")
    phase = macro.phases.filter(pk=phase_id).first() if phase_id else macro.current_phase

    phase_type = request.POST.get("phase_type", "")
    if phase_type not in PhaseType.values:
        raise ValueError("不認得的期別。")

    week_start = _plan_int(request.POST.get("week_start"), 1, macro.total_weeks, 1)
    week_end = _plan_int(request.POST.get("week_end"), 1, macro.total_weeks, macro.total_weeks)
    if week_end < week_start:
        raise ValueError("結束週不能早於起始週。")

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
        f"分期已更新為「{phase.get_phase_type_display()}」"
        f"（第 {week_start}–{week_end} 週，目標週負荷 {phase.target_weekly_load} AU）。",
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
        raise Http404("看不到這名運動員。")

    back = f"{reverse('web:dashboard')}?athlete={athlete.id}"
    if not _can_edit_plan(request.user, athlete):
        messages.error(request, "只有這名運動員本人、他的教練或管理員可以改備戰計劃。")
        return redirect(back)

    action = request.POST.get("action")
    try:
        if action == "set_target":
            _save_target(request, athlete)
        elif action == "set_phase":
            _save_phase(request, athlete)
        else:
            messages.error(request, "不認得的動作。")
    except ValueError as exc:
        messages.error(request, f"沒有存起來：{exc}")
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
            messages.error(request, "只有管理員可以分配項目。")
            return redirect("web:plan")

        action = request.POST.get("action")
        project = get_object_or_404(Project, pk=request.POST.get("project_id"))

        if action == "assign":
            coach_ids = request.POST.getlist("coach_ids")
            added = 0
            for coach in CoachProfile.objects.filter(id__in=coach_ids):
                _, created = ProjectAssignment.objects.update_or_create(
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
                request, f"已把「{project.title}」分配給 {len(coach_ids)} 位教練（新增 {added} 筆）。"
            )
        elif action == "unassign":
            ProjectAssignment.objects.filter(
                project=project, coach_id=request.POST.get("coach_id")
            ).delete()
            messages.info(request, f"已取消「{project.title}」的一筆教練分配。")
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
        raise Http404("這個項目沒有分配給你。")

    if request.method == "POST":
        return _plan_detail_import(request, project)

    visible = set(athlete_ids_visible_to(request.user))
    athletes = [a for a in project_athletes(project) if a.id in visible]
    rows = [_athlete_row(a) for a in athletes]

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
            "not_imported": project.applications.filter(athlete__isnull=True),
            "today": date.today(),
        },
    )


def _plan_detail_import(request, project):
    """在計劃頁直接把選取的報名表載入成 ATM 運動員檔案（等同後台的「匯入 ATM」）。"""
    if not _is_admin(request.user):
        messages.error(request, "只有管理員可以匯入報名表。")
        return redirect("web:plan_detail", pk=project.pk)

    applications = project.applications.filter(
        athlete__isnull=True, id__in=request.POST.getlist("application_ids")
    )
    if not applications:
        messages.warning(request, "沒有選取任何未匯入的報名表。")
        return redirect("web:plan_detail", pk=project.pk)

    created = 0
    for application in applications:
        try:
            import_application(application)
        except ProgramImportError as exc:
            messages.error(request, f"{application.name_en}：{exc}")
            continue
        created += 1

    if created:
        messages.success(
            request,
            f"已把 {created} 份報名載入「{project.title}」，"
            "帳號密碼為隨機值，請用後台的『重設密碼』給對方。",
        )
    return redirect("web:plan_detail", pk=project.pk)


# ------------------------------------------------------------------ 日曆


DEFAULT_PROGRAM_TITLES = {
    SessionType.TRACK: "田徑場訓練",
    SessionType.STRENGTH: "重量訓練",
    SessionType.RECOVERY: "恢復訓練",
    SessionType.REHAB: "治療康復",
    SessionType.OTHER: "其他安排",
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
            messages.error(request, "不認得的 program 類別。")
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
            f"已在 {on_date} 新增「{session.title}」（{session.get_session_type_display()}）。",
        )
        return redirect(
            f"{request.path}?athlete={athlete.id}&year={on_date.year}&month={on_date.month}"
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

    weeks, cursor = [], grid_start
    while cursor <= grid_end:
        row = []
        for _ in range(7):
            row.append(
                {
                    "date": cursor,
                    "in_month": cursor.month == month,
                    "is_today": cursor == today,
                    "sessions": by_day.get(cursor, []),
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
        "month_name": f"{year} 年 {month} 月",
        "prev": {"year": prev_m.year, "month": prev_m.month},
        "next": {"year": next_m.year, "month": next_m.month},
        "macro": macro,
        "phases": macro.phases.all() if macro else [],
        "month_load": sum(s.session_load for s in sessions if first <= s.date <= last),
        "month_count": sum(1 for s in sessions if first <= s.date <= last),
        "today_iso": today.isoformat(),
        "cal_version": _stamp(sessions),
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
            messages.success(request, f"已完成打卡，本次負荷 {session.session_load} AU。")
        elif action == "coach_comment":
            session.coach_comment = request.POST.get("coach_comment", "")
            session.save(update_fields=["coach_comment", "updated_at"])
            messages.success(request, "已儲存教練評語。")
        elif action == "modify":
            changes = inj.apply_modifications(session)
            messages.info(request, f"已依傷患調整，共 {len(changes)} 項變更。")
        elif action == "add_activity":
            _add_activity(request, session)
        elif action == "new_definition":
            _new_definition(request, session)
        elif action == "delete_activity":
            _delete_row(request, SessionActivity, request.POST.get("id"), "活動")
        elif action == "add_note":
            _add_note(request, session)
        elif action == "delete_note":
            _delete_row(request, SessionNote, request.POST.get("id"), "記事")
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
        raise Http404("無權限存取此課表。")
    return session


def _session_context(request, session):
    """課表頁的完整 context（整頁與輪詢刷新的片段共用同一份）。"""
    blocked, reason = inj.should_block_high_intensity(session.athlete, session.date)
    library = list(ActivityDefinition.objects.filter(is_active=True))

    blocks = []
    for value, label, activities in session.activities_by_block():
        blocks.append(
            {
                "value": value,
                "label": label,
                "activities": [
                    {"a": a, "editable": liveedit.can_edit(a, request.user, "name")}
                    for a in activities
                ],
            }
        )

    notes = [
        {"n": n, "editable": liveedit.can_edit(n, request.user, "body")}
        for n in session.notes.select_related("author")
    ]

    return {
        "page": "calendar",
        "s": session,
        "blocks": blocks,
        "notes": notes,
        "note_kinds": NoteKind.choices,
        "block_choices": BlockType.choices,
        "activity_fields": ACTIVITY_FIELDS,
        "library": library,
        # 給前端挑活動時自動帶入預設值用（模板以 json_script 輸出，不會被 HTML 咬到）
        "library_data": [
            dict(id=d.id, name=d.name, block=d.default_block, **d.defaults_payload())
            for d in library
        ],
        "track_sets": session.track_sets.all(),
        "strength_sets": session.strength_sets.select_related("exercise"),
        "blocked": blocked,
        "block_reason": reason,
        "is_coach": request.user.role in (Role.COACH, Role.ADMIN),
        "can_edit_plan": liveedit.can_edit(session, request.user, "title"),
        "can_log": liveedit.can_edit(session, request.user, "session_rpe"),
        "can_comment": liveedit.can_edit(session, request.user, "coach_comment"),
        "version": session.content_version,
        "session_types": program_type_choices(),
        "status_choices": SessionStatus.choices,
    }


def _add_activity(request, session):
    """在某一區（熱身 / 正課 / 補充 / 恢復）加一項活動。"""
    block = request.POST.get("block")
    if block not in BlockType.values:
        messages.error(request, "不認得的課表區塊。")
        return

    definition = None
    definition_id = request.POST.get("definition")
    if definition_id:
        definition = ActivityDefinition.objects.filter(pk=definition_id).first()

    name = request.POST.get("name", "").strip() or (definition.name if definition else "")
    if not name:
        messages.error(request, "請挑一個活動，或自己打一個名稱。")
        return

    last = session.activities.filter(block=block).order_by("-order").first()
    SessionActivity.objects.create(
        session=session,
        block=block,
        order=(last.order + 1) if last else 1,
        definition=definition,
        name=name,
        sets=request.POST.get("sets", "").strip(),
        reps=request.POST.get("reps", "").strip(),
        distance=request.POST.get("distance", "").strip(),
        weight=request.POST.get("weight", "").strip(),
        intensity=request.POST.get("intensity", "").strip(),
        rest=request.POST.get("rest", "").strip(),
        key_points=request.POST.get("key_points", "").strip(),
        note=request.POST.get("note", "").strip(),
        created_by=request.user,
    )
    if definition:
        ActivityDefinition.objects.filter(pk=definition.pk).update(
            use_count=F("use_count") + 1
        )
    messages.success(request, f"已加入「{name}」到{BlockType(block).label}。")


def _new_definition(request, session):
    """把一個新的訓練活動寫進名稱庫，之後所有課表都挑得到。"""
    name = request.POST.get("name", "").strip()
    if not name:
        messages.error(request, "請填活動名稱。")
        return
    block = request.POST.get("default_block")
    if block not in BlockType.values:
        block = BlockType.WARMUP

    definition, created = ActivityDefinition.objects.get_or_create(
        name=name,
        defaults={
            "default_block": block,
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
    if created:
        messages.success(request, f"已新增訓練活動「{name}」，以後可以直接挑。")
    else:
        messages.info(request, f"「{name}」已經在活動清單裡了。")

    if request.POST.get("also_add"):
        post = request.POST.copy()
        post["definition"] = str(definition.id)
        post["block"] = definition.default_block
        request.POST = post
        _add_activity(request, session)


def _add_note(request, session):
    body = request.POST.get("body", "").strip()
    if not body:
        messages.error(request, "記事不能是空的。")
        return
    kind = request.POST.get("kind")
    SessionNote.objects.create(
        session=session,
        author=request.user,
        kind=kind if kind in NoteKind.values else NoteKind.NOTE,
        body=body,
    )
    messages.success(request, "已寫入，同一版面的教練與運動員都看得到。")


def _delete_row(request, model, pk, label):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        messages.error(request, f"這筆{label}已經不在了。")
        return
    if not liveedit.can_delete(obj, request.user):
        messages.error(request, f"只能刪自己寫下的{label}。")
        return
    obj.delete()
    messages.success(request, f"已刪除這筆{label}。")


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
        return JsonResponse({"ok": False, "error": "看不懂的請求格式。"}, status=400)

    parts = str(payload.get("target", "")).split(":")
    if len(parts) != 3:
        return JsonResponse({"ok": False, "error": "看不懂要改哪一格。"}, status=400)
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

    # ---- 新增項目 / 新增紀錄 ----
    if request.method == "POST":
        action = request.POST.get("action")
        back = f"{request.path}?athlete={athlete.id}&domain={request.POST.get('domain', '')}"

        if action == "add_item":
            name = request.POST.get("name", "").strip()
            domain = request.POST.get("domain")
            if not name:
                messages.error(request, "請填項目名稱。")
            elif domain not in MetricDomain.values:
                messages.error(request, "不認得的範疇。")
            else:
                item, created = MetricItem.objects.get_or_create(
                    domain=domain,
                    name=name,
                    defaults={
                        "unit": request.POST.get("unit", "").strip(),
                        "higher_is_better": bool(request.POST.get("higher_is_better")),
                        "created_by": request.user,
                    },
                )
                if created:
                    messages.success(request, f"已新增項目「{item.name}」。")
                else:
                    messages.info(request, f"「{item.name}」已經在清單裡了。")
                back += f"&item={item.id}"
            return redirect(back)

        if action == "add_record":
            item = get_object_or_404(MetricItem, pk=request.POST.get("item_id"))
            session_id = request.POST.get("session") or None
            session = None
            if session_id:
                session = TrainingSession.objects.filter(
                    pk=session_id, athlete=athlete
                ).first()
            # 一次可以送多組——同一堂課的不同組，重量／次數／休息時間都不一樣，
            # 所以表單是一列一組，每一列各存成一筆紀錄。
            on_date = request.POST.get("date") or date.today()
            context = request.POST.get("context", "")
            note = request.POST.get("note", "")
            values = request.POST.getlist("value")
            weights = request.POST.getlist("weight")
            reps_list = request.POST.getlist("reps")
            rests = request.POST.getlist("rest_sec")
            dones = request.POST.getlist("completed")
            multi = len(values) > 1

            def _num(seq, i, cast):
                raw = (seq[i] if i < len(seq) else "").strip()
                if not raw:
                    return None
                try:
                    return cast(raw)
                except (TypeError, ValueError):
                    return None

            created = []
            for i, raw_value in enumerate(values):
                raw_value = raw_value.strip()
                if not raw_value:
                    continue  # 空白列＝使用者加了組卻沒填，跳過
                try:
                    value = Decimal(raw_value)
                except (InvalidOperation, ValueError):
                    messages.error(request, f"第 {i + 1} 組的數值不是有效數字。")
                    continue
                created.append(
                    MetricRecord.objects.create(
                        athlete=athlete,
                        item=item,
                        session=session,
                        date=on_date,
                        value=value,
                        set_no=(i + 1) if multi else None,
                        weight_kg=_num(weights, i, Decimal),
                        reps=_num(reps_list, i, int),
                        rest_sec=_num(rests, i, int),
                        completed=(dones[i] if i < len(dones) else "1") != "0",
                        context=context,
                        note=note,
                    )
                )

            if not created:
                messages.error(request, "沒有記錄到任何一組，請至少填一個數值。")
            elif len(created) == 1:
                r = created[0]
                messages.success(
                    request, f"已記錄 {item.name} {r.value}{item.unit}（{r.date}）。"
                )
            else:
                failed = sum(1 for r in created if not r.completed)
                messages.success(
                    request,
                    f"已記錄 {item.name} {len(created)} 組（{created[0].date}）"
                    + (f"，其中 {failed} 組未成功完成。" if failed else "。"),
                )
            return redirect(f"{back}&item={item.id}")

        if action == "delete_record":
            record = get_object_or_404(MetricRecord, pk=request.POST.get("record_id"))
            if record.athlete_id != athlete.id:
                raise Http404("無權限刪除這筆紀錄。")
            item_id = record.item_id
            record.delete()
            messages.info(request, "已刪除一筆紀錄。")
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
        domain = MetricDomain.COMPETITION
    overview = an.metric_overview(athlete, domain)

    requested_item = request.GET.get("item")
    item = None
    if requested_item:
        item = MetricItem.objects.filter(pk=requested_item, domain=domain).first()
    if item is None:
        with_records = [r["item"] for r in overview if r["count"]]
        item = with_records[0] if with_records else (overview[0]["item"] if overview else None)

    analysis = an.metric_analysis(athlete, item) if item else None

    # 給「這筆數據來自哪一堂 program」的下拉選單
    recent_sessions = athlete.sessions.filter(
        date__gte=date.today() - timedelta(days=60)
    ).order_by("-date")[:40]

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
            "labels": json.dumps([p["label"] for p in prog]),
            "loads": json.dumps([p["total_load"] for p in prog]),
            "acwrs": json.dumps([p["acwr"] for p in prog]),
            "monotonies": json.dumps([p["monotony"] for p in prog]),
            "dist_labels": json.dumps([d["type"] for d in dist]),
            "dist_values": json.dumps([d["load"] for d in dist]),
            "dist": dist,
            # 數據紀錄
            "domains": MetricDomain.choices,
            "domain": domain,
            "domain_label": dict(MetricDomain.choices)[domain],
            "overview": overview,
            "item": item,
            "analysis": analysis,
            "chart_points": json.dumps(analysis["points"] if analysis else []),
            "recent_sessions": recent_sessions,
            "today_iso": date.today().isoformat(),
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
        if request.POST.get("action") == "morning":
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
            messages.success(request, "已儲存今日晨間問卷。")
        elif request.POST.get("action") == "recalc":
            nu.calculate_targets(athlete, today, goal=request.POST.get("goal", "MAINTAIN"))
            messages.success(request, "已重新計算今日營養目標。")
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
            "macro_labels": json.dumps(["碳水", "蛋白質", "脂肪"]),
            "macro_values": json.dumps([split["carb"], split["protein"], split["fat"]]),
            "sleep_labels": json.dumps([r["date"].strftime("%m/%d") for r in sleep_rows]),
            "sleep_values": json.dumps(
                [float(r["sleep_hours"]) if r["sleep_hours"] else None for r in sleep_rows]
            ),
            "soreness_values": json.dumps([r["soreness_level"] for r in sleep_rows]),
        },
    )


# ------------------------------------------------------------------ 傷患


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
            messages.success(request, f"已建立傷患紀錄：{injury.get_body_part_display()}")
        elif action == "pain_log":
            injury = get_object_or_404(Injury, pk=request.POST["injury_id"], athlete=athlete)
            log, _ = PainLog.objects.update_or_create(
                injury=injury,
                date=date.today(),
                defaults={
                    "pain_at_rest": int(request.POST.get("pain_at_rest", 0)),
                    "pain_during_activity": int(request.POST.get("pain_during_activity", 0)),
                    "swelling": bool(request.POST.get("swelling")),
                    "rom_limited": bool(request.POST.get("rom_limited")),
                    "note": request.POST.get("note", ""),
                },
            )
            if log.blocks_high_intensity:
                n = 0
                for s in athlete.sessions.filter(date=date.today()):
                    n += len(inj.apply_modifications(s))
                messages.warning(
                    request,
                    f"疼痛 {log.pain_during_activity}/10 已超過門檻，"
                    f"今日課表已自動調整（{n} 項變更）。",
                )
            else:
                messages.success(request, "已記錄今日疼痛。")
        elif action == "update_status":
            injury = get_object_or_404(Injury, pk=request.POST["injury_id"], athlete=athlete)
            injury.status = request.POST["status"]
            injury.save(update_fields=["status", "updated_at"])
            inj.sync_athlete_status(athlete)
            messages.success(request, f"已更新狀態為 {injury.get_status_display()}。")
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
                request, f"已更新治療方向：{injury.get_treatment_status_display()}。"
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
                f"已記錄 {log.date} 的{log.get_treatment_type_display()}"
                f"（{log.get_effect_display()}）。",
            )
        return redirect("web:injuries")

    injuries = list(athlete.injuries.all())
    active = [i for i in injuries if i.is_active]

    detail = []
    for i in active:
        trend = i.pain_trend(28)
        detail.append(
            {
                "injury": i,
                "report": inj.injury_alternatives_report(i),
                "rtp": inj.rtp_checklist(i),
                "direction": inj.suggest_treatment_direction(i),
                "treatments": inj.treatment_summary(i),
                "labels": json.dumps([r["date"].strftime("%m/%d") for r in trend]),
                "rest": json.dumps([r["pain_at_rest"] for r in trend]),
                "activity": json.dumps([r["pain_during_activity"] for r in trend]),
                "today_log": i.pain_logs.filter(date=date.today()).first(),
            }
        )

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
            "today": date.today(),
        },
    )

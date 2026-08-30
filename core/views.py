"""HTML 前端 views（與 DRF API 並存，共用 services 層）。"""

import calendar as pycalendar
import json
import logging
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import AthleteProfile, CoachProfile, Event
from analytics import services as an
from analytics.models import (
    MetricDomain,
    MetricItem,
    MetricRecord,
    ensure_builtin_items,
)
from core.glossary import all_terms, as_groups
from core.models import Role, SessionStatus, SessionType, program_type_choices
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
    Microcycle,
    ProjectAssignment,
    TrainingSession,
    project_athletes,
    projects_for,
)
from programs.models import Project
from training.models import Exercise

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
        return redirect("web:coach_dashboard")
    return redirect("web:dashboard")


# ------------------------------------------------------------------ 儀表板


@login_required
def dashboard(request):
    if request.user.role == Role.COACH and not request.GET.get("athlete"):
        return redirect("web:coach_dashboard")

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

    return render(
        request,
        "web/dashboard.html",
        {
            "page": "dashboard",
            "athlete": athlete,
            "athletes": _athlete_switcher(request),
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
            planned_duration_min=int(request.POST.get("planned_duration_min") or 90),
        )
        messages.success(
            request,
            f"已在 {on_date} 新增「{session.title}」（{session.get_session_type_display()}）。",
        )
        return redirect(
            f"{request.path}?athlete={athlete.id}&year={on_date.year}&month={on_date.month}"
        )

    today = date.today()
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))

    first = date(year, month, 1)
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    grid_start = first - timedelta(days=first.weekday())
    grid_end = last + timedelta(days=(6 - last.weekday()))

    sessions = TrainingSession.objects.filter(
        athlete=athlete, date__gte=grid_start, date__lte=grid_end
    ).order_by("date", "time_slot")

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

    return render(
        request,
        "web/calendar.html",
        {
            "page": "calendar",
            "athlete": athlete,
            "athletes": _athlete_switcher(request),
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
            "program_types": program_type_choices(),
            "today_iso": today.isoformat(),
        },
    )


@login_required
def session_detail(request, pk):
    session = get_object_or_404(
        TrainingSession.objects.select_related("athlete", "assigned_by"), pk=pk
    )
    if session.athlete_id not in set(athlete_ids_visible_to(request.user)):
        raise Http404("無權限存取此課表。")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "complete":
            session.mark_complete(
                duration_min=int(request.POST["actual_duration_min"]),
                rpe=int(request.POST["session_rpe"]),
                completion_pct=int(request.POST.get("completion_pct", 100)),
                feedback=request.POST.get("athlete_feedback", ""),
            )
            messages.success(request, f"已完成打卡，本次負荷 {session.session_load} AU。")
        elif action == "coach_comment":
            session.coach_comment = request.POST.get("coach_comment", "")
            session.save(update_fields=["coach_comment", "updated_at"])
            messages.success(request, "已儲存教練評語。")
        elif action == "modify":
            changes = inj.apply_modifications(session)
            messages.info(request, f"已依傷患調整，共 {len(changes)} 項變更。")
        return redirect("web:session_detail", pk=pk)

    blocked, reason = inj.should_block_high_intensity(session.athlete, session.date)

    return render(
        request,
        "web/session_detail.html",
        {
            "page": "calendar",
            "s": session,
            "track_sets": session.track_sets.all(),
            "strength_sets": session.strength_sets.select_related("exercise"),
            "blocked": blocked,
            "block_reason": reason,
            "is_coach": request.user.role in (Role.COACH, Role.ADMIN),
        },
    )


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
            record = MetricRecord.objects.create(
                athlete=athlete,
                item=item,
                session=session,
                date=request.POST.get("date") or date.today(),
                value=request.POST["value"],
                context=request.POST.get("context", ""),
                note=request.POST.get("note", ""),
            )
            messages.success(
                request, f"已記錄 {item.name} {record.value}{item.unit}（{record.date}）。"
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

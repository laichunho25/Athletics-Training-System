"""HTML 前端 views（與 DRF API 並存，共用 services 層）。"""

import calendar as pycalendar
import json
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import AthleteProfile, Event
from analytics import services as an
from core.models import Role, SessionStatus
from core.permissions import athlete_ids_visible_to
from injury import services as inj
from injury.models import Injury, PainLog
from nutrition import services as nu
from nutrition.models import NutritionTarget, RecoveryLog, RecoveryMethod
from planning.models import TrainingSession
from training.models import Exercise

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


@login_required
def home(request):
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


# ------------------------------------------------------------------ 日曆


@login_required
def calendar_view(request):
    athlete = _current_athlete(request)
    if athlete is None:
        return render(request, "web/no_athlete.html", {"page": "calendar"})

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
    athlete = _current_athlete(request)
    if athlete is None:
        return render(request, "web/no_athlete.html", {"page": "analytics"})

    weeks = int(request.GET.get("weeks", 12))
    prog = an.weekly_load_progression(athlete, weeks)
    acwr = an.acwr_report(athlete)
    badge, color = RISK_CSS[acwr["risk_flag"]]

    event_code = request.GET.get("event") or athlete.primary_event.code
    event = Event.objects.filter(code=event_code).first() or athlete.primary_event
    trend = an.performance_trend(athlete, event)

    ex_code = request.GET.get("exercise", "BACK_SQUAT")
    exercise = Exercise.objects.filter(code=ex_code).first()
    strength = an.strength_trend(athlete, exercise) if exercise else {"points": []}

    dist = an.volume_distribution(athlete)
    week_start = an.monday_of(date.today())

    # 可選項目：主項 + 副項 + 有紀錄的項目
    events = [athlete.primary_event] + list(athlete.secondary_events.all())

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
            "events": events,
            "event": event,
            "exercises": Exercise.objects.filter(is_measured_by_1rm=True)[:20],
            "exercise": exercise,
            "trend": trend,
            "strength": strength,
            "labels": json.dumps([p["label"] for p in prog]),
            "loads": json.dumps([p["total_load"] for p in prog]),
            "acwrs": json.dumps([p["acwr"] for p in prog]),
            "monotonies": json.dumps([p["monotony"] for p in prog]),
            "trend_data": json.dumps(
                [{"x": str(p["date"]), "y": p["mark"], "src": p["source"]} for p in trend["points"]]
            ),
            "strength_data": json.dumps(
                [{"x": str(p["date"]), "y": p["value"]} for p in strength["points"]]
            ),
            "dist_labels": json.dumps([d["type"] for d in dist]),
            "dist_values": json.dumps([d["load"] for d in dist]),
            "dist": dist,
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
            "today": date.today(),
        },
    )

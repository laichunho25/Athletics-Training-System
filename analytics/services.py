"""
負荷監控與表現分析的全部計算邏輯。

原則：view / serializer 不做計算，只呼叫這裡的函式。

負荷定義（Foster sRPE）：
    session_load = session_rpe × actual_duration_min      單位 AU (Arbitrary Unit)
"""

import statistics
from datetime import date, timedelta

from django.db.models import Avg, Sum

from accounts.models import AthleteProfile
from analytics.models import DailyLoad, RiskFlag, WeeklySummary
from core.models import SessionStatus

ACUTE_DAYS = 7
CHRONIC_DAYS = 28
MIN_DAYS_FOR_ACWR = 28


# --------------------------------------------------------------- 每日彙總


def rebuild_daily_load(athlete, on_date):
    """重算某運動員某日的 DailyLoad 快取。"""
    from planning.models import TrainingSession

    sessions = TrainingSession.objects.filter(
        athlete=athlete,
        date=on_date,
        status__in=[SessionStatus.COMPLETED, SessionStatus.PARTIAL],
    ).prefetch_related("track_sets", "strength_sets")

    total_load = sum(s.session_load for s in sessions)
    track_volume = sum(s.total_track_volume_m for s in sessions)
    tonnage = sum(s.total_tonnage_kg for s in sessions)
    duration = sum(s.actual_duration_min or 0 for s in sessions)
    rpes = [s.session_rpe for s in sessions if s.session_rpe]

    obj, _ = DailyLoad.objects.update_or_create(
        athlete=athlete,
        date=on_date,
        defaults={
            "total_load_au": int(total_load),
            "track_volume_m": int(track_volume),
            "strength_tonnage_kg": round(tonnage, 1),
            "session_count": sessions.count(),
            "duration_min": int(duration),
            "avg_rpe": round(statistics.mean(rpes), 2) if rpes else None,
        },
    )
    return obj


def rebuild_range(athlete, start_date, end_date):
    """區間重算（部署後回填歷史資料用）。"""
    results = []
    cursor = start_date
    while cursor <= end_date:
        results.append(rebuild_daily_load(athlete, cursor))
        cursor += timedelta(days=1)
    return results


def _daily_load_series(athlete, start_date, end_date):
    """回傳 {date: load} 且補齊缺漏日為 0（統計標準差時必要）。"""
    rows = DailyLoad.objects.filter(
        athlete=athlete, date__gte=start_date, date__lte=end_date
    ).values_list("date", "total_load_au")
    mapping = dict(rows)
    series = {}
    cursor = start_date
    while cursor <= end_date:
        series[cursor] = mapping.get(cursor, 0)
        cursor += timedelta(days=1)
    return series


# --------------------------------------------------------------- 負荷指標


def acute_load(athlete, on_date=None):
    """急性負荷 = 最近 7 天負荷總和。"""
    on_date = on_date or date.today()
    start = on_date - timedelta(days=ACUTE_DAYS - 1)
    total = DailyLoad.objects.filter(
        athlete=athlete, date__gte=start, date__lte=on_date
    ).aggregate(t=Sum("total_load_au"))["t"]
    return int(total or 0)


def chronic_load(athlete, on_date=None):
    """慢性負荷 = 最近 28 天負荷總和 ÷ 4（換算成週平均）。"""
    on_date = on_date or date.today()
    start = on_date - timedelta(days=CHRONIC_DAYS - 1)
    total = DailyLoad.objects.filter(
        athlete=athlete, date__gte=start, date__lte=on_date
    ).aggregate(t=Sum("total_load_au"))["t"]
    return round((total or 0) / 4, 1)


def has_enough_history(athlete, on_date=None):
    """ACWR 至少需要 28 天資料才有意義。"""
    on_date = on_date or date.today()
    first = DailyLoad.objects.filter(athlete=athlete).order_by("date").first()
    if first is None:
        return False
    return (on_date - first.date).days >= MIN_DAYS_FOR_ACWR - 1


def calculate_acwr(athlete, on_date=None):
    """
    傳統 Rolling Average ACWR = 急性 / 慢性。
    資料不足 28 天時回傳 None（前端顯示「資料累積中」）。
    """
    on_date = on_date or date.today()
    if not has_enough_history(athlete, on_date):
        return None
    chronic = chronic_load(athlete, on_date)
    if not chronic:
        return None
    return round(acute_load(athlete, on_date) / chronic, 2)


def calculate_ewma_acwr(athlete, on_date=None, acute_span=7, chronic_span=28):
    """
    EWMA 版 ACWR（Williams et al. 2017），對近期負荷更敏感，建議作為主要指標。
    λ = 2 / (span + 1)
    """
    on_date = on_date or date.today()
    if not has_enough_history(athlete, on_date):
        return None

    start = on_date - timedelta(days=chronic_span * 2)
    series = _daily_load_series(athlete, start, on_date)

    la = 2 / (acute_span + 1)
    lc = 2 / (chronic_span + 1)
    ewma_a = ewma_c = None
    for _, load in sorted(series.items()):
        ewma_a = load if ewma_a is None else load * la + ewma_a * (1 - la)
        ewma_c = load if ewma_c is None else load * lc + ewma_c * (1 - lc)

    if not ewma_c:
        return None
    return round(ewma_a / ewma_c, 2)


def classify_acwr(acwr):
    """ACWR 四段燈號判定。"""
    if acwr is None:
        return RiskFlag.INSUFFICIENT
    if acwr < 0.80:
        return RiskFlag.UNDER
    if acwr <= 1.30:
        return RiskFlag.OPTIMAL
    if acwr <= 1.50:
        return RiskFlag.ELEVATED
    return RiskFlag.HIGH


ACWR_ADVICE = {
    RiskFlag.UNDER: ("🔵", "訓練量偏低，體能儲備可能流失。可在下週逐步增量 5–10%。"),
    RiskFlag.OPTIMAL: ("🟢", "負荷處於甜蜜點 (0.8–1.3)，維持目前節奏。"),
    RiskFlag.ELEVATED: ("🟡", "負荷偏高，注意睡眠與恢復，避免連續兩週再加量。"),
    RiskFlag.HIGH: ("🔴", "高受傷風險 (ACWR > 1.5)！建議本週減量 20–30%，並加強恢復手段。"),
    RiskFlag.INSUFFICIENT: ("⚪", "資料累積中，需滿 28 天訓練紀錄才能計算 ACWR。"),
}


def acwr_report(athlete, on_date=None):
    on_date = on_date or date.today()
    value = calculate_acwr(athlete, on_date)
    ewma = calculate_ewma_acwr(athlete, on_date)
    flag = classify_acwr(value)
    icon, advice = ACWR_ADVICE[flag]
    return {
        "date": on_date,
        "acute_load": acute_load(athlete, on_date),
        "chronic_load": chronic_load(athlete, on_date),
        "acwr": value,
        "acwr_ewma": ewma,
        "risk_flag": flag,
        "risk_label": RiskFlag(flag).label,
        "icon": icon,
        "advice": advice,
    }


# --------------------------------------------------------------- 單調度與張力


def calculate_monotony(athlete, week_start):
    """
    Monotony = 該週平均日負荷 / 該週日負荷標準差。
    > 2.0 為警訊（訓練太平均、缺乏高低起伏，容易累積疲勞）。
    """
    series = _daily_load_series(athlete, week_start, week_start + timedelta(days=6))
    loads = list(series.values())
    if len(loads) < 2:
        return None
    sd = statistics.pstdev(loads)
    if sd == 0:
        return None
    return round(statistics.mean(loads) / sd, 2)


def calculate_strain(athlete, week_start):
    """Strain = 週總負荷 × Monotony。"""
    monotony = calculate_monotony(athlete, week_start)
    if monotony is None:
        return None
    total = sum(_daily_load_series(athlete, week_start, week_start + timedelta(days=6)).values())
    return round(total * monotony, 1)


def week_over_week_change(athlete, week_start):
    """本週 vs 上週負荷增幅 (%)。建議 ≤ 10%。"""
    this_week = sum(
        _daily_load_series(athlete, week_start, week_start + timedelta(days=6)).values()
    )
    prev_start = week_start - timedelta(days=7)
    last_week = sum(
        _daily_load_series(athlete, prev_start, prev_start + timedelta(days=6)).values()
    )
    if not last_week:
        return None
    return round((this_week - last_week) / last_week * 100, 1)


def monday_of(any_date):
    return any_date - timedelta(days=any_date.weekday())


def rebuild_weekly_summary(athlete, week_start=None):
    """重算某週彙總（week_start 必須是週一）。"""
    week_start = monday_of(week_start or date.today())
    week_end = week_start + timedelta(days=6)
    total = sum(_daily_load_series(athlete, week_start, week_end).values())
    ref_date = min(week_end, date.today())

    acwr = calculate_acwr(athlete, ref_date)
    obj, _ = WeeklySummary.objects.update_or_create(
        athlete=athlete,
        week_start=week_start,
        defaults={
            "total_load": int(total),
            "monotony": calculate_monotony(athlete, week_start),
            "strain": calculate_strain(athlete, week_start),
            "acwr": acwr,
            "acute_load": acute_load(athlete, ref_date),
            "chronic_load": chronic_load(athlete, ref_date),
            "week_over_week_pct": week_over_week_change(athlete, week_start),
            "risk_flag": classify_acwr(acwr),
        },
    )
    return obj


def weekly_load_progression(athlete, weeks=12):
    """近 N 週負荷走勢（給柱狀圖 + ACWR 折線用）。"""
    this_monday = monday_of(date.today())
    out = []
    for i in range(weeks - 1, -1, -1):
        ws = this_monday - timedelta(weeks=i)
        summary = WeeklySummary.objects.filter(athlete=athlete, week_start=ws).first()
        if summary is None:
            summary = rebuild_weekly_summary(athlete, ws)
        out.append(
            {
                "week_start": ws,
                "label": ws.strftime("%m/%d"),
                "total_load": summary.total_load,
                "acwr": float(summary.acwr) if summary.acwr else None,
                "monotony": float(summary.monotony) if summary.monotony else None,
                "risk_flag": summary.risk_flag,
            }
        )
    return out


# --------------------------------------------------------------- 表現趨勢


def _linear_slope(xs, ys):
    """最小平方法斜率；xs 為天數，ys 為成績。"""
    n = len(xs)
    if n < 2:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


def performance_trend(athlete, event, days=365):
    """
    專項成績趨勢：比賽成績 + 訓練中該距離的最佳單趟。
    回傳含線性回歸斜率（時間項目斜率為負 = 進步）。
    """
    from core.models import MeasureUnit
    from planning.models import CompetitionEntry
    from training.models import TrackSet

    since = date.today() - timedelta(days=days)
    points = []

    for entry in CompetitionEntry.objects.filter(
        athlete=athlete, event=event, result_mark__isnull=False, competition__date__gte=since
    ).select_related("competition"):
        points.append(
            {
                "date": entry.competition.date,
                "mark": float(entry.result_mark),
                "source": "COMPETITION",
                "label": entry.competition.name,
            }
        )

    if event.distance_m:
        for ts in TrackSet.objects.filter(
            session__athlete=athlete,
            distance_m=event.distance_m,
            actual_time_sec__isnull=False,
            session__date__gte=since,
        ).select_related("session"):
            points.append(
                {
                    "date": ts.session.date,
                    "mark": float(ts.actual_time_sec),
                    "source": "TRAINING",
                    "label": ts.description,
                }
            )

    points.sort(key=lambda p: p["date"])
    if not points:
        return {"event": event.code, "points": [], "slope": None, "improving": None}

    origin = points[0]["date"]
    xs = [(p["date"] - origin).days for p in points]
    ys = [p["mark"] for p in points]
    slope = _linear_slope(xs, ys)

    improving = None
    if slope is not None:
        improving = slope < 0 if event.unit == MeasureUnit.TIME else slope > 0

    return {
        "event": event.code,
        "event_name": event.name_zh,
        "unit": event.unit,
        "points": points,
        "best": (min if event.unit == MeasureUnit.TIME else max)(ys),
        "slope_per_day": round(slope, 5) if slope is not None else None,
        "slope_per_month": round(slope * 30, 3) if slope is not None else None,
        "improving": improving,
    }


def strength_trend(athlete, exercise, days=365):
    """1RM（實測 + 推估）與噸位成長曲線。"""
    from training.models import OneRepMax, StrengthSet

    since = date.today() - timedelta(days=days)
    points = [
        {"date": o.test_date, "value": float(o.value_kg), "source": "TEST"}
        for o in OneRepMax.objects.filter(
            athlete=athlete, exercise=exercise, test_date__gte=since
        )
    ]

    best_by_day = {}
    for s in StrengthSet.objects.filter(
        session__athlete=athlete, exercise=exercise, session__date__gte=since, weight_kg__gt=0
    ).select_related("session"):
        est = s.estimated_1rm
        if est is None:
            continue
        d = s.session.date
        if est > best_by_day.get(d, 0):
            best_by_day[d] = est
    points += [
        {"date": d, "value": v, "source": "ESTIMATED"} for d, v in best_by_day.items()
    ]

    points.sort(key=lambda p: p["date"])
    if not points:
        return {"exercise": exercise.code, "points": [], "slope_per_month": None}

    origin = points[0]["date"]
    slope = _linear_slope(
        [(p["date"] - origin).days for p in points], [p["value"] for p in points]
    )
    return {
        "exercise": exercise.code,
        "exercise_name": exercise.name_zh,
        "points": points,
        "current_1rm": points[-1]["value"],
        "best_1rm": max(p["value"] for p in points),
        "slope_per_month": round(slope * 30, 2) if slope is not None else None,
    }


def volume_distribution(athlete, days=28):
    """訓練量分佈（給圓餅圖）：各 session_type 佔的負荷比例。"""
    from planning.models import TrainingSession

    since = date.today() - timedelta(days=days)
    sessions = TrainingSession.objects.filter(
        athlete=athlete,
        date__gte=since,
        status__in=[SessionStatus.COMPLETED, SessionStatus.PARTIAL],
    )
    buckets = {}
    for s in sessions:
        buckets[s.get_session_type_display()] = buckets.get(s.get_session_type_display(), 0) + s.session_load
    total = sum(buckets.values()) or 1
    return [
        {"type": k, "load": v, "pct": round(v / total * 100, 1)}
        for k, v in sorted(buckets.items(), key=lambda kv: -kv[1])
    ]


# --------------------------------------------------------------- 準備度


def readiness_score(athlete, on_date=None):
    """
    綜合準備度 0–100：睡眠 30 + 痠痛 25 + 壓力 15 + 疼痛 20 + 神經肌肉 10。
    缺項則按剩餘權重歸一化。
    """
    from injury.models import PainLog
    from nutrition.models import RecoveryLog
    from training.models import NeuromuscularTest

    on_date = on_date or date.today()
    parts, weights = [], []

    rec = RecoveryLog.objects.filter(athlete=athlete, date=on_date).first()
    if rec:
        if rec.sleep_hours is not None:
            parts.append(min(float(rec.sleep_hours) / 8.0, 1.0) * 100)
            weights.append(30)
        if rec.soreness_level:
            parts.append((10 - rec.soreness_level) / 9 * 100)
            weights.append(25)
        if rec.stress_level:
            parts.append((5 - rec.stress_level) / 4 * 100)
            weights.append(15)

    worst_pain = (
        PainLog.objects.filter(injury__athlete=athlete, date=on_date).aggregate(
            m=Avg("pain_during_activity")
        )["m"]
    )
    if worst_pain is not None:
        parts.append((10 - float(worst_pain)) / 10 * 100)
        weights.append(20)

    nm = NeuromuscularTest.objects.filter(athlete=athlete, date=on_date).first()
    if nm and nm.pct_of_baseline:
        parts.append(min(float(nm.pct_of_baseline), 110) / 110 * 100)
        weights.append(10)

    if not parts:
        return {"score": None, "label": "無資料", "inputs": 0}

    score = round(sum(p * w for p, w in zip(parts, weights)) / sum(weights), 1)
    if score >= 80:
        label = "🟢 狀態良好，可執行高強度"
    elif score >= 65:
        label = "🟡 尚可，維持計劃但注意反應"
    elif score >= 50:
        label = "🟠 疲勞明顯，建議降低強度"
    else:
        label = "🔴 恢復不足，改為主動恢復或休息"
    return {"score": score, "label": label, "inputs": len(parts)}


# --------------------------------------------------------------- 儀表板


def athlete_dashboard(athlete, on_date=None):
    """運動員儀表板的一次性資料組裝。"""
    from planning.models import Competition, TrainingSession

    on_date = on_date or date.today()
    macro = athlete.macrocycles.filter(is_active=True).first()
    target = (
        macro.target_competition
        if macro
        else Competition.objects.filter(is_target=True, date__gte=on_date).first()
    )
    phase = macro.current_phase if macro else None

    return {
        "athlete": athlete,
        "date": on_date,
        "target_competition": target,
        "countdown": target.countdown_display if target else None,
        "current_week": macro.current_week_number if macro else None,
        "current_phase": phase,
        "today_sessions": TrainingSession.objects.filter(athlete=athlete, date=on_date),
        "acwr": acwr_report(athlete, on_date),
        "readiness": readiness_score(athlete, on_date),
        "active_injuries": athlete.active_injuries.count(),
    }


def coach_dashboard(coach, on_date=None):
    """教練團隊儀表板：每位運動員的燈號一覽。"""
    on_date = on_date or date.today()
    rows = []
    for athlete in coach.athletes.select_related("user", "primary_event"):
        report = acwr_report(athlete, on_date)
        rows.append(
            {
                "athlete": athlete,
                "status": athlete.get_status_display(),
                "acwr": report["acwr"],
                "risk_flag": report["risk_flag"],
                "icon": report["icon"],
                "readiness": readiness_score(athlete, on_date)["score"],
                "injuries": athlete.active_injuries.count(),
                "today_sessions": athlete.sessions.filter(date=on_date).count(),
            }
        )
    rows.sort(key=lambda r: (r["acwr"] is None, -(r["acwr"] or 0)))
    return {"date": on_date, "coach": coach, "rows": rows}


def rebuild_all(athlete, days=90):
    """一鍵回填某運動員近 N 天的所有彙總（管理指令使用）。"""
    today = date.today()
    rebuild_range(athlete, today - timedelta(days=days), today)
    ws = monday_of(today - timedelta(days=days))
    while ws <= monday_of(today):
        rebuild_weekly_summary(athlete, ws)
        ws += timedelta(days=7)


def rebuild_everyone(days=90):
    for athlete in AthleteProfile.objects.all():
        rebuild_all(athlete, days)

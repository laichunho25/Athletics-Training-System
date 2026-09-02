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


# --------------------------------------------------------------- 數據紀錄分析


def metric_points(athlete, item, days=365):
    """某位運動員在某個數據項目上的所有紀錄（由舊到新）。"""
    from analytics.models import MetricRecord

    since = date.today() - timedelta(days=days)
    return list(
        MetricRecord.objects.filter(athlete=athlete, item=item, date__gte=since)
        .select_related("session")
        .order_by("date", "set_no", "id")
    )


def scored(records):
    """只有填了完成數值的紀錄才算得進統計（數值不是必填，可以先留空）。"""
    return [r for r in records if r.value is not None]


def metric_days(records, item):
    """把紀錄按日期收成一天一列——列上顯示當日最重與最輕，展開才看每一組。

    紀錄明細一組一列的話，重訓一堂課十幾組會把表拉得很長；
    以「一天一個單位」收起來，先看得到當日的高低點，需要細節再點開。
    """
    by_date = {}
    for record in records:
        by_date.setdefault(record.date, []).append(record)

    unit_is_weight = (item.unit or "").strip().lower() == "kg"
    result = []
    for on_date in sorted(by_date, reverse=True):  # 新的一天放最上面
        rows = sorted(by_date[on_date], key=lambda r: (r.set_no or 0, r.id))
        values = [float(r.value) for r in scored(rows)]
        tonnages = [r.tonnage for r in rows if r.tonnage is not None]
        result.append(
            {
                "date": on_date,
                "records": rows,
                "count": len(rows),
                "high": max(values) if values else None,   # 當日最重／最高
                "low": min(values) if values else None,    # 當日最輕／最低
                "best": (max if item.higher_is_better else min)(values) if values else None,
                "unit_is_weight": unit_is_weight,
                "failed": sum(1 for r in rows if not r.completed),
                "total_reps": sum(r.reps for r in rows if r.reps is not None) or None,
                "tonnage": round(sum(tonnages), 1) if tonnages else None,
                "context": next((r.context for r in rows if r.context), ""),
                "session": next((r.session for r in rows if r.session_id), None),
            }
        )
    return result


def metric_analysis(athlete, item, days=365):
    """依紀錄自動產生分析：最佳、最近、趨勢、與最佳的差距、建議。

    「好」的方向由項目自己的 higher_is_better 決定——計時類越小越好，
    重量與距離類越大越好，所以進步與否不能只看斜率正負。
    """
    records = metric_points(athlete, item, days)
    with_value = scored(records)          # 只有填了完成數值的才算得出趨勢
    values = [float(r.value) for r in with_value]
    result = {
        "item": item,
        "records": records,
        "count": len(records),
        "points": [
            {
                "date": str(r.date),
                "value": float(r.value) if r.value is not None else None,
                "target": float(r.target_value) if r.target_value is not None else None,
                "session": r.session.title if r.session_id else "",
                "context": r.context,
                "set_no": r.set_no,
                "weight": float(r.weight_kg) if r.weight_kg is not None else None,
                "intensity": r.intensity,
                "reps": r.reps,
                "rest_sec": r.rest_sec,
                "tonnage": r.tonnage,
                "completed": r.completed,
                "label": (f"{r.date} 第{r.set_no}組" if r.set_no else str(r.date)),
            }
            for r in records
        ],
        "days": [],
        "set_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "completion_pct": None,
        "total_tonnage": None,
        "avg_rest_sec": None,
        "best": None,
        "latest": None,
        "first": None,
        "average": None,
        "slope_per_month": None,
        "improving": None,
        "gap_to_best": None,
        "change_pct": None,
        "advice": "",
    }
    result["days"] = metric_days(records, item)
    result["set_count"] = len(records)
    result["completed_count"] = sum(1 for r in records if r.completed)
    result["failed_count"] = result["set_count"] - result["completed_count"]
    if records:
        result["completion_pct"] = round(
            result["completed_count"] / result["set_count"] * 100, 1
        )
    tonnages = [r.tonnage for r in records if r.tonnage is not None]
    if tonnages:
        result["total_tonnage"] = round(sum(tonnages), 1)
    rests = [r.rest_sec for r in records if r.rest_sec is not None]
    if rests:
        result["avg_rest_sec"] = round(statistics.mean(rests))

    if not values:
        result["advice"] = "尚無紀錄。到訓練日曆完成一堂 program 後，回來這裡把數據登進去。"
        return result

    better = max if item.higher_is_better else min
    result["best"] = better(values)
    result["latest"] = values[-1]
    result["first"] = values[0]
    result["average"] = round(statistics.mean(values), 2)
    result["gap_to_best"] = round(abs(values[-1] - result["best"]), 2)

    if len(values) < 2:
        result["advice"] = "只有 1 筆紀錄，再累積至少 1 筆才算得出趨勢。"
        return result

    base = date.today()
    xs = [(r.date - base).days for r in with_value]
    slope = _linear_slope(xs, values)
    if slope is not None:
        result["slope_per_month"] = round(slope * 30, 3)
        result["improving"] = slope > 0 if item.higher_is_better else slope < 0

    if values[0]:
        change = (values[-1] - values[0]) / abs(values[0]) * 100
        result["change_pct"] = round(change if item.higher_is_better else -change, 1)

    spread = statistics.pstdev(values)
    if result["improving"] is True:
        result["advice"] = (
            f"趨勢向好，每月約 {abs(result['slope_per_month'])} {item.unit}。"
            "維持目前的課表方向，別急著加量。"
        )
    elif result["improving"] is False:
        result["advice"] = (
            f"近期退步，每月約 {abs(result['slope_per_month'])} {item.unit}。"
            "先看同期的 ACWR 與睡眠——多數情況是累積疲勞而不是能力下降。"
        )
    else:
        result["advice"] = "數值持平，可考慮調整刺激（強度或動作選擇）。"

    if result["best"] and spread / (abs(statistics.mean(values)) or 1) > 0.15:
        result["advice"] += " 另外波動偏大，記錄時記得註明情境（風速、組次、疲勞度）。"

    if result["failed_count"]:
        result["advice"] += (
            f" 有 {result['failed_count']} 組沒有成功完成"
            f"（完成率 {result['completion_pct']}%），"
            "重量或組數可能開太高，下一輪先降 5–10% 再往上疊。"
        )

    return result


def metric_overview(athlete, domain, days=365, used_only=False, keep_ids=None):
    """一個範疇底下所有項目的摘要，給數據分析頁的項目清單用。"""
    from analytics.models import MetricItem, MetricRecord

    items = MetricItem.objects.filter(domain=domain, is_active=True)
    if used_only:
        # 沒登過數據的項目不佔版面；要開新項目就從活動庫或「新增項目」挑
        used = set(
            MetricRecord.objects.filter(athlete=athlete, item__domain=domain)
            .values_list("item_id", flat=True)
        )
        used.update(keep_ids or [])
        items = items.filter(id__in=used)
    since = date.today() - timedelta(days=days)
    rows = []
    for item in items:
        qs = MetricRecord.objects.filter(athlete=athlete, item=item, date__gte=since)
        pairs = list(qs.values_list("value", "date"))
        # 只填了目標、還沒填完成數值的紀錄算得進筆數，但算不出最佳與最近
        values = [p for p in pairs if p[0] is not None]
        if values:
            nums = [float(v) for v, _ in values]
            latest = max(values, key=lambda p: p[1])
            best = (max if item.higher_is_better else min)(nums)
        else:
            nums, latest, best = [], None, None
        rows.append(
            {
                "item": item,
                "count": len(pairs),
                "latest": float(latest[0]) if latest else None,
                "latest_date": latest[1] if latest else None,
                "best": best,
            }
        )
    rows.sort(key=lambda r: (-r["count"], r["item"].name))
    return rows


def overview_by_category(rows):
    """項目清單依動作分類分組；空的分類不顯示。"""
    from analytics.models import MetricCategory

    labels = dict(MetricCategory.choices)
    buckets = {}
    for row in rows:
        buckets.setdefault(row["item"].category, []).append(row)
    groups = []
    for value, label in MetricCategory.choices:
        if buckets.get(value):
            groups.append({"value": value, "label": label, "rows": buckets[value]})
    # 資料庫裡若有不認得的分類，照樣列出來，不要讓項目憑空消失
    for value, rows_ in buckets.items():
        if value not in labels:
            groups.append({"value": value, "label": "其他", "rows": rows_})
    return groups


# ------------------------------------------------- 分組比較（整體／年份／時期）


#: 比較的幾種切法（「分強度」只對田徑練習有意義，見 compare_modes_for）
COMPARE_MODES = [
    ("all", "整體"),
    ("year", "分年份"),
    ("phase", "分時期"),
    ("intensity", "分強度"),
]

#: 每個範疇能用的比較切法
COMPARE_MODES_BY_DOMAIN = {"TRACK": ["all", "year", "phase", "intensity"]}
DEFAULT_COMPARE_MODES = ["all", "year", "phase"]


def compare_modes_for(domain):
    """這個範疇的比較切法——只有田徑練習多一個「分強度」。"""
    allowed = COMPARE_MODES_BY_DOMAIN.get(domain, DEFAULT_COMPARE_MODES)
    return [(v, l) for v, l in COMPARE_MODES if v in allowed]


def _intensity_key(record):
    """紀錄的強度分組鍵（沒填強度的歸到一組）。"""
    return (record.intensity or "").strip() or "—"


def _intensity_order(key):
    """強度由高到低排；純數字（90、95%）照數字排，文字的排在後面。"""
    digits = "".join(c for c in key if c.isdigit() or c == ".")
    try:
        return (0, -float(digits))
    except ValueError:
        return (1, 0) if key != "—" else (2, 0)


def phase_lookup(athlete):
    """回傳一個 date → Phase 的查表函式（一次撈完，不要逐筆查資料庫）。"""
    from planning.models import Phase

    phases = list(
        Phase.objects.filter(macrocycle__athlete=athlete)
        .select_related("macrocycle")
        .order_by("start_date")
    )

    def lookup(on_date):
        for phase in phases:
            if phase.start_date <= on_date <= phase.end_date:
                return phase
        return None

    return lookup


def _group_stats(key, label, records, item, sublabel=""):
    """一組紀錄的摘要：最佳、平均、最近、噸位、完成率、期間內的變化。"""
    values = [float(r.value) for r in scored(records)]
    better = max if item.higher_is_better else min
    dates = [r.date for r in records]
    tonnages = [r.tonnage for r in records if r.tonnage is not None]
    completed = sum(1 for r in records if r.completed)
    first_v, last_v = (values[0], values[-1]) if values else (None, None)
    change_pct = None
    if first_v:
        raw = (last_v - first_v) / abs(first_v) * 100
        change_pct = round(raw if item.higher_is_better else -raw, 1)
    return {
        "key": key,
        "label": label,
        "sublabel": sublabel,
        "count": len(values),
        "days": len(set(dates)),
        "first_date": min(dates),
        "last_date": max(dates),
        "best": better(values) if values else None,
        "worst": (min if item.higher_is_better else max)(values) if values else None,
        "average": round(statistics.mean(values), 2) if values else None,
        "latest": last_v,
        "total_tonnage": round(sum(tonnages), 1) if tonnages else None,
        "total_reps": sum(r.reps for r in records if r.reps is not None) or None,
        "completion_pct": round(completed / len(records) * 100, 1),
        "failed": len(records) - completed,
        "change_pct": change_pct,
        "improving": None if change_pct is None else change_pct > 0,
    }


def metric_comparison(athlete, item, mode="all", days=1825):
    """把一個項目的紀錄依「整體 / 年份 / 時期」分組比較。

    分時期用的是這名運動員自己備戰計劃裡的分期（planning.Phase）——
    同一個動作在一般準備期和比賽期本來就不該是同一個數字，分開看才有意義。
    """
    from core.models import PhaseType, phase_guide

    if mode not in {m for m, _ in COMPARE_MODES}:
        mode = "all"

    records = metric_points(athlete, item, days)
    result = {
        "mode": mode,
        "mode_label": dict(COMPARE_MODES)[mode],
        "item": item,
        "groups": [],
        "best_group": None,
        "count": len(records),
    }
    if not records:
        return result

    buckets = {}
    order = {}
    if mode == "year":
        for r in records:
            key = str(r.date.year)
            buckets.setdefault(key, []).append(r)
            order[key] = key
    elif mode == "intensity":
        for r in records:
            buckets.setdefault(_intensity_key(r), []).append(r)
        order = {
            k: f"{i:02d}"
            for i, k in enumerate(sorted(buckets, key=_intensity_order))
        }
    elif mode == "phase":
        lookup = phase_lookup(athlete)
        for r in records:
            phase = lookup(r.date)
            key = phase.phase_type if phase else "NONE"
            buckets.setdefault(key, []).append(r)
        # 依教科書上的時期順序排，未分期放最後
        order = {t.value: f"{i}" for i, t in enumerate(PhaseType)}
        order["NONE"] = "9"
    else:
        buckets["all"] = list(records)
        order["all"] = "0"

    labels = dict(PhaseType.choices)
    for key, rows in buckets.items():
        if mode == "phase":
            label = labels.get(key, "未分期")
            guide = phase_guide(key)
            sublabel = guide.get("feature", "這些日期不在任何一個分期裡")
        elif mode == "year":
            label = f"{key} 年"
            sublabel = ""
        elif mode == "intensity":
            label = "未填強度" if key == "—" else f"強度 {key}"
            sublabel = f"{len({r.date for r in rows})} 天的紀錄"
        else:
            label = "整體"
            sublabel = f"{records[0].date} 至 {records[-1].date}"
        result["groups"].append(_group_stats(key, label, rows, item, sublabel))

    result["groups"].sort(key=lambda g: order.get(g["key"], g["key"]))

    bests = [g["best"] for g in result["groups"] if g["best"] is not None]
    overall_best = (max if item.higher_is_better else min)(bests) if bests else None
    for g in result["groups"]:
        g["is_best"] = g["best"] is not None and g["best"] == overall_best
        if g["is_best"] and result["best_group"] is None:
            result["best_group"] = g
    return result


def top_movements(athlete, domain, days=365, limit=8):
    """這個範疇裡做得最多的項目排行（重量訓練頁的「最常做的動作」）。

    以「練過幾天」排序而不是「幾組」——一堂課做十組深蹲不代表常做深蹲，
    十天各做三組才是。
    """
    from analytics.models import MetricRecord

    since = date.today() - timedelta(days=days)
    records = (
        MetricRecord.objects.filter(
            athlete=athlete, item__domain=domain, date__gte=since, item__is_active=True
        )
        .select_related("item")
        .order_by("date", "id")
    )

    by_item = {}
    for r in records:
        by_item.setdefault(r.item_id, {"item": r.item, "records": []})["records"].append(r)

    rows = []
    for entry in by_item.values():
        item = entry["item"]
        stats = _group_stats("item", item.name, entry["records"], item)
        stats["item"] = item
        rows.append(stats)

    rows.sort(key=lambda r: (-r["days"], -r["count"], r["label"]))
    return rows[:limit]


# ---------------------------------------------------------------- 比賽分析


def competition_report(athlete, days=1825):
    """把比賽數據依「一場比賽」整理起來，並跟個人最佳與上一場比較。

    比賽的看法跟練習不一樣：教練關心的是「這場比出什麼、比上一場進步了沒、
    離個人最佳還差多少」，所以這裡以賽事為單位，而不是以動作為單位。
    """
    from analytics.models import MetricDomain, MetricRecord

    since = date.today() - timedelta(days=days)
    records = list(
        MetricRecord.objects.filter(
            athlete=athlete, item__domain=MetricDomain.COMPETITION, date__gte=since,
            value__isnull=False,          # 只填了目標、還沒有成績的先不進逐場分析
        )
        .select_related("item", "competition", "session")
        .order_by("date", "id")
    )
    if not records:
        return []

    # 個人最佳（同一個項目全部紀錄裡最好的一筆）
    bests = {}
    for r in records:
        value = float(r.value)
        best = bests.get(r.item_id)
        if best is None or (value > best if r.item.higher_is_better else value < best):
            bests[r.item_id] = value

    # 依賽事分組；沒指定賽事的就用日期當一場
    meets = {}
    for r in records:
        if r.competition_id:
            key = ("comp", r.competition_id)
            label = r.competition.name
            on_date = r.competition.date
            level = r.competition.get_level_display()
        else:
            key = ("date", r.date)
            label = r.session.title if r.session else f"{r.date} 的比賽紀錄"
            on_date = r.date
            level = ""
        meet = meets.setdefault(
            key,
            {
                "key": f"{key[0]}-{key[1]}",
                "competition": r.competition,
                "label": label,
                "date": on_date,
                "level": level,
                "items": {},
            },
        )
        meet["items"].setdefault(r.item_id, {"item": r.item, "records": []})[
            "records"
        ].append(r)

    ordered = sorted(meets.values(), key=lambda m: m["date"])

    # 逐場算出每個項目的成績、與上一場的差距、與個人最佳的差距
    previous = {}
    for meet in ordered:
        rows, pb_count = [], 0
        for entry in meet["items"].values():
            item = entry["item"]
            values = [float(r.value) for r in entry["records"]]
            mark = (max if item.higher_is_better else min)(values)
            prev = previous.get(item.id)
            delta = round(mark - prev, 2) if prev is not None else None
            improved = None
            if delta is not None and delta != 0:
                improved = (delta > 0) if item.higher_is_better else (delta < 0)
            pb = bests.get(item.id)
            is_pb = pb is not None and abs(mark - pb) < 1e-9
            pb_count += int(is_pb)
            rows.append(
                {
                    "item": item,
                    "mark": round(mark, 2),
                    "count": len(values),
                    "records": entry["records"],
                    "prev": prev,
                    "delta": delta,
                    "improved": improved,
                    "pb": pb,
                    "gap_to_pb": (
                        round(abs(mark - pb), 2) if pb is not None and not is_pb else None
                    ),
                    "is_pb": is_pb,
                }
            )
            previous[item.id] = mark
        rows.sort(key=lambda row: row["item"].name)
        meet["rows"] = rows
        meet["pb_count"] = pb_count
        meet["item_count"] = len(rows)
        improved_rows = [r for r in rows if r["improved"] is True]
        if pb_count:
            meet["summary"] = f"這一場刷新了 {pb_count} 項個人最佳。"
        elif improved_rows:
            meet["summary"] = f"{len(improved_rows)} 項比上一場進步，尚未破個人最佳。"
        elif any(r["prev"] is not None for r in rows):
            meet["summary"] = "成績未超越上一場，可回頭看賽前減量與熱身安排。"
        else:
            meet["summary"] = "這是這些項目的第一場紀錄，之後就有得比。"
        del meet["items"]

    ordered.reverse()  # 最近的一場排最前
    return ordered

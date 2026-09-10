"""
負荷監控與表現分析的全部計算邏輯。

原則：view / serializer 不做計算，只呼叫這裡的函式。

負荷定義（Foster sRPE）：
    session_load = session_rpe × actual_duration_min      單位 AU (Arbitrary Unit)
"""

import re
import statistics
from datetime import date, timedelta

from django.db.models import Avg, Max, Sum
from django.utils.translation import gettext_lazy as _

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

    obj, _unused = DailyLoad.objects.update_or_create(
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
    for _unused, load in sorted(series.items()):
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
    RiskFlag.UNDER: ("🔵", _("訓練量偏低，體能儲備可能流失。可在下週逐步增量 5–10%。")),
    RiskFlag.OPTIMAL: ("🟢", _("負荷處於甜蜜點 (0.8–1.3)，維持目前節奏。")),
    RiskFlag.ELEVATED: ("🟡", _("負荷偏高，注意睡眠與恢復，避免連續兩週再加量。")),
    RiskFlag.HIGH: ("🔴", _("高受傷風險 (ACWR > 1.5)！建議本週減量 20–30%，並加強恢復手段。")),
    RiskFlag.INSUFFICIENT: ("⚪", _("資料累積中，需滿 28 天訓練紀錄才能計算 ACWR。")),
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
    obj, _unused = WeeklySummary.objects.update_or_create(
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
        return {"score": None, "label": _("無資料"), "inputs": 0}

    score = round(sum(p * w for p, w in zip(parts, weights)) / sum(weights), 1)
    if score >= 80:
        label = _("🟢 狀態良好，可執行高強度")
    elif score >= 65:
        label = _("🟡 尚可，維持計劃但注意反應")
    elif score >= 50:
        label = _("🟠 疲勞明顯，建議降低強度")
    else:
        label = _("🔴 恢復不足，改為主動恢復或休息")
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
        else Competition.objects.filter(
            athlete=athlete, is_target=True, date__gte=on_date
        ).first()
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
                # 當天的狀態註記（同一天通常同一個狀態，取第一個有填的）
                "status": next((r.status for r in rows if r.status), ""),
                "status_label": next((r.status_label for r in rows if r.status), ""),
            }
        )
    return result


def status_breakdown(records, item):
    """這個項目的紀錄，各在什麼狀態下練出來的。

    分析退步與否之前要先看這一份——同一個動作在傷害治療期跟比賽調整期
    跑出來的數字本來就是兩回事，混在一起算斜率只會得到錯的結論。
    """
    from analytics.models import TrainingStatus, status_guide

    labels = dict(TrainingStatus.choices)
    buckets = {}
    for r in records:
        buckets.setdefault(r.status or "", []).append(r)

    order = {t.value: i for i, t in enumerate(TrainingStatus)}
    order[""] = 99
    rows = []
    for key in sorted(buckets, key=lambda k: order.get(k, 98)):
        group = buckets[key]
        values = [float(r.value) for r in scored(group)]
        better = max if item.higher_is_better else min
        guide = status_guide(key)
        rows.append(
            {
                "value": key,
                "label": labels.get(key, "未註記狀態"),
                "count": len(group),
                "days": len({r.date for r in group}),
                "first_date": min(r.date for r in group),
                "last_date": max(r.date for r in group),
                "best": better(values) if values else None,
                "average": round(statistics.mean(values), 2) if values else None,
                "feature": guide["feature"],
                "reading": guide["reading"],
            }
        )
    return rows


#: 分析一段時間的表現時，除了狀態註記還該一起看的東西
def _considerations(athlete, item, records, status_rows, result):
    """「先確認這些，再下結論」——把同期該一起看的因素列出來。

    這些不是結論，是判讀的前提：狀態註記、傷患、負荷、睡眠、完成率、
    強度與休息的變化。全部看過一輪，才知道退步是狀態造成的還是能力掉了。
    """
    from injury.models import Injury
    from nutrition.models import RecoveryLog

    factors = []
    if not records:
        return factors

    window_start = min(r.date for r in records[-30:])
    window_end = max(r.date for r in records)

    # ① 當天的狀態註記——這是第一順位
    stated = [row for row in status_rows if row["value"]]
    unstated = next((row for row in status_rows if not row["value"]), None)
    if stated:
        text = "；".join(
            _("%(v0)s %(v1)s 天／%(v2)s 組") % {"v0": row['label'], "v1": row['days'], "v2": row['count']}
            + (_("（最佳 %(v0)s%(v1)s）") % {"v0": row['best'], "v1": item.unit} if row["best"] is not None else "")
            for row in stated
        )
        factors.append(
            {
                "key": "status",
                "label": _("同日的狀態註記"),
                "text": text + "。" + "；".join(
                    f"{row['label']}：{row['reading']}" for row in stated
                ),
                "level": "warn" if any(
                    row["value"] in ("INJURY", "OFFSEASON", "RETURN") for row in stated
                ) else "ok",
            }
        )
    if unstated:
        factors.append(
            {
                "key": "status_missing",
                "label": _("還沒註記狀態的紀錄"),
                "text": _("有 %(v0)s 天／%(v1)s 組沒有填狀態。在紀錄明細把那幾天的狀態補上（季後休息／訓練準備／比賽調整／傷害治療／恢復回歸），趨勢才分得清是狀態還是能力。") % {"v0": unstated['days'], "v1": unstated['count']},
                "level": "warn" if not stated else "info",
            }
        )

    # ② 這段期間身上有沒有傷
    injuries = [
        inj
        for inj in Injury.objects.filter(athlete=athlete).order_by("-onset_date")[:20]
        if inj.onset_date <= window_end
        and (inj.is_active or inj.updated_at.date() >= window_start)
    ]
    if injuries:
        factors.append(
            {
                "key": "injury",
                "label": _("同期的傷患紀錄"),
                "text": "；".join(
                    _("%(v0)s%(v1)s（%(v2)s 起，%(v3)s）") % {"v0": i.get_body_part_display(), "v1": i.get_injury_type_display(), "v2": i.onset_date, "v3": i.get_status_display()}
                    for i in injuries[:3]
                )
                + _("。帶著這個傷練出來的數字，先當成受限表現，不要當成能力下降。"),
                "level": "warn",
            }
        )

    # ③ 同期的訓練負荷（ACWR / 單調度）
    report = acwr_report(athlete)
    if report.get("acwr"):
        factors.append(
            {
                "key": "load",
                "label": _("同期的訓練負荷"),
                "text": f"ACWR {report['acwr']}（{report['risk_label']}）。{report['advice']}",
                "level": "warn" if report["risk_flag"] in ("HIGH", "ELEVATED") else "ok",
            }
        )
    else:
        factors.append(
            {
                "key": "load",
                "label": _("同期的訓練負荷"),
                "text": _("課表完成紀錄還不夠，算不出 ACWR。先把每堂課的時長與 RPE 補齊。"),
                "level": "info",
            }
        )

    # ④ 睡眠與恢復
    logs = list(
        RecoveryLog.objects.filter(
            athlete=athlete, date__gte=window_start, date__lte=window_end
        ).values_list("sleep_hours", "soreness_level")
    )
    sleeps = [float(h) for h, _unused in logs if h is not None]
    sores = [s for _unused, s in logs if s]
    if sleeps:
        avg_sleep = round(statistics.mean(sleeps), 1)
        bits = [_("平均睡眠 %(v0)s 小時") % {"v0": avg_sleep}]
        if sores:
            bits.append(_("平均痠痛 %(v0)s/10") % {"v0": round(statistics.mean(sores), 1)})
        factors.append(
            {
                "key": "sleep",
                "label": _("同期的睡眠與恢復"),
                "text": "、".join(bits)
                + (_("。睡眠不足 7 小時的期間，速度與爆發力先掉，不代表能力退步。")
                   if avg_sleep < 7 else _("。恢復面看起來沒有明顯拖累。")),
                "level": "warn" if avg_sleep < 7 else "ok",
            }
        )
    else:
        factors.append(
            {
                "key": "sleep",
                "label": _("同期的睡眠與恢復"),
                "text": _("這段期間沒有恢復紀錄（睡眠、痠痛、壓力）。到營養／恢復頁補上，才判斷得出是疲勞還是能力。"),
                "level": "info",
            }
        )

    # ⑤ 課表本身有沒有做完
    if result["failed_count"]:
        factors.append(
            {
                "key": "completion",
                "label": _("課表完成情況"),
                "text": _("有 %(v0)s 組沒有成功完成（完成率 %(v1)s%%）。先確認是開太重／開太快，還是當天狀態就不行。") % {"v0": result['failed_count'], "v1": result['completion_pct']},
                "level": "warn",
            }
        )

    # ⑥ 強度要求與休息時間——條件不一樣，數字本來就不一樣
    intensities = {(r.intensity or "").strip() for r in records if (r.intensity or "").strip()}
    if len(intensities) > 1:
        factors.append(
            {
                "key": "intensity",
                "label": _("強度要求不一致"),
                "text": _("這些紀錄混了 ") + "、".join(sorted(intensities))
                        + _(" 幾種強度要求。用上面的「分強度」比較，同一檔強度對同一檔強度看才準。"),
                "level": "info",
            }
        )
    rests = [r.rest_sec for r in records if r.rest_sec is not None]
    if len(rests) >= 4:
        first_half = statistics.mean(rests[: len(rests) // 2])
        second_half = statistics.mean(rests[len(rests) // 2 :])
        if first_half and abs(second_half - first_half) / first_half > 0.3:
            factors.append(
                {
                    "key": "rest",
                    "label": _("休息時間變了"),
                    "text": _("前段平均休息 %(v0)s 分、後段 %(v1)s 分。休息縮短本來就會讓數字變差，這是課表設計不是能力變化。") % {"v0": round(first_half / 60, 1), "v1": round(second_half / 60, 1)},
                    "level": "info",
                }
            )
    return factors


def metric_analysis(athlete, item, days=365):
    """依紀錄自動產生分析：最佳、最近、趨勢、與最佳的差距、建議。

    「好」的方向由項目自己的 higher_is_better 決定——計時類越小越好，
    重量與距離類越大越好，所以進步與否不能只看斜率正負。
    """
    from core.models import PhaseType

    records = metric_points(athlete, item, days)
    with_value = scored(records)          # 只有填了完成數值的才算得出趨勢
    values = [float(r.value) for r in with_value]
    # 主圖可以切「分年份和月份／分時期／分狀態」，所以每一筆都先帶上分組標籤
    phase_of = phase_lookup(athlete)
    phase_labels = dict(PhaseType.choices)

    def _phase_label(on_date):
        phase = phase_of(on_date)
        return phase_labels.get(phase.phase_type, "未分期") if phase else _("未分期")
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
                # 距離：課表正課那一欄登進來的米數，圖上點一下看得到
                "distance": float(r.distance_m) if r.distance_m is not None else None,
                "intensity": r.intensity,
                "reps": r.reps,
                "rest_sec": r.rest_sec,
                "rest_min": r.rest_min,
                "tonnage": r.tonnage,
                "completed": r.completed,
                "label": (_("%(v0)s 第%(v1)s組") % {"v0": r.date, "v1": r.set_no} if r.set_no else str(r.date)),
                # 主圖分組用：年、年月、時期、狀態
                "year": str(r.date.year),
                "month": f"{r.date.year}-{r.date.month:02d}",
                "phase": _phase_label(r.date),
                "status": r.status_label if r.status else _("未註記狀態"),
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
        "avg_rest_min": None,
        "best": None,
        "latest": None,
        "first": None,
        "average": None,
        "slope_per_month": None,
        "improving": None,
        "gap_to_best": None,
        "change_pct": None,
        "advice": "",
        # 下結論之前要先看過的東西
        "status_rows": [],
        "considerations": [],
        "status_note": "",
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
        result["avg_rest_min"] = round(result["avg_rest_sec"] / 60, 2)

    if records:
        result["status_rows"] = status_breakdown(records, item)

    if not values:
        result["advice"] = _("尚無完成數值。到訓練日曆完成一堂 program 後，回來這裡把數據登進去。")
        return result

    better = max if item.higher_is_better else min
    result["best"] = better(values)
    result["latest"] = values[-1]
    result["first"] = values[0]
    result["average"] = round(statistics.mean(values), 2)
    result["gap_to_best"] = round(abs(values[-1] - result["best"]), 2)

    if len(values) < 2:
        result["advice"] = _("只有 1 筆紀錄，再累積至少 1 筆才算得出趨勢。")
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

    # 下結論之前，先把該看的看過一輪：當天在什麼狀態下練的、
    # 同期有沒有傷、負荷與睡眠如何、課表有沒有做完、條件是不是變了。
    result["considerations"] = _considerations(
        athlete, item, records, result["status_rows"], result
    )
    stated = [row for row in result["status_rows"] if row["value"]]
    mixed = len(stated) > 1
    special = [row for row in stated if row["value"] in ("INJURY", "RETURN", "OFFSEASON")]

    if special:
        result["status_note"] = (
            _("這段紀錄有 ")
            + "、".join(str(_("%(v0)s（%(v1)s 天）") % {"v0": row['label'], "v1": row['days']}) for row in special)
            + _("——這些日子本來就跑不出平常的水準，先把它們排除或分開看，再談進退步。")
        )
    elif mixed:
        result["status_note"] = (
            _("這段紀錄橫跨 ")
            + "、".join(str(row["label"]) for row in stated)
            + _(" 幾種狀態，各期的訓練目的不同，用上面的「分狀態」比較才對得起來。")
        )
    elif not stated:
        result["status_note"] = (
            _("這些紀錄都沒有註記當天的狀態。先在紀錄明細把狀態補上（季後休息期／訓練準備期／比賽調整期／傷害治療期／恢復回歸期），分析才分得清是狀態造成的還是能力變化。")
        )

    # 全部紀錄同一天的話算不出斜率，這時候就不要寫「每月約幾秒」
    trend = (
        _("每月約 %(v0)s %(v1)s") % {"v0": abs(result['slope_per_month']), "v1": item.unit}
        if result["slope_per_month"] is not None
        else _("但算不出每月變化（紀錄集中在同一天）")
    )
    if result["improving"] is True:
        head = _("趨勢向好，%(v0)s。") % {"v0": trend}
        tail = (
            _("在上面的狀態與同期條件都確認過之後，這個進步才算數；確認無誤就維持目前的課表方向，別急著加量。")
        )
    elif result["improving"] is False:
        head = _("數字上是退步，%(v0)s。") % {"v0": trend}
        if special:
            tail = (
                _("但同期有") + "、".join(str(row["label"]) for row in special)
                + _("，這種狀態下數字本來就會掉——先當成狀態造成的受限表現，等回到正常訓練狀態再重新取一段來比。")
            )
        else:
            tail = (
                _("先把上面列的因素逐項對過（狀態註記、傷患、ACWR、睡眠、完成率、強度與休息是否一致）——多數情況是累積疲勞或條件改變，全部排除之後才判定是能力下降。")
            )
    else:
        head = _("數值持平。")
        tail = _("先確認上面的狀態與條件沒有變；沒有的話，可考慮調整刺激（強度或動作選擇）。")
    result["advice"] = head + tail

    if result["best"] and spread / (abs(statistics.mean(values)) or 1) > 0.15:
        result["advice"] += _(" 另外波動偏大，記錄時記得註明狀態與情境（風速、組次、疲勞度）。")

    if result["failed_count"]:
        result["advice"] += (
            _(" 有 %(v0)s 組沒有成功完成（完成率 %(v1)s%%），重量或組數可能開太高，下一輪先降 5–10%% 再往上疊。") % {"v0": result['failed_count'], "v1": result['completion_pct']}
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
    # 清單依「最新登錄」排序，看的是這個項目最後一次登記錄是哪一天——
    # 那一天可能在一年之外，所以不受下面的時間窗限制，另外算一次。
    logged = dict(
        MetricRecord.objects.filter(athlete=athlete, item__domain=domain)
        .values("item_id")
        .annotate(last=Max("date"))
        .values_list("item_id", "last")
    )
    since = date.today() - timedelta(days=days)
    rows = []
    for item in items:
        qs = MetricRecord.objects.filter(athlete=athlete, item=item, date__gte=since)
        pairs = list(qs.values_list("value", "date"))
        # 只填了目標、還沒填完成數值的紀錄算得進筆數，但算不出最佳與最近
        values = [p for p in pairs if p[0] is not None]
        if values:
            nums = [float(v) for v, _unused in values]
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
                # 最後一次登記錄的日期（沒填完成數值的那幾筆也算）
                "last_date": logged.get(item.id),
                "best": best,
            }
        )
    rows.sort(key=lambda r: (-r["count"], r["item"].name))
    return rows


def overview_by_recent(rows):
    """項目清單依「最新登錄」排：剛記過的排最上面，沒登過的排最後。"""
    return sorted(
        rows,
        key=lambda r: (
            (0, -r["last_date"].toordinal()) if r["last_date"] else (1, 0),
            r["item"].name,
        ),
    )


# ------------------------------------------------- 分組比較（整體／年份／時期）


#: 比較的幾種切法（「分強度」只對田徑練習有意義，見 compare_modes_for）
COMPARE_MODES = [
    ("all", _("整體")),
    ("year", _("分年份")),
    ("phase", _("分時期")),
    ("status", _("分狀態")),
    ("intensity", _("分強度")),
]

#: 每個範疇能用的比較切法
COMPARE_MODES_BY_DOMAIN = {"TRACK": ["all", "year", "phase", "status", "intensity"]}
DEFAULT_COMPARE_MODES = ["all", "year", "phase", "status"]


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

    if mode not in {m for m, _unused in COMPARE_MODES}:
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
    elif mode == "status":
        from analytics.models import TrainingStatus

        for r in records:
            buckets.setdefault(r.status or "", []).append(r)
        order = {t.value: f"{i}" for i, t in enumerate(TrainingStatus)}
        order[""] = "9"          # 沒註記狀態的排最後
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
            label = _("%(v0)s 年") % {"v0": key}
            sublabel = ""
        elif mode == "status":
            from analytics.models import TrainingStatus, status_guide

            label = dict(TrainingStatus.choices).get(key, "未註記狀態")
            sublabel = status_guide(key)["feature"]
        elif mode == "intensity":
            label = _("未填強度") if key == "—" else _("強度 %(v0)s") % {"v0": key}
            sublabel = _("%(v0)s 天的紀錄") % {"v0": len({r.date for r in rows})}
        else:
            label = _("整體")
            sublabel = _("%(v0)s 至 %(v1)s") % {"v0": records[0].date, "v1": records[-1].date}
        result["groups"].append(_group_stats(key, label, rows, item, sublabel))

    result["groups"].sort(key=lambda g: order.get(g["key"], g["key"]))

    bests = [g["best"] for g in result["groups"] if g["best"] is not None]
    overall_best = (max if item.higher_is_better else min)(bests) if bests else None
    for g in result["groups"]:
        g["is_best"] = g["best"] is not None and g["best"] == overall_best
        if g["is_best"] and result["best_group"] is None:
            result["best_group"] = g
    return result


# ------------------------------------------- 相關的項目（要不要加在一起分析）
#
# 課表上一個活動按了「登記錄」，數據分析裡常常已經有一個講同一件事的項目：
# 同一個距離不同方式（150m 節奏跑／150m 反覆跑）、同一個動作換個寫法。
# 這種時候分開看看不出所以然，所以在畫面上問一句「要不要加在一起分析」。


#: 名稱裡「不決定這是哪一件事」的部分：括號註解、數字（連同 m / kg / 秒）、分隔符
_NAME_NOISE = re.compile(
    r"[（(][^)）]*[)）]|\d+(?:\.\d+)?\s*(?:m|米|公尺|kg|公斤|秒|s)?|[\s·・\-_/、]+",
    re.IGNORECASE,
)


def name_core(name):
    """把距離、括號註解、空白拿掉，剩下的就是「這是哪一件事」。

    「150m 反覆跑」→「反覆跑」、「30m 衝刺」→「衝刺」，
    所以同一種練法的不同距離認得出是一夥的。
    """
    return _NAME_NOISE.sub("", name or "").strip().lower()


def _relation(item, other):
    """other 跟 item 是哪一種「相關」；不相關回 None。"""
    from analytics.models import MetricDomain

    if item.domain == MetricDomain.TRACK.value:
        if item.track_distance_m and item.track_distance_m == other.track_distance_m:
            return _("同樣是 %(v0)s m") % {"v0": item.track_distance_m}
        if item.track_method and item.track_method == other.track_method:
            return _("同樣是%(v0)s") % {"v0": other.get_track_method_display()}
    core = name_core(item.name)
    if core and core == name_core(other.name):
        return _("名稱講的是同一件事")
    return None


def related_items(athlete, item, days=365, limit=6):
    """同一個範疇裡跟這個項目相關、而且這名運動員已經有紀錄的其他項目。

    回傳 [{item, reason, count, days, last_date}]，紀錄多的排前面；
    沒有相關的就回空清單（畫面上那句提問也就不出現）。
    """
    from analytics.models import MetricItem, MetricRecord

    if item is None:
        return []
    candidates = [
        other
        for other in MetricItem.objects.filter(domain=item.domain, is_active=True).exclude(
            pk=item.pk
        )
        if _relation(item, other)
    ]
    if not candidates:
        return []

    since = date.today() - timedelta(days=days)
    rows = []
    for other in candidates:
        dates = list(
            MetricRecord.objects.filter(
                athlete=athlete, item=other, date__gte=since
            ).values_list("date", flat=True)
        )
        if not dates:
            continue
        rows.append(
            {
                "item": other,
                "reason": _relation(item, other),
                "count": len(dates),
                "days": len(set(dates)),
                "last_date": max(dates),
            }
        )
    rows.sort(key=lambda r: (-r["count"], r["item"].name))
    return rows[:limit]


def multi_item_analysis(athlete, items, days=365):
    """把幾個項目放在一起比。

    田徑練習常常出現「同一個距離、不同方式」（150m 節奏跑 vs 150m 反覆跑）
    或「同一個方式、不同距離」，重量訓練也有相近的動作。
    這些項目各自的趨勢分開看沒意思，並排看才知道哪一種練得起來。
    """
    items = [i for i in items if i is not None]
    result = {"items": items, "rows": [], "series": [], "units": [], "note": ""}
    if not items:
        return result

    for item in items:
        records = metric_points(athlete, item, days)
        if not records:
            result["rows"].append(
                {
                    "item": item,
                    "count": 0,
                    "days": 0,
                    "best": None,
                    "average": None,
                    "latest": None,
                    "change_pct": None,
                    "improving": None,
                    "completion_pct": None,
                    "empty": True,
                }
            )
            result["series"].append({"item": item.display_name, "unit": item.unit, "points": []})
            continue

        stats = _group_stats("item", item.display_name, records, item)
        stats["item"] = item
        stats["empty"] = False
        stats["higher_is_better"] = item.higher_is_better
        result["rows"].append(stats)

        # 圖上一條線一個項目：一天一個代表值（當天最好的那一組）
        by_date = {}
        for r in scored(records):
            by_date.setdefault(str(r.date), []).append(float(r.value))
        better = max if item.higher_is_better else min
        result["series"].append(
            {
                "item": item.display_name,
                "unit": item.unit or "",
                "higher_is_better": item.higher_is_better,
                "points": [
                    {"date": d, "value": round(better(vs), 2), "sets": len(vs)}
                    for d, vs in sorted(by_date.items())
                ],
            }
        )

    result["units"] = sorted({(i.unit or "").strip() for i in items})
    directions = {i.higher_is_better for i in items}
    if len(result["units"]) > 1:
        result["note"] = (
            _("挑到的項目單位不一樣（") + "、".join(str(u or _("無單位")) for u in result["units"])
            + _("），數字不能直接比大小，看的是各自的走勢。")
        )
    elif len(directions) > 1:
        result["note"] = _("挑到的項目有的越大越好、有的越小越好，看走勢就好，別直接比高低。")
    else:
        only = result["units"][0] if result["units"] else ""
        result["note"] = _("單位一致（") + (only or _("無單位")) + _("），可以直接並排比。")
    result["rows"].sort(key=lambda r: (r["empty"], -r["count"]))
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


def movement_stats(athlete, items, days=365):
    """指定的幾個項目各自的近況（欄位跟 top_movements 一樣）。

    「主要必看的訓練項目」用這一份：釘出來的項目就算最近沒練過也要列出來
    （才知道它已經多久沒碰了），所以沒有紀錄的項目也回一列。
    """
    from analytics.models import MetricRecord

    items = [i for i in items if i is not None]
    if not items:
        return []
    since = date.today() - timedelta(days=days)
    records = (
        MetricRecord.objects.filter(
            athlete=athlete, item__in=items, date__gte=since
        )
        .select_related("item")
        .order_by("date", "id")
    )
    by_item = {}
    for r in records:
        by_item.setdefault(r.item_id, []).append(r)

    rows = []
    for item in items:
        mine = by_item.get(item.id, [])
        if mine:
            stats = _group_stats("item", item.name, mine, item)
        else:
            stats = {
                "key": "item", "label": item.name, "sublabel": "",
                "count": 0, "days": 0, "first_date": None, "last_date": None,
                "best": None, "worst": None, "average": None, "latest": None,
                "total_tonnage": None, "total_reps": None, "completion_pct": None,
                "failed": 0, "change_pct": None, "improving": None,
            }
        stats["item"] = item
        rows.append(stats)
    return rows


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
            label = r.session.title if r.session else _("%(v0)s 的比賽紀錄") % {"v0": r.date}
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
            meet["summary"] = _("這一場刷新了 %(v0)s 項個人最佳。") % {"v0": pb_count}
        elif improved_rows:
            meet["summary"] = _("%(v0)s 項比上一場進步，尚未破個人最佳。") % {"v0": len(improved_rows)}
        elif any(r["prev"] is not None for r in rows):
            meet["summary"] = _("成績未超越上一場，可回頭看賽前減量與熱身安排。")
        else:
            meet["summary"] = _("這是這些項目的第一場紀錄，之後就有得比。")
        del meet["items"]

    ordered.reverse()  # 最近的一場排最前
    return ordered

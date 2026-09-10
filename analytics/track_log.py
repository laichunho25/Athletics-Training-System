"""田徑練習訓練紀錄：一張平鋪的清單，挑幾筆出來再分析。

以前要看田徑練習的數據，得先在左邊挑一個「項目」（150m 反覆跑），
才看得到它底下的紀錄；想比「今年的 150m 跟去年的 150m」就只能自己記著
上一頁看過什麼。這裡反過來做——把課表上登過的田徑練習全部攤成一張清單，
用年份月份和關鍵字（打「150」就出所有 150m）挑出想看的那幾筆，
再挑一個方向分析：

    perf    表現與時間 —— 這幾筆練得怎樣、跟隊上其他人比是什麼水準
    period  同距離跨時段 —— 一樣的距離在不同年／月／時期，量與強度變成怎樣
    cross   拼入其他數據 —— 同一段時間的重量訓練與身體結構一起看

田徑練習記的是秒，一律越小越好（項目建立時就是這樣定的），
所以這個檔裡的「最佳」都是最小值。
"""

import calendar
import statistics
from datetime import date

from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from analytics.body_strength import estimate_1rm
from analytics.models import (
    MetricDomain,
    MetricRecord,
    TrainingStatus,
    block_choices,
)

#: 清單一次最多列幾筆（再多就請人用年月或關鍵字縮小範圍）
MAX_ROWS = 500

#: 一次最多挑幾筆來分析
MAX_PICKS = 400

#: 跨時段比較時最多列幾個距離（挑做得最多的那幾個）
MAX_DISTANCES = 6

#: 「跟隊上其他人比」最多列幾個人
MAX_PEERS = 8

DIRECTIONS = [
    ("perf", _lazy("表現與時間")),
    ("period", _lazy("同距離跨時段")),
    ("cross", _lazy("拼入重量與身體結構")),
]

GROUPINGS = [
    ("month", _lazy("分月份")),
    ("year", _lazy("分年份")),
    ("phase", _lazy("分訓練時期")),
]

#: 強度欄寫「全力」這種字時，當成 100% 來算平均
MAXIMAL_WORDS = {"全力", "全速", "最大", "max", "maximal", "all out", "all-out"}


# ------------------------------------------------------------------ 清單


def _base(athlete):
    """這名運動員所有田徑練習的紀錄，新的排前面、同一天照組別排。"""
    return (
        MetricRecord.objects.filter(athlete=athlete, item__domain=MetricDomain.TRACK)
        .select_related("item", "session")
        .order_by("-date", "set_no", "id")
    )


def filter_options(athlete, year=None):
    """清單上面那兩個下拉：有紀錄的年份，以及那一年底下有紀錄的月份。"""
    years, months = {}, {}
    for on_date in _base(athlete).values_list("date", flat=True):
        years[on_date.year] = years.get(on_date.year, 0) + 1
        if year in (None, on_date.year):
            months[on_date.month] = months.get(on_date.month, 0) + 1
    return {
        "years": [
            {"value": y, "count": c} for y, c in sorted(years.items(), reverse=True)
        ],
        "months": [{"value": m, "count": months[m]} for m in sorted(months)],
    }


def _number(term):
    try:
        return float(term)
    except ValueError:
        return None


def _term_filter(term):
    """一個關鍵字要比對的所有欄位。

    打「150」找的是距離（連項目名稱裡的 150m 也算），
    打「反覆跑」找項目，打「傷害治療」「正課」找的是狀態與區塊——
    那兩欄存的是代碼，所以先把畫面上的字翻回代碼再比。
    """
    where = (
        Q(item__name__icontains=term)
        | Q(item__name_en__icontains=term)
        | Q(intensity__icontains=term)
        | Q(context__icontains=term)
        | Q(note__icontains=term)
        | Q(session__title__icontains=term)
    )
    number = _number(term)
    if number is not None:
        where |= Q(distance_m=number) | Q(item__track_distance_m=int(number))
    codes = [v for v, label in TrainingStatus.choices if term in str(label)]
    if codes:
        where |= Q(status__in=codes)
    blocks = [v for v, label in block_choices() if term in str(label)]
    if blocks:
        where |= Q(block__in=blocks)
    return where


def search_records(athlete, year=None, month=None, query="", limit=MAX_ROWS):
    """依年份／月份／關鍵字挑出田徑練習的紀錄。"""
    rows = _base(athlete)
    if year:
        rows = rows.filter(date__year=year)
    if month:
        rows = rows.filter(date__month=month)
    for term in (query or "").split():
        rows = rows.filter(_term_filter(term))
    total = rows.count()
    shown = list(rows[:limit])
    return {
        "rows": shown,
        "total": total,
        "shown": len(shown),
        "capped": total > len(shown),
        "limit": limit,
    }


def picked_records(athlete, ids):
    """挑來分析的那幾筆（只認這名運動員自己的紀錄）。"""
    ids = list(ids)[:MAX_PICKS]
    if not ids:
        return []
    found = {r.id: r for r in _base(athlete).filter(id__in=ids)}
    return sorted(
        (found[i] for i in ids if i in found),
        key=lambda r: (r.date, r.set_no or 0, r.id),
    )


# -------------------------------------------------------------- 共用計算


def _distance(record):
    """這一組跑幾米：紀錄自己有就用自己的，沒有就用項目上的距離。"""
    if record.distance_m is not None:
        return float(record.distance_m)
    if record.item.track_distance_m:
        return float(record.item.track_distance_m)
    return None


def _intensity_pct(record):
    """強度要求換成數字（「90%」→ 90、「全力」→ 100），換不出來就 None。"""
    raw = (record.intensity or "").strip()
    if not raw:
        return None
    if raw.lower() in MAXIMAL_WORDS:
        return 100.0
    digits = "".join(c for c in raw if c.isdigit() or c == ".")
    try:
        value = float(digits)
    except ValueError:
        return None
    return value if 0 < value <= 100 else None


def _avg(values, digits=1):
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), digits) if values else None


def _pct_change(old, new, digits=1):
    if not old or new is None:
        return None
    return round((new - old) / abs(old) * 100, digits)


def summarise(records):
    """一批紀錄的摘要：量、強度、成績、完成率都在這裡算好。"""
    records = list(records)
    values = [float(r.value) for r in records if r.value is not None]
    known = [d for d in (_distance(r) for r in records) if d]
    intens = [i for i in (_intensity_pct(r) for r in records) if i is not None]
    rests = [r.rest_sec for r in records if r.rest_sec is not None]
    scored = [r for r in records if r.value is not None and r.target_value is not None]
    on_target = sum(1 for r in scored if float(r.value) <= float(r.target_value))
    dates = sorted({r.date for r in records})
    completed = sum(1 for r in records if r.completed)
    return {
        "count": len(records),
        "days": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        # 秒數越小越好，所以「最佳」＝最小
        "best": min(values) if values else None,
        "worst": max(values) if values else None,
        "average": round(statistics.mean(values), 2) if values else None,
        "scored": len(values),
        "volume_m": round(sum(known)) if known else 0,
        "distances": sorted({int(d) for d in known}),
        "avg_distance": _avg(known),
        "avg_intensity": _avg(intens),
        "avg_rest_min": round(statistics.mean(rests) / 60, 1) if rests else None,
        "completed": completed,
        "failed": len(records) - completed,
        "completion_pct": round(completed / len(records) * 100, 1) if records else None,
        "target_count": len(scored),
        "on_target": on_target,
        "on_target_pct": round(on_target / len(scored) * 100, 1) if scored else None,
    }


def _breakdown(records, keyfunc, sortfunc=None):
    """照某一欄（強度／距離／狀態）分堆，每一堆給一份摘要。"""
    buckets = {}
    for record in records:
        buckets.setdefault(keyfunc(record), []).append(record)
    rows = []
    for label, group in buckets.items():
        stat = summarise(group)
        stat["label"] = label
        rows.append(stat)
    rows.sort(key=sortfunc or (lambda r: -r["count"]))
    return rows


# --------------------------------------------------- 方向一：表現與時間


def _peer_rows(athlete, records, viewer):
    """同樣的距離、同一段日子，隊上其他人跑出什麼。

    比的是水準不是排名——教練要判斷「這個秒數在這個組別算什麼位置」，
    自己一個人的曲線看不出來，擺在同期其他人旁邊才有參照。
    """
    if viewer is None or not records:
        return []
    from core.permissions import athlete_ids_visible_to

    wanted = {int(d) for d in (_distance(r) for r in records) if d}
    if not wanted:
        return []
    ids = [i for i in athlete_ids_visible_to(viewer) if i != athlete.id]
    if not ids:
        return []
    first = min(r.date for r in records)
    last = max(r.date for r in records)
    ints = sorted(wanted)
    others = (
        MetricRecord.objects.filter(
            athlete_id__in=ids,
            item__domain=MetricDomain.TRACK,
            date__gte=first,
            date__lte=last,
            value__isnull=False,
        )
        .filter(Q(distance_m__in=ints) | Q(item__track_distance_m__in=ints))
        .select_related("athlete__user", "item")[: MAX_PICKS * 5]
    )

    buckets = {}
    for record in others:
        if int(_distance(record) or 0) not in wanted:
            continue
        buckets.setdefault(record.athlete, []).append(record)

    mine = summarise(records)
    rows = [
        {
            "name": _("這名運動員"),
            "is_self": True,
            "count": mine["count"],
            "best": mine["best"],
            "average": mine["average"],
        }
    ]
    for other, group in buckets.items():
        stat = summarise(group)
        rows.append(
            {
                "name": other.user.get_full_name() or other.user.username,
                "is_self": False,
                "count": stat["count"],
                "best": stat["best"],
                "average": stat["average"],
            }
        )
    rows.sort(key=lambda r: (r["best"] is None, r["best"] or 0))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows[: MAX_PEERS + 1]


def _perf_insights(stat, points):
    """幾句白話：練了多少、跑得怎樣、有沒有照課表做到。"""
    out = []
    if stat["count"]:
        out.append(
            _("挑出來的 %(v0)s 組分佈在 %(v1)s 天，總距離 %(v2)s m。")
            % {"v0": stat["count"], "v1": stat["days"], "v2": stat["volume_m"]}
        )
    if stat["best"] is not None:
        out.append(
            _("最佳 %(v0)s 秒、平均 %(v1)s 秒。")
            % {"v0": stat["best"], "v1": stat["average"]}
        )
    scored = [p for p in points if p["value"] is not None]
    if len(scored) >= 4:
        half = len(scored) // 2
        early = _avg([p["value"] for p in scored[:half]], 2)
        late = _avg([p["value"] for p in scored[half:]], 2)
        change = _pct_change(early, late)
        if change is not None:
            if change < 0:
                tail = _("後面這幾組快了 %(v0)s%%。") % {"v0": abs(change)}
            elif change > 0:
                tail = _("後面這幾組慢了 %(v0)s%%，先看是不是累積疲勞。") % {"v0": change}
            else:
                tail = _("前後沒有分別。")
            out.append(
                _("前半段平均 %(v0)s 秒、後半段 %(v1)s 秒——") % {"v0": early, "v1": late}
                + tail
            )
    if stat["on_target_pct"] is not None:
        out.append(
            _("有目標數值的 %(v0)s 組裡，做到目標的佔 %(v1)s%%。")
            % {"v0": stat["target_count"], "v1": stat["on_target_pct"]}
        )
    if stat["failed"]:
        out.append(
            _("其中 %(v0)s 組沒有完成，分析成績之前先看那幾天的狀態欄。")
            % {"v0": stat["failed"]}
        )
    return out


def performance_view(athlete, records, viewer=None):
    """方向一：不斷收集回來的數據，先看這幾筆本身練得怎樣。"""
    stat = summarise(records)
    points = [
        {
            "date": r.date.isoformat(),
            "label": f"{r.date:%m/%d}" + (f" #{r.set_no}" if r.set_no else ""),
            "item": r.item.name,
            "distance": _distance(r),
            "value": float(r.value) if r.value is not None else None,
            "target": float(r.target_value) if r.target_value is not None else None,
            "intensity": (r.intensity or "").strip(),
            "completed": r.completed,
            "status": r.status_label,
            "session": r.session.title if r.session else "",
        }
        for r in records
    ]
    return {
        "summary": stat,
        "points": points,
        "by_distance": _breakdown(records, lambda r: _distance_label(_distance(r))),
        "by_intensity": _breakdown(
            records, lambda r: (r.intensity or "").strip() or _("未填強度")
        ),
        "by_status": _breakdown(records, lambda r: r.status_label or _("未註記狀態")),
        "peers": _peer_rows(athlete, records, viewer),
        "insights": _perf_insights(stat, points),
    }


# ----------------------------------------------- 方向二：同距離跨時段


def _bucket(mode, on_date, phase_at):
    """一個日期屬於哪一段時間：(排序鍵, 標題, 副標, 起, 訖)。分不出來回 None。"""
    if mode == "year":
        return (
            f"{on_date.year}",
            _("%(v0)s 年") % {"v0": on_date.year},
            "",
            date(on_date.year, 1, 1),
            date(on_date.year, 12, 31),
        )
    if mode == "month":
        last = calendar.monthrange(on_date.year, on_date.month)[1]
        return (
            f"{on_date.year}-{on_date.month:02d}",
            f"{on_date.year}/{on_date.month:02d}",
            "",
            date(on_date.year, on_date.month, 1),
            date(on_date.year, on_date.month, last),
        )
    phase = phase_at(on_date)
    if phase is None:
        return None
    return (
        f"{phase.start_date.isoformat()}#{phase.pk}",
        phase.get_phase_type_display(),
        f"{phase.start_date:%Y/%m/%d} → {phase.end_date:%Y/%m/%d}",
        phase.start_date,
        phase.end_date,
    )


def _periods(records, mode, phase_at):
    """把紀錄切成一段一段的時間，回傳 (時段清單, 紀錄 → 時段鍵, 分不出來的筆數)。"""
    periods, belongs, missed = {}, {}, 0
    for record in records:
        bucket = _bucket(mode, record.date, phase_at)
        if bucket is None:
            missed += 1
            continue
        key, label, sublabel, start, end = bucket
        periods.setdefault(
            key,
            {
                "key": key,
                "label": label,
                "sublabel": sublabel,
                "start": start,
                "end": end,
            },
        )
        belongs[record.id] = key
    return [periods[k] for k in sorted(periods)], belongs, missed


def _distance_label(value):
    return _("%(v0)s m") % {"v0": int(value)} if value else _("未填距離")


def _period_insights(rows, periods):
    """挑最會講故事的那一兩個距離，寫成白話。"""
    out = []
    if len(periods) < 2:
        out.append(_("挑出來的紀錄只落在一個時段裡，換一個切法（分月份／分年份）才比得出變化。"))
        return out
    for row in rows[:2]:
        cells = [c for c in row["cells"] if c]
        if len(cells) < 2:
            continue
        first, last = cells[0], cells[-1]
        pieces = [
            _("%(v0)s：%(v1)s → %(v2)s，")
            % {"v0": row["label"], "v1": first["period"], "v2": last["period"]}
        ]
        if first["average"] and last["average"]:
            delta = round(last["average"] - first["average"], 2)
            pieces.append(
                _("平均由 %(v0)s 秒變成 %(v1)s 秒（%(v2)s%(v3)s 秒）")
                % {
                    "v0": first["average"],
                    "v1": last["average"],
                    "v2": "+" if delta > 0 else "",
                    "v3": delta,
                }
            )
        volume = _pct_change(first["volume_m"], last["volume_m"])
        if volume is not None:
            pieces.append(
                _("；訓練量 %(v0)s%(v1)s%%") % {"v0": "+" if volume > 0 else "", "v1": volume}
            )
        if first["avg_intensity"] and last["avg_intensity"]:
            pieces.append(
                _("；平均強度 %(v0)s%% → %(v1)s%%")
                % {"v0": first["avg_intensity"], "v1": last["avg_intensity"]}
            )
        out.append("".join(pieces) + "。")
    if not out:
        out.append(_("同一個距離要在兩個以上的時段都練過，才排得出變化。"))
    return out


def period_view(athlete, records, mode="month"):
    """方向二：同一個距離，在不同年／月／時期的量與強度變化。"""
    from analytics.services import phase_lookup

    if mode not in {m for m, _unused in GROUPINGS}:
        mode = "month"
    phase_at = phase_lookup(athlete)
    periods, belongs, missed = _periods(records, mode, phase_at)

    by_distance = {}
    for record in records:
        key = belongs.get(record.id)
        if key is None:
            continue
        value = _distance(record)
        bucket = by_distance.setdefault(int(value) if value else 0, {})
        bucket.setdefault(key, []).append(record)

    order = sorted(
        by_distance, key=lambda d: -sum(len(g) for g in by_distance[d].values())
    )[:MAX_DISTANCES]

    rows = []
    for distance in order:
        cells = []
        for period in periods:
            group = by_distance[distance].get(period["key"])
            if not group:
                cells.append(None)
                continue
            stat = summarise(group)
            stat["period"] = period["label"]
            cells.append(stat)
        seen = [c for c in cells if c]
        rows.append(
            {
                "distance": distance,
                "label": _distance_label(distance),
                "count": sum(c["count"] for c in seen),
                "cells": cells,
                "best": min(
                    (c["best"] for c in seen if c["best"] is not None), default=None
                ),
                "volume_m": sum(c["volume_m"] for c in seen),
                "change_pct": (
                    _pct_change(seen[0]["average"], seen[-1]["average"], 2)
                    if len(seen) > 1
                    else None
                ),
                "volume_change_pct": (
                    _pct_change(seen[0]["volume_m"], seen[-1]["volume_m"])
                    if len(seen) > 1
                    else None
                ),
            }
        )

    totals = []
    for period in periods:
        group = [r for r in records if belongs.get(r.id) == period["key"]]
        stat = summarise(group)
        stat.update(period)
        totals.append(stat)

    return {
        "mode": mode,
        "groupings": GROUPINGS,
        "periods": periods,
        "rows": rows,
        "totals": totals,
        "missed": missed,
        "insights": _period_insights(rows, periods),
    }


# --------------------------------- 方向三：拼入重量訓練與身體結構


def _strength_in(athlete, start, end):
    """一段時間裡的重量訓練（只算單位是 kg、標了已完成、有填重量的組）。"""
    rows = (
        MetricRecord.objects.filter(
            athlete=athlete,
            item__domain=MetricDomain.STRENGTH,
            date__gte=start,
            date__lte=end,
            completed=True,
            weight_kg__isnull=False,
        )
        .select_related("item")
        .order_by("date", "id")
    )
    return [r for r in rows if (r.item.unit or "").strip().lower() == "kg"]


def _strength_stat(records, body_weight=None):
    """一段時間的重量訓練摘要：做了多少、最重舉得起多少、每公斤體重幾倍。"""
    if not records:
        return None
    best_by_item, tonnage = {}, 0.0
    for record in records:
        if record.tonnage:
            tonnage += record.tonnage
        e1rm = estimate_1rm(record.weight_kg, record.reps)
        if e1rm is None:
            continue
        current = best_by_item.get(record.item_id)
        if current is None or e1rm > current["e1rm"]:
            best_by_item[record.item_id] = {"name": record.item.name, "e1rm": e1rm}
    best = max(best_by_item.values(), key=lambda x: x["e1rm"]) if best_by_item else None
    per_bw = None
    if best_by_item and body_weight:
        per_bw = _avg([x["e1rm"] / body_weight for x in best_by_item.values()], 2)
    return {
        "sets": len(records),
        "days": len({r.date for r in records}),
        "tonnage": round(tonnage, 1),
        "best": best,
        "lifts": len(best_by_item),
        "avg_per_bw": per_bw,
    }


def _body_stat(athlete, start, end):
    """一段時間裡量過的體組成，取平均。"""
    rows = [b for b in athlete.body_metrics.all() if start <= b.date <= end]
    if not rows:
        return None
    weight = _avg([float(b.weight_kg) for b in rows])
    lean = _avg([b.lean_mass_kg for b in rows])
    return {
        "count": len(rows),
        "weight": weight,
        "fat_pct": _avg(
            [float(b.body_fat_pct) for b in rows if b.body_fat_pct is not None]
        ),
        "lean": lean,
        "muscle_pct": round(lean / weight * 100, 1) if lean and weight else None,
    }


def _cross_insights(rows):
    """把三件事擺在同一句話裡：跑的、舉的、身體的。"""
    out = []
    usable = [r for r in rows if r["track"]["count"]]
    if len(usable) < 2:
        out.append(_("要有兩個以上的時段，才看得出「這幾公斤是練回來的、還是輕了才顯得快」。"))
        return out
    first, last = usable[0], usable[-1]
    speed = None
    if first["track"]["average"] and last["track"]["average"]:
        speed = round(last["track"]["average"] - first["track"]["average"], 2)
        out.append(
            _("%(v0)s → %(v1)s：田徑練習平均由 %(v2)s 秒變成 %(v3)s 秒（%(v4)s%(v5)s 秒）。")
            % {
                "v0": first["label"],
                "v1": last["label"],
                "v2": first["track"]["average"],
                "v3": last["track"]["average"],
                "v4": "+" if speed > 0 else "",
                "v5": speed,
            }
        )
    if first["strength"] and last["strength"]:
        change = _pct_change(first["strength"]["tonnage"], last["strength"]["tonnage"])
        line = _("同一段時間的重量訓練：總噸位 %(v0)s → %(v1)s kg") % {
            "v0": first["strength"]["tonnage"],
            "v1": last["strength"]["tonnage"],
        }
        if change is not None:
            line += _("（%(v0)s%(v1)s%%）") % {
                "v0": "+" if change > 0 else "",
                "v1": change,
            }
        if first["strength"]["avg_per_bw"] and last["strength"]["avg_per_bw"]:
            line += _("，每公斤體重舉得起 %(v0)s → %(v1)s 倍") % {
                "v0": first["strength"]["avg_per_bw"],
                "v1": last["strength"]["avg_per_bw"],
            }
        out.append(line + "。")
    if first["body"] and last["body"]:
        line = _("身體結構：體重 %(v0)s → %(v1)s kg") % {
            "v0": first["body"]["weight"],
            "v1": last["body"]["weight"],
        }
        if first["body"]["fat_pct"] and last["body"]["fat_pct"]:
            line += _("、體脂 %(v0)s%% → %(v1)s%%") % {
                "v0": first["body"]["fat_pct"],
                "v1": last["body"]["fat_pct"],
            }
        if first["body"]["muscle_pct"] and last["body"]["muscle_pct"]:
            line += _("、肌肉率 %(v0)s%% → %(v1)s%%") % {
                "v0": first["body"]["muscle_pct"],
                "v1": last["body"]["muscle_pct"],
            }
        out.append(line + "。")
        if speed is not None and first["body"]["weight"] and last["body"]["weight"]:
            lighter = last["body"]["weight"] < first["body"]["weight"]
            if speed < 0 and lighter:
                out.append(_("跑得比較快、體重也降了——先確認掉的是脂肪不是肌肉，不是每一次變輕都算進步。"))
            elif speed < 0:
                out.append(_("重了但也跑得比較快，這個方向是對的：加上去的是用得上的重量。"))
            else:
                out.append(_("這段時間跑得比較慢，對照上面的量與強度，看是疲勞、還是身體結構走了方向。"))
    if not any(r["strength"] for r in rows):
        out.append(_("這段時間沒有可以算的重量訓練紀錄（要填重量、單位是 kg、而且標了已完成）。"))
    if not any(r["body"] for r in rows):
        out.append(_("這段時間沒有體組成量測；到運動員總覽登一次體測，這一欄才有東西比。"))
    return out


def cross_view(athlete, records, mode="month"):
    """方向三：田徑練習 × 重量訓練 × 身體結構，同一段時間擺在同一列。"""
    from analytics.services import phase_lookup

    if mode not in {m for m, _unused in GROUPINGS}:
        mode = "month"
    phase_at = phase_lookup(athlete)
    periods, belongs, missed = _periods(records, mode, phase_at)

    rows = []
    for period in periods:
        group = [r for r in records if belongs.get(r.id) == period["key"]]
        body = _body_stat(athlete, period["start"], period["end"])
        strength = _strength_stat(
            _strength_in(athlete, period["start"], period["end"]),
            body_weight=body["weight"] if body else None,
        )
        rows.append(
            {
                **period,
                "track": summarise(group),
                "strength": strength,
                "body": body,
            }
        )
    return {
        "mode": mode,
        "groupings": GROUPINGS,
        "rows": rows,
        "missed": missed,
        "insights": _cross_insights(rows),
    }


def analyse(athlete, records, direction="perf", mode="month", viewer=None):
    """挑出來的紀錄 ＋ 一個方向 → 一份分析。"""
    if not records:
        return None
    if direction == "period":
        return {"direction": "period", "period": period_view(athlete, records, mode)}
    if direction == "cross":
        return {"direction": "cross", "cross": cross_view(athlete, records, mode)}
    return {
        "direction": "perf",
        "perf": performance_view(athlete, records, viewer=viewer),
    }

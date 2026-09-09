"""多面向分析：體能動作的重量 × 肌肉脂肪比例 × 訓練時間。

單看某一個動作的曲線，只知道「有沒有進步」；把同一段時間的體組成
（肌肉／脂肪比例）和實際練了多少小時擺在一起，才看得出來
「這幾公斤是練回來的、還是輕了才顯得舉得起」。

分組的方式有兩種，兩種都答同一個問題、只是尺度不同：
    phase —— 分訓練時期（一般準備期／專項準備期／賽前期…）
    year  —— 分年份

每一組算出來的東西：
    訓練量  課次、訓練時數、總負荷（RPE × 分鐘）
    體組成  期間內體測的平均體重／體脂率／肌肉率
    力量    每個體能動作的最佳 e1RM、相對力量（e1RM ÷ 體重）、總噸位

最後再把相鄰兩組拿來比，寫成幾句白話（insights）。
"""

import statistics
from datetime import date, timedelta

from django.utils.translation import gettext as _

from analytics.body_strength import estimate_1rm
from analytics.models import MetricDomain, MetricRecord
from core.models import SessionStatus

#: 版面上最多列幾個體能動作（照做的組數排，多過這個數就不列了）
MAX_LIFTS = 8

#: 預設回看多久（三年，夠涵蓋兩三個完整年度計劃）
DEFAULT_DAYS = 1095

MODES = [
    ("phase", _("分訓練時期")),
    ("year", _("分年份")),
]


def _avg(values, digits=1):
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), digits) if values else None


def _pct_change(old, new, digits=1):
    if old in (None, 0) or new is None:
        return None
    return round((new - old) / abs(old) * 100, digits)


def _strength_sets(athlete, since):
    """重量訓練裡「幾公斤 × 幾次」的組；單位不是 kg 的動作（平板支撐…）不算。"""
    rows = (
        MetricRecord.objects.filter(
            athlete=athlete,
            item__domain=MetricDomain.STRENGTH,
            date__gte=since,
            completed=True,
            weight_kg__isnull=False,
        )
        .select_related("item")
        .order_by("date", "id")
    )
    return [r for r in rows if (r.item.unit or "").strip().lower() == "kg"]


def _sessions(athlete, since):
    """真的練了的課：已完成／部分完成，時長沒填就用計劃時長頂上。"""
    return list(
        athlete.sessions.filter(
            date__gte=since,
            status__in=[SessionStatus.COMPLETED, SessionStatus.PARTIAL],
        ).order_by("date")
    )


def _session_minutes(session):
    return session.actual_duration_min or session.planned_duration_min or 0


def _bucket_of(mode, on_date, phase_at):
    """一個日期屬於哪一組：回傳 (排序鍵, 標題, 副標)。分不出來就 None。"""
    if mode == "year":
        return (str(on_date.year), _("%(v0)s 年") % {"v0": on_date.year}, "")
    phase = phase_at(on_date)
    if phase is None:
        return None
    return (
        f"{phase.start_date.isoformat()}#{phase.pk}",
        phase.get_phase_type_display(),
        _("%(v0)s 年 W%(v1)s-%(v2)s")
        % {
            "v0": phase.start_date.year,
            "v1": phase.week_start,
            "v2": phase.week_end,
        },
    )


def _new_group(key, label, sublabel):
    return {
        "key": key,
        "label": label,
        "sublabel": sublabel,
        "start": None,
        "end": None,
        "sessions": 0,
        "minutes": 0,
        "hours": 0.0,
        "load": 0,
        "sets": 0,
        "tonnage": 0.0,
        "reps": 0,
        "weight": None,
        "fat_pct": None,
        "muscle_pct": None,
        "lean": None,
        "body_count": 0,
        "lifts": {},
        "best_lift": None,
        "avg_per_bw": None,
        "tonnage_per_hour": None,
    }


def _touch(group, on_date):
    if group["start"] is None or on_date < group["start"]:
        group["start"] = on_date
    if group["end"] is None or on_date > group["end"]:
        group["end"] = on_date


def multi_dimension_report(athlete, mode="phase", days=DEFAULT_DAYS):
    """體能動作重量 × 體組成 × 訓練時間，分時期／分年份擺在一起看。"""
    from analytics.services import phase_lookup

    if mode not in {m for m, _unused in MODES}:
        mode = "phase"
    since = date.today() - timedelta(days=days)
    phase_at = phase_lookup(athlete)

    sets = _strength_sets(athlete, since)
    sessions = _sessions(athlete, since)
    bodies = [b for b in athlete.body_metrics.order_by("date") if b.date >= since]

    report = {
        "mode": mode,
        "modes": MODES,
        "days": days,
        "groups": [],
        "lifts": [],
        "insights": [],
        "notes": [],
        "has_data": False,
        "has_body": bool(bodies),
        "has_strength": bool(sets),
    }

    groups = {}

    def group_for(on_date):
        bucket = _bucket_of(mode, on_date, phase_at)
        if bucket is None:
            return None
        key, label, sublabel = bucket
        group = groups.get(key)
        if group is None:
            group = groups[key] = _new_group(key, label, sublabel)
        _touch(group, on_date)
        return group

    # ---- 訓練時間 ----
    for session in sessions:
        group = group_for(session.date)
        if group is None:
            continue
        group["sessions"] += 1
        group["minutes"] += _session_minutes(session)
        group["load"] += int(session.session_load or 0)

    # ---- 體組成 ----
    body_rows = {}
    for body in bodies:
        group = group_for(body.date)
        if group is None:
            continue
        body_rows.setdefault(group["key"], []).append(body)

    # ---- 體能動作的重量 ----
    lift_sets = {}
    for row in sets:
        group = group_for(row.date)
        if group is None:
            continue
        group["sets"] += 1
        group["reps"] += row.reps or 0
        if row.tonnage:
            group["tonnage"] += row.tonnage
        e1rm = estimate_1rm(row.weight_kg, row.reps)
        lift = group["lifts"].get(row.item_id)
        if lift is None:
            lift = group["lifts"][row.item_id] = {
                "item": row.item,
                "name": row.item.name,
                "sets": 0,
                "best_e1rm": None,
                "best_weight": None,
                "tonnage": 0.0,
                "per_bw": None,
            }
        lift["sets"] += 1
        if row.tonnage:
            lift["tonnage"] += row.tonnage
        if e1rm is not None and (lift["best_e1rm"] is None or e1rm > lift["best_e1rm"]):
            lift["best_e1rm"] = e1rm
        weight = float(row.weight_kg)
        if lift["best_weight"] is None or weight > lift["best_weight"]:
            lift["best_weight"] = weight
        lift_sets[row.item_id] = lift_sets.get(row.item_id, 0) + 1

    if not groups:
        if mode == "phase":
            report["notes"].append(
                _("這段時間的課還沒排進任何一個訓練時期。到年度計劃把分期建起來，這裡才分得出時期來比。")
            )
        else:
            report["notes"].append(_("這段時間還沒有已完成的課，也沒有重量訓練紀錄。"))
        return report

    ordered = [groups[k] for k in sorted(groups)]

    # ---- 收尾：每一組的平均值與衍生數字 ----
    for group in ordered:
        rows = body_rows.get(group["key"], [])
        group["body_count"] = len(rows)
        group["weight"] = _avg([float(b.weight_kg) for b in rows])
        group["fat_pct"] = _avg(
            [float(b.body_fat_pct) for b in rows if b.body_fat_pct is not None]
        )
        group["lean"] = _avg([b.lean_mass_kg for b in rows])
        if group["lean"] and group["weight"]:
            group["muscle_pct"] = round(group["lean"] / group["weight"] * 100, 1)
        group["hours"] = round(group["minutes"] / 60, 1)
        group["tonnage"] = round(group["tonnage"], 1)
        if group["hours"]:
            group["tonnage_per_hour"] = round(group["tonnage"] / group["hours"], 1)

        per_bws = []
        for lift in group["lifts"].values():
            lift["tonnage"] = round(lift["tonnage"], 1)
            if lift["best_e1rm"] is not None and group["weight"]:
                lift["per_bw"] = round(lift["best_e1rm"] / group["weight"], 2)
                per_bws.append(lift["per_bw"])
        group["avg_per_bw"] = round(statistics.mean(per_bws), 2) if per_bws else None
        best = [x for x in group["lifts"].values() if x["best_e1rm"] is not None]
        if best:
            group["best_lift"] = max(best, key=lambda x: x["best_e1rm"])

    report["groups"] = ordered
    report["has_data"] = any(g["sessions"] or g["sets"] for g in ordered)

    # ---- 每個動作一列，橫向就是各組 ----
    top_ids = sorted(lift_sets, key=lambda i: -lift_sets[i])[:MAX_LIFTS]
    for item_id in top_ids:
        cells, item = [], None
        for group in ordered:
            lift = group["lifts"].get(item_id)
            if lift is not None:
                item = lift["item"]
            cells.append(lift)
        seen = [c for c in cells if c and c["best_e1rm"] is not None]
        first, last = (seen[0], seen[-1]) if seen else (None, None)
        report["lifts"].append(
            {
                "item": item,
                "name": item.name if item else "",
                "cells": cells,
                "sets": lift_sets[item_id],
                "best": max((c["best_e1rm"] for c in seen), default=None),
                "change_pct": (
                    _pct_change(first["best_e1rm"], last["best_e1rm"])
                    if first is not None and last is not None and first is not last
                    else None
                ),
                "per_bw_change_pct": (
                    _pct_change(first["per_bw"], last["per_bw"])
                    if first is not None
                    and last is not None
                    and first is not last
                    and first["per_bw"]
                    and last["per_bw"]
                    else None
                ),
            }
        )

    report["insights"] = build_insights(report)
    if not bodies:
        report["notes"].append(
            _("這段時間沒有體測紀錄，所以只看得到絕對重量，算不出「每公斤體重舉得起多少」。")
        )
    if not sets:
        report["notes"].append(
            _("這段時間的重量訓練還沒登過「幾公斤 × 幾次」，先去課表明細登幾組。")
        )
    return report


def build_insights(report):
    """把相鄰兩組的差異寫成幾句白話。"""
    groups = [g for g in report["groups"] if g["sessions"] or g["sets"]]
    lines = []
    if len(groups) < 2:
        if groups:
            lines.append(
                _("目前只有「%(v0)s」這一組有資料，再多練一段時間才比得出差別。")
                % {"v0": groups[0]["label"]}
            )
        return lines

    older, newer = groups[-2], groups[-1]

    # 1) 相對力量：練起來了還是只是輕了
    if older["avg_per_bw"] and newer["avg_per_bw"]:
        ratio = _pct_change(older["avg_per_bw"], newer["avg_per_bw"])
        fat_delta = (
            round(newer["fat_pct"] - older["fat_pct"], 1)
            if newer["fat_pct"] is not None and older["fat_pct"] is not None
            else None
        )
        lean_delta = (
            round(newer["lean"] - older["lean"], 1)
            if newer["lean"] is not None and older["lean"] is not None
            else None
        )
        text = _(
            "每公斤體重舉得起的重量從 %(v0)s 的 %(v1)s 變成 %(v2)s 的 %(v3)s（%(v4)s%%）。"
        ) % {
            "v0": older["label"],
            "v1": older["avg_per_bw"],
            "v2": newer["label"],
            "v3": newer["avg_per_bw"],
            "v4": f"{ratio:+}" if ratio is not None else "—",
        }
        if ratio is not None and ratio > 0:
            if lean_delta is not None and lean_delta > 0.5:
                text += _("去脂體重同時多了 %(v0)s kg，是練出來的，不是輕出來的。") % {
                    "v0": lean_delta
                }
            elif fat_delta is not None and fat_delta < -0.5:
                text += _("體脂率同時降了 %(v0)s 個百分點，比值變好有一部分來自體重變輕。") % {
                    "v0": abs(fat_delta)
                }
        elif ratio is not None and ratio < 0:
            text += _("要看是重量掉了，還是體重上去了——下面兩欄對著看。")
        lines.append(text)

    # 2) 訓練時間 ←→ 力量：練得多有沒有換到東西
    if older["hours"] and newer["hours"]:
        hours_change = _pct_change(older["hours"], newer["hours"])
        strength_change = (
            _pct_change(older["avg_per_bw"], newer["avg_per_bw"])
            if older["avg_per_bw"] and newer["avg_per_bw"]
            else None
        )
        text = _("訓練時數 %(v0)s 小時 → %(v1)s 小時（%(v2)s%%），課次 %(v3)s → %(v4)s。") % {
            "v0": older["hours"],
            "v1": newer["hours"],
            "v2": f"{hours_change:+}" if hours_change is not None else "—",
            "v3": older["sessions"],
            "v4": newer["sessions"],
        }
        if hours_change is not None and strength_change is not None:
            if hours_change > 10 and strength_change <= 0:
                text += _("時間加了但力量沒跟上，先檢查強度是不是不夠，或者恢復吃掉了效果。")
            elif hours_change < -10 and strength_change > 0:
                text += _("時間反而少了、力量還升，這一段的安排效率不錯，值得沿用。")
        lines.append(text)

    # 3) 體組成本身
    if newer["fat_pct"] is not None and older["fat_pct"] is not None:
        lines.append(
            _("體脂率 %(v0)s%% → %(v1)s%%，肌肉率 %(v2)s → %(v3)s，平均體重 %(v4)s → %(v5)s kg。")
            % {
                "v0": older["fat_pct"],
                "v1": newer["fat_pct"],
                "v2": f"{older['muscle_pct']}%" if older["muscle_pct"] is not None else "—",
                "v3": f"{newer['muscle_pct']}%" if newer["muscle_pct"] is not None else "—",
                "v4": older["weight"] if older["weight"] is not None else "—",
                "v5": newer["weight"] if newer["weight"] is not None else "—",
            }
        )

    # 4) 個別動作：進步最多與退最多的
    ranked = [x for x in report["lifts"] if x["change_pct"] is not None]
    if ranked:
        best = max(ranked, key=lambda x: x["change_pct"])
        worst = min(ranked, key=lambda x: x["change_pct"])
        if best["change_pct"] > 0:
            lines.append(
                _("進步最多的動作是「%(v0)s」（%(v1)s%%）。")
                % {"v0": best["name"], "v1": f"{best['change_pct']:+}"}
            )
        if worst is not best and worst["change_pct"] < 0:
            lines.append(
                _("「%(v0)s」退了 %(v1)s%%，下一段可以特別排一下。")
                % {"v0": worst["name"], "v1": abs(worst["change_pct"])}
            )

    # 5) 效率：每小時推得動多少噸位
    tph = [(g["label"], g["tonnage_per_hour"]) for g in groups if g["tonnage_per_hour"]]
    if len(tph) >= 2:
        lines.append(
            _("每小時的總噸位 %(v0)s：%(v1)s kg → %(v2)s：%(v3)s kg。")
            % {"v0": tph[-2][0], "v1": tph[-2][1], "v2": tph[-1][0], "v3": tph[-1][1]}
        )
    return lines

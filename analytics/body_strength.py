"""體組成 × 重量訓練：脂肪比例、肌肉比例、體重與「舉得起多少」之間的關係。

同一個 100kg 背蹲舉，70kg 的人與 85kg 的人不是同一件事——田徑場上真正
起作用的是「每公斤體重舉得起多少」。這裡做三件事：

1. 把重量訓練的紀錄換算成估算 1RM，再除以體重與去脂體重，得出兩個比值：
   相對力量（1RM / 體重）與去脂相對力量（1RM / 去脂體重）。
2. 把歷次體測接回每一筆重訓紀錄，看比值本身的走勢——數字進步是真的變強，
   還是只是體重掉了；體重升了但比值沒動，加的就是脂肪不是力量。
3. 推演「如果體脂降 2%」「如果去脂體重加 1kg」之後，比值會變成多少，
   再把該往哪個方向走交給營養頁去執行。

絕對力量與去脂體重的關係用異速生長（allometric）指數 0.67 估：
肌肉出力大致與橫切面積成正比，而面積 ~ 質量^(2/3)。這是估算不是保證，
畫面上會寫清楚是推估值。
"""

from datetime import date, timedelta

from django.utils.translation import gettext_lazy as _

from analytics.models import MetricDomain, MetricRecord

#: 去脂體重變動 → 絕對力量變動的異速生長指數
LEAN_EXPONENT = 0.67

#: 估算 1RM 時次數的上限；超過這個次數的組換算誤差太大
MAX_REPS_FOR_1RM = 12

#: 一次只挑幾個動作出來看
MAX_LIFTS = 6

#: 減脂速度（每週佔體重的百分比）。緩降保肌肉，急降連肌肉一起掉。
CUT_RATE_PCT = 0.5
TRIM_RATE_PCT = 0.3

#: 增去脂體重的速度（kg / 週）與熱量盈餘
LEAN_GAIN_KG_PER_WEEK = 0.2
LEAN_GAIN_KCAL = 250
LEAN_GAIN_TARGET_KG = 1.5

#: 1 kg 體重 ≈ 7700 kcal
KCAL_PER_KG = 7700


def estimate_1rm(weight_kg, reps):
    """Epley：1RM ≈ 重量 × (1 + (次數−1)/30)。

    次數留空或只做 1 下時，舉起來的重量本身就是 1RM，所以用 (次數−1)
    這個版本——原式在 1 次時會平白多算 3%。
    """
    if weight_kg is None:
        return None
    reps = min(int(reps or 1), MAX_REPS_FOR_1RM)
    return round(float(weight_kg) * (1 + (reps - 1) / 30), 1)


def fat_bands(sex):
    """這個性別在田徑專項上的體脂參考帶（%）。"""
    from nutrition.services import FAT_BANDS

    return FAT_BANDS.get(sex, (8.0, 20.0))


def _body_snapshot(latest):
    """一次體測換算成計算要用的四個數字。"""
    weight = float(latest.weight_kg)
    lean = latest.lean_mass_kg
    fat_mass = latest.fat_mass_kg
    pct = float(latest.body_fat_pct) if latest.body_fat_pct is not None else None
    if lean is None and pct is not None:
        lean = round(weight * (1 - pct / 100), 1)
    if fat_mass is None and lean is not None:
        fat_mass = round(weight - lean, 1)
    if pct is None and fat_mass is not None and weight:
        pct = round(fat_mass / weight * 100, 1)
    return {
        "date": latest.date,
        "weight": weight,
        "lean": lean,
        "fat_mass": fat_mass,
        "fat_pct": pct,
        "muscle_pct": round(lean / weight * 100, 1) if lean and weight else None,
    }


def _strength_records(athlete, days):
    """重量訓練裡「舉得動幾公斤」的紀錄；單位不是 kg 的（平板支撐…）不算。"""
    since = date.today() - timedelta(days=days)
    rows = (
        MetricRecord.objects.filter(
            athlete=athlete,
            item__domain=MetricDomain.STRENGTH,
            date__gte=since,
            completed=True,
        )
        .select_related("item")
        .order_by("date", "id")
    )
    return [
        r
        for r in rows
        if r.weight_kg is not None and (r.item.unit or "").strip().lower() == "kg"
    ]


def _body_at(bodies, on_date):
    """那一天當下最近一次的體測（優先取當天或之前的，沒有才往後找）。"""
    before = [b for b in bodies if b.date <= on_date]
    if before:
        return before[-1]
    return bodies[0] if bodies else None


def _ratio(value, base):
    return round(value / base, 2) if value is not None and base else None


def strength_ratio_report(athlete, days=730):
    """脂肪比例／肌肉比例／體重 × 重量訓練比值的完整分析。"""
    bodies = list(athlete.body_metrics.order_by("date"))
    records = _strength_records(athlete, days)

    report = {
        "has_body": bool(bodies),
        "has_strength": bool(records),
        "body": _body_snapshot(bodies[-1]) if bodies else None,
        "previous": _body_snapshot(bodies[-2]) if len(bodies) > 1 else None,
        "bands": fat_bands(athlete.sex),
        "lifts": [],
        "focus": None,
        "series": [],
        "scenarios": [],
        "recommendation": None,
        "notes": [],
    }
    if not records:
        report["notes"].append(
            _("重量訓練還沒有登過「幾公斤 × 幾次」的紀錄。到上面的重量訓練範疇登幾組，這裡才算得出相對力量。")
        )
        return report
    if not bodies:
        report["notes"].append(
            _("還沒有體組成紀錄。到「身體數據」頁上傳一張體測報告，這裡才分得出「變強」與「只是體重變了」。")
        )
        return report

    body = report["body"]
    weight, lean = body["weight"], body["lean"]

    # ---- 每個動作的估算 1RM 與兩個比值 ----
    by_item = {}
    for r in records:
        e1rm = estimate_1rm(r.weight_kg, r.reps)
        if e1rm is None:
            continue
        cur = by_item.get(r.item_id)
        if cur is None or e1rm > cur["e1rm"]:
            by_item[r.item_id] = {"item": r.item, "e1rm": e1rm, "date": r.date, "reps": r.reps}

    lifts = sorted(by_item.values(), key=lambda row: -row["e1rm"])[:MAX_LIFTS]
    for row in lifts:
        row["per_bw"] = _ratio(row["e1rm"], weight)
        row["per_lean"] = _ratio(row["e1rm"], lean) if lean else None
    report["lifts"] = lifts
    report["focus"] = lifts[0] if lifts else None

    # ---- 比值走勢：每一次重訓紀錄配上當下最近的一次體測 ----
    focus_item_id = report["focus"]["item"].id if report["focus"] else None
    per_day = {}
    for r in records:
        if r.item_id != focus_item_id:
            continue
        e1rm = estimate_1rm(r.weight_kg, r.reps)
        if e1rm is not None and e1rm > per_day.get(r.date, 0):
            per_day[r.date] = e1rm
    for on_date in sorted(per_day):
        snap = _body_at(bodies, on_date)
        if snap is None:
            continue
        snap = _body_snapshot(snap)
        report["series"].append(
            {
                "date": str(on_date),
                "e1rm": per_day[on_date],
                "weight": snap["weight"],
                "fat_pct": snap["fat_pct"],
                "per_bw": _ratio(per_day[on_date], snap["weight"]),
                "per_lean": _ratio(per_day[on_date], snap["lean"]) if snap["lean"] else None,
            }
        )

    report["scenarios"] = build_scenarios(report)
    report["recommendation"] = recommend_direction(athlete, report)
    report["notes"].extend(_read_the_trend(report))
    return report


# --------------------------------------------------------------- 情境推演


def _scenario(label, kind, base, e1rm, lean_new, fat_new, item_unit="kg"):
    """把「去脂體重變成 X、脂肪量變成 Y」換算成體重、體脂率與比值。"""
    weight_new = round(lean_new + fat_new, 1)
    fat_pct_new = round(fat_new / weight_new * 100, 1) if weight_new else None
    e1rm_new = round(e1rm * (lean_new / base["lean"]) ** LEAN_EXPONENT, 1)
    per_bw = _ratio(e1rm_new, weight_new)
    base_ratio = _ratio(e1rm, base["weight"])
    return {
        "label": label,
        "kind": kind,
        "weight": weight_new,
        "weight_delta": round(weight_new - base["weight"], 1),
        "lean": round(lean_new, 1),
        "lean_delta": round(lean_new - base["lean"], 1),
        "fat_pct": fat_pct_new,
        "fat_pct_delta": (
            round(fat_pct_new - base["fat_pct"], 1)
            if fat_pct_new is not None and base["fat_pct"] is not None
            else None
        ),
        "e1rm": e1rm_new,
        "per_bw": per_bw,
        "unit": item_unit,
        "gain_pct": (
            round((per_bw - base_ratio) / base_ratio * 100, 1)
            if per_bw and base_ratio
            else None
        ),
    }


def build_scenarios(report):
    """如果脂肪掉一點／肌肉多一點，相對力量會變成多少。

    假設：減脂時去脂體重守得住（蛋白夠、重訓照做），所以絕對力量不變、
    體重變輕，比值直接變好；增去脂體重時絕對力量按 LBM^0.67 上調。
    """
    body, focus = report.get("body"), report.get("focus")
    if not body or not focus or not body.get("lean") or body.get("fat_mass") is None:
        return []

    lean, fat = body["lean"], body["fat_mass"]
    e1rm, unit = focus["e1rm"], focus["item"].unit or "kg"
    rows = [
        {
            "label": _("現況"),
            "kind": "NOW",
            "weight": body["weight"],
            "weight_delta": 0.0,
            "lean": lean,
            "lean_delta": 0.0,
            "fat_pct": body["fat_pct"],
            "fat_pct_delta": 0.0,
            "e1rm": e1rm,
            "per_bw": _ratio(e1rm, body["weight"]),
            "unit": unit,
            "gain_pct": 0.0,
        }
    ]

    def fat_for_pct(drop_pct):
        """體脂率降 drop_pct 個百分點、去脂體重不變時，剩下多少脂肪。"""
        target_pct = (body["fat_pct"] or 0) - drop_pct
        if target_pct <= 0:
            return None
        return lean * target_pct / (100 - target_pct)

    if body["fat_pct"]:
        for drop in (1.0, 2.0, 3.0):
            fat_new = fat_for_pct(drop)
            if fat_new is None or fat_new < 0:
                continue
            rows.append(
                _scenario(
                    _("體脂 −%(v0)s%%（肌肉守住）") % {"v0": f"{drop:g}"},
                    "CUT",
                    body,
                    e1rm,
                    lean,
                    fat_new,
                    unit,
                )
            )

    for gain in (1.0, 2.0):
        rows.append(
            _scenario(
                _("去脂體重 +%(v0)s kg（脂肪不變）") % {"v0": f"{gain:g}"},
                "GAIN",
                body,
                e1rm,
                lean + gain,
                fat,
                unit,
            )
        )

    if fat >= 1.5:
        # 體態重組：脂肪少 1.5 kg、去脂體重多 1 kg，體重幾乎不動但比值往上走
        rows.append(
            _scenario(
                _("脂肪 −1.5 kg 同時去脂體重 +1 kg"),
                "RECOMP",
                body,
                e1rm,
                lean + 1.0,
                fat - 1.5,
                unit,
            )
        )
    return rows


# ------------------------------------------------------------ 該往哪走


def recommend_direction(athlete, report):
    """依體脂帶與比值走勢，決定「減脂／微修／增肌／先把飯吃夠」。

    回傳的 dict 直接餵給營養頁：目標體重、每週速度、每日熱量增減、蛋白下限。
    """
    body = report.get("body")
    if not body or body.get("fat_pct") is None or not body.get("lean"):
        return None

    low, high = report["bands"]
    pct, weight, lean = body["fat_pct"], body["weight"], body["lean"]
    mid = (low + high) / 2

    def weight_at(target_pct):
        return round(lean / (1 - target_pct / 100), 1)

    if pct > high:
        direction, target_pct, rate = "CUT", high, CUT_RATE_PCT
        headline = _("先減脂：體脂 %(pct).1f%% 高於這個性別在田徑上的參考帶（%(low).0f–%(high).0f%%）。"
                     "掉下來的是純負重，力量不變、比值就自己上去。") % {"pct": pct, "low": low, "high": high}
    elif pct < low:
        direction, target_pct, rate = "FUEL", low, -CUT_RATE_PCT
        headline = _("先把飯吃夠：體脂 %(pct).1f%% 已經低於參考帶下緣（%(low).0f%%）。"
                     "再減下去掉的是肌肉與骨質，力量會跟著掉。") % {"pct": pct, "low": low}
    elif pct > mid:
        direction, target_pct, rate = "TRIM", mid, TRIM_RATE_PCT
        headline = _("小幅修一點：體脂 %(pct).1f%% 在參考帶內偏高的一半，"
                     "慢慢修到 %(mid).1f%% 就好，別在高強度期做大赤字。") % {"pct": pct, "mid": mid}
    else:
        direction, target_pct, rate = "GAIN", pct, 0.0
        headline = _("體脂 %(pct).1f%% 已經在參考帶的好位置，接下來靠加去脂體重把絕對力量抬上去，"
                     "脂肪維持不動。") % {"pct": pct}

    if direction == "GAIN":
        lean_delta = LEAN_GAIN_TARGET_KG
        target_weight = round(weight + lean_delta, 1)
        weight_delta = lean_delta
        # 脂肪量不動、體重多了去脂的部分，體脂率自己會往下走一點
        fat_mass = body.get("fat_mass") or weight * pct / 100
        target_pct = round(fat_mass / target_weight * 100, 1)
        weeks = max(1, round(lean_delta / LEAN_GAIN_KG_PER_WEEK))
        kcal_delta = LEAN_GAIN_KCAL
        goal = "GAIN"
        rate_text = _("每週約 +%(v0)s kg 去脂體重（再快就是加脂肪）") % {"v0": LEAN_GAIN_KG_PER_WEEK}
    else:
        target_weight = weight_at(target_pct)
        weight_delta = round(target_weight - weight, 1)
        per_week = round(weight * abs(rate) / 100, 2) or 0.1
        weeks = max(1, round(abs(weight_delta) / per_week))
        # 每日熱量增減 = 每週該變動的體重 × 7700 ÷ 7
        kcal_delta = int(round(per_week * KCAL_PER_KG / 7)) * (1 if weight_delta > 0 else -1)
        lean_delta = 0.0
        goal = "GAIN" if weight_delta > 0 else "LOSE"
        rate_text = (
            _("每週約 %(v0)s kg（體重的 %(v1)s%%），緩降才守得住肌肉")
            % {"v0": per_week, "v1": f"{abs(rate):g}"}
            if weight_delta < 0
            else _("每週約 +%(v0)s kg，慢慢加回來") % {"v0": per_week}
        )

    # 這樣走完，主項的相對力量會變成多少
    payoff = None
    focus = report.get("focus")
    if focus and lean:
        lean_new = lean + lean_delta
        fat_new = max(target_weight - lean_new, 0)
        payoff = _scenario(
            _("完成後"), direction, body, focus["e1rm"], lean_new, fat_new,
            focus["item"].unit or "kg",
        )

    return {
        "direction": direction,
        "goal": goal,                     # 對得上營養目標的 LOSE / MAINTAIN / GAIN
        "headline": headline,
        "fat_pct_now": pct,
        "target_fat_pct": round(target_pct, 1),
        "weight_now": weight,
        "target_weight": target_weight,
        "weight_delta": weight_delta,
        "lean_delta": lean_delta,
        "weeks": weeks,
        "rate_text": rate_text,
        "kcal_delta": kcal_delta,
        # 減脂期蛋白要拉高才守得住肌肉；增肌期 2.0 g/kg LBM 夠用
        "protein_per_kg_lean": 2.4 if direction in ("CUT", "TRIM") else 2.0,
        "protein_g": int(round((2.4 if direction in ("CUT", "TRIM") else 2.0) * lean)),
        "payoff": payoff,
        "focus": focus,
    }


def _read_the_trend(report):
    """比值走勢會說話：體重變了、比值沒變，加的就不是力量。"""
    notes = []
    series = report.get("series") or []
    if len(series) < 2:
        return notes

    first, last = series[0], series[-1]
    if not first["per_bw"] or not last["per_bw"]:
        return notes

    ratio_chg = (last["per_bw"] - first["per_bw"]) / first["per_bw"] * 100
    abs_chg = (
        (last["e1rm"] - first["e1rm"]) / first["e1rm"] * 100 if first["e1rm"] else 0
    )
    weight_chg = round(last["weight"] - first["weight"], 1)
    name = report["focus"]["item"].display_name

    if abs_chg > 2 and ratio_chg <= 0.5 and weight_chg > 0.5:
        notes.append(
            _("%(name)s 的絕對重量進步了 %(abs).1f%%，但體重同時多了 %(w)s kg，"
              "每公斤體重舉得起的反而沒有變好——這一段長的比較像體重不是力量，"
              "下面的體脂數字要一起看。")
            % {"name": name, "abs": abs_chg, "w": weight_chg}
        )
    elif ratio_chg > 2 and abs_chg <= 0.5 and weight_chg < -0.5:
        notes.append(
            _("%(name)s 的絕對重量幾乎沒動，但體重少了 %(w)s kg，相對力量進步 %(r).1f%%——"
              "這正是減脂該有的樣子：力量守住、負重變輕。")
            % {"name": name, "w": abs(weight_chg), "r": ratio_chg}
        )
    elif ratio_chg < -2 and weight_chg > 0.5:
        notes.append(
            _("體重多了 %(w)s kg，%(name)s 的相對力量卻掉了 %(r).1f%%——"
              "增上來的重量沒有換成力量，先確認蛋白與重訓量，再決定要不要收一點熱量。")
            % {"w": weight_chg, "name": name, "r": abs(ratio_chg)}
        )
    return notes

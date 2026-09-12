"""
營養計算：Mifflin-St Jeor BMR → TDEE → 三大營養素分配。

碳水與蛋白質採 g/kg 體重（運動營養標準做法），脂肪取剩餘熱量，
並設下限 0.8 g/kg 以保障荷爾蒙合成。
"""

from datetime import date
from django.utils.translation import gettext_lazy as _

from core.models import DayType, Sex, SessionType
from nutrition.models import NutritionGoal, NutritionTarget

# day_type: (活動係數, 碳水 g/kg, 蛋白 g/kg, 脂肪佔比)
DAY_TYPE_PROFILE = {
    DayType.REST: (1.20, 3.5, 1.7, 0.28),
    DayType.EASY: (1.375, 4.5, 1.8, 0.28),
    DayType.MODERATE: (1.55, 6.0, 1.9, 0.23),
    DayType.HARD: (1.725, 8.0, 2.0, 0.22),
    DayType.COMPETITION: (1.725, 9.0, 1.9, 0.20),
}

GOAL_ADJUSTMENT = {
    NutritionGoal.LOSE: -0.15,
    NutritionGoal.MAINTAIN: 0.0,
    NutritionGoal.GAIN: 0.12,
}

MIN_FAT_G_PER_KG = 0.8


def mifflin_st_jeor(weight_kg, height_cm, age, sex):
    """BMR（kcal/day）"""
    base = 10 * float(weight_kg) + 6.25 * float(height_cm) - 5 * age
    return round(base + 5 if sex == Sex.MALE else base - 161)


def infer_day_type(athlete, on_date):
    """依當日已排定的訓練課推斷訓練日類型。"""
    from planning.models import TrainingSession

    sessions = TrainingSession.objects.filter(athlete=athlete, date=on_date)
    if not sessions.exists():
        return DayType.REST

    types = set(sessions.values_list("session_type", flat=True))
    if SessionType.COMPETITION in types:
        return DayType.COMPETITION
    if types <= {SessionType.REST}:
        return DayType.REST
    if types <= {SessionType.RECOVERY, SessionType.REST}:
        return DayType.EASY

    planned_min = sum(s.planned_duration_min for s in sessions)
    hard = {SessionType.TRACK, SessionType.STRENGTH}
    if types & hard and (planned_min >= 120 or len(sessions) > 1):
        return DayType.HARD
    if types & hard:
        return DayType.MODERATE
    return DayType.EASY


def training_kcal(athlete, on_date):
    """訓練額外消耗估算：約 0.10 kcal / kg / AU-分鐘當量。"""
    from core.models import SessionStatus
    from planning.models import TrainingSession

    sessions = TrainingSession.objects.filter(athlete=athlete, date=on_date)
    total = 0
    for s in sessions:
        minutes = (
            s.actual_duration_min
            if s.status in (SessionStatus.COMPLETED, SessionStatus.PARTIAL) and s.actual_duration_min
            else s.planned_duration_min
        )
        rpe = s.session_rpe or 6
        # MET 近似：RPE 6 ≈ 8 MET，每 RPE 約 1.2 MET
        met = 2.0 + rpe * 1.0
        total += met * float(athlete.current_weight_kg) * (minutes / 60) * 1.05
    return round(total)


def calculate_targets(athlete, on_date=None, day_type=None, goal=NutritionGoal.MAINTAIN, save=True):
    """計算（並可選擇儲存）某日的營養目標。"""
    on_date = on_date or date.today()
    day_type = day_type or infer_day_type(athlete, on_date)
    # 表單傳來的值不一定在選項內（舊分頁、手改網址）：認不得就當「維持」，不要整頁掛掉
    if goal not in GOAL_ADJUSTMENT:
        goal = NutritionGoal.MAINTAIN
    weight = float(athlete.current_weight_kg)

    bmr = mifflin_st_jeor(weight, athlete.height_cm, athlete.age, athlete.sex)
    activity_factor, carb_per_kg, protein_per_kg, fat_ratio = DAY_TYPE_PROFILE[day_type]

    # TDEE = BMR × 活動係數（活動係數已含日常活動）＋ 訓練額外消耗的一半（避免重複計算）
    tdee = round(bmr * activity_factor + training_kcal(athlete, on_date) * 0.5)
    target_kcal = round(tdee * (1 + GOAL_ADJUSTMENT[goal]))

    carb_g = round(carb_per_kg * weight)
    protein_g = round(protein_per_kg * weight)
    remaining = target_kcal - carb_g * 4 - protein_g * 4
    fat_g = max(round(remaining / 9), round(MIN_FAT_G_PER_KG * weight))

    # 若脂肪被下限撐高導致超標，回頭削碳水
    overshoot = (carb_g * 4 + protein_g * 4 + fat_g * 9) - target_kcal
    if overshoot > 0:
        carb_g = max(carb_g - round(overshoot / 4), round(3.0 * weight))

    training_hours = sum(
        (s.actual_duration_min or s.planned_duration_min)
        for s in athlete.sessions.filter(date=on_date)
    ) / 60
    water_ml = round(35 * weight + training_hours * 700)

    data = {
        "day_type": day_type,
        "goal": goal,
        "bmr_kcal": bmr,
        "tdee_kcal": tdee,
        "target_kcal": target_kcal,
        "carb_g": carb_g,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "water_ml": water_ml,
    }

    if not save:
        return data

    obj, _unused = NutritionTarget.objects.update_or_create(
        athlete=athlete, date=on_date, defaults=data
    )
    return obj


def weekly_compliance(athlete, week_start):
    """一週營養達成率（實際 vs 目標）。"""
    from datetime import timedelta

    rows = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        target = NutritionTarget.objects.filter(athlete=athlete, date=d).first()
        if target is None:
            rows.append({"date": d, "has_target": False})
            continue
        rows.append(
            {
                "date": d,
                "has_target": True,
                "day_type": target.get_day_type_display(),
                "target_kcal": target.target_kcal,
                "actual": target.actual_intake(),
                "compliance": target.compliance(),
            }
        )
    return rows


COMMON_SUPPLEMENTS = [
    ("Creatine Monohydrate", "5 g/day", _("任何時間，每日固定"), _("提升磷酸肌酸再合成、爆發力")),
    ("Caffeine", "3–6 mg/kg", _("運動前 45–60 分鐘"), _("提升警覺與衝刺表現")),
    ("Whey Protein", "20–40 g", _("訓練後 / 蛋白攝取不足時"), _("補足每日蛋白需求")),
    ("Vitamin D3", "1000–2000 IU", _("隨餐"), _("骨骼健康、肌肉功能")),
    ("Iron", _("依血檢調整"), _("空腹配維他命C"), _("耐力運動員常見缺乏（須先驗血）")),
    ("Beta-Alanine", "3–6 g/day", _("分次服用"), _("緩衝乳酸，對 400m–1500m 有效")),
    ("Sodium Bicarbonate", "0.2–0.3 g/kg", _("賽前 90–150 分鐘"), _("血液緩衝（腸胃反應需先測試）")),
]


# ------------------------------------------------------- InBody × 營養 交叉分析

#: 田徑運動員的體脂參考帶（%）。不是健康門檻，是「這個數字在專項上偏高／偏低」的判讀線。
FAT_BANDS = {
    Sex.MALE: (6.0, 12.0),
    Sex.FEMALE: (14.0, 22.0),
}


def katch_mcardle(lean_mass_kg):
    """用去脂體重算 BMR：370 + 21.6 × LBM。

    Mifflin-St Jeor 只看體重與身高，同體重的人不管肌肉多少都算出同一個數字；
    有 InBody 的去脂體重時，Katch-McArdle 對運動員準得多。
    """
    return round(370 + 21.6 * float(lean_mass_kg))


def body_composition_insight(athlete, target=None):
    """把最新一次體組成量測與今天的營養目標擺在一起看。

    回傳畫面直接用的 dict；沒有任何體測紀錄時 has_data 為 False。
    """
    latest = athlete.body_metrics.order_by("-date").first()
    if latest is None:
        return {"has_data": False}

    previous = athlete.body_metrics.filter(date__lt=latest.date).order_by("-date").first()
    lean = latest.lean_mass_kg
    fat_mass = latest.fat_mass_kg
    weight = float(latest.weight_kg)

    rows = []
    notes = []

    def delta(now, before, unit, better_lower=False):
        if now is None or before is None:
            return None
        diff = round(float(now) - float(before), 1)
        return {
            "value": diff,
            "text": f"{diff:+.1f} {unit}",
            "good": (diff < 0) if better_lower else (diff > 0),
            "flat": abs(diff) < 0.1,
        }

    rows.append(
        {
            "label": _("體重"),
            "value": f"{weight:.1f} kg",
            "delta": delta(latest.weight_kg, previous.weight_kg if previous else None, "kg"),
        }
    )
    if latest.body_fat_pct is not None:
        rows.append(
            {
                "label": _("體脂率"),
                "value": f"{float(latest.body_fat_pct):.1f} %",
                "delta": delta(
                    latest.body_fat_pct,
                    previous.body_fat_pct if previous else None,
                    "%",
                    better_lower=True,
                ),
            }
        )
    if lean is not None:
        rows.append(
            {
                "label": _("去脂體重"),
                "value": f"{lean:.1f} kg",
                "delta": delta(lean, previous.lean_mass_kg if previous else None, "kg"),
            }
        )
    if fat_mass is not None:
        rows.append(
            {
                "label": _("脂肪量"),
                "value": f"{fat_mass:.1f} kg",
                "delta": delta(
                    fat_mass, previous.fat_mass_kg if previous else None, "kg", better_lower=True
                ),
            }
        )
    if latest.body_water_pct is not None:
        rows.append(
            {"label": _("體水分率"), "value": f"{float(latest.body_water_pct):.1f} %", "delta": None}
        )

    # ---- BMR：磅上的、Mifflin、Katch-McArdle 三個數字擺一起 ----
    mifflin = mifflin_st_jeor(weight, athlete.height_cm, athlete.age, athlete.sex)
    katch = katch_mcardle(lean) if lean is not None else None
    bmr_rows = [{"label": _("Mifflin-St Jeor（依體重身高）"), "value": mifflin}]
    if latest.bmr_kcal:
        bmr_rows.append({"label": _("體組成磅量測（%(v0)s）") % {"v0": latest.date}, "value": latest.bmr_kcal})
    if katch:
        bmr_rows.append({"label": _("Katch-McArdle（依去脂體重）"), "value": katch})
        if abs(katch - mifflin) >= 60:
            notes.append(
                (
                    _(
                        "依去脂體重算出的 BMR 是 %(katch)s kcal，比只看體重身高的 %(mifflin)s kcal "
                        "高 %(diff)s kcal——肌肉量偏離同體重的平均值，熱量目標可以往這個方向微調。"
                    )
                    if katch > mifflin
                    else _(
                        "依去脂體重算出的 BMR 是 %(katch)s kcal，比只看體重身高的 %(mifflin)s kcal "
                        "低 %(diff)s kcal——肌肉量偏離同體重的平均值，熱量目標可以往這個方向微調。"
                    )
                ) % {"katch": katch, "mifflin": mifflin, "diff": abs(katch - mifflin)}
            )

    # ---- 蛋白質：改用去脂體重來看 g/kg ----
    protein = None
    if target is not None and lean:
        protein = {
            "target_g": target.protein_g,
            "per_kg": round(target.protein_g / weight, 2),
            "per_kg_lean": round(target.protein_g / lean, 2),
        }
        if protein["per_kg_lean"] < 2.0:
            notes.append(
                _("今日蛋白目標換算成去脂體重是 %(v0)s g/kg LBM，增肌期建議 2.0-2.4 g/kg LBM，可以再加一點。") % {"v0": protein['per_kg_lean']}
            )

    # ---- 體脂帶判讀 ----
    if latest.body_fat_pct is not None:
        low, high = FAT_BANDS.get(athlete.sex, (8.0, 20.0))
        pct = float(latest.body_fat_pct)
        if pct > high:
            notes.append(
                _(
                    "體脂 %(pct).1f%% 高於此性別的競賽參考帶（%(low).0f-%(high).0f%%），"
                    "減脂請走每週 0.5%% 體重的緩降，別在高強度期做大幅赤字。"
                ) % {"pct": pct, "low": low, "high": high}
            )
        elif pct < low:
            notes.append(
                _(
                    "體脂 %(pct).1f%% 低於參考帶下緣（%(low).0f%%），"
                    "留意能量供應不足（RED-S）：月經、睡眠、晨脈與骨骼健康都要一起看。"
                ) % {"pct": pct, "low": low}
            )

    # ---- 部位不對稱 ----
    asym = []
    for label, right, left in (
        (_("下肢肌肉量"), latest.muscle_leg_r, latest.muscle_leg_l),
        (_("上肢肌肉量"), latest.muscle_arm_r, latest.muscle_arm_l),
    ):
        if right is None or left is None:
            continue
        r, l = float(right), float(left)
        base = max(r, l)
        if base and abs(r - l) / base >= 0.05:
            asym.append(
                _("%(label)s左右差 %(diff).2f kg（%(pct).0f%%）")
                % {"label": label, "diff": abs(r - l), "pct": abs(r - l) / base * 100}
            )
    if asym:
        notes.append("；".join(str(a) for a in asym) + _("——差距超過 5%，配合單邊力量訓練與傷患紀錄一起看。"))

    return {
        "has_data": True,
        "latest": latest,
        "previous": previous,
        "days_since": (date.today() - latest.date).days,
        "rows": rows,
        "bmr_rows": bmr_rows,
        "katch_bmr": katch,
        "protein": protein,
        "notes": notes,
        "segments": latest.segments,
    }


# ------------------------------------------------------------------ 補充餐單

#: 補充餐單的候選清單：(名稱, 說明, 熱量, 碳水, 蛋白, 脂肪, 主要補什麼)
#: 全部是便利商店 / 家裡拿得到的東西，寫成一句「吃什麼、多少」，運動員才照做得出來。
SUPPLEMENT_FOODS = [
    (_("香蕉 1 條 + 蜂蜜水 300ml"), _("訓練後 30 分鐘內最快補回肝醣"), 165, 40, 1, 0, "carb"),
    (_("白飯 1 碗（200g）"), _("最便宜的碳水，配主餐一起加量"), 260, 57, 5, 1, "carb"),
    (_("烏冬 / 意粉 1 份（乾重 80g）"), _("訓練前 3 小時的主食"), 285, 58, 10, 1, "carb"),
    (_("低脂朱古力奶 500ml"), _("碳水蛋白比約 3:1，經典的訓練後恢復飲"), 320, 50, 17, 6, "carb"),
    (_("運動飲料 500ml"), _("長時間或高溫訓練時補水與電解質"), 130, 32, 0, 0, "carb"),
    (_("雞胸肉 150g"), _("低脂高蛋白，午晚餐加一份"), 250, 0, 46, 5, "protein"),
    (_("乳清蛋白 1 匙 + 水"), _("蛋白差得不多時用來補尾數"), 120, 3, 25, 1, "protein"),
    (_("希臘乳酪 200g"), _("睡前的慢消化蛋白"), 180, 8, 20, 6, "protein"),
    (_("雞蛋 2 隻"), _("早餐或加餐，同時補脂肪"), 155, 1, 13, 11, "protein"),
    (_("原味堅果 30g"), _("熱量密度高，補脂肪不佔胃"), 180, 6, 6, 16, "fat"),
    (_("牛油果半個"), _("單元不飽和脂肪，配沙拉或多士"), 160, 9, 2, 15, "fat"),
]

MACRO_KCAL = {"carb": 4, "protein": 4, "fat": 9}
MACRO_INDEX = {"carb": 3, "protein": 4, "fat": 5}
MACRO_LABEL = {"carb": _("碳水"), "protein": _("蛋白質"), "fat": _("脂肪")}


def _gap(target_value, actual_value):
    return max(round(target_value - (actual_value or 0)), 0)


def _pick_supplements(gaps, limit=6):
    """按缺口大小挑補充項目；每挑一項就把它補到的量從缺口扣掉。"""
    remaining = dict(gaps)
    picks = []
    used = set()
    macros = sorted(MACRO_KCAL, key=lambda k: -remaining.get(k, 0) * MACRO_KCAL[k])
    for macro in macros:
        # 少於約 120 kcal 的缺口就不值得再加一項東西
        while remaining[macro] * MACRO_KCAL[macro] >= 120 and len(picks) < limit:
            options = [f for f in SUPPLEMENT_FOODS if f[6] == macro and f[0] not in used]
            if not options:
                break
            pick = min(options, key=lambda f: abs(f[MACRO_INDEX[macro]] - remaining[macro]))
            used.add(pick[0])
            picks.append(
                {
                    "name": pick[0],
                    "why": pick[1],
                    "kcal": pick[2],
                    "carb_g": pick[3],
                    "protein_g": pick[4],
                    "fat_g": pick[5],
                    "fills": MACRO_LABEL[macro],
                }
            )
            remaining["carb"] = max(remaining["carb"] - pick[3], 0)
            remaining["protein"] = max(remaining["protein"] - pick[4], 0)
            remaining["fat"] = max(remaining["fat"] - pick[5], 0)
        if len(picks) >= limit:
            break
    return picks


def supplement_plan(athlete, on_date=None, target=None):
    """訓練加進來之後，今天還差多少、該補什麼。

    邏輯很直接：目標（已含當日訓練的額外消耗）減掉已經吃進去的，
    差額按碳水／蛋白／脂肪分別挑東西補，並依當日有沒有訓練給時機建議。
    """
    from planning.models import TrainingSession

    on_date = on_date or date.today()
    if target is None:
        target = NutritionTarget.objects.filter(athlete=athlete, date=on_date).first()
    if target is None:
        target = calculate_targets(athlete, on_date)

    actual = target.actual_intake()
    gaps = {
        "kcal": _gap(target.target_kcal, actual["kcal"]),
        "carb": _gap(target.carb_g, actual["carb"]),
        "protein": _gap(target.protein_g, actual["protein"]),
        "fat": _gap(target.fat_g, actual["fat"]),
    }

    sessions = list(TrainingSession.objects.filter(athlete=athlete, date=on_date))
    picks = _pick_supplements(gaps)

    if sessions:
        # 課表上只有上午／下午兩個時段，沒有實際鐘點；一天兩堂就以早的那一堂為準
        slots = {s.time_slot for s in sessions}
        slot = "AM" if "AM" in slots else ("PM" if "PM" in slots else "")
        label = dict(TrainingSession.time_slot.field.choices).get(slot)
        when = _("（今日訓練排在%(v0)s）") % {"v0": label} if label else ""
        timing = [
            _("訓練前 2-3 小時%(v0)s：以碳水為主、低脂低纖的一餐，避免腸胃不適。") % {"v0": when},
            _("訓練前 30-60 分鐘：一份好消化的碳水（香蕉、能量棒），不要試新東西。"),
            _("訓練中超過 60 分鐘：每小時 30-60 g 碳水 ＋ 含電解質的水。"),
            _("訓練後 30-60 分鐘：碳水 1.0-1.2 g/kg ＋ 蛋白 0.3-0.4 g/kg，越早越好。"),
            _("睡前：20-40 g 慢消化蛋白（希臘乳酪、酪蛋白），支撐夜間修復。"),
        ]
    else:
        timing = [
            _("今天沒有排訓練：熱量與碳水本來就該比訓練日低，別硬補到訓練日的量。"),
            _("蛋白質不減：休息日才是肌肉真正修復的時候，維持每餐 0.3-0.4 g/kg。"),
        ]

    recovery = athlete.recovery_logs.filter(date=on_date).first()
    drunk = recovery.water_intake_ml if recovery else 0

    return {
        "date": on_date,
        "target": target,
        "actual": actual,
        "gaps": gaps,
        "sessions": sessions,
        "training_kcal": training_kcal(athlete, on_date),
        "picks": picks,
        "picked_kcal": sum(p["kcal"] for p in picks),
        "timing": timing,
        "on_track": gaps["kcal"] <= 150 and gaps["protein"] <= 15,
        "water_gap": _gap(target.water_ml, drunk),
    }


# ------------------------------------------------- 體重／體脂方向 → 怎麼吃

#: 每個方向給的執行重點：這一段是運動員照著做的部分，寫成一句一個動作。
DIRECTION_ACTIONS = {
    "CUT": [
        _("赤字只從脂肪與精緻碳水扣，訓練前後的碳水一律不動——那是拿來跑的，不是拿來胖的。"),
        _("休息日把碳水降下來、訓練日照吃：一週的赤字靠休息日湊，高強度日不要餓著練。"),
        _("每餐 0.4 g/kg 蛋白、分 4 餐，睡前再加一份慢消化蛋白，減脂期守肌肉靠這個。"),
        _("重訓的重量不要降。減脂期減的是量不是強度，強度一降，掉的就會是肌肉。"),
        _("每週固定同一天、同一時間、同一狀態量體重與體脂，只看週平均，不看單日跳動。"),
    ],
    "TRIM": [
        _("小赤字就好：一天少一份精緻碳水或一份油，不用改整個菜單。"),
        _("賽前期或高強度週先暫停赤字，回到維持量，比賽完再修。"),
        _("蛋白與訓練前後的碳水維持原樣，只動訓練以外的時段。"),
    ],
    "GAIN": [
        _("盈餘放在訓練後：練完 30–60 分鐘那一餐加碳水加蛋白，增的才會進肌肉。"),
        _("每天多一餐加餐（果仁、乳酪、朱古力奶），不要靠正餐硬塞到脹。"),
        _("重訓要有漸進超負荷：熱量加了但重量沒加，加的就是脂肪。"),
        _("每兩週檢查一次體脂率：體重升、體脂率也升得快，就把盈餘收一半。"),
    ],
    "FUEL": [
        _("先把熱量吃回維持量以上，這不是增肌是止血——能量供應不足會拖垮荷爾蒙、骨質與睡眠。"),
        _("碳水優先補回來：肝醣是速度與力量的燃料，低碳水撐不起高強度訓練。"),
        _("這一段先不要量體脂追數字，看的是晨脈、睡眠、月經（女生）與訓練感覺。"),
        _("同時把這件事告訴教練與隊醫，RED-S 不是靠自己調飲食就能解決的。"),
    ],
}


def body_goal_plan(athlete, target=None, report=None, custom=None):
    """把數據分析算出來的體重／體脂方向，翻成今天餐桌上的數字。

    數據分析頁回答的是「改變體脂與體重，重訓比值會變成多少」；
    這裡回答「那要怎麼吃」——每日熱量、蛋白下限、執行重點，
    以及做完之後相對力量能換到多少，讓方向本身變得值得做。

    `custom` 是運動員在數據分析頁自己填的 (體重, 體脂%)；有填就照他決定的
    數值走，系統建議退到旁邊，但速度與下限的提醒照樣給。
    """
    from analytics import body_strength as bs

    report = report or bs.strength_ratio_report(athlete)
    rec = report.get("recommendation")
    custom_plan = None
    if custom and any(custom):
        custom_plan = bs.custom_plan(report, custom[0], custom[1])
        if custom_plan.get("has_plan"):
            rec = custom_plan["rec"]
    if rec is None:
        return {"has_plan": False, "report": report}

    if target is None:
        target = NutritionTarget.objects.filter(athlete=athlete, date=date.today()).first()

    kcal_now = target.target_kcal if target else None
    kcal_goal = kcal_now + rec["kcal_delta"] if kcal_now else None

    # 蛋白照去脂體重給；碳水不動（那是訓練的燃料），差額全部從脂肪調
    protein_g = rec["protein_g"]
    protein_now = target.protein_g if target else None
    carb_g = target.carb_g if target else None
    fat_g = None
    if kcal_goal and carb_g is not None:
        fat_g = max(round((kcal_goal - carb_g * 4 - protein_g * 4) / 9), round(MIN_FAT_G_PER_KG * float(athlete.current_weight_kg)))

    payoff = rec.get("payoff")
    focus = rec.get("focus")
    why = []
    if payoff and focus and (payoff.get("gain_pct") or 0) > 0:
        why.append(
            _("走完這 %(weeks)s 週，%(name)s 每公斤體重舉得起的會從 %(now)s 變成 %(then)s（+%(gain).1f%%）——"
              "起跑與跳躍靠的就是這個比值。")
            % {
                "weeks": rec["weeks"],
                "name": focus["item"].display_name,
                "now": _ratio_text(focus.get("per_bw")),
                "then": _ratio_text(payoff.get("per_bw")),
                "gain": payoff["gain_pct"],
            }
        )
    if rec["direction"] in ("CUT", "TRIM"):
        why.append(
            _("減下來的 %(kg)s kg 是純負重：力量一分沒少，每一步、每一跳要抬的重量卻少了這麼多。")
            % {"kg": abs(rec["weight_delta"])}
        )
    elif rec["direction"] == "GAIN":
        why.append(
            _("加的是去脂體重，絕對力量跟著上去；只要體脂率守住，相對力量就不會被體重吃掉。")
        )

    return {
        "has_plan": True,
        "report": report,
        "rec": rec,
        "target": target,
        "kcal_now": kcal_now,
        "kcal_goal": kcal_goal,
        "kcal_delta": rec["kcal_delta"],
        "protein_now": protein_now,
        "protein_goal": protein_g,
        "carb_g": carb_g,
        "fat_goal": fat_g,
        "actions": DIRECTION_ACTIONS.get(rec["direction"], []),
        "why": why,
        "goal_choice": rec["goal"],
        "is_custom": bool(rec.get("custom")),
        "custom_plan": custom_plan,
        "warnings": (custom_plan or {}).get("warnings", []),
        "phases": phase_schedule(rec, kcal_now),
    }


def _ratio_text(value):
    return f"{value:.2f}×" if value else "—"


#: 調整方案切成幾段；段數再多也只是把同一件事寫得更碎
MAX_PHASES = 4


def phase_schedule(rec, kcal_now):
    """把整段目標切成幾個檢查點：每一段要到哪個體重體脂、當週吃多少。

    一次給一個遙遠的目標很難走；切成幾段，每一段都有可以量得到的中繼點，
    最後一段回到維持量，把成果穩住而不是一路餓下去。
    """
    weeks = rec.get("weeks") or 0
    if not weeks or kcal_now is None:
        return []

    steps = min(MAX_PHASES, weeks)
    w0, wt = rec["weight_now"], rec["target_weight"]
    f0, ft = rec.get("fat_pct_now"), rec.get("target_fat_pct")
    kcal_goal = kcal_now + rec["kcal_delta"]
    rows = []
    for i in range(1, steps + 1):
        share = i / steps
        week_to = max(1, int(round(weeks * share)))
        last = i == steps
        if i == 1:
            note = _("建立節奏：同一天同一時間量體重與體脂，這一段先求穩定不求快。")
        elif last:
            note = _("收尾：回到維持量，讓體重在目標上下 0.5 kg 站穩兩週再談下一步。")
        else:
            note = _("檢查點：連續兩週沒動就把熱量再調 10%，有動就一個字都不要改。")
        rows.append(
            {
                "week_to": week_to,
                "weight": round(w0 + (wt - w0) * share, 1),
                "fat_pct": round(f0 + (ft - f0) * share, 1) if f0 and ft else None,
                "kcal": kcal_now if last and rec["kcal_delta"] else kcal_goal,
                "note": note,
            }
        )
    return rows

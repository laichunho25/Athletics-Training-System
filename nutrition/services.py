"""
營養計算：Mifflin-St Jeor BMR → TDEE → 三大營養素分配。

碳水與蛋白質採 g/kg 體重（運動營養標準做法），脂肪取剩餘熱量，
並設下限 0.8 g/kg 以保障荷爾蒙合成。
"""

from datetime import date

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

    obj, _ = NutritionTarget.objects.update_or_create(
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
    ("Creatine Monohydrate", "5 g/day", "任何時間，每日固定", "提升磷酸肌酸再合成、爆發力"),
    ("Caffeine", "3–6 mg/kg", "運動前 45–60 分鐘", "提升警覺與衝刺表現"),
    ("Whey Protein", "20–40 g", "訓練後 / 蛋白攝取不足時", "補足每日蛋白需求"),
    ("Vitamin D3", "1000–2000 IU", "隨餐", "骨骼健康、肌肉功能"),
    ("Iron", "依血檢調整", "空腹配維他命C", "耐力運動員常見缺乏（須先驗血）"),
    ("Beta-Alanine", "3–6 g/day", "分次服用", "緩衝乳酸，對 400m–1500m 有效"),
    ("Sodium Bicarbonate", "0.2–0.3 g/kg", "賽前 90–150 分鐘", "血液緩衝（腸胃反應需先測試）"),
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
            "label": "體重",
            "value": f"{weight:.1f} kg",
            "delta": delta(latest.weight_kg, previous.weight_kg if previous else None, "kg"),
        }
    )
    if latest.body_fat_pct is not None:
        rows.append(
            {
                "label": "體脂率",
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
                "label": "去脂體重",
                "value": f"{lean:.1f} kg",
                "delta": delta(lean, previous.lean_mass_kg if previous else None, "kg"),
            }
        )
    if fat_mass is not None:
        rows.append(
            {
                "label": "脂肪量",
                "value": f"{fat_mass:.1f} kg",
                "delta": delta(
                    fat_mass, previous.fat_mass_kg if previous else None, "kg", better_lower=True
                ),
            }
        )
    if latest.body_water_pct is not None:
        rows.append(
            {"label": "體水分率", "value": f"{float(latest.body_water_pct):.1f} %", "delta": None}
        )

    # ---- BMR：磅上的、Mifflin、Katch-McArdle 三個數字擺一起 ----
    mifflin = mifflin_st_jeor(weight, athlete.height_cm, athlete.age, athlete.sex)
    katch = katch_mcardle(lean) if lean is not None else None
    bmr_rows = [{"label": "Mifflin-St Jeor（依體重身高）", "value": mifflin}]
    if latest.bmr_kcal:
        bmr_rows.append({"label": f"體組成磅量測（{latest.date}）", "value": latest.bmr_kcal})
    if katch:
        bmr_rows.append({"label": "Katch-McArdle（依去脂體重）", "value": katch})
        if abs(katch - mifflin) >= 60:
            notes.append(
                f"依去脂體重算出的 BMR 是 {katch} kcal，比只看體重身高的 {mifflin} kcal "
                f"{'高' if katch > mifflin else '低'} {abs(katch - mifflin)} kcal——"
                "肌肉量偏離同體重的平均值，熱量目標可以往這個方向微調。"
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
                f"今日蛋白目標換算成去脂體重是 {protein['per_kg_lean']} g/kg LBM，"
                "增肌期建議 2.0-2.4 g/kg LBM，可以再加一點。"
            )

    # ---- 體脂帶判讀 ----
    if latest.body_fat_pct is not None:
        low, high = FAT_BANDS.get(athlete.sex, (8.0, 20.0))
        pct = float(latest.body_fat_pct)
        if pct > high:
            notes.append(
                f"體脂 {pct:.1f}% 高於此性別的競賽參考帶（{low:.0f}-{high:.0f}%），"
                "減脂請走每週 0.5% 體重的緩降，別在高強度期做大幅赤字。"
            )
        elif pct < low:
            notes.append(
                f"體脂 {pct:.1f}% 低於參考帶下緣（{low:.0f}%），"
                "留意能量供應不足（RED-S）：月經、睡眠、晨脈與骨骼健康都要一起看。"
            )

    # ---- 部位不對稱 ----
    asym = []
    for label, right, left in (
        ("下肢肌肉量", latest.muscle_leg_r, latest.muscle_leg_l),
        ("上肢肌肉量", latest.muscle_arm_r, latest.muscle_arm_l),
    ):
        if right is None or left is None:
            continue
        r, l = float(right), float(left)
        base = max(r, l)
        if base and abs(r - l) / base >= 0.05:
            asym.append(f"{label}左右差 {abs(r - l):.2f} kg（{abs(r - l) / base * 100:.0f}%）")
    if asym:
        notes.append("；".join(asym) + "——差距超過 5%，配合單邊力量訓練與傷患紀錄一起看。")

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
    ("香蕉 1 條 + 蜂蜜水 300ml", "訓練後 30 分鐘內最快補回肝醣", 165, 40, 1, 0, "carb"),
    ("白飯 1 碗（200g）", "最便宜的碳水，配主餐一起加量", 260, 57, 5, 1, "carb"),
    ("烏冬 / 意粉 1 份（乾重 80g）", "訓練前 3 小時的主食", 285, 58, 10, 1, "carb"),
    ("低脂朱古力奶 500ml", "碳水蛋白比約 3:1，經典的訓練後恢復飲", 320, 50, 17, 6, "carb"),
    ("運動飲料 500ml", "長時間或高溫訓練時補水與電解質", 130, 32, 0, 0, "carb"),
    ("雞胸肉 150g", "低脂高蛋白，午晚餐加一份", 250, 0, 46, 5, "protein"),
    ("乳清蛋白 1 匙 + 水", "蛋白差得不多時用來補尾數", 120, 3, 25, 1, "protein"),
    ("希臘乳酪 200g", "睡前的慢消化蛋白", 180, 8, 20, 6, "protein"),
    ("雞蛋 2 隻", "早餐或加餐，同時補脂肪", 155, 1, 13, 11, "protein"),
    ("原味堅果 30g", "熱量密度高，補脂肪不佔胃", 180, 6, 6, 16, "fat"),
    ("牛油果半個", "單元不飽和脂肪，配沙拉或多士", 160, 9, 2, 15, "fat"),
]

MACRO_KCAL = {"carb": 4, "protein": 4, "fat": 9}
MACRO_INDEX = {"carb": 3, "protein": 4, "fat": 5}
MACRO_LABEL = {"carb": "碳水", "protein": "蛋白質", "fat": "脂肪"}


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
        starts = [s.start_time for s in sessions if s.start_time]
        when = f"（今日訓練 {min(starts).strftime('%H:%M')} 開始）" if starts else ""
        timing = [
            f"訓練前 2-3 小時{when}：以碳水為主、低脂低纖的一餐，避免腸胃不適。",
            "訓練前 30-60 分鐘：一份好消化的碳水（香蕉、能量棒），不要試新東西。",
            "訓練中超過 60 分鐘：每小時 30-60 g 碳水 ＋ 含電解質的水。",
            "訓練後 30-60 分鐘：碳水 1.0-1.2 g/kg ＋ 蛋白 0.3-0.4 g/kg，越早越好。",
            "睡前：20-40 g 慢消化蛋白（希臘乳酪、酪蛋白），支撐夜間修復。",
        ]
    else:
        timing = [
            "今天沒有排訓練：熱量與碳水本來就該比訓練日低，別硬補到訓練日的量。",
            "蛋白質不減：休息日才是肌肉真正修復的時候，維持每餐 0.3-0.4 g/kg。",
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

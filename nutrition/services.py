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

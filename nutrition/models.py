from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import AthleteProfile
from core.models import DayType, TimeStampedModel


class NutritionGoal(models.TextChoices):
    LOSE = "LOSE", "減脂"
    MAINTAIN = "MAINTAIN", "維持"
    GAIN = "GAIN", "增重"


class NutritionTarget(TimeStampedModel):
    """每日營養目標，依當日訓練日類型自動計算。"""

    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="nutrition_targets"
    )
    date = models.DateField("日期")
    day_type = models.CharField("訓練日類型", max_length=15, choices=DayType.choices)
    goal = models.CharField(
        "體重目標", max_length=10, choices=NutritionGoal.choices, default=NutritionGoal.MAINTAIN
    )
    bmr_kcal = models.PositiveIntegerField("BMR (kcal)", default=0)
    tdee_kcal = models.PositiveIntegerField("TDEE (kcal)", default=0)
    target_kcal = models.PositiveIntegerField("目標熱量 (kcal)", default=0)
    carb_g = models.PositiveIntegerField("碳水 (g)", default=0)
    protein_g = models.PositiveIntegerField("蛋白質 (g)", default=0)
    fat_g = models.PositiveIntegerField("脂肪 (g)", default=0)
    water_ml = models.PositiveIntegerField("水份 (ml)", default=0)

    class Meta:
        verbose_name = "每日營養目標"
        verbose_name_plural = "每日營養目標"
        unique_together = ("athlete", "date")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.athlete} {self.date} {self.target_kcal}kcal"

    @property
    def macro_kcal_split(self):
        return {
            "carb": self.carb_g * 4,
            "protein": self.protein_g * 4,
            "fat": self.fat_g * 9,
        }

    def actual_intake(self):
        agg = MealLog.objects.filter(athlete=self.athlete, date=self.date).aggregate(
            kcal=models.Sum("kcal"),
            carb=models.Sum("carb_g"),
            protein=models.Sum("protein_g"),
            fat=models.Sum("fat_g"),
        )
        return {k: v or 0 for k, v in agg.items()}

    def compliance(self):
        """達成率 (%)。"""
        actual = self.actual_intake()
        def pct(a, t):
            return round(a / t * 100, 1) if t else None
        return {
            "kcal": pct(actual["kcal"], self.target_kcal),
            "carb": pct(actual["carb"], self.carb_g),
            "protein": pct(actual["protein"], self.protein_g),
            "fat": pct(actual["fat"], self.fat_g),
        }


class MealType(models.TextChoices):
    BREAKFAST = "BREAKFAST", "早餐"
    LUNCH = "LUNCH", "午餐"
    DINNER = "DINNER", "晚餐"
    PRE_TRAINING = "PRE_TRAINING", "訓練前"
    POST_TRAINING = "POST_TRAINING", "訓練後"
    SNACK = "SNACK", "加餐"


class MealLog(TimeStampedModel):
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE, related_name="meals")
    date = models.DateField("日期")
    meal_type = models.CharField("餐次", max_length=15, choices=MealType.choices)
    description = models.TextField("內容")
    kcal = models.PositiveIntegerField("熱量 (kcal)", default=0)
    carb_g = models.PositiveIntegerField("碳水 (g)", default=0)
    protein_g = models.PositiveIntegerField("蛋白質 (g)", default=0)
    fat_g = models.PositiveIntegerField("脂肪 (g)", default=0)
    photo = models.ImageField("餐點照片", upload_to="meals/", null=True, blank=True)

    class Meta:
        verbose_name = "飲食紀錄"
        verbose_name_plural = "飲食紀錄"
        ordering = ["-date", "meal_type"]
        indexes = [models.Index(fields=["athlete", "date"])]

    def __str__(self):
        return f"{self.date} {self.get_meal_type_display()} {self.kcal}kcal"


class SupplementLog(TimeStampedModel):
    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="supplements"
    )
    date = models.DateField("日期")
    name = models.CharField("補充劑", max_length=80)
    dose = models.CharField("劑量", max_length=50)
    timing = models.CharField("服用時機", max_length=80, blank=True)
    purpose = models.CharField("目的", max_length=120, blank=True)

    class Meta:
        verbose_name = "補充劑紀錄"
        verbose_name_plural = "補充劑紀錄"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} {self.name} {self.dose}"


class RecoveryMethod(models.Model):
    name = models.CharField("恢復手段", max_length=60, unique=True)
    category = models.CharField("分類", max_length=40, blank=True)
    default_duration_min = models.PositiveSmallIntegerField("建議時長 (分)", default=10)
    description = models.TextField("說明", blank=True)

    class Meta:
        verbose_name = "恢復手段"
        verbose_name_plural = "恢復手段"
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class RecoveryLog(TimeStampedModel):
    """晨間問卷 + 恢復手段紀錄，是 readiness_score 的主要輸入。"""

    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="recovery_logs"
    )
    date = models.DateField("日期")
    sleep_hours = models.DecimalField(
        "睡眠時長 (小時)", max_digits=3, decimal_places=1, null=True, blank=True
    )
    sleep_quality = models.PositiveSmallIntegerField(
        "睡眠質量 (1-5)", null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    bedtime = models.TimeField("就寢時間", null=True, blank=True)
    wake_time = models.TimeField("起床時間", null=True, blank=True)
    water_intake_ml = models.PositiveIntegerField("飲水量 (ml)", default=0)
    soreness_level = models.PositiveSmallIntegerField(
        "肌肉痠痛 (1-10)", null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    stress_level = models.PositiveSmallIntegerField(
        "壓力 (1-5)", null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    mood = models.PositiveSmallIntegerField(
        "心情 (1-5)", null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    resting_hr = models.PositiveSmallIntegerField("晨脈", null=True, blank=True)
    methods = models.ManyToManyField(
        RecoveryMethod, blank=True, related_name="logs", verbose_name="使用的恢復手段"
    )
    note = models.TextField("備註", blank=True)

    class Meta:
        verbose_name = "恢復日誌"
        verbose_name_plural = "恢復日誌"
        unique_together = ("athlete", "date")
        ordering = ["-date"]
        indexes = [models.Index(fields=["athlete", "date"])]

    def __str__(self):
        return f"{self.athlete} {self.date} 睡{self.sleep_hours}h"

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import AthleteProfile
from core.models import TimeStampedModel
from planning.models import TrainingSession

RPE_VALIDATORS = [MinValueValidator(1), MaxValueValidator(10)]


# ---------------------------------------------------------------- 田徑專項


class Surface(models.TextChoices):
    TRACK = "TRACK", "田徑場"
    GRASS = "GRASS", "草地"
    HILL = "HILL", "斜坡"
    TREADMILL = "TREADMILL", "跑步機"
    ROAD = "ROAD", "路跑"
    SAND = "SAND", "沙地"


class TrackSet(TimeStampedModel):
    session = models.ForeignKey(
        TrainingSession, on_delete=models.CASCADE, related_name="track_sets"
    )
    order = models.PositiveSmallIntegerField("排序", default=1)
    description = models.CharField("描述", max_length=150, help_text="例：6 × 200m")
    distance_m = models.PositiveIntegerField("單趟距離 (m)")
    reps = models.PositiveSmallIntegerField("趟數", default=1)
    sets = models.PositiveSmallIntegerField("組數", default=1)
    target_time_sec = models.DecimalField(
        "目標時間 (秒)", max_digits=7, decimal_places=2, null=True, blank=True
    )
    actual_time_sec = models.DecimalField(
        "實際平均時間 (秒)", max_digits=7, decimal_places=2, null=True, blank=True
    )
    rest_between_reps_sec = models.PositiveIntegerField("趟間休息 (秒)", default=0)
    rest_between_sets_sec = models.PositiveIntegerField("組間休息 (秒)", default=0)
    intensity_pct = models.DecimalField(
        "強度 (% PB)", max_digits=5, decimal_places=1, null=True, blank=True
    )
    avg_hr = models.PositiveSmallIntegerField("平均心率", null=True, blank=True)
    max_hr = models.PositiveSmallIntegerField("最高心率", null=True, blank=True)
    rpe = models.PositiveSmallIntegerField(
        "RPE (1-10)", null=True, blank=True, validators=RPE_VALIDATORS
    )
    technical_focus = models.TextField("技術重點", blank=True)
    surface = models.CharField("場地", max_length=10, choices=Surface.choices, default=Surface.TRACK)
    spikes_used = models.BooleanField("穿釘鞋", default=False)

    class Meta:
        verbose_name = "專項訓練組"
        verbose_name_plural = "專項訓練組"
        ordering = ["session", "order"]

    def __str__(self):
        return f"{self.description} ({self.session.date})"

    @property
    def total_volume_m(self):
        return self.distance_m * self.reps * self.sets

    @property
    def total_reps(self):
        return self.reps * self.sets

    @property
    def pace_per_100m(self):
        if not self.actual_time_sec or not self.distance_m:
            return None
        return round(float(self.actual_time_sec) / self.distance_m * 100, 2)

    @property
    def speed_ms(self):
        if not self.actual_time_sec or not float(self.actual_time_sec):
            return None
        return round(self.distance_m / float(self.actual_time_sec), 2)

    def intensity_vs_pb(self):
        """以主項 PB 換算的相對強度百分比（時間項目適用）。"""
        from accounts.models import Event
        from core.models import MeasureUnit

        if not self.actual_time_sec:
            return None
        event = Event.objects.filter(distance_m=self.distance_m, unit=MeasureUnit.TIME).first()
        if event is None:
            return None
        pb = self.session.athlete.pb_for(event)
        if pb is None or not pb.mark:
            return None
        return round(float(pb.mark) / float(self.actual_time_sec) * 100, 1)


class RepSplit(models.Model):
    """逐趟分段紀錄（可選）。"""

    track_set = models.ForeignKey(TrackSet, on_delete=models.CASCADE, related_name="splits")
    rep_number = models.PositiveSmallIntegerField("第幾趟")
    time_sec = models.DecimalField("時間 (秒)", max_digits=7, decimal_places=2)
    note = models.CharField("備註", max_length=120, blank=True)

    class Meta:
        verbose_name = "分趟成績"
        verbose_name_plural = "分趟成績"
        unique_together = ("track_set", "rep_number")
        ordering = ["rep_number"]

    def __str__(self):
        return f"#{self.rep_number} {self.time_sec}s"


# ---------------------------------------------------------------- 力量訓練


class ExerciseCategory(models.TextChoices):
    SQUAT = "SQUAT", "蹲系"
    HINGE = "HINGE", "髖鉸鏈"
    PUSH = "PUSH", "推"
    PULL = "PULL", "拉"
    OLYMPIC = "OLYMPIC", "奧舉"
    PLYO = "PLYO", "增強式"
    CORE = "CORE", "核心"
    UNILATERAL = "UNILATERAL", "單邊"
    ACCESSORY = "ACCESSORY", "輔助"
    REHAB = "REHAB", "復健"


class OneRMFormula(models.TextChoices):
    EPLEY = "EPLEY", "Epley"
    BRZYCKI = "BRZYCKI", "Brzycki"
    DIRECT = "DIRECT", "實測"


class Exercise(models.Model):
    code = models.CharField("代碼", max_length=30, unique=True)
    name_zh = models.CharField("中文名稱", max_length=60)
    name_en = models.CharField("英文名稱", max_length=80)
    category = models.CharField("分類", max_length=12, choices=ExerciseCategory.choices)
    is_measured_by_1rm = models.BooleanField("以 1RM 計算強度", default=True)
    is_plyometric = models.BooleanField("增強式動作", default=False)
    primary_muscles = models.CharField("主要肌群", max_length=120, blank=True)
    video_url = models.URLField("示範影片", blank=True)

    class Meta:
        verbose_name = "力量動作"
        verbose_name_plural = "力量動作"
        ordering = ["category", "name_zh"]

    def __str__(self):
        return f"{self.name_zh} ({self.code})"


def epley_1rm(weight_kg, reps):
    """1RM = w × (1 + reps/30)"""
    if not weight_kg or not reps:
        return None
    return round(float(weight_kg) * (1 + reps / 30), 1)


def brzycki_1rm(weight_kg, reps):
    """1RM = w × 36 / (37 − reps)，reps < 37"""
    if not weight_kg or not reps or reps >= 37:
        return None
    return round(float(weight_kg) * 36 / (37 - reps), 1)


class OneRepMax(TimeStampedModel):
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE, related_name="one_rms")
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name="one_rms")
    value_kg = models.DecimalField("1RM (kg)", max_digits=6, decimal_places=2)
    test_date = models.DateField("測試日期")
    is_estimated = models.BooleanField("推估值", default=False)
    estimation_formula = models.CharField(
        "推估公式", max_length=10, choices=OneRMFormula.choices, default=OneRMFormula.DIRECT
    )

    class Meta:
        verbose_name = "最大肌力 1RM"
        verbose_name_plural = "最大肌力 1RM"
        unique_together = ("athlete", "exercise", "test_date")
        ordering = ["-test_date"]

    def __str__(self):
        return f"{self.athlete} {self.exercise.code} {self.value_kg}kg"

    @classmethod
    def latest_for(cls, athlete, exercise):
        return cls.objects.filter(athlete=athlete, exercise=exercise).order_by("-test_date").first()

    def load_at(self, pct):
        """回傳指定 % 1RM 的重量，四捨五入到 2.5kg。"""
        raw = float(self.value_kg) * pct / 100
        return round(raw / 2.5) * 2.5


class StrengthSet(TimeStampedModel):
    session = models.ForeignKey(
        TrainingSession, on_delete=models.CASCADE, related_name="strength_sets"
    )
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name="strength_sets")
    order = models.PositiveSmallIntegerField("動作排序", default=1)
    set_number = models.PositiveSmallIntegerField("第幾組", default=1)
    reps = models.PositiveSmallIntegerField("次數")
    weight_kg = models.DecimalField("重量 (kg)", max_digits=6, decimal_places=2, default=0)
    target_1rm_pct = models.DecimalField(
        "目標強度 (% 1RM)", max_digits=5, decimal_places=1, null=True, blank=True
    )
    actual_1rm_pct = models.DecimalField(
        "實際強度 (% 1RM)", max_digits=5, decimal_places=1, null=True, blank=True, editable=False
    )
    tempo = models.CharField("節奏", max_length=15, blank=True, help_text="例：3-1-X-0")
    rest_sec = models.PositiveIntegerField("組間休息 (秒)", default=120)
    rir = models.PositiveSmallIntegerField(
        "RIR 保留次數", null=True, blank=True, validators=[MaxValueValidator(10)]
    )
    rpe = models.PositiveSmallIntegerField(
        "RPE (1-10)", null=True, blank=True, validators=RPE_VALIDATORS
    )
    bar_velocity_ms = models.DecimalField(
        "槓速 (m/s)", max_digits=4, decimal_places=2, null=True, blank=True
    )
    is_failure = models.BooleanField("力竭", default=False)
    note = models.CharField("備註", max_length=150, blank=True)

    class Meta:
        verbose_name = "力量訓練組"
        verbose_name_plural = "力量訓練組"
        ordering = ["session", "order", "set_number"]

    def __str__(self):
        return f"{self.exercise.name_zh} {self.weight_kg}kg × {self.reps}"

    @property
    def tonnage(self):
        return float(self.weight_kg) * self.reps

    @property
    def estimated_1rm(self):
        return epley_1rm(self.weight_kg, self.reps)

    def save(self, *args, **kwargs):
        # 依當前 1RM 自動回填實際強度百分比
        if self.weight_kg and self.exercise_id and self.exercise.is_measured_by_1rm:
            current = OneRepMax.latest_for(self.session.athlete, self.exercise)
            if current and float(current.value_kg):
                self.actual_1rm_pct = Decimal(
                    str(round(float(self.weight_kg) / float(current.value_kg) * 100, 1))
                )
        super().save(*args, **kwargs)


class NeuromuscularTestType(models.TextChoices):
    CMJ = "CMJ", "反向跳 CMJ (cm)"
    SJ = "SJ", "蹲跳 SJ (cm)"
    BROAD_JUMP = "BROAD_JUMP", "立定跳遠 (cm)"
    GRIP = "GRIP", "握力 (kg)"
    SPRINT_10M = "SPRINT_10M", "10m 衝刺 (秒)"


class NeuromuscularTest(TimeStampedModel):
    """神經肌肉疲勞監控：與 7 日基線比較，跌幅 >10% 觸發警示。"""

    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="nm_tests"
    )
    date = models.DateField("日期")
    test_type = models.CharField("測試項目", max_length=15, choices=NeuromuscularTestType.choices)
    value = models.DecimalField("數值", max_digits=7, decimal_places=2)
    unit = models.CharField("單位", max_length=10, default="cm")
    note = models.CharField("備註", max_length=150, blank=True)

    class Meta:
        verbose_name = "神經肌肉測試"
        verbose_name_plural = "神經肌肉測試"
        unique_together = ("athlete", "date", "test_type")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.athlete} {self.get_test_type_display()} {self.value}"

    @property
    def lower_is_better(self):
        return self.test_type == NeuromuscularTestType.SPRINT_10M

    def baseline(self, days=28):
        """前 N 天（不含今日）的平均值。"""
        from datetime import timedelta

        qs = NeuromuscularTest.objects.filter(
            athlete=self.athlete,
            test_type=self.test_type,
            date__lt=self.date,
            date__gte=self.date - timedelta(days=days),
        )
        agg = qs.aggregate(avg=models.Avg("value"))["avg"]
        return float(agg) if agg else None

    @property
    def pct_of_baseline(self):
        base = self.baseline()
        if not base:
            return None
        return round(float(self.value) / base * 100, 1)

    @property
    def is_fatigued(self):
        """相對基線退步超過 10% → 疲勞警示。"""
        pct = self.pct_of_baseline
        if pct is None:
            return False
        return pct > 110 if self.lower_is_better else pct < 90

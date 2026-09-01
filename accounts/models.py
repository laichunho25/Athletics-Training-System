from datetime import date

from django.contrib.auth.models import AbstractUser
from django.db import models

from core.models import (
    AthleteStatus,
    EventCategory,
    MeasureUnit,
    Role,
    Sex,
    TimeStampedModel,
    format_mark,
)


class User(AbstractUser):
    role = models.CharField("角色", max_length=10, choices=Role.choices, default=Role.ATHLETE)
    phone = models.CharField("電話", max_length=30, blank=True)
    avatar = models.ImageField("頭像", upload_to="avatars/", null=True, blank=True)

    class Meta:
        # 後台 Accounts 區塊只保留四張表，這張是「管理員」（帳號與角色）
        verbose_name = "管理員"
        verbose_name_plural = "管理員"

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"

    @property
    def is_coach(self):
        return self.role == Role.COACH

    @property
    def is_athlete(self):
        return self.role == Role.ATHLETE


class Event(models.Model):
    """項目字典表：100M / 400M / LJ / SP …"""

    code = models.CharField("代碼", max_length=20, unique=True)
    name_zh = models.CharField("中文名稱", max_length=50)
    name_en = models.CharField("英文名稱", max_length=50)
    category = models.CharField("類別", max_length=15, choices=EventCategory.choices)
    unit = models.CharField("計量單位", max_length=10, choices=MeasureUnit.choices)
    distance_m = models.PositiveIntegerField("距離 (m)", null=True, blank=True)

    class Meta:
        verbose_name = "田徑項目"
        verbose_name_plural = "田徑項目"
        ordering = ["category", "distance_m", "code"]

    def __str__(self):
        return f"{self.name_zh} ({self.code})"


class CoachProfile(TimeStampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="coach_profile")
    squad_name = models.CharField("組別名稱", max_length=80, blank=True)
    specialties = models.CharField("專長", max_length=120, blank=True)
    certification = models.CharField("執照", max_length=120, blank=True)
    years_of_experience = models.PositiveSmallIntegerField("執教年資", default=0)

    class Meta:
        verbose_name = "教練檔案"
        verbose_name_plural = "教練檔案"

    def __str__(self):
        return f"教練 {self.user.get_full_name() or self.user.username}"

    @property
    def athlete_count(self):
        return self.athletes.count()


class AthleteProfile(TimeStampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="athlete_profile")
    coach = models.ForeignKey(
        CoachProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="athletes",
        verbose_name="所屬教練",
    )
    birth_date = models.DateField("出生日期")
    sex = models.CharField("性別", max_length=1, choices=Sex.choices)
    height_cm = models.DecimalField("身高 (cm)", max_digits=5, decimal_places=1)
    weight_kg = models.DecimalField("體重 (kg)", max_digits=5, decimal_places=1)
    primary_event = models.ForeignKey(
        Event, on_delete=models.PROTECT, related_name="primary_athletes", verbose_name="主項"
    )
    secondary_events = models.ManyToManyField(
        Event, blank=True, related_name="secondary_athletes", verbose_name="副項"
    )
    training_days_per_week = models.PositiveSmallIntegerField("每週訓練日數", default=5)
    strength_experience_years = models.DecimalField(
        "力量訓練年資", max_digits=3, decimal_places=1, default=0
    )
    status = models.CharField(
        "目前狀態", max_length=10, choices=AthleteStatus.choices, default=AthleteStatus.HEALTHY
    )
    school_or_club = models.CharField("學校/會所", max_length=100, blank=True)
    notes = models.TextField("備註", blank=True)

    class Meta:
        verbose_name = "運動員檔案"
        verbose_name_plural = "運動員檔案"
        ordering = ["user__username"]

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    @property
    def age(self):
        today = date.today()
        return (
            today.year
            - self.birth_date.year
            - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        )

    @property
    def latest_body_metric(self):
        return self.body_metrics.order_by("-date").first()

    @property
    def current_weight_kg(self):
        """優先取最新的體測紀錄，否則用 profile 上的值。"""
        latest = self.body_metrics.order_by("-date").first()
        return latest.weight_kg if latest and latest.weight_kg else self.weight_kg

    @property
    def bmi(self):
        h = float(self.height_cm) / 100
        return round(float(self.current_weight_kg) / (h * h), 1) if h else None

    def pb_for(self, event):
        return self.personal_bests.filter(event=event, is_current=True).first()

    @property
    def active_injuries(self):
        return self.injuries.exclude(status="RESOLVED")


class PersonalBest(TimeStampedModel):
    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="personal_bests"
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="personal_bests")
    mark = models.DecimalField("成績", max_digits=8, decimal_places=2, help_text="時間存秒，距離存公尺")
    wind = models.DecimalField("風速 (m/s)", max_digits=4, decimal_places=1, null=True, blank=True)
    date = models.DateField("創造日期")
    competition_name = models.CharField("賽事名稱", max_length=120, blank=True)
    is_current = models.BooleanField("目前最佳", default=True)

    class Meta:
        verbose_name = "個人最佳"
        verbose_name_plural = "個人最佳"
        unique_together = ("athlete", "event", "date")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.athlete} {self.event.code} {self.mark_display}"

    @property
    def mark_display(self):
        return format_mark(self.mark, self.event.unit)

    @property
    def is_better_is_lower(self):
        """時間項目：數字越小越好；距離/分數：越大越好。"""
        return self.event.unit == MeasureUnit.TIME

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_current:
            # 同項目只保留一筆 current
            PersonalBest.objects.filter(
                athlete=self.athlete, event=self.event, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)


class BodyMetricLog(TimeStampedModel):
    """一次體組成量測（InBody / Tanita 之類的身體組成磅）。

    最少只要有日期與體重就成立；其餘欄位量得到就填，量不到留空——
    不同型號的磅給的欄位不一樣，總覽頁只顯示有值的那幾格。
    """

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "手動輸入"
        IMPORT = "IMPORT", "檔案匯入"

    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="body_metrics"
    )
    date = models.DateField("日期")
    measured_at = models.TimeField("量測時間", null=True, blank=True)
    device = models.CharField("量測機型", max_length=40, blank=True, help_text="例：RD-545AS")

    # ------------------------------------------------------------ 全身數據
    weight_kg = models.DecimalField("體重 (kg)", max_digits=5, decimal_places=1)
    body_fat_pct = models.DecimalField(
        "體脂肪率 (%)", max_digits=4, decimal_places=1, null=True, blank=True
    )
    muscle_mass_kg = models.DecimalField(
        "肌肉量 (kg)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    muscle_mass_index = models.SmallIntegerField("肌肉量判定指數", null=True, blank=True)
    bmi = models.DecimalField("BMI", max_digits=4, decimal_places=1, null=True, blank=True)
    muscle_quality_score = models.SmallIntegerField("肌肉質量指數", null=True, blank=True)
    visceral_fat_level = models.DecimalField(
        "內臟脂肪等級", max_digits=4, decimal_places=1, null=True, blank=True
    )
    bone_mass_kg = models.DecimalField(
        "推定骨量 (kg)", max_digits=4, decimal_places=2, null=True, blank=True
    )
    body_water_pct = models.DecimalField(
        "體水分率 (%)", max_digits=4, decimal_places=1, null=True, blank=True
    )
    bmr_kcal = models.PositiveIntegerField("基礎代謝量 (kcal)", null=True, blank=True)
    metabolic_age = models.PositiveSmallIntegerField("體內年齡 (歲)", null=True, blank=True)

    # -------------------------------------------------------- 部位肌肉量
    muscle_arm_r = models.DecimalField(
        "右上肢肌肉量 (kg)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    muscle_arm_l = models.DecimalField(
        "左上肢肌肉量 (kg)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    muscle_leg_r = models.DecimalField(
        "右腳肌肉量 (kg)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    muscle_leg_l = models.DecimalField(
        "左腳肌肉量 (kg)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    muscle_trunk = models.DecimalField(
        "軀幹部位肌肉量 (kg)", max_digits=5, decimal_places=2, null=True, blank=True
    )

    # -------------------------------------------------------- 部位脂肪率
    fat_arm_r = models.DecimalField(
        "右上肢脂肪率 (%)", max_digits=4, decimal_places=1, null=True, blank=True
    )
    fat_arm_l = models.DecimalField(
        "左上肢脂肪率 (%)", max_digits=4, decimal_places=1, null=True, blank=True
    )
    fat_leg_r = models.DecimalField(
        "右腳脂肪率 (%)", max_digits=4, decimal_places=1, null=True, blank=True
    )
    fat_leg_l = models.DecimalField(
        "左腳脂肪率 (%)", max_digits=4, decimal_places=1, null=True, blank=True
    )
    fat_trunk = models.DecimalField(
        "軀幹部位脂肪率 (%)", max_digits=4, decimal_places=1, null=True, blank=True
    )

    # ---------------------------------------------------- 部位肌肉品質點數
    mq_arm_r = models.SmallIntegerField("右上肢肌肉品質點數", null=True, blank=True)
    mq_arm_l = models.SmallIntegerField("左上肢肌肉品質點數", null=True, blank=True)
    mq_leg_r = models.SmallIntegerField("右腳肌肉品質點數", null=True, blank=True)
    mq_leg_l = models.SmallIntegerField("左腳肌肉品質點數", null=True, blank=True)
    mba_rating = models.CharField("MBA 判定", max_length=20, blank=True)

    # -------------------------------------------------------------- 其他
    resting_hr = models.PositiveSmallIntegerField("靜息心率", null=True, blank=True)
    hrv = models.PositiveSmallIntegerField("HRV (ms)", null=True, blank=True)
    note = models.TextField("備註", blank=True)
    source = models.CharField(
        "來源", max_length=10, choices=Source.choices, default=Source.MANUAL
    )
    source_file = models.CharField("匯入檔名", max_length=120, blank=True)

    class Meta:
        verbose_name = "體組成紀錄"
        verbose_name_plural = "體組成紀錄"
        unique_together = ("athlete", "date")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.athlete} {self.date} {self.weight_kg}kg"

    # ------------------------------------------------------------ 衍生數值

    @property
    def bmi_value(self):
        """磅有給就用磅的，沒有就用身高換算。"""
        if self.bmi is not None:
            return float(self.bmi)
        h = float(self.athlete.height_cm) / 100
        return round(float(self.weight_kg) / (h * h), 1) if h else None

    @property
    def fat_mass_kg(self):
        if self.body_fat_pct is None:
            return None
        return round(float(self.weight_kg) * float(self.body_fat_pct) / 100, 1)

    @property
    def lean_mass_kg(self):
        fat = self.fat_mass_kg
        return round(float(self.weight_kg) - fat, 1) if fat is not None else None

    @property
    def segments(self):
        """部位資料整理成表格用的列：(部位, 肌肉量, 脂肪率, 肌肉品質點數)。"""
        rows = [
            ("右上肢", self.muscle_arm_r, self.fat_arm_r, self.mq_arm_r),
            ("左上肢", self.muscle_arm_l, self.fat_arm_l, self.mq_arm_l),
            ("右腳", self.muscle_leg_r, self.fat_leg_r, self.mq_leg_r),
            ("左腳", self.muscle_leg_l, self.fat_leg_l, self.mq_leg_l),
            ("軀幹", self.muscle_trunk, self.fat_trunk, None),
        ]
        return [
            {"part": part, "muscle": muscle, "fat": fat, "quality": quality}
            for part, muscle, fat, quality in rows
            if muscle is not None or fat is not None or quality is not None
        ]

    @property
    def has_segments(self):
        return bool(self.segments)

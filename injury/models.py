from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import AthleteProfile
from core.models import TimeStampedModel
from training.models import Exercise

PAIN_VALIDATORS = [MinValueValidator(0), MaxValueValidator(10)]


class BodyPart(models.TextChoices):
    HAMSTRING = "HAMSTRING", "膕繩肌"
    QUAD = "QUAD", "股四頭肌"
    CALF = "CALF", "小腿"
    ACHILLES = "ACHILLES", "阿基里斯腱"
    PLANTAR = "PLANTAR", "足底"
    KNEE = "KNEE", "膝關節"
    ANKLE = "ANKLE", "踝關節"
    HIP = "HIP", "髖關節"
    GROIN = "GROIN", "鼠蹊"
    LOW_BACK = "LOW_BACK", "下背"
    SHOULDER = "SHOULDER", "肩部"
    SHIN = "SHIN", "脛骨"
    FOOT = "FOOT", "足部"


class Side(models.TextChoices):
    LEFT = "LEFT", "左"
    RIGHT = "RIGHT", "右"
    BILATERAL = "BILATERAL", "雙側"
    NA = "NA", "不適用"


class InjuryType(models.TextChoices):
    STRAIN = "STRAIN", "肌肉拉傷"
    SPRAIN = "SPRAIN", "韌帶扭傷"
    TENDINOPATHY = "TENDINOPATHY", "肌腱病變/肌腱炎"
    PERIOSTITIS = "PERIOSTITIS", "骨膜炎"
    STRESS_FRACTURE = "STRESS_FRACTURE", "應力性骨折"
    CONTUSION = "CONTUSION", "挫傷"
    OVERUSE = "OVERUSE", "過度使用"
    OTHER = "OTHER", "其他"


class InjuryStatus(models.TextChoices):
    ACUTE = "ACUTE", "急性期"
    REHAB = "REHAB", "復健中"
    RETURN_TO_RUN = "RETURN_TO_RUN", "回歸跑動"
    RESOLVED = "RESOLVED", "已康復"


class TreatmentStage(models.TextChoices):
    """治療方向的四個階段——決定現在該做什麼、什麼時候可以往下一步。"""

    ASSESS = "ASSESS", "評估診斷"
    RELIEVE = "RELIEVE", "消炎止痛"
    RESTORE = "RESTORE", "恢復功能"
    RECONDITION = "RECONDITION", "重建體能"


class TreatmentType(models.TextChoices):
    DOCTOR = "DOCTOR", "醫生診症"
    IMAGING = "IMAGING", "影像檢查"
    PHYSIO = "PHYSIO", "物理治療"
    MANUAL = "MANUAL", "手法治療 / 推拿"
    ACUPUNCTURE = "ACUPUNCTURE", "針灸 / 針刺"
    ICE = "ICE", "冰敷 / 冷療"
    HEAT = "HEAT", "熱敷"
    STRETCH = "STRETCH", "伸展 / 筋膜放鬆"
    STRENGTH = "STRENGTH", "復健強化訓練"
    TAPING = "TAPING", "貼紮 / 護具"
    MEDICATION = "MEDICATION", "藥物"
    SURGERY = "SURGERY", "手術"
    REST = "REST", "完全休息"
    OTHER = "OTHER", "其他"


class TreatmentEffect(models.IntegerChoices):
    MUCH_BETTER = 1, "明顯改善"
    BETTER = 2, "略有改善"
    SAME = 3, "無變化"
    WORSE = 4, "變差"


class Injury(TimeStampedModel):
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE, related_name="injuries")
    body_part = models.CharField("部位", max_length=20, choices=BodyPart.choices)
    side = models.CharField("側別", max_length=10, choices=Side.choices, default=Side.NA)
    injury_type = models.CharField("類型", max_length=20, choices=InjuryType.choices)
    mechanism = models.TextField("受傷機制", blank=True, help_text="例：加速期第 3 步、落地瞬間、過度使用")
    onset_date = models.DateField("受傷日期")
    severity = models.PositiveSmallIntegerField(
        "嚴重度 (1-4)",
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(4)],
        help_text="1: <7天 2: 7-28天 3: >28天 4: 賽季報銷",
    )
    status = models.CharField(
        "狀態", max_length=15, choices=InjuryStatus.choices, default=InjuryStatus.ACUTE
    )
    expected_return_date = models.DateField("預計回歸日期", null=True, blank=True)
    diagnosis = models.TextField("診斷", blank=True)
    practitioner = models.CharField("醫療人員", max_length=80, blank=True)
    treatment_direction = models.TextField(
        "治療方向",
        blank=True,
        help_text="這個傷要往哪個方向處理：目標、主要手段、下一步條件",
    )
    treatment_status = models.CharField(
        "治療進度", max_length=15, choices=TreatmentStage.choices, default=TreatmentStage.ASSESS
    )
    next_review_date = models.DateField("下次覆診 / 檢視", null=True, blank=True)

    class Meta:
        verbose_name = "傷患"
        verbose_name_plural = "傷患"
        ordering = ["-onset_date"]
        indexes = [models.Index(fields=["athlete", "status"])]

    def __str__(self):
        return f"{self.athlete} {self.get_side_display()}{self.get_body_part_display()} {self.get_injury_type_display()}"

    @property
    def is_active(self):
        return self.status != InjuryStatus.RESOLVED

    @property
    def days_since_onset(self):
        from datetime import date

        return (date.today() - self.onset_date).days

    @property
    def latest_pain(self):
        return self.pain_logs.order_by("-date").first()

    @property
    def current_pain_level(self):
        log = self.latest_pain
        return log.pain_during_activity if log else None

    def pain_trend(self, days=28):
        """疼痛趨勢資料（給折線圖）。"""
        from datetime import date, timedelta

        since = date.today() - timedelta(days=days)
        return list(
            self.pain_logs.filter(date__gte=since)
            .order_by("date")
            .values("date", "pain_at_rest", "pain_during_activity")
        )


class TreatmentLog(TimeStampedModel):
    """一次治療紀錄。

    傷患管理原本只記「痛不痛」，但教練真正要追的是「做了什麼、有沒有用」——
    所以每一筆都要求填手段與成效，累積起來就看得出哪個方向有效。
    """

    injury = models.ForeignKey(Injury, on_delete=models.CASCADE, related_name="treatments")
    date = models.DateField("治療日期")
    treatment_type = models.CharField("治療手段", max_length=15, choices=TreatmentType.choices)
    provider = models.CharField(
        "治療者 / 機構", max_length=100, blank=True, help_text="例：陳physio、XX 骨科"
    )
    content = models.TextField("處理內容", blank=True, help_text="做了什麼、劑量或時間")
    effect = models.PositiveSmallIntegerField(
        "成效", choices=TreatmentEffect.choices, default=TreatmentEffect.SAME
    )
    pain_after = models.PositiveSmallIntegerField(
        "治療後疼痛 (0-10)", null=True, blank=True, validators=PAIN_VALIDATORS
    )
    next_step = models.CharField("下一步", max_length=200, blank=True)
    cost_hkd = models.DecimalField("費用 (HKD)", max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "治療紀錄"
        verbose_name_plural = "治療紀錄"
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["injury", "date"])]

    def __str__(self):
        return f"{self.injury.get_body_part_display()} {self.date} {self.get_treatment_type_display()}"

    @property
    def is_improving(self):
        return self.effect in (TreatmentEffect.MUCH_BETTER, TreatmentEffect.BETTER)


class PainLog(TimeStampedModel):
    injury = models.ForeignKey(Injury, on_delete=models.CASCADE, related_name="pain_logs")
    date = models.DateField("日期")
    pain_at_rest = models.PositiveSmallIntegerField("靜態疼痛 (0-10)", default=0, validators=PAIN_VALIDATORS)
    pain_during_activity = models.PositiveSmallIntegerField(
        "活動時疼痛 (0-10)", default=0, validators=PAIN_VALIDATORS
    )
    swelling = models.BooleanField("腫脹", default=False)
    rom_limited = models.BooleanField("活動度受限", default=False)
    note = models.TextField("備註", blank=True)

    class Meta:
        verbose_name = "疼痛日誌"
        verbose_name_plural = "疼痛日誌"
        unique_together = ("injury", "date")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.injury.get_body_part_display()} {self.date} 痛{self.pain_during_activity}/10"

    @property
    def blocks_high_intensity(self):
        """活動時疼痛 ≥ 6 → 封鎖當日高強度訓練。"""
        return self.pain_during_activity >= 6


class RehabPhase(models.TextChoices):
    PROTECTION = "PROTECTION", "保護期"
    LOADING = "LOADING", "負荷期"
    STRENGTH = "STRENGTH", "力量期"
    RTP = "RTP", "回歸運動期"


class RehabProtocol(TimeStampedModel):
    injury = models.ForeignKey(Injury, on_delete=models.CASCADE, related_name="protocols")
    phase = models.CharField("復健階段", max_length=15, choices=RehabPhase.choices)
    start_date = models.DateField("開始日期")
    progression_criteria = models.TextField("進階條件", blank=True)
    is_current = models.BooleanField("目前階段", default=True)

    class Meta:
        verbose_name = "復健方案"
        verbose_name_plural = "復健方案"
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.injury} - {self.get_phase_display()}"


class RehabExercise(models.Model):
    protocol = models.ForeignKey(RehabProtocol, on_delete=models.CASCADE, related_name="exercises")
    exercise_name = models.CharField("動作名稱", max_length=100)
    sets = models.PositiveSmallIntegerField("組數", default=3)
    reps = models.CharField("次數/時間", max_length=40, default="10")
    frequency_per_week = models.PositiveSmallIntegerField("每週頻率", default=5)
    note = models.CharField("備註", max_length=150, blank=True)

    class Meta:
        verbose_name = "復健動作"
        verbose_name_plural = "復健動作"

    def __str__(self):
        return f"{self.exercise_name} {self.sets}×{self.reps}"


class ExerciseModification(models.Model):
    """
    替代動作對照表 — 教練核心工具。
    當運動員某部位受傷時，把原動作替換為不加重傷勢的替代動作。
    """

    original_exercise = models.ForeignKey(
        Exercise, on_delete=models.CASCADE, related_name="modifications", verbose_name="原動作"
    )
    substitute_exercise = models.ForeignKey(
        Exercise,
        on_delete=models.CASCADE,
        related_name="substitutes_for",
        null=True,
        blank=True,
        verbose_name="替代動作",
    )
    substitute_name = models.CharField(
        "替代動作名稱", max_length=100, blank=True, help_text="若替代動作不在動作字典中，直接填名稱"
    )
    contraindicated_body_parts = models.JSONField(
        "禁忌部位", default=list, help_text='例：["HAMSTRING", "LOW_BACK"]'
    )
    max_pain_level = models.PositiveSmallIntegerField(
        "可執行的最高疼痛值", default=3, validators=PAIN_VALIDATORS
    )
    rationale = models.TextField("原因", blank=True)

    class Meta:
        verbose_name = "替代動作"
        verbose_name_plural = "替代動作"

    def __str__(self):
        return f"{self.original_exercise.name_zh} → {self.substitute_display}"

    @property
    def substitute_display(self):
        return (
            self.substitute_exercise.name_zh
            if self.substitute_exercise
            else self.substitute_name or "（暫停此動作）"
        )

    def applies_to(self, body_part):
        return body_part in (self.contraindicated_body_parts or [])

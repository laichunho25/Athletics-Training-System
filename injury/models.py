from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.models import AthleteProfile
from core.models import TimeStampedModel
from training.models import Exercise

PAIN_VALIDATORS = [MinValueValidator(0), MaxValueValidator(10)]


class BodyPart(models.TextChoices):
    HAMSTRING = "HAMSTRING", _("膕繩肌")
    QUAD = "QUAD", _("股四頭肌")
    CALF = "CALF", _("小腿")
    ACHILLES = "ACHILLES", _("阿基里斯腱")
    PLANTAR = "PLANTAR", _("足底")
    KNEE = "KNEE", _("膝關節")
    ANKLE = "ANKLE", _("踝關節")
    HIP = "HIP", _("髖關節")
    GROIN = "GROIN", _("鼠蹊")
    LOW_BACK = "LOW_BACK", _("下背")
    SHOULDER = "SHOULDER", _("肩部")
    SHIN = "SHIN", _("脛骨")
    FOOT = "FOOT", _("足部")


class Side(models.TextChoices):
    LEFT = "LEFT", _("左")
    RIGHT = "RIGHT", _("右")
    BILATERAL = "BILATERAL", _("雙側")
    NA = "NA", _("不適用")


class InjuryType(models.TextChoices):
    STRAIN = "STRAIN", _("肌肉拉傷")
    SPRAIN = "SPRAIN", _("韌帶扭傷")
    TENDINOPATHY = "TENDINOPATHY", _("肌腱病變/肌腱炎")
    PERIOSTITIS = "PERIOSTITIS", _("骨膜炎")
    STRESS_FRACTURE = "STRESS_FRACTURE", _("應力性骨折")
    CONTUSION = "CONTUSION", _("挫傷")
    OVERUSE = "OVERUSE", _("過度使用")
    OTHER = "OTHER", _("其他")


class InjuryStatus(models.TextChoices):
    ACUTE = "ACUTE", _("急性期")
    REHAB = "REHAB", _("復健中")
    RETURN_TO_RUN = "RETURN_TO_RUN", _("回歸跑動")
    RESOLVED = "RESOLVED", _("已康復")


class TrainingMode(models.TextChoices):
    """受傷期間這個人到底怎麼練——教練與運動員每天要看的就是這一格。

    分成五級是因為實務上「能不能練」從來不是是非題：
    完全休養與完全訓練之間，大部分時間都落在中間那三級。
    """

    FULL_REST = "FULL_REST", _("完全休養")
    REHAB_ONLY = "REHAB_ONLY", _("只做康復")
    MODIFIED = "MODIFIED", _("調整訓練")
    GRADUAL = "GRADUAL", _("漸進回歸")
    FULL = "FULL", _("完全訓練")


#: 每一級的白話說明：今天可以做什麼、不可以做什麼。
TRAINING_MODE_GUIDE = {
    TrainingMode.FULL_REST: {
        "do": _("完全停練，處理發炎與疼痛；可做不牽涉患部的日常活動"),
        "avoid": _("任何會誘發疼痛的動作、負重與衝擊"),
        "tone": "red",
    },
    TrainingMode.REHAB_ONLY: {
        "do": _("只做復健動作與不痛範圍的活動度訓練；上肢／對側可維持體能"),
        "avoid": _("專項課表、跑跳與最大負荷"),
        "tone": "red",
    },
    TrainingMode.MODIFIED: {
        "do": _("照常出席，患部動作換成替代動作，強度與總量都先降一級"),
        "avoid": _("衝刺、增強式、患部最大力量"),
        "tone": "yellow",
    },
    TrainingMode.GRADUAL: {
        "do": _("分級加回專項：慢跑 → 節奏跑 → 加速 → 全速，每次只加一項"),
        "avoid": _("一次同時加強度又加量；比賽與計時測驗"),
        "tone": "blue",
    },
    TrainingMode.FULL: {
        "do": _("完整課表，維持復健動作作為預防"),
        "avoid": _("突然把訓練量拉回受傷前的水平"),
        "tone": "green",
    },
}


class TreatmentStage(models.TextChoices):
    """治療方向的四個階段——決定現在該做什麼、什麼時候可以往下一步。"""

    ASSESS = "ASSESS", _("評估診斷")
    RELIEVE = "RELIEVE", _("消炎止痛")
    RESTORE = "RESTORE", _("恢復功能")
    RECONDITION = "RECONDITION", _("重建體能")


class TreatmentType(models.TextChoices):
    DOCTOR = "DOCTOR", _("醫生診症")
    IMAGING = "IMAGING", _("影像檢查")
    PHYSIO = "PHYSIO", _("物理治療")
    MANUAL = "MANUAL", _("手法治療 / 推拿")
    ACUPUNCTURE = "ACUPUNCTURE", _("針灸 / 針刺")
    ICE = "ICE", _("冰敷 / 冷療")
    HEAT = "HEAT", _("熱敷")
    STRETCH = "STRETCH", _("伸展 / 筋膜放鬆")
    STRENGTH = "STRENGTH", _("復健強化訓練")
    TAPING = "TAPING", _("貼紮 / 護具")
    MEDICATION = "MEDICATION", _("藥物")
    SURGERY = "SURGERY", _("手術")
    REST = "REST", _("完全休息")
    OTHER = "OTHER", _("其他")


class TreatmentEffect(models.IntegerChoices):
    MUCH_BETTER = 1, _("明顯改善")
    BETTER = 2, _("略有改善")
    SAME = 3, _("無變化")
    WORSE = 4, _("變差")


class Injury(TimeStampedModel):
    athlete = models.ForeignKey(AthleteProfile, on_delete=models.CASCADE, related_name="injuries")
    body_part = models.CharField(_("部位"), max_length=20, choices=BodyPart.choices)
    side = models.CharField(_("側別"), max_length=10, choices=Side.choices, default=Side.NA)
    injury_type = models.CharField(_("類型"), max_length=20, choices=InjuryType.choices)
    mechanism = models.TextField(_("受傷機制"), blank=True, help_text=_("例：加速期第 3 步、落地瞬間、過度使用"))
    onset_date = models.DateField(_("受傷日期"))
    severity = models.PositiveSmallIntegerField(
        _("嚴重度 (1-4)"),
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(4)],
        help_text=_("1: <7天 2: 7-28天 3: >28天 4: 賽季報銷"),
    )
    status = models.CharField(
        _("狀態"), max_length=15, choices=InjuryStatus.choices, default=InjuryStatus.ACUTE
    )
    expected_return_date = models.DateField(_("預計回歸日期"), null=True, blank=True)
    diagnosis = models.TextField(_("診斷"), blank=True)
    practitioner = models.CharField(_("醫療人員"), max_length=80, blank=True)
    treatment_direction = models.TextField(
        _("治療方向"),
        blank=True,
        help_text=_("這個傷要往哪個方向處理：目標、主要手段、下一步條件"),
    )
    treatment_status = models.CharField(
        _("治療進度"), max_length=15, choices=TreatmentStage.choices, default=TreatmentStage.ASSESS
    )
    next_review_date = models.DateField(_("下次覆診 / 檢視"), null=True, blank=True)
    training_mode = models.CharField(
        _("訓練處理方式"),
        max_length=15,
        choices=TrainingMode.choices,
        default=TrainingMode.MODIFIED,
        help_text=_("今天這個人怎麼練：完全休養 / 只做康復 / 調整訓練 / 漸進回歸 / 完全訓練"),
    )
    training_note = models.CharField(
        _("訓練備註"),
        max_length=200,
        blank=True,
        help_text=_("給教練看的一句話，例：只做上肢與核心，禁跑跳"),
    )
    rtp_progress = models.JSONField(
        _("RTP 已達成條件"), default=list, blank=True, help_text=_("已勾選的 Return-to-Play 條件索引")
    )

    class Meta:
        verbose_name = _("傷患")
        verbose_name_plural = _("傷患")
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

    @property
    def mode_guide(self):
        return TRAINING_MODE_GUIDE.get(self.training_mode, {})

    @property
    def priority(self):
        """排序用：越大越該先看。急性期與高疼痛排前面。"""
        status_weight = {
            InjuryStatus.ACUTE: 300,
            InjuryStatus.REHAB: 200,
            InjuryStatus.RETURN_TO_RUN: 100,
            InjuryStatus.RESOLVED: 0,
        }
        return status_weight.get(self.status, 0) + (self.current_pain_level or 0) * 10 + self.severity

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
    date = models.DateField(_("治療日期"))
    treatment_type = models.CharField(_("治療手段"), max_length=15, choices=TreatmentType.choices)
    provider = models.CharField(
        _("治療者 / 機構"), max_length=100, blank=True, help_text=_("例：陳physio、XX 骨科")
    )
    content = models.TextField(_("處理內容"), blank=True, help_text=_("做了什麼、劑量或時間"))
    effect = models.PositiveSmallIntegerField(
        _("成效"), choices=TreatmentEffect.choices, default=TreatmentEffect.SAME
    )
    pain_after = models.PositiveSmallIntegerField(
        _("治療後疼痛 (0-10)"), null=True, blank=True, validators=PAIN_VALIDATORS
    )
    next_step = models.CharField(_("下一步"), max_length=200, blank=True)
    cost_hkd = models.DecimalField(_("費用 (HKD)"), max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = _("治療紀錄")
        verbose_name_plural = _("治療紀錄")
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["injury", "date"])]

    def __str__(self):
        return f"{self.injury.get_body_part_display()} {self.date} {self.get_treatment_type_display()}"

    @property
    def is_improving(self):
        return self.effect in (TreatmentEffect.MUCH_BETTER, TreatmentEffect.BETTER)


class DayAction(models.TextChoices):
    """今天這一處傷，練還是不練——每日追蹤時當場就要下的決定。

    痛楚數字本身不會告訴教練今天怎麼辦，所以每天記痛的同時一併記下決定，
    回頭看趨勢時才知道當時是「痛但照練」還是「痛所以停」。
    """

    AS_USUAL = "AS_USUAL", _("可照常訓練")
    REDUCE = "REDUCE", _("減低訓練量")
    CHANGE = "CHANGE", _("改變訓練方向")
    REST = "REST", _("完全休息")


class PainLog(TimeStampedModel):
    injury = models.ForeignKey(Injury, on_delete=models.CASCADE, related_name="pain_logs")
    date = models.DateField(_("日期"))
    pain_at_rest = models.PositiveSmallIntegerField(_("靜態疼痛 (0-10)"), default=0, validators=PAIN_VALIDATORS)
    pain_during_activity = models.PositiveSmallIntegerField(
        _("活動時疼痛 (0-10)"), default=0, validators=PAIN_VALIDATORS
    )
    pain_before = models.PositiveSmallIntegerField(
        _("今早／運動前疼痛 (0-10)"), null=True, blank=True, validators=PAIN_VALIDATORS
    )
    pain_after_session = models.PositiveSmallIntegerField(
        _("運動結束後疼痛 (0-10)"), null=True, blank=True, validators=PAIN_VALIDATORS
    )
    load_intensity = models.PositiveSmallIntegerField(
        _("今日強度（幾分力 0-10）"),
        null=True,
        blank=True,
        validators=PAIN_VALIDATORS,
        help_text=_("用幾分力做：投球力度、跑速、重量。10 = 全力"),
    )
    load_volume = models.CharField(
        _("今日總量"),
        max_length=120,
        blank=True,
        help_text=_("做了多少：例 投 30 球 / 慢跑 3km / 深蹲 60kg×3×8"),
    )
    day_action = models.CharField(
        _("今日決定"),
        max_length=10,
        choices=DayAction.choices,
        blank=True,
        help_text=_("照常訓練 / 減低訓練量 / 改變訓練方向 / 完全休息"),
    )
    swelling = models.BooleanField(_("腫脹"), default=False)
    rom_limited = models.BooleanField(_("活動度受限"), default=False)
    note = models.TextField(_("備註"), blank=True)

    class Meta:
        verbose_name = _("疼痛日誌")
        verbose_name_plural = _("疼痛日誌")
        unique_together = ("injury", "date")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.injury.get_body_part_display()} {self.date} 痛{self.pain_during_activity}/10"

    @property
    def blocks_high_intensity(self):
        """活動時疼痛 ≥ 6 → 封鎖當日高強度訓練。"""
        return self.pain_during_activity >= 6


class RehabPhase(models.TextChoices):
    PROTECTION = "PROTECTION", _("保護期")
    LOADING = "LOADING", _("負荷期")
    STRENGTH = "STRENGTH", _("力量期")
    RTP = "RTP", _("回歸運動期")


class RehabProtocol(TimeStampedModel):
    injury = models.ForeignKey(Injury, on_delete=models.CASCADE, related_name="protocols")
    phase = models.CharField(_("復健階段"), max_length=15, choices=RehabPhase.choices)
    start_date = models.DateField(_("開始日期"))
    progression_criteria = models.TextField(_("進階條件"), blank=True)
    is_current = models.BooleanField(_("目前階段"), default=True)

    class Meta:
        verbose_name = _("復健方案")
        verbose_name_plural = _("復健方案")
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.injury} - {self.get_phase_display()}"


class RehabExercise(models.Model):
    protocol = models.ForeignKey(RehabProtocol, on_delete=models.CASCADE, related_name="exercises")
    exercise_name = models.CharField(_("動作名稱"), max_length=100)
    sets = models.PositiveSmallIntegerField(_("組數"), default=3)
    reps = models.CharField(_("次數/時間"), max_length=40, default="10")
    frequency_per_week = models.PositiveSmallIntegerField(_("每週頻率"), default=5)
    note = models.CharField(_("備註"), max_length=150, blank=True)

    class Meta:
        verbose_name = _("復健動作")
        verbose_name_plural = _("復健動作")

    def __str__(self):
        return f"{self.exercise_name} {self.sets}×{self.reps}"


class ExerciseModification(models.Model):
    """
    替代動作對照表 — 教練核心工具。
    當運動員某部位受傷時，把原動作替換為不加重傷勢的替代動作。
    """

    original_exercise = models.ForeignKey(
        Exercise, on_delete=models.CASCADE, related_name="modifications", verbose_name=_("原動作")
    )
    substitute_exercise = models.ForeignKey(
        Exercise,
        on_delete=models.CASCADE,
        related_name="substitutes_for",
        null=True,
        blank=True,
        verbose_name=_("替代動作"),
    )
    substitute_name = models.CharField(
        _("替代動作名稱"), max_length=100, blank=True, help_text=_("若替代動作不在動作字典中，直接填名稱")
    )
    contraindicated_body_parts = models.JSONField(
        _("禁忌部位"), default=list, help_text=_('例：["HAMSTRING", "LOW_BACK"]')
    )
    max_pain_level = models.PositiveSmallIntegerField(
        _("可執行的最高疼痛值"), default=3, validators=PAIN_VALIDATORS
    )
    rationale = models.TextField(_("原因"), blank=True)

    class Meta:
        verbose_name = _("替代動作")
        verbose_name_plural = _("替代動作")

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

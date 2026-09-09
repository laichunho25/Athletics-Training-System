from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.models import AthleteProfile
from core.models import TimeStampedModel, bilingual_name
from planning.models import TrainingSession

RPE_VALIDATORS = [MinValueValidator(1), MaxValueValidator(10)]


# ---------------------------------------------------------------- 田徑專項


class Surface(models.TextChoices):
    TRACK = "TRACK", _("田徑場")
    GRASS = "GRASS", _("草地")
    HILL = "HILL", _("斜坡")
    TREADMILL = "TREADMILL", _("跑步機")
    ROAD = "ROAD", _("路跑")
    SAND = "SAND", _("沙地")


class TrackSet(TimeStampedModel):
    session = models.ForeignKey(
        TrainingSession, on_delete=models.CASCADE, related_name="track_sets"
    )
    order = models.PositiveSmallIntegerField(_("排序"), default=1)
    description = models.CharField(_("描述"), max_length=150, help_text=_("例：6 × 200m"))
    distance_m = models.PositiveIntegerField(_("單趟距離 (m)"))
    reps = models.PositiveSmallIntegerField(_("趟數"), default=1)
    sets = models.PositiveSmallIntegerField(_("組數"), default=1)
    target_time_sec = models.DecimalField(
        _("目標時間 (秒)"), max_digits=7, decimal_places=2, null=True, blank=True
    )
    actual_time_sec = models.DecimalField(
        _("實際平均時間 (秒)"), max_digits=7, decimal_places=2, null=True, blank=True
    )
    rest_between_reps_sec = models.PositiveIntegerField(_("趟間休息 (秒)"), default=0)
    rest_between_sets_sec = models.PositiveIntegerField(_("組間休息 (秒)"), default=0)
    intensity_pct = models.DecimalField(
        _("強度 (% PB)"), max_digits=5, decimal_places=1, null=True, blank=True
    )
    avg_hr = models.PositiveSmallIntegerField(_("平均心率"), null=True, blank=True)
    max_hr = models.PositiveSmallIntegerField(_("最高心率"), null=True, blank=True)
    rpe = models.PositiveSmallIntegerField(
        "RPE (1-10)", null=True, blank=True, validators=RPE_VALIDATORS
    )
    technical_focus = models.TextField(_("技術重點"), blank=True)
    surface = models.CharField(_("場地"), max_length=10, choices=Surface.choices, default=Surface.TRACK)
    spikes_used = models.BooleanField(_("穿釘鞋"), default=False)

    class Meta:
        verbose_name = _("專項訓練組")
        verbose_name_plural = _("專項訓練組")
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
    rep_number = models.PositiveSmallIntegerField(_("第幾趟"))
    time_sec = models.DecimalField(_("時間 (秒)"), max_digits=7, decimal_places=2)
    note = models.CharField(_("備註"), max_length=120, blank=True)

    class Meta:
        verbose_name = _("分趟成績")
        verbose_name_plural = _("分趟成績")
        unique_together = ("track_set", "rep_number")
        ordering = ["rep_number"]

    def __str__(self):
        return f"#{self.rep_number} {self.time_sec}s"


# ---------------------------------------------------------------- 力量訓練


class ExerciseCategory(models.TextChoices):
    SQUAT = "SQUAT", _("蹲系")
    HINGE = "HINGE", _("髖鉸鏈")
    PUSH = "PUSH", _("推")
    PULL = "PULL", _("拉")
    OLYMPIC = "OLYMPIC", _("奧舉")
    PLYO = "PLYO", _("增強式")
    CORE = "CORE", _("核心")
    UNILATERAL = "UNILATERAL", _("單邊")
    ACCESSORY = "ACCESSORY", _("輔助")
    REHAB = "REHAB", _("復健")


class OneRMFormula(models.TextChoices):
    EPLEY = "EPLEY", "Epley"
    BRZYCKI = "BRZYCKI", "Brzycki"
    DIRECT = "DIRECT", _("實測")


class Exercise(models.Model):
    code = models.CharField(_("代碼"), max_length=30, unique=True)
    name_zh = models.CharField(_("中文名稱"), max_length=60)
    name_en = models.CharField(_("英文名稱"), max_length=80)
    category = models.CharField(_("分類"), max_length=12, choices=ExerciseCategory.choices)
    is_measured_by_1rm = models.BooleanField(_("以 1RM 計算強度"), default=True)
    is_plyometric = models.BooleanField(_("增強式動作"), default=False)
    primary_muscles = models.CharField(_("主要肌群"), max_length=120, blank=True)
    video_url = models.URLField(_("示範影片"), blank=True)

    class Meta:
        verbose_name = _("力量動作")
        verbose_name_plural = _("力量動作")
        ordering = ["category", "name_zh"]

    def __str__(self):
        return f"{self.name_zh} ({self.code})"

    @property
    def display_name(self):
        """中文（English）；介面切英文時只留英文名。"""
        return bilingual_name(self.name_zh, self.name_en)


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
    test_date = models.DateField(_("測試日期"))
    is_estimated = models.BooleanField(_("推估值"), default=False)
    estimation_formula = models.CharField(
        _("推估公式"), max_length=10, choices=OneRMFormula.choices, default=OneRMFormula.DIRECT
    )

    class Meta:
        verbose_name = _("最大肌力 1RM")
        verbose_name_plural = _("最大肌力 1RM")
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
    order = models.PositiveSmallIntegerField(_("動作排序"), default=1)
    set_number = models.PositiveSmallIntegerField(_("第幾組"), default=1)
    reps = models.PositiveSmallIntegerField(_("次數"))
    weight_kg = models.DecimalField(_("重量 (kg)"), max_digits=6, decimal_places=2, default=0)
    target_1rm_pct = models.DecimalField(
        _("目標強度 (% 1RM)"), max_digits=5, decimal_places=1, null=True, blank=True
    )
    actual_1rm_pct = models.DecimalField(
        _("實際強度 (% 1RM)"), max_digits=5, decimal_places=1, null=True, blank=True, editable=False
    )
    tempo = models.CharField(_("節奏"), max_length=15, blank=True, help_text=_("例：3-1-X-0"))
    rest_sec = models.PositiveIntegerField(_("組間休息 (秒)"), default=120)
    rir = models.PositiveSmallIntegerField(
        _("RIR 保留次數"), null=True, blank=True, validators=[MaxValueValidator(10)]
    )
    rpe = models.PositiveSmallIntegerField(
        "RPE (1-10)", null=True, blank=True, validators=RPE_VALIDATORS
    )
    bar_velocity_ms = models.DecimalField(
        _("槓速 (m/s)"), max_digits=4, decimal_places=2, null=True, blank=True
    )
    is_failure = models.BooleanField(_("力竭"), default=False)
    note = models.CharField(_("備註"), max_length=150, blank=True)

    class Meta:
        verbose_name = _("力量訓練組")
        verbose_name_plural = _("力量訓練組")
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
    CMJ = "CMJ", _("反向跳 CMJ (cm)")
    SJ = "SJ", _("蹲跳 SJ (cm)")
    BROAD_JUMP = "BROAD_JUMP", _("立定跳遠 (cm)")
    GRIP = "GRIP", _("握力 (kg)")
    SPRINT_10M = "SPRINT_10M", _("10m 衝刺 (秒)")


class NeuromuscularTest(TimeStampedModel):
    """神經肌肉疲勞監控：與 7 日基線比較，跌幅 >10% 觸發警示。"""

    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="nm_tests"
    )
    date = models.DateField(_("日期"))
    test_type = models.CharField(_("測試項目"), max_length=15, choices=NeuromuscularTestType.choices)
    value = models.DecimalField(_("數值"), max_digits=7, decimal_places=2)
    unit = models.CharField(_("單位"), max_length=10, default="cm")
    note = models.CharField(_("備註"), max_length=150, blank=True)

    class Meta:
        verbose_name = _("神經肌肉測試")
        verbose_name_plural = _("神經肌肉測試")
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


# ------------------------------------------------------- 分區課表內容（活動）


class BlockType(models.TextChoices):
    """課表內容的四個層面。輸入時分區進行，輸出時依這個順序排。"""

    WARMUP = "WARMUP", _("熱身")
    MAIN = "MAIN", _("正課")
    SUPPLEMENT = "SUPPLEMENT", _("補充練習")
    RECOVERY = "RECOVERY", _("恢復練習")


#: 課表內容區塊的固定顯示順序
BLOCK_ORDER = [
    BlockType.WARMUP,
    BlockType.MAIN,
    BlockType.SUPPLEMENT,
    BlockType.RECOVERY,
]

#: 每一項活動都會出現的六個必要欄位（欄位名 → 顯示名）
ACTIVITY_FIELDS = [
    ("sets", "組數"),
    ("reps", "次數"),
    ("distance", "距離"),
    ("weight", "重量"),
    ("intensity", "強度"),
    ("rest", "休息時間"),
]


class ActivityCategory(models.TextChoices):
    """活動庫的分類。挑活動時先收窄到某一類，比在一長串裡面找快。"""

    WARMUP = "WARMUP", _("熱身")
    TRACK = "TRACK", _("田徑專項")
    UPPER = "UPPER", _("上肢力量")
    LOWER = "LOWER", _("下肢力量")
    CORE = "CORE", _("核心")
    PLYO = "PLYO", _("增強式／爆發力")
    # 增強式的東西多，四大部份分開列，挑動作時才不用在一長串裡找
    PLYO_BASIC = "PLYO_BASIC", _("增強式：基礎與進階跳躍")
    PLYO_TRACK = "PLYO_TRACK", _("增強式：田徑專項")
    PLYO_UPPER = "PLYO_UPPER", _("增強式：上肢與全身旋轉")
    PLYO_POGO = "PLYO_POGO", _("增強式：踝彈跳 Pogo")
    ACCESSORY = "ACCESSORY", _("輔助／預防傷害")
    RECOVERY = "RECOVERY", _("恢復／放鬆")


# ------------------------------------------------- 運動練習項目庫（分層目錄）


class LibraryStatus(models.TextChoices):
    """項目庫的審核狀態。

    教練、運動員、管理員都可以往庫裡加東西，但加進來的先是「待確認」，
    管理員按確認之後才會永久出現在項目庫、也才會出現在別人的挑選清單裡。
    """

    PENDING = "PENDING", _("待管理員確認")
    APPROVED = "APPROVED", _("已確認")
    REJECTED = "REJECTED", _("已退回")


class LibraryNode(TimeStampedModel):
    """項目庫三層目錄（運動種類 / 運動項目 / 訓練動作種類）的共同欄位。"""

    name = models.CharField(_("名稱"), max_length=60)
    name_en = models.CharField(_("英文名稱"), max_length=80, blank=True)
    note = models.CharField(_("說明"), max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(_("排序"), default=50)
    status = models.CharField(
        _("狀態"), max_length=10, choices=LibraryStatus.choices, default=LibraryStatus.APPROVED
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("建立者"),
    )
    is_builtin = models.BooleanField(_("系統內建"), default=False)

    class Meta:
        abstract = True

    def __str__(self):
        return self.name

    @property
    def is_approved(self):
        return self.status == LibraryStatus.APPROVED

    @property
    def display_name(self):
        return bilingual_name(self.name, self.name_en)


class SportType(LibraryNode):
    """運動種類：田徑、體能訓練、共通基礎…"""

    name = models.CharField(_("運動種類"), max_length=60, unique=True)

    class Meta:
        verbose_name = _("運動種類")
        verbose_name_plural = _("運動種類")
        ordering = ["order", "name"]


class Discipline(LibraryNode):
    """運動項目：田徑底下的短跑、跨欄；體能訓練底下的肌力與重量訓練…"""

    sport = models.ForeignKey(
        SportType, on_delete=models.CASCADE, related_name="disciplines", verbose_name=_("運動種類")
    )
    activity_category = models.CharField(
        _("預設分類"),
        max_length=12,
        choices=ActivityCategory.choices,
        default=ActivityCategory.WARMUP,
        help_text=_("這個項目底下新加的動作預設算哪一類——決定數據分析把它歸到哪個範疇"),
    )

    class Meta:
        verbose_name = _("運動項目")
        verbose_name_plural = _("運動項目")
        ordering = ["sport__order", "order", "name"]
        unique_together = ("sport", "name")

    @property
    def full_label(self):
        """運動種類 · 運動項目——下拉選單的分組標題用得到。"""
        return f"{self.sport.name} · {self.name}"


class MovementKind(LibraryNode):
    """訓練動作種類：熱身、專項動作、主課動作、輔助動作、恢復放鬆…

    這一層是各個運動項目共用的字彙——「熱身」不用在每個項目底下各建一次。
    """

    name = models.CharField(_("訓練動作種類"), max_length=60, unique=True)

    class Meta:
        verbose_name = _("訓練動作種類")
        verbose_name_plural = _("訓練動作種類")
        ordering = ["order", "name"]


class ActivityDefinition(TimeStampedModel):
    """訓練活動名稱庫。

    教練不用每次逐字打「Single Leg Hip Bridge」，從清單挑一個就會把預設的
    組數/次數/距離/重量/強度/休息時間一起帶進課表，之後再改成當天的數字。
    清單上沒有的活動，隨時按「新增活動」寫一個進去，下次就挑得到。
    """

    name = models.CharField(_("活動名稱"), max_length=120, unique=True)
    name_en = models.CharField(
        _("英文名稱"), max_length=120, blank=True,
        help_text=_("健身房器材與課表上常寫英文，兩個名字都留著才找得到"),
    )
    category = models.CharField(
        _("分類"), max_length=12, choices=ActivityCategory.choices,
        default=ActivityCategory.WARMUP,
    )
    default_block = models.CharField(
        _("預設區塊"), max_length=12, choices=BlockType.choices, default=BlockType.WARMUP
    )
    default_sets = models.CharField(_("預設組數"), max_length=30, blank=True)
    default_reps = models.CharField(_("預設次數"), max_length=30, blank=True)
    default_distance = models.CharField(_("預設距離"), max_length=30, blank=True)
    default_weight = models.CharField(_("預設重量"), max_length=40, blank=True)
    default_intensity = models.CharField(_("預設強度"), max_length=40, blank=True)
    default_rest = models.CharField(_("預設休息時間"), max_length=80, blank=True)
    default_key_points = models.TextField(_("預設訓練要點"), blank=True)
    note = models.CharField(_("說明"), max_length=200, blank=True)
    discipline = models.ForeignKey(
        Discipline,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
        verbose_name=_("運動項目"),
    )
    movement_kind = models.ForeignKey(
        MovementKind,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
        verbose_name=_("訓練動作種類"),
    )
    extra_disciplines = models.ManyToManyField(
        Discipline,
        blank=True,
        related_name="extra_activities",
        verbose_name=_("也屬於的運動項目"),
        help_text=_("同一個動作常常好幾種運動都在練（例：深蹲在田徑與體能訓練都用得到）"),
    )
    status = models.CharField(
        _("狀態"), max_length=10, choices=LibraryStatus.choices, default=LibraryStatus.APPROVED
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_definitions",
        verbose_name=_("建立者"),
    )
    is_builtin = models.BooleanField(_("系統內建"), default=False)
    use_count = models.PositiveIntegerField(_("使用次數"), default=0)
    is_active = models.BooleanField(_("可挑選"), default=True)

    class Meta:
        verbose_name = _("訓練活動")
        verbose_name_plural = _("訓練活動")
        ordering = ["category", "default_block", "-use_count", "name"]

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        """中文（英文）——挑活動的下拉裡兩個名字一起顯示。"""
        return bilingual_name(self.name, self.name_en)

    @property
    def is_approved(self):
        return self.status == LibraryStatus.APPROVED

    @property
    def all_disciplines(self):
        """這個動作掛在哪些運動項目底下（主項目排前面，不重複）。"""
        rows = [self.discipline] if self.discipline_id else []
        for extra in self.extra_disciplines.all():
            if extra.id != self.discipline_id:
                rows.append(extra)
        return rows

    def defaults_payload(self):
        """挑選時要帶進課表的預設值。"""
        return {
            "sets": self.default_sets,
            "reps": self.default_reps,
            "distance": self.default_distance,
            "weight": self.default_weight,
            "intensity": self.default_intensity,
            "rest": self.default_rest,
            "key_points": self.default_key_points,
        }


class SessionActivity(TimeStampedModel):
    """課表裡的一項活動：熱身 / 正課 / 補充 / 恢復 其中一區的一列。

    數值都用文字存，因為實際填的東西不一定是數字——重量可能是 body weight、
    休息可能是 walk back、強度可能是 80%-90%、次數可能是「左/右腳 15 次」。
    """

    session = models.ForeignKey(
        TrainingSession, on_delete=models.CASCADE, related_name="activities"
    )
    block = models.CharField(_("區塊"), max_length=12, choices=BlockType.choices)
    order = models.PositiveSmallIntegerField(_("排序"), default=1)
    definition = models.ForeignKey(
        ActivityDefinition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uses",
        verbose_name=_("來源活動"),
    )
    name = models.CharField(_("活動名稱"), max_length=120)
    sets = models.CharField(_("組數"), max_length=30, blank=True)
    reps = models.CharField(_("次數"), max_length=30, blank=True)
    distance = models.CharField(_("距離"), max_length=30, blank=True)
    weight = models.CharField(_("重量"), max_length=40, blank=True)
    intensity = models.CharField(_("強度"), max_length=40, blank=True)
    rest = models.CharField(_("休息時間"), max_length=80, blank=True)
    key_points = models.TextField(_("訓練要點"), blank=True)
    note = models.TextField(_("當日備注"), blank=True)
    satisfaction = models.PositiveSmallIntegerField(
        _("滿意度 (1-5)"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text=_("完成後自評對這項訓練的滿意程度"),
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="session_activities",
        verbose_name=_("寫入者"),
    )

    class Meta:
        verbose_name = _("課表活動")
        verbose_name_plural = _("課表活動")
        ordering = ["session", "block", "order", "id"]
        indexes = [models.Index(fields=["session", "block", "order"])]

    def __str__(self):
        return f"[{self.get_block_display()}] {self.name}"

    @property
    def summary(self):
        """一行摘要：Single Leg Hip Bridge 15 次 × 3 組 @ body weight，休 30s"""
        bits = [self.name]
        for value, suffix in (
            (self.distance, ""),
            (self.reps, " 次"),
            (self.sets, " 組"),
        ):
            if value:
                bits.append(f"{value}{suffix}")
        if self.weight:
            bits.append(f"@ {self.weight}")
        if self.intensity:
            bits.append(f"強度 {self.intensity}")
        if self.rest:
            bits.append(f"休 {self.rest}")
        return " ".join(bits)


# ------------------------------------------------- 區塊 program（可重用的一區內容）


class BlockProgram(TimeStampedModel):
    """一區排好的內容（熱身／正課／補充練習／恢復練習）存成可重用的 program。

    教練把今天的熱身排好之後按「儲存成 program」，下一課在同一區按「套用」，
    整組活動連同組數／次數／休息一起寫進去，不用逐項再挑一次。
    存下來的 program 全隊共用，但只有建立者（和管理員）改得動、刪得掉。
    """

    name = models.CharField(_("program 名稱"), max_length=120)
    block = models.CharField(_("區塊"), max_length=12, choices=BlockType.choices)
    session_type = models.CharField(
        _("來源課別"), max_length=20, blank=True, help_text=_("存下來時那一堂課的課別，只作提示")
    )
    note = models.CharField(_("說明"), max_length=200, blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="block_programs",
        verbose_name=_("建立者"),
    )
    use_count = models.PositiveIntegerField(_("套用次數"), default=0)

    class Meta:
        verbose_name = _("區塊 program")
        verbose_name_plural = _("區塊 program")
        ordering = ["block", "-use_count", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "block", "name"], name="unique_block_program_per_owner"
            )
        ]

    def __str__(self):
        return f"[{self.get_block_display()}] {self.name}"

    @property
    def item_count(self):
        return self.items.count()

    @property
    def preview(self):
        """下拉選單旁邊給人看的一行：頭三項活動的名字。"""
        names = [i.name for i in self.items.all()[:3]]
        if not names:
            return ""
        more = self.item_count - len(names)
        return "、".join(names) + (f"…（共 {self.item_count} 項）" if more > 0 else "")


class BlockProgramItem(models.Model):
    """program 裡的一項活動——欄位跟課表那一列一樣，套用時原樣抄過去。"""

    program = models.ForeignKey(
        BlockProgram, on_delete=models.CASCADE, related_name="items", verbose_name=_("program")
    )
    order = models.PositiveSmallIntegerField(_("排序"), default=1)
    definition = models.ForeignKey(
        ActivityDefinition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="program_items",
        verbose_name=_("來源活動"),
    )
    name = models.CharField(_("活動名稱"), max_length=120)
    sets = models.CharField(_("組數"), max_length=30, blank=True)
    reps = models.CharField(_("次數"), max_length=30, blank=True)
    distance = models.CharField(_("距離"), max_length=30, blank=True)
    weight = models.CharField(_("重量"), max_length=40, blank=True)
    intensity = models.CharField(_("強度"), max_length=40, blank=True)
    rest = models.CharField(_("休息時間"), max_length=80, blank=True)
    key_points = models.TextField(_("訓練要點"), blank=True)

    class Meta:
        verbose_name = _("program 活動")
        verbose_name_plural = _("program 活動")
        ordering = ["program", "order", "id"]

    def __str__(self):
        return f"{self.program.name} · {self.name}"

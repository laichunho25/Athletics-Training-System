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


# ------------------------------------------------------- 分區課表內容（活動）


class BlockType(models.TextChoices):
    """課表內容的四個層面。輸入時分區進行，輸出時依這個順序排。"""

    WARMUP = "WARMUP", "熱身"
    MAIN = "MAIN", "正課"
    SUPPLEMENT = "SUPPLEMENT", "補充練習"
    RECOVERY = "RECOVERY", "恢復練習"


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

    WARMUP = "WARMUP", "熱身"
    TRACK = "TRACK", "田徑專項"
    UPPER = "UPPER", "上肢力量"
    LOWER = "LOWER", "下肢力量"
    CORE = "CORE", "核心"
    PLYO = "PLYO", "增強式／爆發力"
    # 增強式的東西多，四大部份分開列，挑動作時才不用在一長串裡找
    PLYO_BASIC = "PLYO_BASIC", "增強式：基礎與進階跳躍"
    PLYO_TRACK = "PLYO_TRACK", "增強式：田徑專項"
    PLYO_UPPER = "PLYO_UPPER", "增強式：上肢與全身旋轉"
    PLYO_POGO = "PLYO_POGO", "增強式：踝彈跳 Pogo"
    ACCESSORY = "ACCESSORY", "輔助／預防傷害"
    RECOVERY = "RECOVERY", "恢復／放鬆"


# ------------------------------------------------- 運動練習項目庫（分層目錄）


class LibraryStatus(models.TextChoices):
    """項目庫的審核狀態。

    教練、運動員、管理員都可以往庫裡加東西，但加進來的先是「待確認」，
    管理員按確認之後才會永久出現在項目庫、也才會出現在別人的挑選清單裡。
    """

    PENDING = "PENDING", "待管理員確認"
    APPROVED = "APPROVED", "已確認"
    REJECTED = "REJECTED", "已退回"


class LibraryNode(TimeStampedModel):
    """項目庫三層目錄（運動種類 / 運動項目 / 訓練動作種類）的共同欄位。"""

    name = models.CharField("名稱", max_length=60)
    name_en = models.CharField("英文名稱", max_length=80, blank=True)
    note = models.CharField("說明", max_length=200, blank=True)
    order = models.PositiveSmallIntegerField("排序", default=50)
    status = models.CharField(
        "狀態", max_length=10, choices=LibraryStatus.choices, default=LibraryStatus.APPROVED
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="建立者",
    )
    is_builtin = models.BooleanField("系統內建", default=False)

    class Meta:
        abstract = True

    def __str__(self):
        return self.name

    @property
    def is_approved(self):
        return self.status == LibraryStatus.APPROVED

    @property
    def display_name(self):
        return f"{self.name}（{self.name_en}）" if self.name_en else self.name


class SportType(LibraryNode):
    """運動種類：田徑、體能訓練、共通基礎…"""

    name = models.CharField("運動種類", max_length=60, unique=True)

    class Meta:
        verbose_name = "運動種類"
        verbose_name_plural = "運動種類"
        ordering = ["order", "name"]


class Discipline(LibraryNode):
    """運動項目：田徑底下的短跑、跨欄；體能訓練底下的肌力與重量訓練…"""

    sport = models.ForeignKey(
        SportType, on_delete=models.CASCADE, related_name="disciplines", verbose_name="運動種類"
    )
    activity_category = models.CharField(
        "預設分類",
        max_length=12,
        choices=ActivityCategory.choices,
        default=ActivityCategory.WARMUP,
        help_text="這個項目底下新加的動作預設算哪一類——決定數據分析把它歸到哪個範疇",
    )

    class Meta:
        verbose_name = "運動項目"
        verbose_name_plural = "運動項目"
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

    name = models.CharField("訓練動作種類", max_length=60, unique=True)

    class Meta:
        verbose_name = "訓練動作種類"
        verbose_name_plural = "訓練動作種類"
        ordering = ["order", "name"]


class ActivityDefinition(TimeStampedModel):
    """訓練活動名稱庫。

    教練不用每次逐字打「Single Leg Hip Bridge」，從清單挑一個就會把預設的
    組數/次數/距離/重量/強度/休息時間一起帶進課表，之後再改成當天的數字。
    清單上沒有的活動，隨時按「新增活動」寫一個進去，下次就挑得到。
    """

    name = models.CharField("活動名稱", max_length=120, unique=True)
    name_en = models.CharField(
        "英文名稱", max_length=120, blank=True,
        help_text="健身房器材與課表上常寫英文，兩個名字都留著才找得到",
    )
    category = models.CharField(
        "分類", max_length=12, choices=ActivityCategory.choices,
        default=ActivityCategory.WARMUP,
    )
    default_block = models.CharField(
        "預設區塊", max_length=12, choices=BlockType.choices, default=BlockType.WARMUP
    )
    default_sets = models.CharField("預設組數", max_length=30, blank=True)
    default_reps = models.CharField("預設次數", max_length=30, blank=True)
    default_distance = models.CharField("預設距離", max_length=30, blank=True)
    default_weight = models.CharField("預設重量", max_length=40, blank=True)
    default_intensity = models.CharField("預設強度", max_length=40, blank=True)
    default_rest = models.CharField("預設休息時間", max_length=80, blank=True)
    default_key_points = models.TextField("預設訓練要點", blank=True)
    note = models.CharField("說明", max_length=200, blank=True)
    discipline = models.ForeignKey(
        Discipline,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
        verbose_name="運動項目",
    )
    movement_kind = models.ForeignKey(
        MovementKind,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
        verbose_name="訓練動作種類",
    )
    status = models.CharField(
        "狀態", max_length=10, choices=LibraryStatus.choices, default=LibraryStatus.APPROVED
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_definitions",
        verbose_name="建立者",
    )
    is_builtin = models.BooleanField("系統內建", default=False)
    use_count = models.PositiveIntegerField("使用次數", default=0)
    is_active = models.BooleanField("可挑選", default=True)

    class Meta:
        verbose_name = "訓練活動"
        verbose_name_plural = "訓練活動"
        ordering = ["category", "default_block", "-use_count", "name"]

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        """中文（英文）——挑活動的下拉裡兩個名字一起顯示。"""
        return f"{self.name}（{self.name_en}）" if self.name_en else self.name

    @property
    def is_approved(self):
        return self.status == LibraryStatus.APPROVED

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
    block = models.CharField("區塊", max_length=12, choices=BlockType.choices)
    order = models.PositiveSmallIntegerField("排序", default=1)
    definition = models.ForeignKey(
        ActivityDefinition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uses",
        verbose_name="來源活動",
    )
    name = models.CharField("活動名稱", max_length=120)
    sets = models.CharField("組數", max_length=30, blank=True)
    reps = models.CharField("次數", max_length=30, blank=True)
    distance = models.CharField("距離", max_length=30, blank=True)
    weight = models.CharField("重量", max_length=40, blank=True)
    intensity = models.CharField("強度", max_length=40, blank=True)
    rest = models.CharField("休息時間", max_length=80, blank=True)
    key_points = models.TextField("訓練要點", blank=True)
    note = models.TextField("當日備注", blank=True)
    satisfaction = models.PositiveSmallIntegerField(
        "滿意度 (1-5)",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="完成後自評對這項訓練的滿意程度",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="session_activities",
        verbose_name="寫入者",
    )

    class Meta:
        verbose_name = "課表活動"
        verbose_name_plural = "課表活動"
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

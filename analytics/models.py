from django.db import models

from accounts.models import AthleteProfile
from core.models import SessionType, TimeStampedModel


class RiskFlag(models.TextChoices):
    UNDER = "UNDER", "訓練不足"
    OPTIMAL = "OPTIMAL", "甜蜜點"
    ELEVATED = "ELEVATED", "負荷偏高"
    HIGH = "HIGH", "高受傷風險"
    INSUFFICIENT = "INSUFFICIENT", "資料累積中"


class DailyLoad(TimeStampedModel):
    """每日彙總快取，避免每次分析都即時掃描 session。"""

    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="daily_loads"
    )
    date = models.DateField("日期")
    total_load_au = models.PositiveIntegerField("總負荷 (AU)", default=0)
    track_volume_m = models.PositiveIntegerField("專項總量 (m)", default=0)
    strength_tonnage_kg = models.DecimalField(
        "力量總噸位 (kg)", max_digits=10, decimal_places=1, default=0
    )
    session_count = models.PositiveSmallIntegerField("課次", default=0)
    avg_rpe = models.DecimalField("平均 RPE", max_digits=4, decimal_places=2, null=True, blank=True)
    duration_min = models.PositiveIntegerField("總時長 (分)", default=0)

    class Meta:
        verbose_name = "每日負荷"
        verbose_name_plural = "每日負荷"
        unique_together = ("athlete", "date")
        ordering = ["-date"]
        indexes = [models.Index(fields=["athlete", "date"])]

    def __str__(self):
        return f"{self.athlete} {self.date} {self.total_load_au}AU"


class WeeklySummary(TimeStampedModel):
    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="weekly_summaries"
    )
    week_start = models.DateField("週一日期")
    total_load = models.PositiveIntegerField("週總負荷 (AU)", default=0)
    monotony = models.DecimalField("單調度", max_digits=5, decimal_places=2, null=True, blank=True)
    strain = models.DecimalField("訓練張力", max_digits=10, decimal_places=1, null=True, blank=True)
    acwr = models.DecimalField("ACWR", max_digits=4, decimal_places=2, null=True, blank=True)
    acute_load = models.PositiveIntegerField("急性負荷 (7d)", default=0)
    chronic_load = models.DecimalField("慢性負荷 (28d/4)", max_digits=10, decimal_places=1, default=0)
    week_over_week_pct = models.DecimalField(
        "週增幅 (%)", max_digits=6, decimal_places=1, null=True, blank=True
    )
    risk_flag = models.CharField(
        "風險判定", max_length=15, choices=RiskFlag.choices, default=RiskFlag.INSUFFICIENT
    )

    class Meta:
        verbose_name = "週彙總"
        verbose_name_plural = "週彙總"
        unique_together = ("athlete", "week_start")
        ordering = ["-week_start"]

    def __str__(self):
        return f"{self.athlete} 週 {self.week_start} ACWR={self.acwr}"


# ------------------------------------------------------------------ 數據紀錄
#
# 訓練日曆上的每一堂 program，做完之後可以在「數據分析」把成績登進來。
# 紀錄分三個範疇（比賽 / 田徑練習 / 重量），每個範疇底下是「項目」；
# 內建項目由 BUILTIN_METRIC_ITEMS 提供，教練也可以自己新增項目。


class MetricDomain(models.TextChoices):
    COMPETITION = "COMPETITION", "比賽數據"
    TRACK = "TRACK", "田徑練習訓練紀錄"
    STRENGTH = "STRENGTH", "重量訓練紀錄"


#: 訓練日曆上的課別 ←→ 數據分析的紀錄範疇。
#:
#: 日曆上建了一堂課，做完之後要登數據時，只會看到「這個課別該有的」項目；
#: 反過來在數據分析登紀錄時，「對應 program」的下拉也只列得出這些課別的課。
#: 兩邊寫的是同一批 MetricRecord，所以資料互通，不用重打第二次。
SESSION_TYPE_DOMAINS = {
    SessionType.TRACK.value: [MetricDomain.TRACK],
    SessionType.STRENGTH.value: [MetricDomain.STRENGTH],
    # 治療康復 / 恢復訓練那天可能是跑的、也可能是舉的，兩邊都讓他選
    SessionType.REHAB.value: [MetricDomain.TRACK, MetricDomain.STRENGTH],
    SessionType.RECOVERY.value: [MetricDomain.TRACK, MetricDomain.STRENGTH],
    SessionType.COMPETITION.value: [MetricDomain.COMPETITION],
}


def domains_for_session_type(session_type):
    """這個課別可以登哪些範疇的數據（沒對應的課別回傳空清單）。"""
    return list(SESSION_TYPE_DOMAINS.get(session_type, []))


def session_types_for_domain(domain):
    """這個範疇的紀錄，可以掛在哪些課別的 program 底下。"""
    return [t for t, ds in SESSION_TYPE_DOMAINS.items() if domain in ds]


def domain_pairs_for_session_type(session_type):
    """給畫面用的 (value, label) 清單。"""
    labels = dict(MetricDomain.choices)
    return [(d.value, labels[d.value]) for d in domains_for_session_type(session_type)]


class TrainingStatus(models.TextChoices):
    """這一天的練習是在什麼狀態下進行的。

    同一個動作在傷害治療期跑出來的秒數，本來就不該跟訓練準備期放在一起比。
    分析時先看這一欄，才不會把「那陣子在復健」誤判成「能力退步」。
    """

    OFFSEASON = "OFFSEASON", "季後休息期"
    PREP = "PREP", "訓練準備期"
    TAPER = "TAPER", "比賽調整期"
    INJURY = "INJURY", "傷害治療期"
    RETURN = "RETURN", "恢復回歸期"


#: 每個狀態在看數據時要記得的事——畫面上直接寫在旁邊，
#: 免得看的人要自己回想「季後休息期本來就跑不快」。
STATUS_GUIDE = {
    TrainingStatus.OFFSEASON.value: {
        "feature": "刻意減量休息，體能與專項水準本來就會回落",
        "reading": "這段期間的數字不代表能力，別跟賽季的成績直接比。",
    },
    TrainingStatus.PREP.value: {
        "feature": "量大、強度中等，帶著疲勞在練",
        "reading": "數字比高峰期差是正常的；看的是量能不能吃得下、完成率高不高。",
    },
    TrainingStatus.TAPER.value: {
        "feature": "量降、強度高，狀態往高峰推",
        "reading": "這裡的數字最接近真實水準，適合拿來當基準。",
    },
    TrainingStatus.INJURY.value: {
        "feature": "帶傷或在治療，動作被迫調整",
        "reading": "退步幾乎一定跟傷有關，不要當成能力下降；先看傷患頁的疼痛紀錄。",
    },
    TrainingStatus.RETURN.value: {
        "feature": "剛回歸，刻意壓著強度往上疊",
        "reading": "數字偏低是計劃的一部分；看的是有沒有一週比一週好、有沒有再痛。",
    },
}


def status_guide(value):
    return STATUS_GUIDE.get(value, {"feature": "沒有註記當天的狀態", "reading": "補上狀態註記，分析才分得清是狀態還是能力。"})


class TrackMethod(models.TextChoices):
    """田徑練習的「方式」。

    距離是多變的（今天 120m、明天 150m），所以項目以方式為主：
    先挑方式，再輸入距離，合起來就是一個可以追蹤的項目（例：150m 反覆跑）。
    """

    TEMPO = "TEMPO", "節奏跑"
    REPEAT = "REPEAT", "反覆跑"
    INTERVAL = "INTERVAL", "間歇跑"
    START = "START", "起跑"
    ACCEL = "ACCEL", "加速跑"
    BUILDUP = "BUILDUP", "漸速跑"
    FLYING = "FLYING", "飛行跑"
    MAXSPEED = "MAXSPEED", "全速計時"
    SPLIT = "SPLIT", "分段跑"
    HILL = "HILL", "上坡跑"
    RESIST = "RESIST", "阻力跑"
    HURDLE = "HURDLE", "跨欄節奏"
    RELAY = "RELAY", "接力交棒"
    TECH = "TECH", "技術跑"
    ENDURANCE = "ENDURANCE", "專項耐力跑"


#: 方式 → 英文名（項目名稱一律「中文（English）」，這裡給英文的那一半）
TRACK_METHOD_EN = {
    "TEMPO": "Tempo Run",
    "REPEAT": "Repetition Run",
    "INTERVAL": "Interval Run",
    "START": "Block Start",
    "ACCEL": "Acceleration Run",
    "BUILDUP": "Build-up Run",
    "FLYING": "Flying Sprint",
    "MAXSPEED": "Max Speed Time Trial",
    "SPLIT": "Split Run",
    "HILL": "Hill Sprint",
    "RESIST": "Resisted Sprint",
    "HURDLE": "Hurdle Rhythm",
    "RELAY": "Relay Handover",
    "TECH": "Technical Run",
    "ENDURANCE": "Special Endurance Run",
}


def track_method_choices():
    """挑方式的下拉選單：照這裡其他選項的樣子做中英對照（節奏跑（Tempo Run））。"""
    return [(v, f"{l}（{TRACK_METHOD_EN[v]}）" if TRACK_METHOD_EN.get(v) else l)
            for v, l in TrackMethod.choices]


def track_item_name(method, distance_m):
    """方式 ＋ 距離 → 項目名稱（例：150m 反覆跑；沒填距離就只有方式）。"""
    label = dict(TrackMethod.choices).get(method, "")
    if not label:
        return "", ""
    en = TRACK_METHOD_EN.get(method, "")
    if distance_m:
        return f"{distance_m}m {label}", (f"{distance_m}m {en}" if en else "")
    return label, en


def block_choices():
    """課表的四個區塊（熱身／正課／補充練習／恢復練習）。

    定義放在 training.models（課表那邊才是它的主場），這裡延後匯入，
    免得兩個 app 的 models 互相 import。
    """
    from training.models import BlockType

    return BlockType.choices


def block_order():
    """四個區塊的固定顯示順序（value 清單）。"""
    from training.models import BLOCK_ORDER

    return [b.value for b in BLOCK_ORDER]


class MetricCategory(models.TextChoices):
    """重量訓練紀錄的動作分類——項目清單照這個分組顯示，找動作比一長串快。"""

    WARMUP = "WARMUP", "熱身動作（Warm-up Activities）"
    UPPER = "UPPER", "上身動作（Upper Body Movement）"
    LOWER = "LOWER", "下身動作（Lower Body Movement）"
    CORE = "CORE", "核心肌群（Core Strength）"
    FULL = "FULL", "全身力量（Full-Body Workout）"
    PLYO = "PLYO", "增強式訓練（Plyometric Training）"
    OTHER = "OTHER", "其他"


#: 訓練活動庫的分類 → 數據項目的分類。
#: 課表上挑了一個活動，自動變成數據項目時就落在對應的那一組底下。
ACTIVITY_CATEGORY_TO_METRIC = {
    "WARMUP": MetricCategory.WARMUP.value,
    "UPPER": MetricCategory.UPPER.value,
    "LOWER": MetricCategory.LOWER.value,
    "CORE": MetricCategory.CORE.value,
    "PLYO": MetricCategory.PLYO.value,
    "ACCESSORY": MetricCategory.FULL.value,
    "TRACK": MetricCategory.OTHER.value,
    "RECOVERY": MetricCategory.WARMUP.value,
}


def metric_category_for_activity(category):
    """訓練活動的分類換成數據項目的分類（不認得就丟到「其他」）。"""
    return ACTIVITY_CATEGORY_TO_METRIC.get(category, MetricCategory.OTHER.value)


#: (範疇, 中文名稱, 英文名稱, 單位, 數值越大越好, 分類)
BUILTIN_METRIC_ITEMS = [
    (MetricDomain.COMPETITION, "100m 成績", "100m Result", "秒", False, MetricCategory.OTHER),
    (MetricDomain.COMPETITION, "200m 成績", "200m Result", "秒", False, MetricCategory.OTHER),
    (MetricDomain.COMPETITION, "400m 成績", "400m Result", "秒", False, MetricCategory.OTHER),
    (MetricDomain.COMPETITION, "800m 成績", "800m Result", "秒", False, MetricCategory.OTHER),
    (MetricDomain.COMPETITION, "跳遠成績", "Long Jump", "m", True, MetricCategory.OTHER),
    (MetricDomain.COMPETITION, "跳高成績", "High Jump", "m", True, MetricCategory.OTHER),
    (MetricDomain.COMPETITION, "鉛球成績", "Shot Put", "m", True, MetricCategory.OTHER),
    (MetricDomain.COMPETITION, "起跑反應時間", "Reaction Time", "秒", False, MetricCategory.OTHER),
    (MetricDomain.COMPETITION, "名次", "Placing", "名", False, MetricCategory.OTHER),
    (MetricDomain.TRACK, "30m 衝刺", "30m Sprint", "秒", False, MetricCategory.OTHER),
    (MetricDomain.TRACK, "60m 衝刺", "60m Sprint", "秒", False, MetricCategory.OTHER),
    (MetricDomain.TRACK, "150m 計時", "150m Time Trial", "秒", False, MetricCategory.OTHER),
    (MetricDomain.TRACK, "300m 計時", "300m Time Trial", "秒", False, MetricCategory.OTHER),
    (MetricDomain.TRACK, "最高速度", "Top Speed", "m/s", True, MetricCategory.OTHER),
    (MetricDomain.TRACK, "課堂總距離", "Session Volume", "m", True, MetricCategory.OTHER),
    (MetricDomain.TRACK, "平均每 100m 配速", "Pace per 100m", "秒", False, MetricCategory.OTHER),
    (MetricDomain.TRACK, "課後 RPE", "Session RPE", "分", False, MetricCategory.OTHER),
    (MetricDomain.STRENGTH, "背蹲舉 1RM", "Back Squat 1RM", "kg", True, MetricCategory.LOWER),
    (MetricDomain.STRENGTH, "臥推 1RM", "Bench Press 1RM", "kg", True, MetricCategory.UPPER),
    (MetricDomain.STRENGTH, "硬舉 1RM", "Deadlift 1RM", "kg", True, MetricCategory.LOWER),
    (MetricDomain.STRENGTH, "高翻 1RM", "Power Clean 1RM", "kg", True, MetricCategory.FULL),
    (MetricDomain.STRENGTH, "前蹲舉", "Front Squat", "kg", True, MetricCategory.LOWER),
    (MetricDomain.STRENGTH, "臀推", "Hip Thrust", "kg", True, MetricCategory.LOWER),
    (MetricDomain.STRENGTH, "羅馬尼亞硬舉", "Romanian Deadlift (RDL)", "kg", True, MetricCategory.LOWER),
    (MetricDomain.STRENGTH, "保加利亞分腿蹲", "Bulgarian Split Squat", "kg", True, MetricCategory.LOWER),
    (MetricDomain.STRENGTH, "引體向上（加重）", "Weighted Pull-up", "kg", True, MetricCategory.UPPER),
    (MetricDomain.STRENGTH, "坐姿划船", "Seated Row", "kg", True, MetricCategory.UPPER),
    (MetricDomain.STRENGTH, "肩推", "Shoulder Press", "kg", True, MetricCategory.UPPER),
    (MetricDomain.STRENGTH, "平板支撐", "Plank", "秒", True, MetricCategory.CORE),
    (MetricDomain.STRENGTH, "課堂總噸位", "Session Tonnage", "kg", True, MetricCategory.FULL),
    (MetricDomain.STRENGTH, "反向跳", "Countermovement Jump", "cm", True, MetricCategory.PLYO),
    (MetricDomain.STRENGTH, "立定跳遠", "Standing Long Jump", "cm", True, MetricCategory.PLYO),
]


#: 舊資料庫裡「中文 英文」混在一起的項目名稱 → 純中文名稱（英文改放 name_en）
BUILTIN_RENAMES = {"前蹲舉 Front Squat": "前蹲舉", "臀推 Hip Thrust": "臀推", "羅馬尼亞硬舉 RDL": "羅馬尼亞硬舉", "平板支撐 Plank": "平板支撐", "反向跳 CMJ": "反向跳"}


class MetricItem(models.Model):
    """一個可以記錄的數據項目，例如「30m 衝刺（秒）」。"""

    domain = models.CharField("範疇", max_length=15, choices=MetricDomain.choices)
    name = models.CharField("項目名稱", max_length=60)
    name_en = models.CharField(
        "英文名稱", max_length=80, blank=True,
        help_text="清單與紀錄都以「中文（English）」顯示，兩個名字都找得到",
    )
    category = models.CharField(
        "動作分類", max_length=10, choices=MetricCategory.choices,
        default=MetricCategory.OTHER,
        help_text="重量訓練紀錄的項目清單依這個分組顯示",
    )
    unit = models.CharField("單位", max_length=15, blank=True, help_text="例：秒、m、kg、cm")
    higher_is_better = models.BooleanField(
        "數值越大越好", default=True, help_text="計時類項目請取消勾選（越小越好）"
    )
    # 田徑練習的項目以「方式」為主，距離另外填——同一個距離用不同方式跑
    # （150m 節奏跑 vs 150m 反覆跑）本來就是兩件事，分開記才比得出來。
    track_method = models.CharField(
        "練習方式", max_length=12, choices=TrackMethod.choices, blank=True,
        help_text="田徑練習專用：節奏跑／反覆跑／起跑／加速跑…",
    )
    track_distance_m = models.PositiveIntegerField(
        "距離 (m)", null=True, blank=True, help_text="田徑練習專用：這個項目跑幾米"
    )
    is_builtin = models.BooleanField("內建項目", default=False)
    is_active = models.BooleanField("顯示中", default=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="metric_items",
        verbose_name="新增者",
    )

    class Meta:
        verbose_name = "數據項目"
        verbose_name_plural = "數據項目"
        unique_together = ("domain", "name")
        ordering = ["domain", "category", "-is_builtin", "name"]

    def __str__(self):
        return f"{self.name}（{self.unit}）" if self.unit else self.name

    @property
    def display_name(self):
        """中文（English）——所有畫面都用這個名字顯示。"""
        return f"{self.name}（{self.name_en}）" if self.name_en else self.name

    @property
    def display(self):
        unit = f"（{self.unit}）" if self.unit else ""
        return f"{self.display_name}{unit}"


class MetricRecord(TimeStampedModel):
    """一筆實際數據，可以綁在日曆上的某一堂 program。"""

    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="metric_records"
    )
    item = models.ForeignKey(MetricItem, on_delete=models.CASCADE, related_name="records")
    session = models.ForeignKey(
        "planning.TrainingSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="metric_records",
        verbose_name="對應 program",
        help_text="留空表示不是從日曆的課表產生（例如比賽）",
    )
    competition = models.ForeignKey(
        "planning.Competition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="metric_records",
        verbose_name="賽事",
        help_text="比賽數據登在哪一場比賽底下；練習紀錄留空",
    )
    date = models.DateField("日期")
    # 這一組是課表上的哪一段做的（熱身 / 正課 / 補充練習 / 恢復練習）。
    # 登數據時挑一個，紀錄就「放回」課表對應的那一區，
    # 之後看數據分析也分得出熱身跳的與正課跳的不是同一件事。
    block = models.CharField(
        "課表區塊", max_length=12, choices=block_choices, blank=True,
        help_text="這一組屬於課表的哪一段：熱身／正課／補充練習／恢復練習",
    )
    # 目標與完成分開記：課表上要求做到幾秒、實際做出幾秒，兩個都不是必填，
    # 只要挑了項目就登得進來（之後在數據分析補值也可以）。
    target_value = models.DecimalField(
        "目標數值 (秒)", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="課表上要求的目標，沒有就留空",
    )
    value = models.DecimalField(
        "完成數值 (秒)", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="實際完成的數值，還沒量到可以留空，之後在數據分析補",
    )
    # 同一堂課的不同組，重量／次數／休息時間都可能不一樣，所以一組就是一筆紀錄。
    set_no = models.PositiveSmallIntegerField(
        "組別", null=True, blank=True, help_text="第幾組；單筆成績（例如比賽）可留空"
    )
    weight_kg = models.DecimalField(
        "重量 (kg)", max_digits=6, decimal_places=1, null=True, blank=True
    )
    # 田徑練習不是靠重量分辨強度，而是「這一組要跑到幾成」——
    # 90% / 95% / 全力 都填得進來，之後在紀錄分析圖可以照強度分開比。
    intensity = models.CharField(
        "強度要求", max_length=20, blank=True,
        help_text="田徑練習這一組要求的強度，例：90%、95%、全力",
    )
    reps = models.PositiveSmallIntegerField("次數", null=True, blank=True)
    rest_sec = models.PositiveIntegerField(
        "休息時間 (秒)", null=True, blank=True,
        help_text="這一組做完之後休息多久；表單可以用秒或分鐘填，一律換算成秒存起來",
    )
    completed = models.BooleanField(
        "成功完成", default=True, help_text="這一組有沒有照課表完成（沒完成請取消勾選）"
    )
    # 當天是在什麼狀態下練的——分析退步與否之前，先看這一欄
    status = models.CharField(
        "狀態", max_length=12, choices=TrainingStatus.choices, blank=True,
        help_text="這天的練習在什麼狀態下進行（季後休息／訓練準備／比賽調整／傷害治療／恢復回歸）",
    )
    context = models.CharField(
        "情境", max_length=120, blank=True, help_text="例：順風 1.2、賽前熱身、第 3 組"
    )
    note = models.TextField("備註", blank=True)

    class Meta:
        verbose_name = "數據紀錄"
        verbose_name_plural = "數據紀錄"
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["athlete", "item", "date"])]

    def __str__(self):
        shown = f"{self.value}{self.item.unit}" if self.value is not None else "未填"
        return f"{self.athlete} {self.item.name} {shown} ({self.date})"

    @property
    def status_label(self):
        return self.get_status_display() if self.status else ""

    @property
    def block_label(self):
        return self.get_block_display() if self.block else ""

    @property
    def set_label(self):
        return f"第 {self.set_no} 組" if self.set_no else ""

    @property
    def rest_min(self):
        """休息時間換成分鐘（表單以分鐘為預設單位，最多兩位小數）。"""
        if self.rest_sec is None:
            return None
        return round(self.rest_sec / 60, 2)

    @property
    def rest_display(self):
        """休息時間：超過一分鐘就寫成「N 分 N 秒」，短的直接寫秒。"""
        if self.rest_sec is None:
            return ""
        if self.rest_sec < 60:
            return f"{self.rest_sec} 秒"
        minutes, seconds = divmod(self.rest_sec, 60)
        return f"{minutes} 分" + (f" {seconds} 秒" if seconds else "")

    @property
    def tonnage(self):
        """這一組的噸位（重量 × 次數），沒填就是 None。"""
        if self.weight_kg is None or self.reps is None:
            return None
        return float(self.weight_kg) * self.reps


def ensure_builtin_items():
    """把內建項目補齊（第一次開啟數據分析頁時呼叫，重複執行安全）。"""
    # 舊資料的名稱把中英文混在同一欄，先改成純中文（英文改放 name_en）
    for old_name, new_name in BUILTIN_RENAMES.items():
        stale = MetricItem.objects.filter(name=old_name)
        for obj in stale:
            if MetricItem.objects.filter(domain=obj.domain, name=new_name).exists():
                continue  # 已經有新名字的項目，舊的留著不動免得撞 unique
            MetricItem.objects.filter(pk=obj.pk).update(name=new_name)

    existing = set(MetricItem.objects.values_list("domain", "name"))
    missing = [
        MetricItem(
            domain=d, name=n, name_en=en, unit=u, higher_is_better=hib,
            category=cat, is_builtin=True,
        )
        for d, n, en, u, hib, cat in BUILTIN_METRIC_ITEMS
        if (d.value, n) not in existing
    ]
    if missing:
        MetricItem.objects.bulk_create(missing, ignore_conflicts=True)

    # 舊資料庫裡已經存在的內建項目還沒有英文名／分類，順手補上
    wanted = {
        (d.value, n): (en, cat) for d, n, en, _u, _hib, cat in BUILTIN_METRIC_ITEMS
    }
    for obj in MetricItem.objects.filter(is_builtin=True):
        target = wanted.get((obj.domain, obj.name))
        if target is None:
            continue
        en, cat = target
        changes = {}
        if not obj.name_en:
            changes["name_en"] = en
        if obj.category == MetricCategory.OTHER and cat != MetricCategory.OTHER:
            changes["category"] = cat
        if changes:
            MetricItem.objects.filter(pk=obj.pk).update(**changes)
    return len(missing)


#: 課表活動要自動變成數據項目時，依範疇給一個合理的預設單位
DOMAIN_DEFAULT_UNIT = {
    MetricDomain.COMPETITION.value: "秒",
    MetricDomain.TRACK.value: "秒",
    MetricDomain.STRENGTH.value: "kg",
}


def item_for_name(domain, name, unit=None, user=None, category=None, name_en=""):
    """依名稱取得（必要時建立）一個數據項目。

    課表上寫了「槓鈴深蹲」，登數據時就直接用同一個名字當項目——
    教練不用先到數據分析頁開項目、運動員也不用把動作名再打一次。
    """
    name = (name or "").strip()
    if not name:
        return None
    if unit is None:
        unit = DOMAIN_DEFAULT_UNIT.get(domain, "")
    item, created = MetricItem.objects.get_or_create(
        domain=domain,
        name=name,
        defaults={
            "unit": unit,
            # 計時類（秒）越小越好，重量／距離類越大越好
            "higher_is_better": unit not in ("秒", "名"),
            "category": category or MetricCategory.OTHER,
            "name_en": name_en or "",
            "created_by": user,
        },
    )
    # 先前自動建的項目沒分類／沒英文名，之後從活動庫挑到同一個名字就補上去
    if not created:
        changes = []
        if category and item.category == MetricCategory.OTHER:
            item.category = category
            changes.append("category")
        if name_en and not item.name_en:
            item.name_en = name_en
            changes.append("name_en")
        if changes:
            item.save(update_fields=changes)
    return item


def track_item_for(method, distance_m, user=None):
    """田徑練習：挑一個方式、填一個距離，就得到（必要時建立）一個可追蹤的項目。

    距離是多變的，所以清單上不預先列滿所有距離——
    要追蹤 150m 反覆跑就當場開一個，之後同樣的方式加距離都會對到同一個項目。
    """
    name, name_en = track_item_name(method, distance_m)
    if not name:
        return None
    item, created = MetricItem.objects.get_or_create(
        domain=MetricDomain.TRACK.value,
        name=name,
        defaults={
            "name_en": name_en,
            "unit": "秒",
            "higher_is_better": False,     # 田徑練習記的是時間，越小越好
            "category": MetricCategory.OTHER.value,
            "track_method": method,
            "track_distance_m": distance_m or None,
            "created_by": user,
        },
    )
    # 之前用打名稱的方式建過同名項目，這裡把方式／距離補上去，
    # 之後「同方式不同距離」「同距離不同方式」才分得出來一起比。
    changes = []
    if not item.track_method:
        item.track_method = method
        changes.append("track_method")
    if item.track_distance_m is None and distance_m:
        item.track_distance_m = distance_m
        changes.append("track_distance_m")
    if not item.name_en and name_en:
        item.name_en = name_en
        changes.append("name_en")
    if changes:
        item.save(update_fields=changes)
    return item


#: 這些活動分類屬於重量訓練；治療康復／恢復訓練那種兩個範疇都可以的課，
#: 就靠活動本身的分類決定數據要記在哪一邊。
STRENGTH_ACTIVITY_CATEGORIES = {"UPPER", "LOWER", "CORE", "PLYO", "ACCESSORY"}


def domain_for_activity(session_type, activity_category):
    """課表上加了一項活動，它的數據應該記在哪個範疇（沒有對應就回 None）。"""
    domains = domains_for_session_type(session_type)
    if not domains:
        return None
    if len(domains) == 1:
        return domains[0].value
    prefer = (
        MetricDomain.STRENGTH
        if activity_category in STRENGTH_ACTIVITY_CATEGORIES
        else MetricDomain.TRACK
    )
    return prefer.value if prefer in domains else domains[0].value


def item_for_activity(session_type, name, activity_category="", user=None, name_en=""):
    """課表上的一項活動 → 數據分析裡的同名項目（沒有就建一個）。

    在日曆寫課表時就順手把項目開好，之後登數據不用再到數據分析頁新增一次。
    """
    domain = domain_for_activity(session_type, activity_category)
    if domain is None:
        return None
    # 重量訓練一律先以 kg 為主要單位（撐體、平板那種要記秒的動作，
    # 之後在畫面上把那個項目的單位切成「秒」就可以，見 set_item_unit）
    unit = None
    if domain != MetricDomain.STRENGTH.value and activity_category in ("WARMUP", "RECOVERY"):
        unit = "秒"
    return item_for_name(
        domain,
        name,
        unit=unit,
        user=user,
        category=metric_category_for_activity(activity_category),
        name_en=name_en,
    )


#: 重量訓練項目用得到的單位。大部分動作記的是重量（kg），
#: 平板支撐、懸垂、登階那種撐時間的動作就切成「秒」。
STRENGTH_UNITS = [("kg", "kg（重量）"), ("秒", "秒（時間）")]


def set_item_unit(item, unit):
    """換掉一個項目的單位（kg ↔ 秒），並把「越大越好」調成合理的方向。

    重量訓練記秒的是撐多久（越久越好）；田徑與比賽記秒的是跑多快（越短越好）。
    回傳有沒有真的換過。
    """
    unit = (unit or "").strip()
    if unit not in [u for u, _ in STRENGTH_UNITS]:
        return False
    if unit == (item.unit or "").strip():
        return False
    item.unit = unit
    item.higher_is_better = (
        True if unit == "kg" else item.domain == MetricDomain.STRENGTH.value
    )
    item.save(update_fields=["unit", "higher_is_better"])
    return True

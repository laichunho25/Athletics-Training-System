from django.db import models

from accounts.models import AthleteProfile
from core.models import TimeStampedModel


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


#: (範疇, 項目名稱, 單位, 數值越大越好)
BUILTIN_METRIC_ITEMS = [
    (MetricDomain.COMPETITION, "100m 成績", "秒", False),
    (MetricDomain.COMPETITION, "200m 成績", "秒", False),
    (MetricDomain.COMPETITION, "400m 成績", "秒", False),
    (MetricDomain.COMPETITION, "800m 成績", "秒", False),
    (MetricDomain.COMPETITION, "跳遠成績", "m", True),
    (MetricDomain.COMPETITION, "跳高成績", "m", True),
    (MetricDomain.COMPETITION, "鉛球成績", "m", True),
    (MetricDomain.COMPETITION, "起跑反應時間", "秒", False),
    (MetricDomain.COMPETITION, "名次", "名", False),
    (MetricDomain.TRACK, "30m 衝刺", "秒", False),
    (MetricDomain.TRACK, "60m 衝刺", "秒", False),
    (MetricDomain.TRACK, "150m 計時", "秒", False),
    (MetricDomain.TRACK, "300m 計時", "秒", False),
    (MetricDomain.TRACK, "最高速度", "m/s", True),
    (MetricDomain.TRACK, "課堂總距離", "m", True),
    (MetricDomain.TRACK, "平均每 100m 配速", "秒", False),
    (MetricDomain.TRACK, "課後 RPE", "分", False),
    (MetricDomain.STRENGTH, "背蹲舉 1RM", "kg", True),
    (MetricDomain.STRENGTH, "臥推 1RM", "kg", True),
    (MetricDomain.STRENGTH, "硬舉 1RM", "kg", True),
    (MetricDomain.STRENGTH, "高翻 1RM", "kg", True),
    (MetricDomain.STRENGTH, "課堂總噸位", "kg", True),
    (MetricDomain.STRENGTH, "反向跳 CMJ", "cm", True),
    (MetricDomain.STRENGTH, "立定跳遠", "cm", True),
]


class MetricItem(models.Model):
    """一個可以記錄的數據項目，例如「30m 衝刺（秒）」。"""

    domain = models.CharField("範疇", max_length=15, choices=MetricDomain.choices)
    name = models.CharField("項目名稱", max_length=60)
    unit = models.CharField("單位", max_length=15, blank=True, help_text="例：秒、m、kg、cm")
    higher_is_better = models.BooleanField(
        "數值越大越好", default=True, help_text="計時類項目請取消勾選（越小越好）"
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
        ordering = ["domain", "-is_builtin", "name"]

    def __str__(self):
        return f"{self.name}（{self.unit}）" if self.unit else self.name

    @property
    def display(self):
        return str(self)


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
    date = models.DateField("日期")
    value = models.DecimalField("數值", max_digits=10, decimal_places=2)
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
        return f"{self.athlete} {self.item.name} {self.value}{self.item.unit} ({self.date})"


def ensure_builtin_items():
    """把內建項目補齊（第一次開啟數據分析頁時呼叫，重複執行安全）。"""
    existing = set(MetricItem.objects.values_list("domain", "name"))
    missing = [
        MetricItem(domain=d, name=n, unit=u, higher_is_better=hib, is_builtin=True)
        for d, n, u, hib in BUILTIN_METRIC_ITEMS
        if (d.value, n) not in existing
    ]
    if missing:
        MetricItem.objects.bulk_create(missing, ignore_conflicts=True)
    return len(missing)

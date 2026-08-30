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

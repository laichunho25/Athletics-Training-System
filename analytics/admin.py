from django.contrib import admin

from analytics.models import DailyLoad, WeeklySummary


@admin.register(DailyLoad)
class DailyLoadAdmin(admin.ModelAdmin):
    list_display = ("athlete", "date", "total_load_au", "track_volume_m",
                    "strength_tonnage_kg", "session_count", "avg_rpe")
    list_filter = ("athlete",)
    date_hierarchy = "date"


@admin.register(WeeklySummary)
class WeeklySummaryAdmin(admin.ModelAdmin):
    list_display = ("athlete", "week_start", "total_load", "acwr", "monotony",
                    "strain", "week_over_week_pct", "risk_flag")
    list_filter = ("athlete", "risk_flag")

from django.contrib import admin

from analytics.models import DailyLoad, MetricItem, MetricRecord, WeeklySummary


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


@admin.register(MetricItem)
class MetricItemAdmin(admin.ModelAdmin):
    list_display = ("name", "domain", "unit", "higher_is_better", "is_builtin", "is_active")
    list_filter = ("domain", "is_builtin", "is_active")
    search_fields = ("name",)
    list_editable = ("is_active",)


@admin.register(MetricRecord)
class MetricRecordAdmin(admin.ModelAdmin):
    list_display = ("athlete", "item", "date", "set_no", "target_value", "value", "weight_kg",
                    "reps", "rest_sec", "completed", "session", "context")
    list_filter = ("item__domain", "item", "athlete", "completed")
    date_hierarchy = "date"
    autocomplete_fields = ["item"]

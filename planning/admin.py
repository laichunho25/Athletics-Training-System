from django.contrib import admin

from planning.models import (
    Competition,
    CompetitionEntry,
    Macrocycle,
    Microcycle,
    Phase,
    SessionTemplate,
    TrainingSession,
)
from training.models import StrengthSet, TrackSet


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "level", "is_target", "countdown_display")
    list_filter = ("level", "is_target")


@admin.register(CompetitionEntry)
class CompetitionEntryAdmin(admin.ModelAdmin):
    list_display = ("athlete", "competition", "event", "target_mark", "result_mark", "placing")
    list_filter = ("competition", "event")


class PhaseInline(admin.TabularInline):
    model = Phase
    extra = 0


@admin.register(Macrocycle)
class MacrocycleAdmin(admin.ModelAdmin):
    list_display = ("athlete", "target_competition", "start_date", "total_weeks",
                    "current_week_number", "is_active")
    list_filter = ("is_active", "target_competition")
    inlines = [PhaseInline]
    actions = ["regenerate"]

    @admin.action(description="重新產生分期與週計劃")
    def regenerate(self, request, queryset):
        for macro in queryset:
            macro.generate_phases()
            macro.generate_microcycles()
        self.message_user(request, f"已重新產生 {queryset.count()} 個大週期。")


@admin.register(Microcycle)
class MicrocycleAdmin(admin.ModelAdmin):
    list_display = ("macrocycle", "week_number", "start_date", "planned_load",
                    "actual_load", "completion_rate")
    list_filter = ("macrocycle",)


class TrackSetInline(admin.TabularInline):
    model = TrackSet
    extra = 1


class StrengthSetInline(admin.TabularInline):
    model = StrengthSet
    extra = 1


@admin.register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
    list_display = ("date", "time_slot", "athlete", "title", "session_type",
                    "status", "session_rpe", "session_load", "is_modified")
    list_filter = ("session_type", "status", "athlete", "is_modified")
    date_hierarchy = "date"
    search_fields = ("title", "description")
    inlines = [TrackSetInline, StrengthSetInline]


@admin.register(SessionTemplate)
class SessionTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "coach", "session_type", "planned_duration_min")
    list_filter = ("session_type", "coach")

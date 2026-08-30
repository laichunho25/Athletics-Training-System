from django.contrib import admin

from injury.models import (
    ExerciseModification,
    Injury,
    PainLog,
    RehabExercise,
    RehabProtocol,
)


class PainLogInline(admin.TabularInline):
    model = PainLog
    extra = 0


@admin.register(Injury)
class InjuryAdmin(admin.ModelAdmin):
    list_display = ("athlete", "body_part", "side", "injury_type", "onset_date",
                    "severity", "status", "current_pain_level", "expected_return_date")
    list_filter = ("status", "body_part", "injury_type", "athlete")
    inlines = [PainLogInline]


@admin.register(PainLog)
class PainLogAdmin(admin.ModelAdmin):
    list_display = ("injury", "date", "pain_at_rest", "pain_during_activity",
                    "swelling", "rom_limited", "blocks_high_intensity")
    list_filter = ("swelling", "rom_limited")


class RehabExerciseInline(admin.TabularInline):
    model = RehabExercise
    extra = 1


@admin.register(RehabProtocol)
class RehabProtocolAdmin(admin.ModelAdmin):
    list_display = ("injury", "phase", "start_date", "is_current")
    list_filter = ("phase", "is_current")
    inlines = [RehabExerciseInline]


@admin.register(ExerciseModification)
class ExerciseModificationAdmin(admin.ModelAdmin):
    list_display = ("original_exercise", "substitute_display",
                    "contraindicated_body_parts", "max_pain_level")
    list_filter = ("original_exercise",)
    search_fields = ("original_exercise__name_zh", "substitute_name", "rationale")

from django.contrib import admin

from injury.models import (
    ExerciseModification,
    Injury,
    PainLog,
    RehabExercise,
    RehabProtocol,
    TreatmentLog,
)


class PainLogInline(admin.TabularInline):
    model = PainLog
    extra = 0


class TreatmentLogInline(admin.TabularInline):
    model = TreatmentLog
    extra = 0
    fields = ("date", "treatment_type", "provider", "effect", "pain_after", "next_step")


@admin.register(Injury)
class InjuryAdmin(admin.ModelAdmin):
    list_display = ("athlete", "body_part", "side", "injury_type", "onset_date",
                    "severity", "status", "treatment_status", "current_pain_level",
                    "expected_return_date")
    list_filter = ("status", "treatment_status", "body_part", "injury_type", "athlete")
    inlines = [TreatmentLogInline, PainLogInline]
    fieldsets = (
        ("傷患", {"fields": ("athlete", ("body_part", "side"), ("injury_type", "severity"),
                           ("onset_date", "expected_return_date"), "mechanism", "status")}),
        ("治療方向", {"fields": ("treatment_status", "treatment_direction",
                             "next_review_date", "diagnosis", "practitioner")}),
    )


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


@admin.register(TreatmentLog)
class TreatmentLogAdmin(admin.ModelAdmin):
    list_display = ("injury", "date", "treatment_type", "provider",
                    "effect", "pain_after", "next_step")
    list_filter = ("treatment_type", "effect")
    date_hierarchy = "date"
    search_fields = ("provider", "content", "next_step")

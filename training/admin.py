from django.contrib import admin

from training.models import (
    Exercise,
    NeuromuscularTest,
    OneRepMax,
    RepSplit,
    StrengthSet,
    TrackSet,
)


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("code", "name_zh", "name_en", "category", "is_measured_by_1rm", "is_plyometric")
    list_filter = ("category", "is_measured_by_1rm", "is_plyometric")
    search_fields = ("code", "name_zh", "name_en")


class RepSplitInline(admin.TabularInline):
    model = RepSplit
    extra = 0


@admin.register(TrackSet)
class TrackSetAdmin(admin.ModelAdmin):
    list_display = ("session", "description", "distance_m", "reps", "sets",
                    "actual_time_sec", "total_volume_m", "rpe")
    list_filter = ("surface", "spikes_used")
    inlines = [RepSplitInline]


@admin.register(StrengthSet)
class StrengthSetAdmin(admin.ModelAdmin):
    list_display = ("session", "exercise", "set_number", "reps", "weight_kg",
                    "actual_1rm_pct", "rpe", "tonnage")
    list_filter = ("exercise",)


@admin.register(OneRepMax)
class OneRepMaxAdmin(admin.ModelAdmin):
    list_display = ("athlete", "exercise", "value_kg", "test_date", "is_estimated")
    list_filter = ("exercise", "is_estimated")


@admin.register(NeuromuscularTest)
class NeuromuscularTestAdmin(admin.ModelAdmin):
    list_display = ("athlete", "date", "test_type", "value", "pct_of_baseline", "is_fatigued")
    list_filter = ("test_type", "athlete")

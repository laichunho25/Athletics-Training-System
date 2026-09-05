from django.contrib import admin

from training.models import (
    ActivityDefinition,
    Discipline,
    Exercise,
    LibraryStatus,
    MovementKind,
    NeuromuscularTest,
    OneRepMax,
    RepSplit,
    SessionActivity,
    SportType,
    StrengthSet,
    TrackSet,
)


@admin.action(description="確認選取的項目（讓它永久出現在項目庫）")
def approve_selected(modeladmin, request, queryset):
    count = queryset.update(status=LibraryStatus.APPROVED)
    modeladmin.message_user(request, f"已確認 {count} 筆。")


@admin.action(description="退回選取的項目")
def reject_selected(modeladmin, request, queryset):
    count = queryset.update(status=LibraryStatus.REJECTED)
    modeladmin.message_user(request, f"已退回 {count} 筆。")


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


@admin.register(ActivityDefinition)
class ActivityDefinitionAdmin(admin.ModelAdmin):
    """訓練活動名稱庫：排課表時可以挑的活動都在這裡。"""

    list_display = ("name", "status", "discipline", "movement_kind", "category",
                    "default_block", "default_sets", "default_reps",
                    "default_distance", "default_weight", "default_intensity",
                    "default_rest", "use_count", "is_builtin", "is_active")
    list_filter = ("status", "discipline__sport", "discipline", "movement_kind",
                   "category", "default_block", "is_builtin", "is_active")
    search_fields = ("name", "name_en", "note", "default_key_points")
    list_editable = ("is_active",)
    actions = [approve_selected, reject_selected]


@admin.register(SessionActivity)
class SessionActivityAdmin(admin.ModelAdmin):
    list_display = ("session", "block", "order", "name", "sets", "reps",
                    "distance", "weight", "intensity", "rest", "satisfaction", "created_by")
    list_filter = ("block", "created_by")
    search_fields = ("name", "key_points", "note")
    autocomplete_fields = ["definition"]


# --------------------------------------------- 運動練習項目庫的三層目錄


class LibraryNodeAdmin(admin.ModelAdmin):
    """目錄三層共用：清單上一眼看得出哪些還在等確認。"""

    list_display = ("name", "name_en", "status", "order", "created_by", "is_builtin")
    list_filter = ("status", "is_builtin")
    search_fields = ("name", "name_en", "note")
    actions = [approve_selected, reject_selected]


@admin.register(SportType)
class SportTypeAdmin(LibraryNodeAdmin):
    pass


@admin.register(Discipline)
class DisciplineAdmin(LibraryNodeAdmin):
    list_display = ("name", "sport", "activity_category", "name_en", "status",
                    "order", "created_by", "is_builtin")
    list_filter = ("sport", "status", "is_builtin")


@admin.register(MovementKind)
class MovementKindAdmin(LibraryNodeAdmin):
    pass

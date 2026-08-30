from django.contrib import admin

from nutrition.models import (
    MealLog,
    NutritionTarget,
    RecoveryLog,
    RecoveryMethod,
    SupplementLog,
)


@admin.register(NutritionTarget)
class NutritionTargetAdmin(admin.ModelAdmin):
    list_display = ("athlete", "date", "day_type", "target_kcal", "carb_g",
                    "protein_g", "fat_g", "water_ml")
    list_filter = ("day_type", "goal", "athlete")
    date_hierarchy = "date"


@admin.register(MealLog)
class MealLogAdmin(admin.ModelAdmin):
    list_display = ("athlete", "date", "meal_type", "kcal", "carb_g", "protein_g", "fat_g")
    list_filter = ("meal_type", "athlete")


@admin.register(SupplementLog)
class SupplementLogAdmin(admin.ModelAdmin):
    list_display = ("athlete", "date", "name", "dose", "timing")
    list_filter = ("athlete",)


@admin.register(RecoveryMethod)
class RecoveryMethodAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "default_duration_min")
    list_filter = ("category",)


@admin.register(RecoveryLog)
class RecoveryLogAdmin(admin.ModelAdmin):
    list_display = ("athlete", "date", "sleep_hours", "sleep_quality",
                    "soreness_level", "stress_level", "resting_hr")
    list_filter = ("athlete",)
    filter_horizontal = ("methods",)
    date_hierarchy = "date"

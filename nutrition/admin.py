from django.contrib import admin

from nutrition.models import (
    FoodItem,
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
    list_display = ("athlete", "date", "meal_type", "kcal", "carb_g", "protein_g",
                    "fat_g", "analysis_source")
    list_filter = ("meal_type", "analysis_source", "athlete")
    date_hierarchy = "date"


@admin.register(FoodItem)
class FoodItemAdmin(admin.ModelAdmin):
    """食物字典：沒有 API 金鑰時，相片以外的營養估算全靠這張表。"""

    list_display = ("name_zh", "category", "kcal_per_100g", "carb_per_100g",
                    "protein_per_100g", "fat_per_100g", "typical_serving_g")
    list_filter = ("category",)
    search_fields = ("name_zh", "aliases")


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

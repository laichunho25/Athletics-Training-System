from rest_framework import serializers

from nutrition.models import (
    MealLog,
    NutritionTarget,
    RecoveryLog,
    RecoveryMethod,
    SupplementLog,
)


class NutritionTargetSerializer(serializers.ModelSerializer):
    day_type_display = serializers.CharField(source="get_day_type_display", read_only=True)
    actual_intake = serializers.SerializerMethodField()
    compliance = serializers.SerializerMethodField()
    macro_kcal_split = serializers.DictField(read_only=True)

    class Meta:
        model = NutritionTarget
        fields = [
            "id", "athlete", "date", "day_type", "day_type_display", "goal",
            "bmr_kcal", "tdee_kcal", "target_kcal", "carb_g", "protein_g",
            "fat_g", "water_ml", "macro_kcal_split", "actual_intake", "compliance",
        ]

    def get_actual_intake(self, obj):
        return obj.actual_intake()

    def get_compliance(self, obj):
        return obj.compliance()


class MealLogSerializer(serializers.ModelSerializer):
    meal_type_display = serializers.CharField(source="get_meal_type_display", read_only=True)

    class Meta:
        model = MealLog
        fields = "__all__"


class SupplementLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplementLog
        fields = "__all__"


class RecoveryMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecoveryMethod
        fields = "__all__"


class RecoveryLogSerializer(serializers.ModelSerializer):
    method_names = serializers.SerializerMethodField()

    class Meta:
        model = RecoveryLog
        fields = [
            "id", "athlete", "date", "sleep_hours", "sleep_quality", "bedtime",
            "wake_time", "water_intake_ml", "soreness_level", "stress_level",
            "mood", "resting_hr", "methods", "method_names", "note",
        ]

    def get_method_names(self, obj):
        return [m.name for m in obj.methods.all()]

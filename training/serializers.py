from rest_framework import serializers

from training.models import (
    Exercise,
    NeuromuscularTest,
    OneRepMax,
    RepSplit,
    StrengthSet,
    TrackSet,
)


class ExerciseSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = Exercise
        fields = "__all__"


class RepSplitSerializer(serializers.ModelSerializer):
    class Meta:
        model = RepSplit
        fields = ["id", "track_set", "rep_number", "time_sec", "note"]


class TrackSetSerializer(serializers.ModelSerializer):
    total_volume_m = serializers.IntegerField(read_only=True)
    pace_per_100m = serializers.FloatField(read_only=True)
    speed_ms = serializers.FloatField(read_only=True)
    splits = RepSplitSerializer(many=True, read_only=True)

    class Meta:
        model = TrackSet
        fields = [
            "id", "session", "order", "description", "distance_m", "reps", "sets",
            "target_time_sec", "actual_time_sec", "rest_between_reps_sec",
            "rest_between_sets_sec", "intensity_pct", "avg_hr", "max_hr", "rpe",
            "technical_focus", "surface", "spikes_used",
            "total_volume_m", "pace_per_100m", "speed_ms", "splits",
        ]


class OneRepMaxSerializer(serializers.ModelSerializer):
    exercise_name = serializers.CharField(source="exercise.name_zh", read_only=True)

    class Meta:
        model = OneRepMax
        fields = [
            "id", "athlete", "exercise", "exercise_name", "value_kg",
            "test_date", "is_estimated", "estimation_formula",
        ]


class StrengthSetSerializer(serializers.ModelSerializer):
    exercise_name = serializers.CharField(source="exercise.name_zh", read_only=True)
    tonnage = serializers.FloatField(read_only=True)
    estimated_1rm = serializers.FloatField(read_only=True)

    class Meta:
        model = StrengthSet
        fields = [
            "id", "session", "exercise", "exercise_name", "order", "set_number",
            "reps", "weight_kg", "target_1rm_pct", "actual_1rm_pct", "tempo",
            "rest_sec", "rir", "rpe", "bar_velocity_ms", "is_failure", "note",
            "tonnage", "estimated_1rm",
        ]


class NeuromuscularTestSerializer(serializers.ModelSerializer):
    test_type_display = serializers.CharField(source="get_test_type_display", read_only=True)
    pct_of_baseline = serializers.FloatField(read_only=True)
    is_fatigued = serializers.BooleanField(read_only=True)

    class Meta:
        model = NeuromuscularTest
        fields = [
            "id", "athlete", "date", "test_type", "test_type_display", "value",
            "unit", "note", "pct_of_baseline", "is_fatigued",
        ]


class OneRMCalculatorSerializer(serializers.Serializer):
    """1RM 推估工具的輸入。"""

    weight_kg = serializers.DecimalField(max_digits=6, decimal_places=2)
    reps = serializers.IntegerField(min_value=1, max_value=36)

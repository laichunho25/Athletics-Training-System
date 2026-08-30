from rest_framework import serializers

from injury.models import (
    ExerciseModification,
    Injury,
    PainLog,
    RehabExercise,
    RehabProtocol,
)


class PainLogSerializer(serializers.ModelSerializer):
    blocks_high_intensity = serializers.BooleanField(read_only=True)

    class Meta:
        model = PainLog
        fields = [
            "id", "injury", "date", "pain_at_rest", "pain_during_activity",
            "swelling", "rom_limited", "note", "blocks_high_intensity",
        ]


class RehabExerciseSerializer(serializers.ModelSerializer):
    class Meta:
        model = RehabExercise
        fields = "__all__"


class RehabProtocolSerializer(serializers.ModelSerializer):
    exercises = RehabExerciseSerializer(many=True, read_only=True)
    phase_display = serializers.CharField(source="get_phase_display", read_only=True)

    class Meta:
        model = RehabProtocol
        fields = [
            "id", "injury", "phase", "phase_display", "start_date",
            "progression_criteria", "is_current", "exercises",
        ]


class InjurySerializer(serializers.ModelSerializer):
    body_part_display = serializers.CharField(source="get_body_part_display", read_only=True)
    injury_type_display = serializers.CharField(source="get_injury_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    days_since_onset = serializers.IntegerField(read_only=True)
    current_pain_level = serializers.IntegerField(read_only=True)
    athlete_name = serializers.CharField(source="athlete.__str__", read_only=True)

    class Meta:
        model = Injury
        fields = [
            "id", "athlete", "athlete_name", "body_part", "body_part_display",
            "side", "injury_type", "injury_type_display", "mechanism",
            "onset_date", "severity", "status", "status_display",
            "expected_return_date", "diagnosis", "practitioner",
            "days_since_onset", "current_pain_level",
        ]


class ExerciseModificationSerializer(serializers.ModelSerializer):
    original_name = serializers.CharField(source="original_exercise.name_zh", read_only=True)
    substitute_display = serializers.CharField(read_only=True)

    class Meta:
        model = ExerciseModification
        fields = [
            "id", "original_exercise", "original_name", "substitute_exercise",
            "substitute_name", "substitute_display", "contraindicated_body_parts",
            "max_pain_level", "rationale",
        ]

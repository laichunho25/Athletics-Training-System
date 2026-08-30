from rest_framework import serializers

from planning.models import (
    Competition,
    CompetitionEntry,
    Macrocycle,
    Microcycle,
    Phase,
    SessionTemplate,
    TrainingSession,
)


class CompetitionSerializer(serializers.ModelSerializer):
    days_remaining = serializers.IntegerField(read_only=True)
    weeks_remaining = serializers.IntegerField(read_only=True)
    countdown_display = serializers.CharField(read_only=True)

    class Meta:
        model = Competition
        fields = [
            "id", "name", "date", "end_date", "venue", "level", "is_target",
            "days_remaining", "weeks_remaining", "countdown_display",
        ]


class CompetitionEntrySerializer(serializers.ModelSerializer):
    competition_name = serializers.CharField(source="competition.name", read_only=True)
    event_code = serializers.CharField(source="event.code", read_only=True)

    class Meta:
        model = CompetitionEntry
        fields = "__all__"


class PhaseSerializer(serializers.ModelSerializer):
    phase_type_display = serializers.CharField(source="get_phase_type_display", read_only=True)

    class Meta:
        model = Phase
        fields = [
            "id", "phase_type", "phase_type_display", "week_start", "week_end",
            "start_date", "end_date", "focus", "target_weekly_load",
        ]


class MicrocycleSerializer(serializers.ModelSerializer):
    end_date = serializers.DateField(read_only=True)
    completion_rate = serializers.FloatField(read_only=True)

    class Meta:
        model = Microcycle
        fields = [
            "id", "macrocycle", "phase", "week_number", "start_date", "end_date",
            "planned_load", "actual_load", "completion_rate", "notes",
        ]


class MacrocycleSerializer(serializers.ModelSerializer):
    phases = PhaseSerializer(many=True, read_only=True)
    target_competition_detail = CompetitionSerializer(source="target_competition", read_only=True)
    current_week_number = serializers.IntegerField(read_only=True)
    current_phase = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Macrocycle
        fields = [
            "id", "athlete", "target_competition", "target_competition_detail",
            "start_date", "end_date", "total_weeks", "baseline_weekly_load",
            "is_active", "current_week_number", "current_phase", "phases",
        ]


class TrainingSessionSerializer(serializers.ModelSerializer):
    session_load = serializers.IntegerField(read_only=True)
    session_type_display = serializers.CharField(source="get_session_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    athlete_name = serializers.CharField(source="athlete.__str__", read_only=True)
    total_track_volume_m = serializers.IntegerField(read_only=True)
    total_tonnage_kg = serializers.FloatField(read_only=True)

    class Meta:
        model = TrainingSession
        fields = [
            "id", "athlete", "athlete_name", "microcycle", "date", "time_slot",
            "session_type", "session_type_display", "title", "description",
            "assigned_by", "planned_duration_min", "actual_duration_min",
            "status", "status_display", "completion_pct", "session_rpe",
            "session_load", "is_modified", "athlete_feedback", "coach_comment",
            "total_track_volume_m", "total_tonnage_kg",
        ]


class SessionDetailSerializer(TrainingSessionSerializer):
    """含 track_sets / strength_sets 的完整版。"""

    track_sets = serializers.SerializerMethodField()
    strength_sets = serializers.SerializerMethodField()

    class Meta(TrainingSessionSerializer.Meta):
        fields = TrainingSessionSerializer.Meta.fields + ["track_sets", "strength_sets"]

    def get_track_sets(self, obj):
        from training.serializers import TrackSetSerializer

        return TrackSetSerializer(obj.track_sets.all(), many=True).data

    def get_strength_sets(self, obj):
        from training.serializers import StrengthSetSerializer

        return StrengthSetSerializer(obj.strength_sets.all(), many=True).data


class CompleteSessionSerializer(serializers.Serializer):
    """打卡完成用的輸入序列化。"""

    actual_duration_min = serializers.IntegerField(min_value=1, max_value=600)
    session_rpe = serializers.IntegerField(min_value=1, max_value=10)
    completion_pct = serializers.IntegerField(min_value=0, max_value=100, default=100)
    athlete_feedback = serializers.CharField(required=False, allow_blank=True)


class SessionTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionTemplate
        fields = "__all__"


class AssignTemplateSerializer(serializers.Serializer):
    """教練批次派發模板。"""

    athlete_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    date = serializers.DateField()
    time_slot = serializers.ChoiceField(choices=["AM", "PM"], default="PM")

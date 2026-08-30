from rest_framework import serializers

from accounts.models import (
    AthleteProfile,
    BodyMetricLog,
    CoachProfile,
    Event,
    PersonalBest,
    User,
)


class UserSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "role", "role_display", "phone"]


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = "__all__"


class PersonalBestSerializer(serializers.ModelSerializer):
    mark_display = serializers.CharField(read_only=True)
    event_code = serializers.CharField(source="event.code", read_only=True)

    class Meta:
        model = PersonalBest
        fields = [
            "id", "athlete", "event", "event_code", "mark", "mark_display",
            "wind", "date", "competition_name", "is_current",
        ]


class BodyMetricLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = BodyMetricLog
        fields = "__all__"


class CoachProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    athlete_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = CoachProfile
        fields = ["id", "user", "squad_name", "specialties", "certification",
                  "years_of_experience", "athlete_count"]


class AthleteProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    age = serializers.IntegerField(read_only=True)
    bmi = serializers.FloatField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    primary_event_name = serializers.CharField(source="primary_event.name_zh", read_only=True)
    personal_bests = PersonalBestSerializer(many=True, read_only=True)

    class Meta:
        model = AthleteProfile
        fields = [
            "id", "user", "coach", "birth_date", "age", "sex", "height_cm", "weight_kg",
            "bmi", "primary_event", "primary_event_name", "secondary_events",
            "training_days_per_week", "strength_experience_years", "status",
            "status_display", "school_or_club", "notes", "personal_bests",
        ]


class AthleteListSerializer(serializers.ModelSerializer):
    """教練儀表板用的精簡序列化。"""

    name = serializers.CharField(source="__str__", read_only=True)
    age = serializers.IntegerField(read_only=True)
    primary_event_name = serializers.CharField(source="primary_event.name_zh", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = AthleteProfile
        fields = ["id", "name", "age", "sex", "primary_event_name", "status", "status_display"]

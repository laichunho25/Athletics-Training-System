from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import (
    AthleteProfile,
    BodyMetricLog,
    CoachProfile,
    Event,
    PersonalBest,
)
from accounts.serializers import (
    AthleteListSerializer,
    AthleteProfileSerializer,
    BodyMetricLogSerializer,
    CoachProfileSerializer,
    EventSerializer,
    PersonalBestSerializer,
)
from core.permissions import IsOwnAthleteDataOrCoach, athlete_ids_visible_to


class ScopedToVisibleAthletesMixin:
    """把 queryset 限制在使用者可見的運動員範圍內。"""

    athlete_field = "athlete"

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(**{f"{self.athlete_field}__in": athlete_ids_visible_to(self.request.user)})


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    filterset_fields = ["category", "unit"]


class CoachProfileViewSet(viewsets.ModelViewSet):
    queryset = CoachProfile.objects.select_related("user")
    serializer_class = CoachProfileSerializer

    @action(detail=True, methods=["get"])
    def dashboard(self, request, pk=None):
        """教練團隊儀表板：全隊 ACWR / 準備度 / 傷患燈號。"""
        from analytics.services import coach_dashboard

        data = coach_dashboard(self.get_object())
        return Response(
            {
                "date": data["date"],
                "rows": [
                    {
                        "athlete_id": r["athlete"].id,
                        "name": str(r["athlete"]),
                        "status": r["status"],
                        "acwr": r["acwr"],
                        "risk_flag": r["risk_flag"],
                        "icon": r["icon"],
                        "readiness": r["readiness"],
                        "injuries": r["injuries"],
                        "today_sessions": r["today_sessions"],
                    }
                    for r in data["rows"]
                ],
            }
        )


class AthleteProfileViewSet(viewsets.ModelViewSet):
    queryset = AthleteProfile.objects.select_related("user", "primary_event", "coach")
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["status", "coach", "sex", "primary_event"]

    def get_serializer_class(self):
        return AthleteListSerializer if self.action == "list" else AthleteProfileSerializer

    def get_queryset(self):
        return super().get_queryset().filter(id__in=athlete_ids_visible_to(self.request.user))

    @action(detail=True, methods=["get"])
    def dashboard(self, request, pk=None):
        """運動員儀表板：倒數 + 分期 + 今日課表 + ACWR + 準備度。"""
        from analytics.services import athlete_dashboard
        from planning.serializers import TrainingSessionSerializer

        d = athlete_dashboard(self.get_object())
        return Response(
            {
                "date": d["date"],
                "athlete": str(d["athlete"]),
                "target_competition": (
                    {
                        "name": d["target_competition"].name,
                        "date": d["target_competition"].date,
                        "countdown": d["countdown"],
                    }
                    if d["target_competition"]
                    else None
                ),
                "current_week": d["current_week"],
                "current_phase": str(d["current_phase"]) if d["current_phase"] else None,
                "today_sessions": TrainingSessionSerializer(d["today_sessions"], many=True).data,
                "acwr": d["acwr"],
                "readiness": d["readiness"],
                "active_injuries": d["active_injuries"],
            }
        )


class PersonalBestViewSet(ScopedToVisibleAthletesMixin, viewsets.ModelViewSet):
    queryset = PersonalBest.objects.select_related("event", "athlete")
    serializer_class = PersonalBestSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["athlete", "event", "is_current"]


class BodyMetricLogViewSet(ScopedToVisibleAthletesMixin, viewsets.ModelViewSet):
    queryset = BodyMetricLog.objects.select_related("athlete")
    serializer_class = BodyMetricLogSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["athlete", "date"]

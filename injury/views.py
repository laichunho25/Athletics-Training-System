from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import IsCoachOrAdmin, IsOwnAthleteDataOrCoach, athlete_ids_visible_to
from injury import services
from injury.models import (
    ExerciseModification,
    Injury,
    PainLog,
    RehabExercise,
    RehabProtocol,
)
from injury.serializers import (
    ExerciseModificationSerializer,
    InjurySerializer,
    PainLogSerializer,
    RehabExerciseSerializer,
    RehabProtocolSerializer,
)


class InjuryViewSet(viewsets.ModelViewSet):
    queryset = Injury.objects.select_related("athlete").prefetch_related("pain_logs")
    serializer_class = InjurySerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["athlete", "status", "body_part", "injury_type"]

    def get_queryset(self):
        return super().get_queryset().filter(athlete__in=athlete_ids_visible_to(self.request.user))

    def perform_create(self, serializer):
        injury = serializer.save()
        services.sync_athlete_status(injury.athlete)

    def perform_update(self, serializer):
        injury = serializer.save()
        services.sync_athlete_status(injury.athlete)

    @action(detail=True, methods=["get"])
    def alternatives(self, request, pk=None):
        """此傷患對應的替代動作建議。"""
        return Response(services.injury_alternatives_report(self.get_object()))

    @action(detail=True, methods=["get"])
    def pain_trend(self, request, pk=None):
        days = int(request.query_params.get("days", 28))
        return Response({"days": days, "points": self.get_object().pain_trend(days)})

    @action(detail=True, methods=["get"])
    def rtp_checklist(self, request, pk=None):
        """Return-to-Play 檢核表。"""
        return Response(services.rtp_checklist(self.get_object()))


class PainLogViewSet(viewsets.ModelViewSet):
    queryset = PainLog.objects.select_related("injury__athlete")
    serializer_class = PainLogSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["injury", "date"]

    def get_queryset(self):
        return super().get_queryset().filter(
            injury__athlete__in=athlete_ids_visible_to(self.request.user)
        )

    def perform_create(self, serializer):
        log = serializer.save()
        # 疼痛超標時，自動調整當日課表
        if log.blocks_high_intensity:
            for session in log.injury.athlete.sessions.filter(date=log.date):
                services.apply_modifications(session)


class RehabProtocolViewSet(viewsets.ModelViewSet):
    queryset = RehabProtocol.objects.select_related("injury").prefetch_related("exercises")
    serializer_class = RehabProtocolSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["injury", "phase", "is_current"]

    def get_queryset(self):
        return super().get_queryset().filter(
            injury__athlete__in=athlete_ids_visible_to(self.request.user)
        )


class RehabExerciseViewSet(viewsets.ModelViewSet):
    queryset = RehabExercise.objects.select_related("protocol__injury")
    serializer_class = RehabExerciseSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["protocol"]

    def get_queryset(self):
        return super().get_queryset().filter(
            protocol__injury__athlete__in=athlete_ids_visible_to(self.request.user)
        )


class ExerciseModificationViewSet(viewsets.ModelViewSet):
    """替代動作對照表（教練維護）。"""

    queryset = ExerciseModification.objects.select_related(
        "original_exercise", "substitute_exercise"
    )
    serializer_class = ExerciseModificationSerializer
    permission_classes = [IsCoachOrAdmin]
    filterset_fields = ["original_exercise", "substitute_exercise"]

    @action(detail=False, methods=["get"])
    def by_body_part(self, request):
        """GET /api/injuries/modifications/by_body_part/?body_part=HAMSTRING"""
        part = request.query_params.get("body_part")
        if not part:
            return Response({"detail": "請提供 body_part 參數。"}, status=400)
        rows = [m for m in self.get_queryset() if m.applies_to(part)]
        return Response(self.get_serializer(rows, many=True).data)

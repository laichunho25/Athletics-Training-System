from datetime import timedelta

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import AthleteProfile
from core.permissions import IsCoachOrAdmin, IsOwnAthleteDataOrCoach, athlete_ids_visible_to
from planning.models import (
    Competition,
    CompetitionEntry,
    Macrocycle,
    Microcycle,
    SessionTemplate,
    TrainingSession,
)
from planning.serializers import (
    AssignTemplateSerializer,
    CompetitionEntrySerializer,
    CompetitionSerializer,
    CompleteSessionSerializer,
    MacrocycleSerializer,
    MicrocycleSerializer,
    SessionDetailSerializer,
    SessionTemplateSerializer,
    TrainingSessionSerializer,
)


class CompetitionViewSet(viewsets.ModelViewSet):
    queryset = Competition.objects.all()
    serializer_class = CompetitionSerializer
    permission_classes = [IsCoachOrAdmin]
    filterset_fields = ["level", "is_target"]

    @action(detail=False, methods=["get"])
    def target(self, request):
        """目前的主目標賽事（含倒數）。"""
        from datetime import date

        comp = Competition.objects.filter(is_target=True, date__gte=date.today()).first()
        if comp is None:
            return Response({"detail": "尚未設定主目標賽事。"}, status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(comp).data)


class CompetitionEntryViewSet(viewsets.ModelViewSet):
    queryset = CompetitionEntry.objects.select_related("competition", "event", "athlete")
    serializer_class = CompetitionEntrySerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["athlete", "competition", "event"]

    def get_queryset(self):
        return super().get_queryset().filter(athlete__in=athlete_ids_visible_to(self.request.user))


class MacrocycleViewSet(viewsets.ModelViewSet):
    queryset = Macrocycle.objects.select_related("athlete", "target_competition")
    serializer_class = MacrocycleSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["athlete", "is_active"]

    def get_queryset(self):
        return super().get_queryset().filter(athlete__in=athlete_ids_visible_to(self.request.user))

    @action(detail=True, methods=["post"])
    def generate(self, request, pk=None):
        """一鍵產生 16 週分期 + 每週 Microcycle。"""
        macro = self.get_object()
        phases = macro.generate_phases()
        micros = macro.generate_microcycles()
        return Response(
            {
                "detail": f"已建立 {len(phases)} 個分期、{len(micros)} 個週計劃。",
                "macrocycle": self.get_serializer(macro).data,
            }
        )


class MicrocycleViewSet(viewsets.ModelViewSet):
    queryset = Microcycle.objects.select_related("macrocycle", "phase")
    serializer_class = MicrocycleSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["macrocycle", "week_number"]

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(macrocycle__athlete__in=athlete_ids_visible_to(self.request.user))
        )


class TrainingSessionViewSet(viewsets.ModelViewSet):
    queryset = TrainingSession.objects.select_related("athlete", "assigned_by").prefetch_related(
        "track_sets", "strength_sets"
    )
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["athlete", "status", "session_type", "date", "is_modified"]
    ordering_fields = ["date", "created_at"]

    def get_serializer_class(self):
        if self.action in ("retrieve", "create", "update", "partial_update"):
            return SessionDetailSerializer
        return TrainingSessionSerializer

    def get_queryset(self):
        qs = super().get_queryset().filter(athlete__in=athlete_ids_visible_to(self.request.user))
        params = self.request.query_params
        if params.get("date_from"):
            qs = qs.filter(date__gte=params["date_from"])
        if params.get("date_to"):
            qs = qs.filter(date__lte=params["date_to"])
        return qs

    @action(detail=False, methods=["get"])
    def calendar(self, request):
        """日曆視圖：?athlete=1&year=2026&month=8 回傳該月所有課表。"""
        from datetime import date

        athlete_id = request.query_params.get("athlete")
        year = int(request.query_params.get("year", date.today().year))
        month = int(request.query_params.get("month", date.today().month))
        start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)

        qs = self.get_queryset().filter(date__gte=start, date__lte=end)
        if athlete_id:
            qs = qs.filter(athlete_id=athlete_id)

        days = {}
        for s in qs:
            days.setdefault(str(s.date), []).append(TrainingSessionSerializer(s).data)
        return Response({"start": start, "end": end, "days": days})

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """運動員打卡完成。"""
        session = self.get_object()
        serializer = CompleteSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        session.mark_complete(
            duration_min=data["actual_duration_min"],
            rpe=data["session_rpe"],
            completion_pct=data["completion_pct"],
            feedback=data.get("athlete_feedback", ""),
        )
        from analytics.services import acwr_report

        return Response(
            {
                "session": SessionDetailSerializer(session).data,
                "session_load": session.session_load,
                "acwr": acwr_report(session.athlete, session.date),
            }
        )

    @action(detail=True, methods=["post"])
    def apply_injury_modifications(self, request, pk=None):
        """依當前傷患自動調整此課表。"""
        from injury.services import apply_modifications

        session = self.get_object()
        changes = apply_modifications(session)
        return Response(
            {
                "changes": changes,
                "session": SessionDetailSerializer(session).data,
            }
        )


class SessionTemplateViewSet(viewsets.ModelViewSet):
    queryset = SessionTemplate.objects.select_related("coach")
    serializer_class = SessionTemplateSerializer
    permission_classes = [IsCoachOrAdmin]
    filterset_fields = ["coach", "session_type"]

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """批次派發模板給多名運動員。"""
        template = self.get_object()
        serializer = AssignTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        visible = set(athlete_ids_visible_to(request.user))
        created = []
        for athlete in AthleteProfile.objects.filter(id__in=data["athlete_ids"]):
            if athlete.id not in visible:
                continue
            micro = (
                Microcycle.objects.filter(
                    macrocycle__athlete=athlete,
                    macrocycle__is_active=True,
                    start_date__lte=data["date"],
                    start_date__gte=data["date"] - timedelta(days=6),
                ).first()
            )
            created.append(
                template.clone_to_session(
                    athlete, data["date"], microcycle=micro, time_slot=data["time_slot"]
                )
            )

        return Response(
            {
                "detail": f"已派發給 {len(created)} 名運動員。",
                "sessions": TrainingSessionSerializer(created, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )

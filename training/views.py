from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import IsOwnAthleteDataOrCoach, athlete_ids_visible_to
from training.models import (
    Exercise,
    NeuromuscularTest,
    OneRepMax,
    RepSplit,
    StrengthSet,
    TrackSet,
    brzycki_1rm,
    epley_1rm,
)
from training.serializers import (
    ExerciseSerializer,
    NeuromuscularTestSerializer,
    OneRMCalculatorSerializer,
    OneRepMaxSerializer,
    RepSplitSerializer,
    StrengthSetSerializer,
    TrackSetSerializer,
)


class SessionScopedMixin:
    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(session__athlete__in=athlete_ids_visible_to(self.request.user))
        )


class ExerciseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Exercise.objects.all()
    serializer_class = ExerciseSerializer
    filterset_fields = ["category", "is_measured_by_1rm", "is_plyometric"]

    @action(detail=False, methods=["post"])
    def estimate_1rm(self, request):
        """1RM 推估：同時回傳 Epley 與 Brzycki。"""
        serializer = OneRMCalculatorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        w = serializer.validated_data["weight_kg"]
        r = serializer.validated_data["reps"]
        return Response(
            {
                "weight_kg": w,
                "reps": r,
                "epley": epley_1rm(w, r),
                "brzycki": brzycki_1rm(w, r),
            }
        )

    @action(detail=True, methods=["get"])
    def percentage_table(self, request, pk=None):
        """指定運動員的 %1RM 配重表：?athlete=1"""
        from accounts.models import AthleteProfile

        athlete_id = request.query_params.get("athlete")
        athlete = AthleteProfile.objects.filter(
            id=athlete_id, id__in=athlete_ids_visible_to(request.user)
        ).first()
        if athlete is None:
            return Response({"detail": "請提供有效的 athlete 參數。"}, status=400)

        record = OneRepMax.latest_for(athlete, self.get_object())
        if record is None:
            return Response({"detail": "此運動員尚無該動作的 1RM 紀錄。"}, status=404)

        return Response(
            {
                "exercise": self.get_object().name_zh,
                "one_rm": record.value_kg,
                "test_date": record.test_date,
                "table": [
                    {"pct": p, "weight_kg": record.load_at(p)}
                    for p in range(50, 105, 5)
                ],
            }
        )


class TrackSetViewSet(SessionScopedMixin, viewsets.ModelViewSet):
    queryset = TrackSet.objects.select_related("session").prefetch_related("splits")
    serializer_class = TrackSetSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["session", "distance_m", "surface"]


class RepSplitViewSet(viewsets.ModelViewSet):
    queryset = RepSplit.objects.select_related("track_set")
    serializer_class = RepSplitSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["track_set"]

    def get_queryset(self):
        return super().get_queryset().filter(
            track_set__session__athlete__in=athlete_ids_visible_to(self.request.user)
        )


class StrengthSetViewSet(SessionScopedMixin, viewsets.ModelViewSet):
    queryset = StrengthSet.objects.select_related("session", "exercise")
    serializer_class = StrengthSetSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["session", "exercise"]


class OneRepMaxViewSet(viewsets.ModelViewSet):
    queryset = OneRepMax.objects.select_related("athlete", "exercise")
    serializer_class = OneRepMaxSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["athlete", "exercise", "is_estimated"]

    def get_queryset(self):
        return super().get_queryset().filter(athlete__in=athlete_ids_visible_to(self.request.user))


class NeuromuscularTestViewSet(viewsets.ModelViewSet):
    queryset = NeuromuscularTest.objects.select_related("athlete")
    serializer_class = NeuromuscularTestSerializer
    permission_classes = [IsOwnAthleteDataOrCoach]
    filterset_fields = ["athlete", "test_type", "date"]

    def get_queryset(self):
        return super().get_queryset().filter(athlete__in=athlete_ids_visible_to(self.request.user))

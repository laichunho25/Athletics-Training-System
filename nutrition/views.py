from datetime import date

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AthleteProfile
from core.permissions import IsOwnAthleteDataOrCoach, athlete_ids_visible_to
from nutrition import services
from nutrition.models import (
    MealLog,
    NutritionTarget,
    RecoveryLog,
    RecoveryMethod,
    SupplementLog,
)
from nutrition.serializers import (
    MealLogSerializer,
    NutritionTargetSerializer,
    RecoveryLogSerializer,
    RecoveryMethodSerializer,
    SupplementLogSerializer,
)


class AthleteScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOwnAthleteDataOrCoach]

    def get_queryset(self):
        return super().get_queryset().filter(athlete__in=athlete_ids_visible_to(self.request.user))


class NutritionTargetViewSet(AthleteScopedViewSet):
    queryset = NutritionTarget.objects.select_related("athlete")
    serializer_class = NutritionTargetSerializer
    filterset_fields = ["athlete", "date", "day_type"]

    @action(detail=False, methods=["post"])
    def calculate(self, request):
        """
        POST /api/nutrition/targets/calculate/
        {"athlete": 1, "date": "2026-08-10", "goal": "MAINTAIN", "day_type": null}
        day_type 留空則依當日課表自動推斷。
        """
        athlete = AthleteProfile.objects.filter(
            id=request.data.get("athlete"), id__in=athlete_ids_visible_to(request.user)
        ).first()
        if athlete is None:
            return Response({"detail": "找不到此運動員或無權限。"}, status=404)

        on_date = request.data.get("date")
        on_date = date.fromisoformat(on_date) if on_date else date.today()
        target = services.calculate_targets(
            athlete,
            on_date,
            day_type=request.data.get("day_type") or None,
            goal=request.data.get("goal", "MAINTAIN"),
        )
        return Response(NutritionTargetSerializer(target).data)


class MealLogViewSet(AthleteScopedViewSet):
    queryset = MealLog.objects.select_related("athlete")
    serializer_class = MealLogSerializer
    filterset_fields = ["athlete", "date", "meal_type"]


class SupplementLogViewSet(AthleteScopedViewSet):
    queryset = SupplementLog.objects.select_related("athlete")
    serializer_class = SupplementLogSerializer
    filterset_fields = ["athlete", "date"]

    @action(detail=False, methods=["get"])
    def common(self, request):
        """常見補充劑參考清單。"""
        return Response(
            [
                {"name": n, "dose": d, "timing": t, "purpose": p}
                for n, d, t, p in services.COMMON_SUPPLEMENTS
            ]
        )


class RecoveryMethodViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RecoveryMethod.objects.all()
    serializer_class = RecoveryMethodSerializer


class RecoveryLogViewSet(AthleteScopedViewSet):
    queryset = RecoveryLog.objects.select_related("athlete").prefetch_related("methods")
    serializer_class = RecoveryLogSerializer
    filterset_fields = ["athlete", "date"]


class WeeklyComplianceView(APIView):
    """GET /api/nutrition/compliance/<athlete_id>/?week_start=2026-08-10"""

    def get(self, request, athlete_id):
        from analytics.services import monday_of

        athlete = AthleteProfile.objects.filter(
            id=athlete_id, id__in=athlete_ids_visible_to(request.user)
        ).first()
        if athlete is None:
            return Response({"detail": "找不到此運動員或無權限。"}, status=404)
        ws = request.query_params.get("week_start")
        ws = date.fromisoformat(ws) if ws else monday_of(date.today())
        return Response({"week_start": ws, "days": services.weekly_compliance(athlete, ws)})

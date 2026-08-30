from datetime import date, timedelta

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AthleteProfile, Event
from analytics import services
from analytics.models import DailyLoad, WeeklySummary
from analytics.serializers import DailyLoadSerializer, WeeklySummarySerializer
from core.permissions import athlete_ids_visible_to


def _get_athlete(request, athlete_id):
    return AthleteProfile.objects.filter(
        id=athlete_id, id__in=athlete_ids_visible_to(request.user)
    ).first()


class DailyLoadViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DailyLoad.objects.select_related("athlete")
    serializer_class = DailyLoadSerializer
    filterset_fields = ["athlete", "date"]

    def get_queryset(self):
        return super().get_queryset().filter(athlete__in=athlete_ids_visible_to(self.request.user))


class WeeklySummaryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WeeklySummary.objects.select_related("athlete")
    serializer_class = WeeklySummarySerializer
    filterset_fields = ["athlete", "week_start", "risk_flag"]

    def get_queryset(self):
        return super().get_queryset().filter(athlete__in=athlete_ids_visible_to(self.request.user))


class ACWRView(APIView):
    """GET /api/analytics/acwr/<athlete_id>/?date=2026-08-09"""

    def get(self, request, athlete_id):
        athlete = _get_athlete(request, athlete_id)
        if athlete is None:
            return Response({"detail": "找不到此運動員或無權限。"}, status=404)
        on_date = request.query_params.get("date")
        on_date = date.fromisoformat(on_date) if on_date else date.today()
        return Response(services.acwr_report(athlete, on_date))


class LoadProgressionView(APIView):
    """GET /api/analytics/load-progression/<athlete_id>/?weeks=12 — 柱狀圖 + ACWR 折線"""

    def get(self, request, athlete_id):
        athlete = _get_athlete(request, athlete_id)
        if athlete is None:
            return Response({"detail": "找不到此運動員或無權限。"}, status=404)
        weeks = int(request.query_params.get("weeks", 12))
        rows = services.weekly_load_progression(athlete, weeks)
        return Response(
            {
                "labels": [r["label"] for r in rows],
                "datasets": {
                    "total_load": [r["total_load"] for r in rows],
                    "acwr": [r["acwr"] for r in rows],
                    "monotony": [r["monotony"] for r in rows],
                },
                "rows": rows,
            }
        )


class PerformanceTrendView(APIView):
    """GET /api/analytics/trend/<athlete_id>/?event=400M&days=365"""

    def get(self, request, athlete_id):
        athlete = _get_athlete(request, athlete_id)
        if athlete is None:
            return Response({"detail": "找不到此運動員或無權限。"}, status=404)
        code = request.query_params.get("event")
        event = Event.objects.filter(code=code).first() if code else athlete.primary_event
        if event is None:
            return Response({"detail": "找不到項目。"}, status=404)
        days = int(request.query_params.get("days", 365))
        return Response(services.performance_trend(athlete, event, days))


class StrengthTrendView(APIView):
    """GET /api/analytics/strength-trend/<athlete_id>/?exercise=BACK_SQUAT"""

    def get(self, request, athlete_id):
        from training.models import Exercise

        athlete = _get_athlete(request, athlete_id)
        if athlete is None:
            return Response({"detail": "找不到此運動員或無權限。"}, status=404)
        exercise = Exercise.objects.filter(code=request.query_params.get("exercise")).first()
        if exercise is None:
            return Response({"detail": "請提供有效的 exercise 代碼。"}, status=400)
        days = int(request.query_params.get("days", 365))
        return Response(services.strength_trend(athlete, exercise, days))


class VolumeDistributionView(APIView):
    """GET /api/analytics/volume-distribution/<athlete_id>/?days=28 — 圓餅圖"""

    def get(self, request, athlete_id):
        athlete = _get_athlete(request, athlete_id)
        if athlete is None:
            return Response({"detail": "找不到此運動員或無權限。"}, status=404)
        days = int(request.query_params.get("days", 28))
        return Response({"days": days, "distribution": services.volume_distribution(athlete, days)})


class ReadinessView(APIView):
    """GET /api/analytics/readiness/<athlete_id>/"""

    def get(self, request, athlete_id):
        athlete = _get_athlete(request, athlete_id)
        if athlete is None:
            return Response({"detail": "找不到此運動員或無權限。"}, status=404)
        on_date = request.query_params.get("date")
        on_date = date.fromisoformat(on_date) if on_date else date.today()
        return Response(services.readiness_score(athlete, on_date))


class RebuildView(APIView):
    """POST /api/analytics/rebuild/<athlete_id>/ — 回填近 N 天彙總。"""

    def post(self, request, athlete_id):
        athlete = _get_athlete(request, athlete_id)
        if athlete is None:
            return Response({"detail": "找不到此運動員或無權限。"}, status=404)
        days = int(request.data.get("days", 90))
        services.rebuild_all(athlete, days)
        return Response({"detail": f"已重算 {athlete} 近 {days} 天的負荷彙總。"})

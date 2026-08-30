from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts import views as accounts_views
from analytics import views as analytics_views
from injury import views as injury_views
from nutrition import views as nutrition_views
from planning import views as planning_views
from training import views as training_views

router = DefaultRouter()

# 模組 1 — Profile & 目標
router.register("events", accounts_views.EventViewSet)
router.register("coaches", accounts_views.CoachProfileViewSet)
router.register("athletes", accounts_views.AthleteProfileViewSet)
router.register("personal-bests", accounts_views.PersonalBestViewSet)
router.register("body-metrics", accounts_views.BodyMetricLogViewSet)

# 模組 2 — 日程與計劃
router.register("competitions", planning_views.CompetitionViewSet)
router.register("competition-entries", planning_views.CompetitionEntryViewSet)
router.register("macrocycles", planning_views.MacrocycleViewSet)
router.register("microcycles", planning_views.MicrocycleViewSet)
router.register("sessions", planning_views.TrainingSessionViewSet)
router.register("session-templates", planning_views.SessionTemplateViewSet)

# 模組 3 — 專項與力量
router.register("exercises", training_views.ExerciseViewSet)
router.register("track-sets", training_views.TrackSetViewSet)
router.register("rep-splits", training_views.RepSplitViewSet)
router.register("strength-sets", training_views.StrengthSetViewSet)
router.register("one-rms", training_views.OneRepMaxViewSet)
router.register("nm-tests", training_views.NeuromuscularTestViewSet)

# 模組 4 — 分析
router.register("daily-loads", analytics_views.DailyLoadViewSet)
router.register("weekly-summaries", analytics_views.WeeklySummaryViewSet)

# 模組 5 — 營養與恢復
router.register("nutrition/targets", nutrition_views.NutritionTargetViewSet)
router.register("nutrition/meals", nutrition_views.MealLogViewSet)
router.register("nutrition/supplements", nutrition_views.SupplementLogViewSet)
router.register("nutrition/recovery-methods", nutrition_views.RecoveryMethodViewSet)
router.register("nutrition/recovery-logs", nutrition_views.RecoveryLogViewSet)

# 模組 6 — 傷患
router.register("injuries", injury_views.InjuryViewSet)
router.register("pain-logs", injury_views.PainLogViewSet)
router.register("rehab-protocols", injury_views.RehabProtocolViewSet)
router.register("rehab-exercises", injury_views.RehabExerciseViewSet)
router.register("exercise-modifications", injury_views.ExerciseModificationViewSet)

analytics_urls = [
    path("acwr/<int:athlete_id>/", analytics_views.ACWRView.as_view(), name="acwr"),
    path(
        "load-progression/<int:athlete_id>/",
        analytics_views.LoadProgressionView.as_view(),
        name="load-progression",
    ),
    path("trend/<int:athlete_id>/", analytics_views.PerformanceTrendView.as_view(), name="trend"),
    path(
        "strength-trend/<int:athlete_id>/",
        analytics_views.StrengthTrendView.as_view(),
        name="strength-trend",
    ),
    path(
        "volume-distribution/<int:athlete_id>/",
        analytics_views.VolumeDistributionView.as_view(),
        name="volume-distribution",
    ),
    path("readiness/<int:athlete_id>/", analytics_views.ReadinessView.as_view(), name="readiness"),
    path("rebuild/<int:athlete_id>/", analytics_views.RebuildView.as_view(), name="rebuild"),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api/analytics/", include(analytics_urls)),
    path(
        "api/nutrition/compliance/<int:athlete_id>/",
        nutrition_views.WeeklyComplianceView.as_view(),
        name="nutrition-compliance",
    ),
    path("api-auth/", include("rest_framework.urls")),
    # 登入 / 登出（django.contrib.auth 內建 views）
    path("accounts/", include("django.contrib.auth.urls")),
    # 公開報名
    path("programs/", include("programs.urls")),
    # HTML 前端
    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

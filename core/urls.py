from django.urls import path

from core import views

app_name = "web"

urlpatterns = [
    path("", views.landing, name="landing"),        # 公開首頁
    path("healthz", views.healthz, name="healthz"),  # Render 健康檢查
    path("app/", views.home, name="home"),          # 登入後分流
    path("athletes/", views.athlete_list, name="athlete_list"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("athlete/<int:pk>/plan/", views.athlete_plan_edit, name="athlete_plan_edit"),
    path("team/", views.coach_dashboard, name="coach_dashboard"),
    path("plan/", views.plan_view, name="plan"),
    path("plan/<int:pk>/", views.plan_detail, name="plan_detail"),
    path("calendar/", views.calendar_view, name="calendar"),
    path("session/<int:pk>/", views.session_detail, name="session_detail"),
    # 點格子即改 + 輪詢同步
    path("cell/", views.inline_edit, name="inline_edit"),
    path("session/<int:pk>/live/", views.session_live, name="session_live"),
    path("calendar/live/", views.calendar_live, name="calendar_live"),
    path("analytics/", views.analytics_view, name="analytics"),
    path("nutrition/", views.nutrition_view, name="nutrition"),
    path("injuries/", views.injuries_view, name="injuries"),
]

from django.urls import path

from programs import views

app_name = "programs"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("<slug:slug>/", views.project_detail, name="detail"),
    path("<slug:slug>/apply/", views.apply_view, name="apply"),
    path("<slug:slug>/done/", views.apply_done, name="done"),
]

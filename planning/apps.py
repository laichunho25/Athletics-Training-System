from django.apps import AppConfig


class PlanningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "planning"
    verbose_name = "模組2 日程與訓練計劃"

    def ready(self):
        from planning import signals  # noqa: F401

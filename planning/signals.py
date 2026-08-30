from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from planning.models import TrainingSession


@receiver([post_save, post_delete], sender=TrainingSession)
def refresh_load_caches(sender, instance, **kwargs):
    """課表變動 → 重算當日 DailyLoad、所屬 Microcycle 實際負荷、當週彙總。"""
    from analytics.services import monday_of, rebuild_daily_load, rebuild_weekly_summary

    rebuild_daily_load(instance.athlete, instance.date)
    rebuild_weekly_summary(instance.athlete, monday_of(instance.date))
    if instance.microcycle_id:
        try:
            instance.microcycle.recalculate_actual_load()
        except Exception:  # microcycle 已被刪除
            pass

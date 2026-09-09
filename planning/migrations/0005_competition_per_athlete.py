# 賽事由「全系統共用」改成「掛在運動員底下」，並加入熱身賽 / 備戰對象。
#
# 舊資料裡同一場比賽可能被多名運動員用著，所以資料遷移會按運動員把它複製開，
# 每人一份，之後誰改自己那份都不會影響別人。
import django.db.models.deletion
from django.db import migrations, models


def split_competitions_per_athlete(apps, schema_editor):
    Competition = apps.get_model("planning", "Competition")
    Macrocycle = apps.get_model("planning", "Macrocycle")
    CompetitionEntry = apps.get_model("planning", "CompetitionEntry")
    MetricRecord = apps.get_model("analytics", "MetricRecord")

    for comp in Competition.objects.all():
        athlete_ids = set(
            Macrocycle.objects.filter(target_competition=comp).values_list("athlete_id", flat=True)
        ) | set(
            CompetitionEntry.objects.filter(competition=comp).values_list("athlete_id", flat=True)
        ) | set(
            MetricRecord.objects.filter(competition=comp).values_list("athlete_id", flat=True)
        )
        athlete_ids = sorted(i for i in athlete_ids if i)
        if not athlete_ids:
            continue

        keeper, others = athlete_ids[0], athlete_ids[1:]
        for athlete_id in others:
            clone = Competition.objects.create(
                athlete_id=athlete_id,
                name=comp.name,
                date=comp.date,
                end_date=comp.end_date,
                venue=comp.venue,
                level=comp.level,
                is_target=comp.is_target,
            )
            Macrocycle.objects.filter(target_competition=comp, athlete_id=athlete_id).update(
                target_competition=clone
            )
            CompetitionEntry.objects.filter(competition=comp, athlete_id=athlete_id).update(
                competition=clone
            )
            MetricRecord.objects.filter(competition=comp, athlete_id=athlete_id).update(
                competition=clone
            )

        Competition.objects.filter(pk=comp.pk).update(athlete_id=keeper)


def noop(apps, schema_editor):
    """反向遷移只會拿掉欄位，複製出來的賽事留著也不礙事。"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("analytics", "0005_metricitem_name_en_metricrecord_competition"),
        ("planning", "0004_alter_phase_phase_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="competition",
            name="athlete",
            field=models.ForeignKey(
                blank=True,
                help_text="每名運動員的賽事各自獨立；留空是舊資料，誰先用就歸誰",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="competitions",
                to="accounts.athleteprofile",
                verbose_name="所屬運動員",
            ),
        ),
        migrations.AddField(
            model_name="competition",
            name="is_warmup",
            field=models.BooleanField(
                default=False, help_text="練兵性質的比賽，不是備戰週期的終點", verbose_name="熱身賽"
            ),
        ),
        migrations.AddField(
            model_name="competition",
            name="prep_for",
            field=models.ForeignKey(
                blank=True,
                help_text="只有熱身賽用得著；總週數會以這一場重要比賽來計算",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="warmups",
                to="planning.competition",
                verbose_name="為哪一場重要比賽備戰",
            ),
        ),
        migrations.RunPython(split_competitions_per_athlete, noop),
    ]

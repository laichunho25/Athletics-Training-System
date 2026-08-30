"""
重算所有運動員的負荷彙總（DailyLoad / WeeklySummary）。
建議用 Celery beat 或 Windows 排程每日 00:30 執行。

    python manage.py rebuild_analytics --days 90
    python manage.py rebuild_analytics --athlete 1
"""

from django.core.management.base import BaseCommand

from accounts.models import AthleteProfile
from analytics.services import acwr_report, rebuild_all


class Command(BaseCommand):
    help = "重算負荷彙總並列出高風險運動員"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90)
        parser.add_argument("--athlete", type=int, default=None, help="只處理指定 AthleteProfile id")

    def handle(self, *args, **options):
        qs = AthleteProfile.objects.all()
        if options["athlete"]:
            qs = qs.filter(id=options["athlete"])

        alerts = []
        for athlete in qs:
            rebuild_all(athlete, options["days"])
            report = acwr_report(athlete)
            self.stdout.write(
                f"{report['icon']} {athlete} — ACWR {report['acwr']} "
                f"(急性 {report['acute_load']} / 慢性 {report['chronic_load']}) "
                f"{report['risk_label']}"
            )
            if report["risk_flag"] == "HIGH":
                alerts.append((athlete, report))

        if alerts:
            self.stdout.write(self.style.ERROR(f"\n⚠️ {len(alerts)} 名運動員處於高受傷風險："))
            for athlete, report in alerts:
                self.stdout.write(f"   • {athlete}: {report['advice']}")
        else:
            self.stdout.write(self.style.SUCCESS("\n✅ 無高風險警示。"))

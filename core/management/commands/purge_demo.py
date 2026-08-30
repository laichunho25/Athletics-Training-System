"""
刪除示範帳號與其所有資料——上線前務必執行一次。

    python manage.py purge_demo
    python manage.py purge_demo --dry-run
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User

DEMO_USERNAMES = ["coach_chan", "athlete_lai", "other_athlete", "admin"]


class Command(BaseCommand):
    help = "刪除 seed_demo 建立的示範帳號（弱密碼）"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="只顯示會刪什麼，不實際刪除")

    @transaction.atomic
    def handle(self, *args, **options):
        qs = User.objects.filter(username__in=DEMO_USERNAMES)
        found = list(qs.values_list("username", "is_superuser"))

        if not found:
            self.stdout.write("沒有找到示範帳號，資料庫是乾淨的。")
            return

        for name, is_su in found:
            self.stdout.write(f"  - {name}{'（超級使用者）' if is_su else ''}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\n--dry-run：未實際刪除。"))
            return

        remaining = User.objects.filter(is_superuser=True).exclude(
            username__in=DEMO_USERNAMES
        ).count()
        if remaining == 0:
            self.stdout.write(
                self.style.ERROR(
                    "\n中止：刪除後將沒有任何超級使用者。"
                    "請先執行 `python manage.py create_admin` 建立你自己的管理員。"
                )
            )
            return

        count = qs.delete()[0]
        self.stdout.write(self.style.SUCCESS(f"\n已刪除 {count} 筆相關資料（含連動的課表與紀錄）。"))

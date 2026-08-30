"""部署後健檢：確認資料庫裡真的有帳號可以登入。

正式環境用的是全新的 PostgreSQL，本機 db.sqlite3 不會跟著推上去；
若沒設 ADMIN_USERNAME / ADMIN_PASSWORD，build 會建不出任何帳號，
結果就是 /admin/ 與 /accounts/login/ 兩邊都登入不了。
這個指令把狀況直接印在 Render 的 build log 上。
"""

import os

from django.core.management.base import BaseCommand

from accounts.models import User
from core.db_info import describe_database, is_sqlite
from core.models import Role

RULE = "=" * 64


class Command(BaseCommand):
    help = "列出目前資料庫的帳號數量，沒有可用管理員時發出警告"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-empty",
            action="store_true",
            help="完全沒有帳號時以非零狀態結束（想讓部署直接失敗時使用）",
        )

    def handle(self, *args, **options):
        self.stdout.write(f"目前連線的資料庫：{describe_database()}")

        # 正式環境卻連到 SQLite＝這一步沒讀到 DATABASE_URL。
        # 帳號會寫進容器裡的暫存檔、隨部署消失，上線後當然登不進去。
        if is_sqlite() and os.environ.get("DJANGO_DEBUG", "1") != "1":
            self.stderr.write(
                self.style.ERROR(
                    "\n".join(
                        [
                            "",
                            RULE,
                            "警告：DJANGO_DEBUG=0（正式環境）卻連到 SQLite，"
                            "代表這一步沒讀到 DATABASE_URL。",
                            "現在寫進去的帳號與資料都會隨容器消失，上線後一定登不進去。",
                            "請確認 Environment 裡有 DATABASE_URL"
                            "（Blueprint 會由 fromDatabase 自動注入；"
                            "手動建立的服務要自己加）。",
                            RULE,
                            "",
                        ]
                    )
                )
            )

        total = User.objects.count()
        supers = User.objects.filter(is_superuser=True, is_active=True)
        coaches = User.objects.filter(role=Role.COACH, is_active=True).count()
        athletes = User.objects.filter(role=Role.ATHLETE, is_active=True).count()

        self.stdout.write(
            f"帳號統計：總數 {total}／管理員 {supers.count()}"
            f"／教練 {coaches}／運動員 {athletes}"
        )
        if supers:
            self.stdout.write("可用管理員：" + "、".join(u.username for u in supers))
            self.stdout.write(self.style.SUCCESS("帳號檢查通過。"))
            return

        self.stderr.write(
            self.style.ERROR(
                "\n".join(
                    [
                        "",
                        RULE,
                        "警告：資料庫沒有任何可用的管理員帳號，現在沒有人登入得了。",
                        "請在 Render → Environment 設定下列變數後重新部署：",
                        "    ADMIN_USERNAME=<帳號>",
                        "    ADMIN_EMAIL=<電郵>",
                        "    ADMIN_PASSWORD=<至少 12 個字元的強密碼>",
                        "或直接在 Render Shell 執行：python manage.py create_admin",
                        RULE,
                        "",
                    ]
                )
            )
        )
        if options["fail_on_empty"] and total == 0:
            raise SystemExit(1)

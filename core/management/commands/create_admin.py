"""
從環境變數建立/更新管理員帳號——正式環境專用。

正式站請勿使用 `seed_demo`（內含 atm12345 之類的弱密碼示範帳號）。
Render 上設好環境變數後，在 Shell 執行：

    python manage.py create_admin

    ADMIN_USERNAME=boyce
    ADMIN_EMAIL=laichunho25@gmail.com
    ADMIN_PASSWORD=<強密碼>
"""

import os

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from core.models import Role


class Command(BaseCommand):
    help = "從環境變數建立或更新超級使用者"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-if-unset",
            action="store_true",
            help="環境變數未設定時安靜跳過（給 build.sh 用，避免整個部署失敗）",
        )

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME")
        password = os.environ.get("ADMIN_PASSWORD")
        email = os.environ.get("ADMIN_EMAIL", "")

        if not username or not password:
            if options["skip_if_unset"]:
                self.stdout.write(
                    "未設定 ADMIN_USERNAME / ADMIN_PASSWORD，跳過建立管理員。"
                )
                return
            raise CommandError("請先設定環境變數 ADMIN_USERNAME 與 ADMIN_PASSWORD。")
        if len(password) < 12:
            if options["skip_if_unset"]:
                self.stderr.write("ADMIN_PASSWORD 太短（需 12 字元以上），跳過。")
                return
            raise CommandError("密碼太短，正式環境請至少 12 個字元。")

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "role": Role.ADMIN},
        )
        user.email = email or user.email
        user.role = Role.ADMIN
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        verb = "已建立" if created else "已更新"
        self.stdout.write(self.style.SUCCESS(f"{verb}管理員：{username}"))

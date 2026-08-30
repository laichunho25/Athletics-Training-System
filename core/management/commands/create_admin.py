"""
從環境變數建立/更新管理員帳號——正式環境專用。

正式站請勿使用 `seed_demo`（內含 atm12345 之類的弱密碼示範帳號）。
Render 上設好環境變數後，在 Shell 執行：

    python manage.py create_admin

    ADMIN_USERNAME=coachlai
    ADMIN_EMAIL=laichunho25@gmail.com
    ADMIN_PASSWORD=<強密碼>
"""

import os

from django.contrib.auth import authenticate
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from core.db_info import describe_database
from core.models import Role

MIN_PASSWORD_LEN = 12


class Command(BaseCommand):
    help = "從環境變數建立或更新超級使用者"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-if-unset",
            action="store_true",
            help=(
                "ADMIN_USERNAME / ADMIN_PASSWORD 完全沒設定時安靜跳過（給 build.sh 用）。"
                "注意：有設但不合格（例如密碼太短）仍會報錯，不會被跳過。"
            ),
        )

    def handle(self, *args, **options):
        # Render Dashboard 貼上的值常常夾帶前後空白／換行，會讓密碼永遠對不上
        username = (os.environ.get("ADMIN_USERNAME") or "").strip()
        password = (os.environ.get("ADMIN_PASSWORD") or "").strip()
        email = (os.environ.get("ADMIN_EMAIL") or "").strip()

        raw_password = os.environ.get("ADMIN_PASSWORD") or ""
        if raw_password != password and password:
            self.stderr.write(
                self.style.WARNING(
                    "注意：ADMIN_PASSWORD 前後有空白或換行，已自動去除；"
                    "登入時請用去掉空白後的密碼。"
                )
            )

        # 連資料庫都連錯就什麼都別談了——把真正用到的資料庫印出來
        self.stdout.write(f"目前連線的資料庫：{describe_database()}")

        if not username or not password:
            if options["skip_if_unset"]:
                self.stdout.write(
                    "未設定 ADMIN_USERNAME / ADMIN_PASSWORD，跳過建立管理員。"
                )
                return
            raise CommandError("請先設定環境變數 ADMIN_USERNAME 與 ADMIN_PASSWORD。")

        # 變數「有設但不合格」是設定錯誤，不是「沒打算建管理員」：
        # 這種情況一定要吵，否則部署會安靜地生出一個沒人登得進去的站。
        if len(password) < MIN_PASSWORD_LEN:
            raise CommandError(
                f"ADMIN_PASSWORD 只有 {len(password)} 個字元，"
                f"正式環境需要至少 {MIN_PASSWORD_LEN} 個。"
                "請到 Render → Environment 換一個更長的密碼後重新部署。"
            )

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "role": Role.ADMIN},
        )
        user.email = email or user.email
        user.role = Role.ADMIN
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True          # 曾被停用的帳號也一併復原
        user.set_password(password)
        user.save()

        # 立刻驗證一次：確認這組帳密真的能通過 Django 的認證流程
        if authenticate(username=username, password=password) is None:
            raise CommandError(
                f"帳號 {username} 已寫入，但立即以同一組密碼驗證卻失敗——"
                "請檢查是否有自訂的認證後端或密碼雜湊設定。"
            )

        verb = "已建立" if created else "已更新"
        self.stdout.write(
            self.style.SUCCESS(f"{verb}管理員：{username}（已通過登入驗證）")
        )

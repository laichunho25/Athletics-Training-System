"""create_admin / check_accounts 的行為測試。

這兩個指令是正式站唯一的「開帳號」途徑，一旦安靜失敗，
整個網站就會變成沒有人登得進去——所以失敗模式要一條一條釘住。
"""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import User
from core.models import Role


def run(cmd="create_admin", **env):
    """帶著指定環境變數執行指令，回傳 (stdout, stderr)。"""
    out, err = StringIO(), StringIO()
    with mock.patch.dict("os.environ", env, clear=False):
        call_command(cmd, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


class CreateAdminTests(TestCase):
    ENV = {
        "ADMIN_USERNAME": "boyce",
        "ADMIN_EMAIL": "laichunho25@gmail.com",
        "ADMIN_PASSWORD": "a-long-enough-password",
    }

    def test_creates_a_superuser_that_can_actually_log_in(self):
        run(**self.ENV)
        user = User.objects.get(username="boyce")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertEqual(user.role, Role.ADMIN)

        # /admin/ 真的收這組帳密
        resp = self.client.post(
            "/admin/login/",
            {
                "username": "boyce",
                "password": self.ENV["ADMIN_PASSWORD"],
                "next": "/admin/",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/admin/")

    def test_rerun_updates_the_password_instead_of_failing(self):
        run(**self.ENV)
        run(**{**self.ENV, "ADMIN_PASSWORD": "another-long-password"})
        self.assertEqual(User.objects.filter(username="boyce").count(), 1)
        self.assertTrue(
            self.client.login(username="boyce", password="another-long-password")
        )

    def test_whitespace_around_env_values_is_stripped(self):
        """Dashboard 貼上的值常夾帶空白／換行，不處理就永遠對不上密碼。"""
        _, err = run(
            ADMIN_USERNAME="  boyce\n",
            ADMIN_EMAIL=" laichunho25@gmail.com ",
            ADMIN_PASSWORD="  a-long-enough-password \n",
        )
        self.assertIn("空白", err)
        self.assertTrue(User.objects.filter(username="boyce").exists())
        self.assertTrue(
            self.client.login(username="boyce", password="a-long-enough-password")
        )

    def test_short_password_is_a_hard_error_even_with_skip_if_unset(self):
        """有設但太短＝設定錯誤，必須讓部署紅字失敗，不能安靜跳過。"""
        with mock.patch.dict(
            "os.environ",
            {"ADMIN_USERNAME": "boyce", "ADMIN_PASSWORD": "short"},
            clear=False,
        ):
            with self.assertRaises(CommandError) as ctx:
                call_command("create_admin", "--skip-if-unset", stdout=StringIO())
        self.assertIn("12", str(ctx.exception))
        self.assertFalse(User.objects.filter(username="boyce").exists())

    def test_unset_is_skipped_quietly_with_the_flag(self):
        with mock.patch.dict(
            "os.environ", {"ADMIN_USERNAME": "", "ADMIN_PASSWORD": ""}, clear=False
        ):
            out = StringIO()
            call_command("create_admin", "--skip-if-unset", stdout=out)
        self.assertIn("跳過", out.getvalue())
        self.assertEqual(User.objects.count(), 0)

    def test_reactivates_a_disabled_admin(self):
        User.objects.create_user(
            username="boyce", password="x", role=Role.ADMIN, is_active=False
        )
        run(**self.ENV)
        self.assertTrue(User.objects.get(username="boyce").is_active)


class CheckAccountsTests(TestCase):
    def test_warns_loudly_when_nobody_can_log_in(self):
        out, err = run("check_accounts")
        self.assertIn("沒有任何可用的管理員帳號", err)
        self.assertIn("ADMIN_USERNAME", err)
        self.assertIn("資料庫", out)

    def test_reports_the_admin_once_one_exists(self):
        run(**CreateAdminTests.ENV)
        out, err = run("check_accounts")
        self.assertIn("boyce", out)
        self.assertIn("帳號檢查通過", out)
        self.assertEqual(err, "")

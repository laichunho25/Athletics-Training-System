"""後台門禁：只有管理員進得去，教練／運動員一律擋在外面。"""

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.admin import user_may_use_admin
from core.models import Role
from core.test_factories import make_athlete, make_coach


def admin_url(name="admin:index"):
    return reverse(name)


class AdminGateTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user(
            username="coachlai",
            password="a-long-enough-password",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )

    # ------------------------------------------------------------ 放行
    def test_admin_can_open_the_dashboard(self):
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(admin_url()).status_code, 200)

    # ------------------------------------------------------------ 擋下
    def test_coach_cannot_reach_the_admin_even_when_logged_in(self):
        coach = make_coach().user
        self.client.force_login(coach)
        resp = self.client.get(admin_url(), follow=True)
        # 會先被丟去後台登入頁，但那一頁認得他沒權限，直接把他請回系統
        final_url, _ = resp.redirect_chain[-1]
        self.assertNotIn(settings.ADMIN_URL, final_url)
        body = resp.content.decode()
        self.assertNotIn("資料管理", body)          # 沒看到後台內容
        self.assertNotIn('name="password"', body)  # 也沒拿到後台登入框

    def test_athlete_cannot_reach_the_admin(self):
        self.client.force_login(make_athlete().user)
        resp = self.client.get(admin_url(), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("資料管理", resp.content.decode())

    def test_staff_flag_alone_is_not_enough(self):
        """就算誤把教練勾成 staff，也不該進得了後台。"""
        coach = make_coach(username="staffy").user
        coach.is_staff = True
        coach.save()
        self.assertFalse(user_may_use_admin(coach))

    def test_coach_login_attempt_at_admin_is_turned_away_with_a_message(self):
        self.client.force_login(make_coach(username="c2").user)
        resp = self.client.post(
            reverse("admin:login"),
            {"username": "c2", "password": "test-pw-12345"},
            follow=True,
        )
        self.assertIn("沒有後台權限", resp.content.decode())

    def test_inactive_admin_is_locked_out(self):
        self.boss.is_active = False
        self.boss.save()
        self.assertFalse(user_may_use_admin(self.boss))

    def test_anonymous_sees_no_admin_content(self):
        body = self.client.get(admin_url(), follow=True).content.decode()
        self.assertNotIn("資料管理", body)

    # -------------------------------------------------- 可再鎖到指定帳號
    def test_username_allowlist_narrows_it_further(self):
        with self.settings(ADMIN_ALLOWED_USERS=["someone_else"]):
            self.assertFalse(user_may_use_admin(self.boss))
        with self.settings(ADMIN_ALLOWED_USERS=["coachlai"]):
            self.assertTrue(user_may_use_admin(self.boss))


class AdminUrlTests(TestCase):
    def test_admin_lives_at_the_configured_url(self):
        """網址由 DJANGO_ADMIN_URL 決定，換掉之後 /admin/ 就不存在了。"""
        self.assertTrue(admin_url().startswith("/" + settings.ADMIN_URL))
        self.assertTrue(settings.ADMIN_URL.endswith("/"))
        self.assertFalse(settings.ADMIN_URL.startswith("/"))

    def test_urlconf_does_not_hardcode_the_path(self):
        from pathlib import Path

        src = (Path(settings.BASE_DIR) / "config" / "urls.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("path(settings.ADMIN_URL, admin.site.urls)", src)
        self.assertNotIn('path("admin/", admin.site.urls)', src)


class AdminLinkTests(TestCase):
    """導覽列的「後台」連結只給進得去的人看，而且要跟著設定走。"""

    def test_link_shown_to_admin(self):
        boss = User.objects.create_user(
            username="boss2", password="x", role=Role.ADMIN,
            is_staff=True, is_superuser=True,
        )
        self.client.force_login(boss)
        body = self.client.get(reverse("web:dashboard")).content.decode()
        self.assertIn(">後台</a>", body)
        self.assertIn("/" + settings.ADMIN_URL, body)

    def test_link_hidden_from_coach(self):
        self.client.force_login(make_coach(username="c3").user)
        body = self.client.get(reverse("web:coach_dashboard")).content.decode()
        self.assertNotIn(">後台</a>", body)


class CsrfFailurePageTests(TestCase):
    """CSRF 失敗要給看得懂的頁，而不是瀏覽器直接吐 403。"""

    def test_login_post_without_token_gets_the_explanation_page(self):
        client = self.client_class(enforce_csrf_checks=True)
        resp = client.post(
            reverse("login"), {"username": "x", "password": "y"}
        )
        self.assertEqual(resp.status_code, 403)
        body = resp.content.decode()
        self.assertIn("安全檢查擋下", body)
        self.assertIn("不是帳號或密碼有問題", body)
        self.assertIn(reverse("login"), body)

    def test_setting_points_at_the_view(self):
        self.assertEqual(settings.CSRF_FAILURE_VIEW, "core.views.csrf_failure")


class AdminFirstLoginFlowTests(TestCase):
    """管理員登入後那一連串轉址不能爆掉——這是「一登入就死 error」的回歸測試。"""

    def setUp(self):
        self.pw = "a-long-enough-password"
        self.boss = User.objects.create_user(
            username="coachlai", password=self.pw, role=Role.ADMIN,
            is_staff=True, is_superuser=True,
        )

    def test_login_then_follow_every_redirect_to_a_real_page(self):
        resp = self.client.post(
            reverse("login"),
            {"username": "coachlai", "password": self.pw, "next": ""},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        # 管理員名下沒有運動員，應該看到說明頁而不是 500
        self.assertIn("尚未建立運動員資料", resp.content.decode())

    def test_admin_without_athlete_profile_sees_a_page_not_an_error(self):
        self.client.force_login(self.boss)
        for name in ("web:dashboard", "web:calendar", "web:analytics",
                     "web:nutrition", "web:injuries"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

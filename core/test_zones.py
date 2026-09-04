"""後台與系統各一份登入：同一個瀏覽器可以兩邊掛不同帳號，誰都不會頂掉誰。"""

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import Role
from core.test_factories import make_athlete, make_coach
from core.zones import ADMIN_PREFIX, admin_aliases, is_admin_zone

PW = "a-long-enough-password"
SESSION = settings.SESSION_COOKIE_NAME
ADMIN_SESSION = ADMIN_PREFIX + SESSION


def make_boss(username="boss"):
    return User.objects.create_user(
        username=username, password=PW, role=Role.ADMIN, is_staff=True, is_superuser=True
    )


class ZoneHelperTests(TestCase):
    def test_only_the_admin_path_counts_as_the_admin_zone(self):
        self.assertTrue(is_admin_zone("/" + settings.ADMIN_URL))
        self.assertTrue(is_admin_zone("/" + settings.ADMIN_URL + "auth/user/"))
        for path in ("/app/", "/dashboard/", "/accounts/login/", "/api/athletes/", "/"):
            with self.subTest(path=path):
                self.assertFalse(is_admin_zone(path))

    def test_both_session_and_csrf_cookies_get_their_own_name(self):
        aliases = admin_aliases()
        self.assertEqual(aliases[SESSION], ADMIN_SESSION)
        self.assertEqual(aliases[settings.CSRF_COOKIE_NAME], ADMIN_PREFIX + settings.CSRF_COOKIE_NAME)


class SimultaneousLoginTests(TestCase):
    """同一個瀏覽器（同一組 cookie）兩邊各登入一個帳號。"""

    def setUp(self):
        self.boss = make_boss()
        self.coach = make_coach().user

    def _login_admin(self):
        return self.client.post(
            reverse("admin:login"),
            {"username": self.boss.username, "password": PW, "next": reverse("admin:index")},
            follow=True,
        )

    def _login_app(self):
        return self.client.post(
            reverse("login"),
            {"username": self.coach.username, "password": "test-pw-12345"},
            follow=True,
        )

    def test_admin_login_writes_its_own_cookie(self):
        self._login_admin()
        self.assertIn(ADMIN_SESSION, self.client.cookies)
        self.assertNotIn(SESSION, self.client.cookies)

    def test_logging_into_the_app_afterwards_keeps_the_admin_logged_in(self):
        self._login_admin()
        admin_key = self.client.cookies[ADMIN_SESSION].value

        self._login_app()
        # 系統那邊拿到自己的 cookie，後台那一份原封不動
        self.assertIn(SESSION, self.client.cookies)
        self.assertEqual(self.client.cookies[ADMIN_SESSION].value, admin_key)

        self.assertEqual(self.client.get(admin_url()).context["user"], self.boss)
        self.assertEqual(self.client.get(reverse("web:athlete_list")).context["user"], self.coach)

    def test_logging_into_the_admin_afterwards_keeps_the_app_logged_in(self):
        self._login_app()
        app_key = self.client.cookies[SESSION].value

        self._login_admin()
        self.assertEqual(self.client.cookies[SESSION].value, app_key)

        self.assertEqual(self.client.get(admin_url()).context["user"], self.boss)
        self.assertEqual(self.client.get(reverse("web:athlete_list")).context["user"], self.coach)

    def test_logging_out_of_the_admin_leaves_the_app_signed_in(self):
        self._login_admin()
        self._login_app()

        self.client.post(reverse("admin:logout"))
        self.assertEqual(self.client.get(reverse("web:athlete_list")).context["user"], self.coach)

    def test_logging_out_of_the_app_leaves_the_admin_signed_in(self):
        self._login_admin()
        self._login_app()

        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(admin_url()).context["user"], self.boss)

    def test_the_app_never_reads_the_admin_cookie(self):
        self._login_admin()
        r = self.client.get(reverse("web:home"), follow=True)
        self.assertIn("/accounts/login/", r.redirect_chain[-1][0])


class AdminLoginFormTests(TestCase):
    """後台登入表單擋掉沒有後台權限的帳號，並說清楚原因。"""

    def test_coach_credentials_are_refused_with_a_permission_message(self):
        make_coach(username="c_form")
        r = self.client.post(
            reverse("admin:login"),
            {"username": "c_form", "password": "test-pw-12345"},
            follow=True,
        )
        self.assertIn("沒有後台權限", r.content.decode())
        self.assertNotIn(ADMIN_SESSION, self.client.cookies)

    def test_athlete_credentials_are_refused_too(self):
        make_athlete(username="a_form")
        r = self.client.post(
            reverse("admin:login"),
            {"username": "a_form", "password": "test-pw-12345"},
            follow=True,
        )
        self.assertIn("沒有後台權限", r.content.decode())

    def test_admin_credentials_are_accepted(self):
        make_boss("boss_ok")
        self.client.post(
            reverse("admin:login"),
            {"username": "boss_ok", "password": PW, "next": reverse("admin:index")},
            follow=True,
        )
        self.assertEqual(self.client.get(admin_url()).status_code, 200)


def admin_url():
    return reverse("admin:index")

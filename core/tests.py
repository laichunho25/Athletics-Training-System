"""權限收斂測試——運動員只能看自己，教練只能看旗下，管理員全部。"""

from django.test import TestCase
from django.urls import reverse

from core.permissions import athlete_ids_visible_to, resolve_athlete
from core.test_factories import (
    TODAY,
    make_admin,
    make_athlete,
    make_coach,
    make_session,
)


class AthleteIdsVisibleToTests(TestCase):
    def setUp(self):
        self.coach_a = make_coach("coach_a", "A 隊")
        self.coach_b = make_coach("coach_b", "B 隊")
        self.a1 = make_athlete("a1", coach=self.coach_a)
        self.a2 = make_athlete("a2", coach=self.coach_a)
        self.b1 = make_athlete("b1", coach=self.coach_b)
        self.orphan = make_athlete("orphan", coach=None)
        self.admin = make_admin()

    def test_athlete_sees_only_self(self):
        self.assertEqual(set(athlete_ids_visible_to(self.a1.user)), {self.a1.id})

    def test_coach_sees_only_own_squad(self):
        visible = set(athlete_ids_visible_to(self.coach_a.user))
        self.assertEqual(visible, {self.a1.id, self.a2.id})
        self.assertNotIn(self.b1.id, visible)
        self.assertNotIn(self.orphan.id, visible)

    def test_admin_sees_everyone(self):
        visible = set(athlete_ids_visible_to(self.admin))
        self.assertEqual(
            visible, {self.a1.id, self.a2.id, self.b1.id, self.orphan.id}
        )

    def test_anonymous_sees_nobody(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(list(athlete_ids_visible_to(AnonymousUser())), [])

    def test_coach_without_athletes_sees_nobody(self):
        lonely = make_coach("coach_c", "C 隊")
        self.assertEqual(list(athlete_ids_visible_to(lonely.user)), [])


class ResolveAthleteTests(TestCase):
    def test_walks_fk_up_to_athlete_profile(self):
        athlete = make_athlete()
        session = make_session(athlete, TODAY)
        self.assertEqual(resolve_athlete(session), athlete)

    def test_athlete_profile_resolves_to_itself_via_session(self):
        athlete = make_athlete("a9")
        self.assertIsNone(resolve_athlete(object()))


class ViewAccessControlTests(TestCase):
    """HTML 前端的權限：擋匿名、擋跨運動員。"""

    def setUp(self):
        self.coach = make_coach()
        self.mine = make_athlete("mine", coach=self.coach)
        self.other_coach = make_coach("coach_x", "X 隊")
        self.theirs = make_athlete("theirs", coach=self.other_coach)
        self.pw = "test-pw-12345"

    def test_anonymous_is_redirected_to_login(self):
        for name in ("web:dashboard", "web:calendar", "web:analytics",
                     "web:nutrition", "web:injuries", "web:home"):
            with self.subTest(view=name):
                r = self.client.get(reverse(name))
                self.assertEqual(r.status_code, 302)
                self.assertIn("/accounts/login/", r["Location"])

    def test_landing_page_is_public(self):
        r = self.client.get(reverse("web:landing"))
        self.assertEqual(r.status_code, 200)

    def test_athlete_cannot_view_another_athlete_by_query_param(self):
        self.client.login(username="mine", password=self.pw)
        r = self.client.get(reverse("web:dashboard"), {"athlete": self.theirs.id})
        self.assertEqual(r.status_code, 200)
        # 參數被忽略，落回自己的資料，而不是換成別人的
        self.assertEqual(r.context["athlete"].id, self.mine.id)

    def test_coach_cannot_view_athlete_outside_squad(self):
        self.client.login(username="coach1", password=self.pw)
        r = self.client.get(reverse("web:dashboard"), {"athlete": self.theirs.id})
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.context["athlete"].id, self.theirs.id)

    def test_session_detail_404_for_other_athletes_session(self):
        session = make_session(self.theirs, TODAY)
        self.client.login(username="mine", password=self.pw)
        r = self.client.get(reverse("web:session_detail", args=[session.id]))
        self.assertEqual(r.status_code, 404)

    def test_session_detail_ok_for_own_session(self):
        session = make_session(self.mine, TODAY)
        self.client.login(username="mine", password=self.pw)
        r = self.client.get(reverse("web:session_detail", args=[session.id]))
        self.assertEqual(r.status_code, 200)

    def test_coach_can_open_own_squad_athlete_session(self):
        session = make_session(self.mine, TODAY)
        self.client.login(username="coach1", password=self.pw)
        r = self.client.get(reverse("web:session_detail", args=[session.id]))
        self.assertEqual(r.status_code, 200)

    def test_athlete_cannot_post_check_in_to_other_athletes_session(self):
        session = make_session(self.theirs, TODAY, rpe=None, minutes=None)
        self.client.login(username="mine", password=self.pw)
        r = self.client.post(
            reverse("web:session_detail", args=[session.id]),
            {"action": "complete", "session_rpe": 9, "actual_duration_min": 120},
        )
        self.assertEqual(r.status_code, 404)
        session.refresh_from_db()
        self.assertIsNone(session.session_rpe)

    def test_home_dispatches_by_role(self):
        self.client.login(username="mine", password=self.pw)
        self.assertRedirects(
            self.client.get(reverse("web:home")), reverse("web:dashboard")
        )
        self.client.logout()
        self.client.login(username="coach1", password=self.pw)
        self.assertRedirects(
            self.client.get(reverse("web:home")), reverse("web:coach_dashboard")
        )


class LoginPageTests(TestCase):
    def test_demo_credentials_hidden_when_debug_off(self):
        with self.settings(DEBUG=False):
            body = self.client.get("/accounts/login/").content.decode()
        for secret in ("atm12345", "admin12345", "coach_chan"):
            self.assertNotIn(secret, body)

    def test_demo_credentials_shown_in_debug(self):
        with self.settings(DEBUG=True):
            body = self.client.get("/accounts/login/").content.decode()
        self.assertIn("atm12345", body)

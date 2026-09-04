"""跨頁沿用同一位運動員：挑過的人不會在換頁時掉回名單第一位。"""

from django.test import TestCase
from django.urls import reverse

from core.test_factories import TODAY, make_athlete, make_coach, make_session

PW = "test-pw-12345"

ATHLETE_PAGES = ("web:dashboard", "web:calendar", "web:analytics", "web:nutrition", "web:injuries")


class StickyAthleteTests(TestCase):
    def setUp(self):
        self.coach = make_coach()
        self.first = make_athlete("a_first", coach=self.coach)
        self.second = make_athlete("a_second", coach=self.coach)
        self.client.login(username="coach1", password=PW)

    def test_picked_athlete_carries_to_every_other_page(self):
        self.client.get(reverse("web:dashboard"), {"athlete": self.second.id})
        for name in ATHLETE_PAGES:
            with self.subTest(view=name):
                r = self.client.get(reverse(name))
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.context["athlete"].id, self.second.id)

    def test_opening_a_session_switches_the_remembered_athlete(self):
        self.client.get(reverse("web:dashboard"), {"athlete": self.second.id})
        session = make_session(self.first, TODAY)
        self.client.get(reverse("web:session_detail", args=[session.id]))
        r = self.client.get(reverse("web:calendar"))
        self.assertEqual(r.context["athlete"].id, self.first.id)

    def test_invisible_athlete_is_neither_shown_nor_remembered(self):
        outsider = make_athlete("outsider", coach=make_coach("coach_x", "X 隊"))
        r = self.client.get(reverse("web:dashboard"), {"athlete": outsider.id})
        self.assertNotEqual(r.context["athlete"].id, outsider.id)
        r2 = self.client.get(reverse("web:calendar"))
        self.assertNotEqual(r2.context["athlete"].id, outsider.id)

    def test_coach_lands_on_the_list_before_picking_anyone(self):
        self.assertRedirects(
            self.client.get(reverse("web:dashboard")), reverse("web:athlete_list")
        )

    def test_coach_returns_to_the_last_athlete_after_picking(self):
        self.client.get(reverse("web:dashboard"), {"athlete": self.second.id})
        r = self.client.get(reverse("web:dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["athlete"].id, self.second.id)

    def test_athlete_only_ever_sees_themselves(self):
        self.client.logout()
        self.client.login(username="a_first", password=PW)
        r = self.client.get(reverse("web:dashboard"), {"athlete": self.second.id})
        self.assertEqual(r.context["athlete"].id, self.first.id)
        self.assertEqual(list(r.context["nav_athletes"]), [])


class NavContextTests(TestCase):
    """側欄／麵包屑用的外框變數。"""

    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete("a_nav", coach=self.coach)
        self.client.login(username="coach1", password=PW)

    def test_sidebar_links_carry_the_current_athlete(self):
        r = self.client.get(reverse("web:dashboard"), {"athlete": self.athlete.id})
        self.assertEqual(r.context["nav_athlete_qs"], f"?athlete={self.athlete.id}")
        self.assertContains(r, f'{reverse("web:calendar")}?athlete={self.athlete.id}')

    def test_switcher_lists_the_whole_squad_once(self):
        make_athlete("a_nav2", coach=self.coach)
        r = self.client.get(reverse("web:athlete_list"))
        self.assertEqual(len(r.context["nav_athletes"]), 2)

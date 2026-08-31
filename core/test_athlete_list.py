"""運動員列表（搜尋／篩選／排序）與儀表板上的目標賽事、分期編輯。"""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from core.test_factories import make_admin, make_athlete, make_coach, make_event
from injury.models import Injury, InjuryStatus
from planning.models import Competition, Macrocycle


class AthleteListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.coach = make_coach()
        cls.lj = make_event(code="LJ", name="跳遠", distance=None)
        cls.ann = make_athlete(
            "ann", coach=cls.coach, birth_date=date(2010, 1, 1), school_or_club="拔萃"
        )
        cls.bob = make_athlete(
            "bob", coach=cls.coach, event=cls.lj, birth_date=date(2000, 1, 1)
        )
        cls.outsider = make_athlete("zoe")  # 沒有教練 → 這名教練看不到
        Injury.objects.create(
            athlete=cls.bob,
            body_part="HAMSTRING",
            injury_type="STRAIN",
            severity=2,
            status=InjuryStatus.REHAB,
            onset_date=date(2026, 5, 1),
        )

    def setUp(self):
        self.client.force_login(self.coach.user)

    def names(self, response):
        return [a.user.username for a in response.context["athletes"]]

    def test_only_shows_athletes_the_coach_can_see(self):
        rows = self.names(self.client.get(reverse("web:athlete_list")))
        self.assertEqual(rows, ["ann", "bob"])
        self.assertNotIn("zoe", rows)

    def test_search_matches_name_event_and_school(self):
        url = reverse("web:athlete_list")
        self.assertEqual(self.names(self.client.get(url, {"q": "ann"})), ["ann"])
        self.assertEqual(self.names(self.client.get(url, {"q": "跳遠"})), ["bob"])
        self.assertEqual(self.names(self.client.get(url, {"q": "拔萃"})), ["ann"])

    def test_filter_by_event_and_injury(self):
        url = reverse("web:athlete_list")
        self.assertEqual(
            self.names(self.client.get(url, {"event": self.lj.id})), ["bob"]
        )
        self.assertEqual(
            self.names(self.client.get(url, {"injury": "HAS_INJURY"})), ["bob"]
        )
        self.assertEqual(
            self.names(self.client.get(url, {"injury": "HEALTHY"})), ["ann", "bob"]
        )

    def test_sort_by_age_both_directions(self):
        url = reverse("web:athlete_list")
        # 2010 年出生的 ann 比 2000 年的 bob 年輕
        self.assertEqual(self.names(self.client.get(url, {"sort": "age"})), ["ann", "bob"])
        self.assertEqual(
            self.names(self.client.get(url, {"sort": "age", "dir": "desc"})),
            ["bob", "ann"],
        )

    def test_sort_links_keep_the_current_search(self):
        response = self.client.get(reverse("web:athlete_list"), {"q": "ann", "sort": "age"})
        self.assertIn("q=ann", response.context["sort_urls"]["age"])
        # 同一欄再點一次就變倒序
        self.assertIn("dir=desc", response.context["sort_urls"]["age"])
        self.assertIn("dir=asc", response.context["sort_urls"]["name"])


class PlanEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.coach = make_coach()
        cls.athlete = make_athlete("ann", coach=cls.coach)
        cls.other_coach = make_coach("coach2")
        cls.competition = Competition.objects.create(
            name="學界錦標賽", date=date.today() + timedelta(weeks=20)
        )

    def post(self, data, user=None):
        self.client.force_login(user or self.coach.user)
        return self.client.post(
            reverse("web:athlete_plan_edit", args=[self.athlete.id]), data
        )

    def test_setting_target_creates_macrocycle_with_phases_and_weeks(self):
        response = self.post(
            {
                "action": "set_target",
                "competition": self.competition.id,
                "total_weeks": 16,
                "baseline_weekly_load": 1800,
            }
        )
        self.assertRedirects(
            response, f"{reverse('web:dashboard')}?athlete={self.athlete.id}"
        )
        macro = Macrocycle.objects.get(athlete=self.athlete)
        self.assertEqual(macro.target_competition, self.competition)
        self.assertEqual(macro.total_weeks, 16)
        self.assertEqual(macro.phases.count(), 4)
        self.assertEqual(macro.microcycles.count(), 16)
        # 沒填開始日期 → 由比賽日往回數 16 週，並對齊週一
        self.assertEqual(macro.start_date.weekday(), 0)

    def test_new_competition_can_be_created_inline(self):
        self.post(
            {
                "action": "set_target",
                "competition": "__new__",
                "comp_name": "校運會",
                "comp_date": (date.today() + timedelta(weeks=10)).isoformat(),
                "total_weeks": 10,
            }
        )
        comp = Competition.objects.get(name="校運會")
        self.assertTrue(comp.is_target)
        self.assertEqual(Macrocycle.objects.get(athlete=self.athlete).target_competition, comp)

    def test_editing_a_phase_updates_the_linked_microcycles(self):
        self.post(
            {
                "action": "set_target",
                "competition": self.competition.id,
                "total_weeks": 16,
            }
        )
        macro = Macrocycle.objects.get(athlete=self.athlete)
        phase = macro.phases.first()

        self.post(
            {
                "action": "set_phase",
                "phase_id": phase.id,
                "phase_type": "TAPER_COMP",
                "week_start": 1,
                "week_end": 3,
                "target_weekly_load": 900,
                "focus": "減量調整",
            }
        )
        phase.refresh_from_db()
        self.assertEqual(phase.phase_type, "TAPER_COMP")
        self.assertEqual(phase.week_end, 3)
        self.assertEqual(phase.focus, "減量調整")
        self.assertEqual(
            macro.microcycles.get(week_number=2).planned_load, 900
        )
        # 第 4 週已經不在這段分期裡了
        self.assertNotEqual(macro.microcycles.get(week_number=4).phase_id, phase.id)

    def test_phase_rejects_an_end_week_before_the_start_week(self):
        self.post({"action": "set_target", "competition": self.competition.id})
        macro = Macrocycle.objects.get(athlete=self.athlete)
        before = list(macro.phases.values_list("week_end", flat=True))

        response = self.post(
            {
                "action": "set_phase",
                "phase_id": macro.phases.first().id,
                "phase_type": "GENERAL_PREP",
                "week_start": 8,
                "week_end": 3,
            }
        )
        self.assertEqual(list(macro.phases.values_list("week_end", flat=True)), before)
        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(any("結束週" in m for m in messages))

    def test_another_coach_cannot_edit(self):
        self.post(
            {"action": "set_target", "competition": self.competition.id},
            user=self.other_coach.user,
        )
        self.assertFalse(Macrocycle.objects.filter(athlete=self.athlete).exists())

    def test_admin_can_edit_anyone(self):
        self.post({"action": "set_target", "competition": self.competition.id}, user=make_admin())
        self.assertTrue(Macrocycle.objects.filter(athlete=self.athlete).exists())

    def test_dashboard_shows_the_saved_target_and_phase(self):
        """儀表板讀的是同一份 Macrocycle / Phase，所以改完馬上看得到。"""
        self.post(
            {
                "action": "set_target",
                "competition": self.competition.id,
                "total_weeks": 16,
                # 從本週一起算，這樣「目前分期」才有東西可看
                "start_date": (date.today() - timedelta(days=date.today().weekday())).isoformat(),
            }
        )
        macro = Macrocycle.objects.get(athlete=self.athlete)
        self.post(
            {
                "action": "set_phase",
                "phase_id": macro.current_phase.id,
                "phase_type": "SPECIFIC_PREP",
                "week_start": macro.current_phase.week_start,
                "week_end": macro.current_phase.week_end,
                "target_weekly_load": 2100,
                "focus": "專項速度",
            }
        )

        body = self.client.get(
            reverse("web:dashboard"), {"athlete": self.athlete.id}
        ).content.decode()
        self.assertIn("學界錦標賽", body)
        self.assertIn("專項期", body)
        self.assertIn("專項速度", body)
        self.assertIn('id="targetDlg"', body)
        self.assertIn('id="phaseDlg"', body)

    def test_the_athlete_can_set_their_own_target(self):
        self.post(
            {"action": "set_target", "competition": self.competition.id},
            user=self.athlete.user,
        )
        self.assertTrue(Macrocycle.objects.filter(athlete=self.athlete).exists())

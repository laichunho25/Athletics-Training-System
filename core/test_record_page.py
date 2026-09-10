"""日曆刪課表，以及頂欄「登紀錄」那一條路。

登紀錄不再只有課表那一條路：教練、運動員、管理員在任何一頁按頂欄的
「登紀錄」，先挑範疇（田徑練習／重量訓練／比賽數據），再挑項目就登得進去。
寫進去的跟課表那邊按「登記錄」是同一張 MetricRecord。
"""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from analytics.models import MetricDomain, MetricItem, MetricRecord
from core.test_factories import make_admin, make_athlete, make_coach
from planning.models import TrainingSession
from training.models import BlockType, SessionActivity

#: 日曆看的是「本月」、對應 program 的下拉只列近 90 天，所以這一份用真的今天
TODAY = date.today()


def _session(athlete, coach=None, user=None, title="加速度課"):
    return TrainingSession.objects.create(
        athlete=athlete,
        date=TODAY,
        time_slot="PM",
        session_type="TRACK",
        title=title,
        assigned_by=coach,
        created_by=user,
    )


class CalendarDeleteTests(TestCase):
    """日曆上每一堂課右上角的 🗑。"""

    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        self.url = reverse("web:calendar")

    def _post(self, session):
        return self.client.post(
            self.url,
            {"action": "delete_session", "athlete": self.athlete.id, "session": session.id},
            follow=True,
        )

    def test_grid_shows_delete_button_for_the_person_who_planned_it(self):
        session = _session(self.athlete, self.coach, self.coach.user)
        self.client.force_login(self.coach.user)
        page = self.client.get(f"{self.url}?athlete={self.athlete.id}")
        self.assertContains(page, "delev")
        self.assertContains(page, f'data-session="{session.id}"')

    def test_delete_removes_the_session_and_its_activities(self):
        session = _session(self.athlete, self.coach, self.coach.user)
        SessionActivity.objects.create(
            session=session, block=BlockType.MAIN, order=1, name="150m 反覆跑"
        )
        self.client.force_login(self.coach.user)
        page = self._post(session)
        self.assertEqual(page.status_code, 200)
        self.assertFalse(TrainingSession.objects.filter(pk=session.pk).exists())
        self.assertFalse(SessionActivity.objects.filter(session_id=session.pk).exists())

    def test_records_survive_but_lose_the_session_link(self):
        """練過的成績不會因為課表被刪掉而不見。"""
        session = _session(self.athlete, self.coach, self.coach.user)
        item = MetricItem.objects.create(domain=MetricDomain.TRACK, name="150m 反覆跑")
        record = MetricRecord.objects.create(
            athlete=self.athlete, item=item, session=session, date=TODAY, value=18
        )
        self.client.force_login(self.coach.user)
        self._post(session)
        record.refresh_from_db()
        self.assertIsNone(record.session_id)

    def test_athlete_cannot_delete_a_session_the_coach_planned(self):
        session = _session(self.athlete, self.coach, self.coach.user)
        self.client.force_login(self.athlete.user)
        page = self._post(session)
        self.assertTrue(TrainingSession.objects.filter(pk=session.pk).exists())
        self.assertContains(page, "只有排課的人或管理員刪得掉")

    def test_athlete_does_not_even_see_the_button(self):
        _session(self.athlete, self.coach, self.coach.user)
        self.client.force_login(self.athlete.user)
        page = self.client.get(f"{self.url}?athlete={self.athlete.id}")
        self.assertNotContains(page, "delev")

    def test_admin_can_delete_anyones_session(self):
        session = _session(self.athlete, self.coach, self.coach.user)
        self.client.force_login(make_admin())
        self._post(session)
        self.assertFalse(TrainingSession.objects.filter(pk=session.pk).exists())


class RecordPageTests(TestCase):
    """頂欄「登紀錄」→ 挑範疇 → 挑項目 → 填數字。"""

    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        self.url = reverse("web:record")

    def test_top_bar_button_is_there_for_every_role(self):
        for user in (self.coach.user, self.athlete.user, make_admin()):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                page = self.client.get(
                    f"{reverse('web:dashboard')}?athlete={self.athlete.id}"
                )
                self.assertContains(page, 'data-act="log-record"')
                self.assertContains(page, "登紀錄")

    def test_first_step_lists_the_three_domains(self):
        self.client.force_login(self.coach.user)
        page = self.client.get(f"{self.url}?athlete={self.athlete.id}")
        self.assertEqual(page.status_code, 200)
        for value, label in MetricDomain.choices:
            self.assertContains(page, f"domain={value}")
            self.assertContains(page, label)

    def test_picking_a_domain_shows_the_item_picker(self):
        self.client.force_login(self.coach.user)
        page = self.client.get(f"{self.url}?athlete={self.athlete.id}&domain=STRENGTH")
        self.assertContains(page, "登哪一個項目")
        self.assertContains(page, "add_item")

    def test_open_a_new_item_then_log_a_set(self):
        self.client.force_login(self.coach.user)
        self.client.post(
            self.url,
            {"action": "add_item", "domain": "STRENGTH", "name": "背蹲舉"},
            follow=True,
        )
        item = MetricItem.objects.get(domain=MetricDomain.STRENGTH, name="背蹲舉")

        self.client.post(
            self.url,
            {
                "action": "add_record",
                "domain": "STRENGTH",
                "item_id": item.id,
                "date": TODAY.isoformat(),
                "value": ["120", "125"],
                "reps": ["5", "3"],
                "completed": ["1", "1"],
            },
            follow=True,
        )
        records = MetricRecord.objects.filter(athlete=self.athlete, item=item)
        self.assertEqual(records.count(), 2)
        self.assertEqual(sorted(int(r.value) for r in records), [120, 125])

    def test_track_item_is_method_plus_distance(self):
        self.client.force_login(self.coach.user)
        self.client.post(
            self.url,
            {"action": "add_track_item", "domain": "TRACK", "method": "REPEAT",
             "distance_m": "150"},
            follow=True,
        )
        item = MetricItem.objects.filter(domain=MetricDomain.TRACK).order_by("-id").first()
        self.assertIn("150", item.name)

    def test_athlete_can_log_their_own(self):
        self.client.force_login(self.athlete.user)
        item = MetricItem.objects.create(domain=MetricDomain.TRACK, name="150m 反覆跑")
        self.client.post(
            self.url,
            {
                "action": "add_record",
                "domain": "TRACK",
                "item_id": item.id,
                "date": TODAY.isoformat(),
                "value": ["18.2"],
                "intensity": ["90%"],
            },
            follow=True,
        )
        self.assertEqual(
            MetricRecord.objects.filter(athlete=self.athlete, item=item).count(), 1
        )

    def test_record_can_hang_on_a_session_from_the_calendar(self):
        session = _session(self.athlete, self.coach, self.coach.user)
        item = MetricItem.objects.create(domain=MetricDomain.TRACK, name="150m 反覆跑")
        self.client.force_login(self.coach.user)
        self.client.post(
            self.url,
            {
                "action": "add_record",
                "domain": "TRACK",
                "item_id": item.id,
                "date": TODAY.isoformat(),
                "session": session.id,
                "value": ["18.2"],
            },
            follow=True,
        )
        self.assertEqual(session.metric_records.count(), 1)

    def test_cannot_log_for_an_athlete_you_cannot_see(self):
        other = make_athlete(username="ath-other", coach=make_coach("coach2"))
        item = MetricItem.objects.create(domain=MetricDomain.TRACK, name="150m 反覆跑")
        self.client.force_login(self.coach.user)
        self.client.post(
            self.url,
            {
                "action": "add_record",
                "domain": "TRACK",
                "item_id": item.id,
                "date": TODAY.isoformat(),
                "value": ["18.2"],
            },
            follow=True,
        )
        self.assertFalse(MetricRecord.objects.filter(athlete=other).exists())

    def test_session_picker_only_lists_sessions_that_fit_the_domain(self):
        _session(self.athlete, self.coach, self.coach.user, title="加速度課")
        TrainingSession.objects.create(
            athlete=self.athlete,
            date=TODAY - timedelta(days=1),
            time_slot="AM",
            session_type="STRENGTH",
            title="下肢最大力量",
            assigned_by=self.coach,
            created_by=self.coach.user,
        )
        self.client.force_login(self.coach.user)
        page = self.client.get(f"{self.url}?athlete={self.athlete.id}&domain=TRACK")
        item = MetricItem.objects.filter(domain=MetricDomain.TRACK).first()
        page = self.client.get(
            f"{self.url}?athlete={self.athlete.id}&domain=TRACK&item={item.id}"
        )
        self.assertContains(page, "加速度課")
        self.assertNotContains(page, "下肢最大力量")


class CoachLogsOnSessionPageTests(TestCase):
    """課表頁那一行活動旁的「登記錄」——教練替運動員補登。

    以前這道門只開給運動員本人和管理員，教練按下去只會看到「只有本人能登」，
    可是練完口頭報數字、運動員沒帶手機是常態，教練得補得了。
    """

    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        self.session = _session(self.athlete, self.coach, self.coach.user)
        self.activity = SessionActivity.objects.create(
            session=self.session, block=BlockType.MAIN, order=1, name="150m 反覆跑", sets=2
        )
        self.url = reverse("web:session_detail", args=[self.session.pk])

    def test_coach_sees_the_log_button(self):
        self.client.force_login(self.coach.user)
        page = self.client.get(self.url)
        self.assertTrue(page.context["can_log"])
        self.assertContains(page, "登記錄")

    def test_coach_can_open_and_fill_a_record(self):
        self.client.force_login(self.coach.user)
        page = self.client.post(
            self.url,
            {"action": "log_activity", "id": self.activity.id, "rdomain": "TRACK"},
            follow=True,
        )
        self.assertEqual(page.status_code, 200)
        item = MetricItem.objects.get(name="150m 反覆跑")
        self.assertTrue(self.session.metric_records.exists())

        self.client.post(
            self.url,
            {
                "action": "add_record",
                "rdomain": "TRACK",
                "item_id": item.id,
                "log": self.activity.id,
                "value": ["18.2"],
            },
            follow=True,
        )
        self.assertTrue(
            MetricRecord.objects.filter(
                athlete=self.athlete, item=item, value=18.2
            ).exists()
        )

    def test_a_coach_who_cannot_see_the_athlete_still_cannot_log(self):
        other = make_coach("coach2")
        self.client.force_login(other.user)
        page = self.client.post(
            self.url,
            {"action": "log_activity", "id": self.activity.id, "rdomain": "TRACK"},
            follow=True,
        )
        self.assertEqual(page.status_code, 404)
        self.assertFalse(self.session.metric_records.exists())

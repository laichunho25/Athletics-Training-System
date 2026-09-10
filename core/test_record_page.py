"""日曆刪課表，以及課表頁那一行活動的「登記錄」。

登紀錄只有課表這一條路：日曆上開一堂課、加好活動，按那一行的「登記錄」
先挑範疇（田徑練習訓練紀錄／重量訓練紀錄／比賽數據），再填每一組的數字。
"""

from datetime import date
from decimal import Decimal

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


class PickDomainOnSessionTests(TestCase):
    """按活動那一行的「登記錄」，先挑三個範疇的其中一個。"""

    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        self.session = _session(self.athlete, self.coach, self.coach.user)
        self.activity = SessionActivity.objects.create(
            session=self.session, block=BlockType.MAIN, order=1, name="150m 反覆跑", sets=2
        )
        self.url = reverse("web:session_detail", args=[self.session.pk])
        self.client.force_login(self.coach.user)

    def test_all_three_domains_are_offered(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'data-act="pick-domain"')
        for value, label in MetricDomain.choices:
            self.assertContains(page, 'value="%s"' % value)
            self.assertContains(page, label)

    def test_the_session_type_domain_comes_first(self):
        page = self.client.get(self.url)
        self.assertEqual(page.context["record_domains"][0][0], MetricDomain.TRACK)

    def test_can_log_strength_on_a_track_session(self):
        """課別不再限制登什麼——田徑課臨時補一組深蹲也記得下來。"""
        page = self.client.post(
            self.url,
            {"action": "log_activity", "id": self.activity.id, "rdomain": "STRENGTH"},
            follow=True,
        )
        self.assertEqual(page.status_code, 200)
        self.assertTrue(
            MetricRecord.objects.filter(
                session=self.session, item__domain=MetricDomain.STRENGTH
            ).exists()
        )


class RecordFormUnitsTests(TestCase):
    """新增一筆紀錄那張表：距離挑 m／km，秒數項目填「分＋秒」。"""

    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        self.session = _session(self.athlete, self.coach, self.coach.user)
        self.activity = SessionActivity.objects.create(
            session=self.session, block=BlockType.MAIN, order=1, name="1600m 節奏跑"
        )
        self.item = MetricItem.objects.create(
            domain=MetricDomain.TRACK, name="1600m 節奏跑", unit="秒"
        )
        self.url = reverse("web:session_detail", args=[self.session.pk])
        self.client.force_login(self.coach.user)

    def _log(self, **fields):
        data = {
            "action": "add_record",
            "rdomain": "TRACK",
            "item_id": self.item.id,
            "log": self.activity.id,
        }
        data.update(fields)
        self.client.post(self.url, data, follow=True)
        return MetricRecord.objects.filter(item=self.item).order_by("id")

    def test_kilometres_are_stored_as_metres(self):
        record = self._log(distance_m=["1.6"], distance_unit="km", value=["330"]).first()
        self.assertEqual(record.distance_m, 1600)

    def test_metres_stay_metres(self):
        record = self._log(distance_m=["150"], distance_unit="m", value=["18.2"]).first()
        self.assertEqual(record.distance_m, 150)

    def test_minutes_plus_seconds_become_seconds(self):
        record = self._log(
            value_min=["5"], value=["32.5"], target_min=["5"], target_value=["30"]
        ).first()
        self.assertEqual(record.value, Decimal("332.5"))
        self.assertEqual(record.target_value, Decimal("330"))

    def test_seconds_alone_still_work(self):
        record = self._log(value_min=[""], value=["11.24"]).first()
        self.assertEqual(record.value, Decimal("11.24"))

    def test_minutes_alone_is_a_whole_number_of_minutes(self):
        record = self._log(value_min=["2"], value=[""]).first()
        self.assertEqual(record.value, 120)

    def test_the_form_shows_the_unit_pickers(self):
        page = self.client.get(f"{self.url}?rdomain=TRACK&log={self.activity.id}")
        self.assertContains(page, 'name="distance_unit"')
        self.assertContains(page, 'name="value_min"')
        self.assertContains(page, "目標數值（分＋秒）")

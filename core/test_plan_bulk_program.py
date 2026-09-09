"""計劃頁的「派同一個 program」：一次過把同一堂課排進多名運動員的日曆。"""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from core.models import SessionType
from core.test_factories import make_admin, make_athlete, make_coach
from planning.models import ProjectAssignment, TrainingSession
from programs.models import Application
from programs.tests import make_project
from training.models import BlockType, SessionActivity

DAY = date(2026, 9, 16)
NEXT = date(2026, 9, 23)


def enrol(project, athlete, email):
    """把一名已有的運動員掛進報名項目（等同報名表已匯入 ATM）。"""
    return Application.objects.create(
        project=project,
        athlete=athlete,
        name_en=athlete.user.username,
        sex="M",
        birth_date=date(2006, 3, 15),
        phone="12345678",
        email=email,
        height_cm=175,
        weight_kg=68,
        emergency_contact_name="家長",
        emergency_contact_phone="87654321",
    )


class PlanBulkProgramTests(TestCase):
    def setUp(self):
        self.project = make_project()
        self.coach = make_coach()
        self.a1 = make_athlete("ath1")
        self.a2 = make_athlete("ath2")
        self.a3 = make_athlete("ath3")
        for i, athlete in enumerate((self.a1, self.a2, self.a3), start=1):
            enrol(self.project, athlete, f"ath{i}@example.com")
        ProjectAssignment.objects.create(project=self.project, coach=self.coach)
        self.url = reverse("web:plan_detail", args=[self.project.pk])

    def payload(self, **kwargs):
        data = {
            "action": "bulk_program",
            "athlete_ids": [self.a1.id, self.a2.id],
            "date": DAY.isoformat(),
            "time_slot": "AM",
            "session_type": SessionType.TRACK,
            "title": "加速度課",
            "description": "3×30m",
            "planned_duration_min": "75",
        }
        data.update(kwargs)
        return data

    def test_assigned_coach_gives_the_picked_athletes_the_same_session(self):
        self.client.force_login(self.coach.user)
        response = self.client.post(self.url, self.payload(), follow=True)
        self.assertEqual(response.status_code, 200)

        sessions = TrainingSession.objects.all()
        self.assertEqual(sessions.count(), 2)
        self.assertEqual(
            {s.athlete_id for s in sessions}, {self.a1.id, self.a2.id}
        )
        for session in sessions:
            self.assertEqual(session.date, DAY)
            self.assertEqual(session.time_slot, "AM")
            self.assertEqual(session.title, "加速度課")
            self.assertEqual(session.description, "3×30m")
            self.assertEqual(session.planned_duration_min, 75)
            self.assertEqual(session.assigned_by_id, self.coach.id)
            self.assertEqual(session.created_by_id, self.coach.user.id)

    def test_unpicked_athlete_in_the_project_gets_nothing(self):
        self.client.force_login(make_admin())
        self.client.post(self.url, self.payload())
        self.assertFalse(TrainingSession.objects.filter(athlete=self.a3).exists())

    def test_extra_dates_build_one_session_per_athlete_per_day(self):
        self.client.force_login(make_admin())
        self.client.post(self.url, self.payload(dates=NEXT.isoformat()))
        self.assertEqual(TrainingSession.objects.count(), 4)
        self.assertEqual(
            set(TrainingSession.objects.filter(athlete=self.a1).values_list("date", flat=True)),
            {DAY, NEXT},
        )

    def test_template_session_copies_its_activities_to_everyone(self):
        source = TrainingSession.objects.create(
            athlete=self.a3,
            date=date(2026, 9, 1),
            session_type=SessionType.TRACK,
            title="範本課",
            description="範本概要",
            planned_duration_min=100,
        )
        SessionActivity.objects.create(
            session=source, block=BlockType.WARMUP, order=1, name="動態熱身", reps="10"
        )
        SessionActivity.objects.create(
            session=source, block=BlockType.MAIN, order=1, name="30m 加速", sets="3"
        )

        self.client.force_login(self.coach.user)
        self.client.post(
            self.url,
            self.payload(
                source=source.id, copy_activities="1", title="", description="",
                planned_duration_min="",
            ),
        )

        new = TrainingSession.objects.exclude(pk=source.pk)
        self.assertEqual(new.count(), 2)
        for session in new:
            self.assertEqual(session.title, "範本課")
            self.assertEqual(session.description, "範本概要")
            self.assertEqual(session.planned_duration_min, 100)
            self.assertEqual(
                sorted(session.activities.values_list("name", flat=True)),
                sorted(["動態熱身", "30m 加速"]),
            )
        # 練完才填的東西不會跟著抄過去
        self.assertEqual(new.first().status, "PLANNED")

    def test_template_without_the_checkbox_copies_only_the_heading(self):
        source = TrainingSession.objects.create(
            athlete=self.a3, date=DAY, session_type=SessionType.TRACK, title="範本課"
        )
        SessionActivity.objects.create(
            session=source, block=BlockType.MAIN, order=1, name="30m 加速"
        )
        self.client.force_login(make_admin())
        self.client.post(self.url, self.payload(source=source.id))
        self.assertEqual(
            SessionActivity.objects.exclude(session=source).count(), 0
        )

    def test_picking_nobody_creates_nothing(self):
        self.client.force_login(make_admin())
        response = self.client.post(self.url, self.payload(athlete_ids=[]), follow=True)
        self.assertEqual(TrainingSession.objects.count(), 0)
        self.assertContains(response, "請至少選一名運動員")

    def test_a_missing_date_creates_nothing(self):
        self.client.force_login(make_admin())
        response = self.client.post(self.url, self.payload(date=""), follow=True)
        self.assertEqual(TrainingSession.objects.count(), 0)
        self.assertContains(response, "請選至少一個日期")

    def test_an_athlete_outside_the_project_is_ignored(self):
        outsider = make_athlete("outsider")
        self.client.force_login(make_admin())
        self.client.post(self.url, self.payload(athlete_ids=[outsider.id]))
        self.assertEqual(TrainingSession.objects.count(), 0)

    def test_an_unassigned_coach_cannot_reach_the_project_at_all(self):
        other = make_coach("coach2", squad="別隊")
        self.client.force_login(other.user)
        response = self.client.post(self.url, self.payload())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(TrainingSession.objects.count(), 0)

    def test_an_athlete_in_the_project_cannot_assign(self):
        self.client.force_login(self.a1.user)
        response = self.client.post(self.url, self.payload(), follow=True)
        self.assertEqual(TrainingSession.objects.count(), 0)
        self.assertContains(response, "只有管理員或這個項目的負責教練可以派課")

    def test_the_form_shows_up_for_the_assigned_coach_only(self):
        self.client.force_login(self.coach.user)
        self.assertTrue(self.client.get(self.url).context["can_assign"])
        self.client.force_login(self.a1.user)
        self.assertFalse(self.client.get(self.url).context["can_assign"])

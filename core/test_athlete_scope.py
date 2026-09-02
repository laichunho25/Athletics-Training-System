"""運動員列表看得到誰：管理員全部、教練只看自己的、運動員只看自己。

一名運動員報了兩個計劃、由兩位教練帶時，兩位教練都要看得到他。
"""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from analytics.models import MetricDomain, MetricItem, MetricRecord
from core.test_factories import make_admin, make_athlete, make_coach
from programs.models import Application, Project, ProjectStatus

TODAY = date(2026, 6, 1)


def make_project(slug, title, *coaches):
    project = Project.objects.create(
        slug=slug, title=title, description="測試用", status=ProjectStatus.OPEN
    )
    if coaches:
        project.coaches.set(coaches)
    return project


def enrol(project, athlete, email):
    return Application.objects.create(
        project=project, athlete=athlete, email=email,
        name_en=athlete.user.username, sex=athlete.sex,
        birth_date=athlete.birth_date, phone="60000000",
        school_or_club="DBSAC", height_cm=175, weight_kg=65,
        emergency_contact_name="家長", emergency_contact_phone="60000001",
    )


class AthleteScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_admin()
        cls.coach_a = make_coach("coach_a", squad="A 隊")
        cls.coach_b = make_coach("coach_b", squad="B 隊")

        cls.own = make_athlete("own", coach=cls.coach_a)      # A 的直屬
        cls.shared = make_athlete("shared")                    # 靠計劃分配
        cls.other = make_athlete("other", coach=cls.coach_b)   # 只屬於 B

        cls.sprint = make_project("sprint", "短跑計劃", cls.coach_a)
        cls.jump = make_project("jump", "跳項計劃", cls.coach_b)
        enrol(cls.sprint, cls.shared, "shared@example.com")
        enrol(cls.jump, cls.shared, "shared2@example.com")

    def names(self, user):
        self.client.force_login(user)
        page = self.client.get(reverse("web:athlete_list"))
        return sorted(a.user.username for a in page.context["athletes"])

    def test_admin_sees_everyone(self):
        self.assertEqual(
            self.names(self.admin), ["other", "own", "shared"]
        )

    def test_athlete_only_sees_themselves(self):
        self.assertEqual(self.names(self.own.user), ["own"])

    def test_coach_sees_own_and_project_athletes_only(self):
        self.assertEqual(self.names(self.coach_a.user), ["own", "shared"])

    def test_the_same_athlete_shows_up_for_both_project_coaches(self):
        self.assertIn("shared", self.names(self.coach_a.user))
        self.assertIn("shared", self.names(self.coach_b.user))

    def test_scope_note_explains_what_is_visible(self):
        self.client.force_login(self.coach_a.user)
        page = self.client.get(reverse("web:athlete_list"))
        self.assertContains(page, "只看得到直屬與自己負責的計劃裡的運動員")


class LastUpdateColumnTests(TestCase):
    """列表要看得到計劃名稱與最後更新時間，還能照它排序與篩選。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_admin()
        cls.fresh = make_athlete("fresh")
        cls.stale = make_athlete("stale")
        project = make_project("camp", "夏季集訓")
        enrol(project, cls.fresh, "fresh@example.com")

        item = MetricItem.objects.create(
            domain=MetricDomain.STRENGTH, name="背蹲舉", unit="kg",
            higher_is_better=True,
        )
        MetricRecord.objects.create(
            athlete=cls.fresh, item=item, date=TODAY, value=100
        )
        # 久沒更新的那位：把檔案的更新時間往回撥
        old = timezone.now() - timedelta(days=200)
        type(cls.stale).objects.filter(pk=cls.stale.pk).update(updated_at=old)

    def setUp(self):
        self.client.force_login(self.admin)

    def get(self, query=""):
        return self.client.get(f"{reverse('web:athlete_list')}{query}")

    def test_the_list_shows_the_project_and_the_last_update(self):
        page = self.get()
        self.assertContains(page, "夏季集訓")
        self.assertContains(page, "最後更新")
        rows = {a.user.username: a.last_update for a in page.context["athletes"]}
        self.assertGreater(rows["fresh"], rows["stale"])

    def test_sorting_by_last_update_puts_the_newest_first(self):
        page = self.get("?sort=updated")
        self.assertEqual(
            [a.user.username for a in page.context["athletes"]], ["fresh", "stale"]
        )

    def test_filtering_by_staleness(self):
        page = self.get("?updated=stale90")
        self.assertEqual(
            [a.user.username for a in page.context["athletes"]], ["stale"]
        )
        page = self.get("?updated=7")
        self.assertEqual(
            [a.user.username for a in page.context["athletes"]], ["fresh"]
        )

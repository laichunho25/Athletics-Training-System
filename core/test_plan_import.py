"""計劃頁的「載入計劃」：把報名表直接轉成 ATM 運動員檔案。"""

from django.test import TestCase
from django.urls import reverse

from accounts.models import AthleteProfile
from core.test_factories import make_admin, make_coach, make_event
from programs.models import Application
from programs.tests import VALID_FORM, make_project


class PlanDetailImportTests(TestCase):
    def setUp(self):
        make_event()  # 100M，匯入時要有項目字典
        self.project = make_project()
        self.client.post(reverse("programs:apply", args=[self.project.slug]), VALID_FORM)
        self.application = Application.objects.get()
        self.url = reverse("web:plan_detail", args=[self.project.pk])

    def test_admin_can_load_selected_applications_into_the_plan(self):
        self.client.force_login(make_admin())
        response = self.client.post(
            self.url, {"application_ids": [self.application.pk]}, follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertTrue(self.application.is_imported)
        self.assertEqual(AthleteProfile.objects.count(), 1)
        # 匯入後就會出現在項目名單，不再列為「尚未匯入」
        self.assertNotIn(self.application, response.context["not_imported"])

    def test_unselected_applications_are_left_alone(self):
        self.client.force_login(make_admin())
        response = self.client.post(self.url, {"application_ids": []}, follow=True)
        self.application.refresh_from_db()
        self.assertFalse(self.application.is_imported)
        self.assertEqual(AthleteProfile.objects.count(), 0)
        self.assertContains(response, "沒有選取任何未匯入的報名表")

    def test_already_imported_application_is_not_imported_twice(self):
        self.client.force_login(make_admin())
        self.client.post(self.url, {"application_ids": [self.application.pk]})
        self.client.post(self.url, {"application_ids": [self.application.pk]})
        self.assertEqual(AthleteProfile.objects.count(), 1)

    def test_coach_cannot_load_applications(self):
        coach = make_coach()
        from planning.models import ProjectAssignment

        ProjectAssignment.objects.create(project=self.project, coach=coach)
        self.client.force_login(coach.user)
        response = self.client.post(
            self.url, {"application_ids": [self.application.pk]}, follow=True
        )
        self.application.refresh_from_db()
        self.assertFalse(self.application.is_imported)
        self.assertContains(response, "只有管理員可以匯入報名表")

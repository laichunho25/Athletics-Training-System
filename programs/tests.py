"""公開報名流程：開放控制、表單驗證、匯入 ATM。"""

from datetime import date, timedelta

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AthleteProfile, User
from core.models import EventCategory, Role, Sex
from core.test_factories import make_coach, make_event
from programs import services
from programs.models import Application, ApplicationStatus, Project, ProjectStatus

VALID_FORM = {
    "name_en": "Chan Tai Man",
    "name_zh": "陳大文",
    "sex": Sex.MALE,
    "birth_date": "2006-03-15",
    "phone": "+852 9000 0000",
    "email": "taiman@example.com",
    "school_or_club": "DBSAC",
    "graduation_year": 2028,
    "has_track_training": "on",
    "event_category": EventCategory.SPRINT,
    "primary_event": "",
    "personal_best": "100m 11.42",
    "training_years": "3.0",
    "training_days_per_week": 5,
    "strength_experience_years": "1.5",
    "current_coach": "Coach Chan",
    "height_cm": "175.0",
    "weight_kg": "66.0",
    "emergency_contact_name": "Chan Siu Ming",
    "emergency_contact_phone": "+852 9111 1111",
    "emergency_contact_relation": "父親",
    "has_current_injury": "",
    "injury_detail": "",
    "injury_history": "",
    "medical_conditions": "",
    "medications": "",
    "allergies": "",
    "doctor_clearance": "on",
    "health_declaration": "on",
    "consent_terms": "on",
    "consent_data": "on",
    "remarks": "",
}


def make_project(**kwargs):
    defaults = {
        "slug": "test-project",
        "title": "測試項目",
        "description": "說明",
        "status": ProjectStatus.OPEN,
    }
    defaults.update(kwargs)
    return Project.objects.create(**defaults)


class ProjectOpenStateTests(TestCase):
    """報名開關是後台唯一控制入口，邊界要準。"""

    def test_draft_is_not_public_and_not_accepting(self):
        project = make_project(status=ProjectStatus.DRAFT)
        self.assertFalse(project.is_public)
        self.assertFalse(project.is_accepting)

    def test_closed_project_is_public_but_not_accepting(self):
        project = make_project(status=ProjectStatus.CLOSED)
        self.assertTrue(project.is_public)
        accepting, reason = project.accepting_reason()
        self.assertFalse(accepting)
        self.assertTrue(reason)

    def test_open_without_dates_is_accepting(self):
        self.assertTrue(make_project().is_accepting)

    def test_before_opens_at_is_not_accepting(self):
        project = make_project(opens_at=timezone.now() + timedelta(days=1))
        self.assertFalse(project.is_accepting)

    def test_after_closes_at_is_not_accepting(self):
        project = make_project(closes_at=timezone.now() - timedelta(minutes=1))
        accepting, reason = project.accepting_reason()
        self.assertFalse(accepting)
        self.assertIn("截止", reason)

    def test_closes_at_in_the_future_still_accepting(self):
        project = make_project(closes_at=timezone.now() + timedelta(minutes=1))
        self.assertTrue(project.is_accepting)


class CapacityTests(TestCase):
    def setUp(self):
        self.project = make_project(capacity_total=2)

    def _apply(self, email, status=ApplicationStatus.NEW):
        return Application.objects.create(
            project=self.project, email=email, status=status,
            name_en="A", sex=Sex.MALE, birth_date=date(2006, 1, 1),
            phone="1", school_or_club="X", height_cm=170, weight_kg=60,
            emergency_contact_name="B", emergency_contact_phone="2",
        )

    def test_unlimited_capacity_is_never_full(self):
        project = make_project(slug="unlimited", capacity_total=None)
        self.assertFalse(project.is_full)
        self.assertIsNone(project.seats_left)

    def test_seats_left_counts_down(self):
        self._apply("a@example.com")
        self.assertEqual(self.project.seats_left, 1)
        self.assertFalse(self.project.is_full)

    def test_full_when_capacity_reached(self):
        self._apply("a@example.com")
        self._apply("b@example.com")
        self.assertTrue(self.project.is_full)
        self.assertEqual(self.project.seats_left, 0)

    def test_cancelled_and_waitlisted_do_not_occupy_seats(self):
        self._apply("a@example.com", ApplicationStatus.CANCELLED)
        self._apply("b@example.com", ApplicationStatus.WAITLIST)
        self.assertEqual(self.project.confirmed_count, 0)
        self.assertFalse(self.project.is_full)


class PublicPageTests(TestCase):
    def setUp(self):
        self.open_project = make_project(slug="open-one", title="開放中的項目")
        self.draft = make_project(slug="draft-one", title="草稿項目", status=ProjectStatus.DRAFT)

    def test_list_page_is_public_and_hides_drafts(self):
        r = self.client.get(reverse("programs:list"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "開放中的項目")
        self.assertNotContains(r, "草稿項目")

    def test_detail_page_renders_for_public_project(self):
        r = self.client.get(reverse("programs:detail", args=["open-one"]))
        self.assertEqual(r.status_code, 200)

    def test_draft_detail_is_404(self):
        r = self.client.get(reverse("programs:detail", args=["draft-one"]))
        self.assertEqual(r.status_code, 404)

    def test_apply_page_renders_the_form(self):
        r = self.client.get(reverse("programs:apply", args=["open-one"]))
        self.assertEqual(r.status_code, 200)
        for field in ("name_en", "graduation_year", "has_track_training", "consent_terms"):
            self.assertContains(r, field)

    def test_apply_is_blocked_when_not_accepting(self):
        self.open_project.status = ProjectStatus.CLOSED
        self.open_project.save()
        r = self.client.get(reverse("programs:apply", args=["open-one"]))
        self.assertEqual(r.status_code, 403)

    def test_landing_page_links_to_programs(self):
        r = self.client.get(reverse("web:landing"))
        self.assertContains(r, reverse("programs:list"))


class SubmitApplicationTests(TestCase):
    def setUp(self):
        self.project = make_project(slug="sc", capacity_total=2)
        self.url = reverse("programs:apply", args=["sc"])

    def post(self, **overrides):
        data = dict(VALID_FORM)
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_valid_submission_creates_application_and_redirects(self):
        r = self.post()
        self.assertRedirects(r, reverse("programs:done", args=["sc"]))
        application = Application.objects.get()
        self.assertEqual(application.project, self.project)
        self.assertEqual(application.status, ApplicationStatus.NEW)
        self.assertEqual(application.school_or_club, "DBSAC")
        self.assertEqual(application.graduation_year, 2028)
        self.assertTrue(application.has_track_training)

    def test_done_page_greets_the_applicant(self):
        self.post()
        r = self.client.get(reverse("programs:done", args=["sc"]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Chan Tai Man")

    def test_submission_over_capacity_becomes_waitlist(self):
        self.post(email="one@example.com")
        self.post(email="two@example.com")
        self.post(email="three@example.com")
        third = Application.objects.get(email="three@example.com")
        self.assertEqual(third.status, ApplicationStatus.WAITLIST)

    def test_duplicate_email_is_rejected_with_a_message(self):
        self.post()
        r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Application.objects.count(), 1)
        self.assertContains(r, "已經報名過")

    def test_consents_are_mandatory(self):
        for field in ("health_declaration", "consent_terms", "consent_data"):
            with self.subTest(field=field):
                r = self.post(**{field: "", "email": f"{field}@example.com"})
                self.assertEqual(r.status_code, 200)
                self.assertFalse(Application.objects.filter(email=f"{field}@example.com").exists())

    def test_injury_detail_required_when_injured(self):
        r = self.post(has_current_injury="on", injury_detail="")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "請描述部位")
        self.assertEqual(Application.objects.count(), 0)

    def test_minor_is_accepted_without_guardian_fields(self):
        """報名只公開給 DBSAC 師兄弟，家長欄位已移除，未成年不再被擋。"""
        minor_birth = timezone.localdate().replace(year=timezone.localdate().year - 15)
        r = self.post(birth_date=minor_birth.isoformat())
        self.assertRedirects(r, reverse("programs:done", args=["sc"]))
        self.assertTrue(Application.objects.get().is_minor)

    def test_guardian_fields_are_gone_from_the_form(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("guardian_name", html)
        self.assertNotIn("guardian_phone", html)
        self.assertNotIn("監護人", html)

    def test_project_can_override_the_school_default(self):
        """PolyU 這類非 DBSAC 主辦的項目，報名表要預填自己的機構名。"""
        project = make_project(
            slug="polyu-test", default_school_or_club="The Hong Kong Polytechnic University"
        )
        response = self.client.get(reverse("programs:apply", args=[project.slug]))
        self.assertEqual(
            response.context["form"]["school_or_club"].value(),
            "The Hong Kong Polytechnic University",
        )

    def test_school_field_defaults_to_dbsac(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("學校 / 體育會", html)
        self.assertIn('value="DBSAC"', html)

    def test_future_birth_date_is_rejected(self):
        future = (timezone.localdate() + timedelta(days=1)).isoformat()
        r = self.post(birth_date=future)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Application.objects.count(), 0)

    def test_email_is_normalised_to_lowercase(self):
        self.post(email="MiXeD@Example.COM")
        self.assertEqual(Application.objects.get().email, "mixed@example.com")


class HealthFlagTests(TestCase):
    def setUp(self):
        self.project = make_project()
        self.client.post(reverse("programs:apply", args=[self.project.slug]), VALID_FORM)

    def test_clean_application_has_no_flags(self):
        self.assertEqual(Application.objects.get().health_flags, [])

    def test_injury_and_condition_raise_flags(self):
        application = Application.objects.get()
        application.has_current_injury = True
        application.medical_conditions = "哮喘"
        application.doctor_clearance = False
        self.assertEqual(len(application.health_flags), 3)


class ImportToAtmTests(TestCase):
    def setUp(self):
        make_event()  # 100M
        self.project = make_project()
        self.client.post(reverse("programs:apply", args=[self.project.slug]), VALID_FORM)
        self.application = Application.objects.get()

    def test_import_creates_user_and_athlete_profile(self):
        athlete = services.import_application(self.application)
        self.assertIsInstance(athlete, AthleteProfile)
        self.assertEqual(athlete.user.role, Role.ATHLETE)
        self.assertEqual(athlete.birth_date, date(2006, 3, 15))
        self.assertEqual(athlete.school_or_club, "DBSAC")
        self.assertEqual(athlete.training_days_per_week, 5)
        self.assertEqual(float(athlete.strength_experience_years), 1.5)
        self.assertEqual(athlete.user.email, "taiman@example.com")
        self.assertEqual(athlete.user.phone, "+852 9000 0000")

    def test_import_marks_the_application_and_is_idempotent(self):
        first = services.import_application(self.application)
        self.application.refresh_from_db()
        self.assertTrue(self.application.is_imported)
        self.assertIsNotNone(self.application.imported_at)

        second = services.import_application(self.application)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(User.objects.filter(role=Role.ATHLETE).count(), 1)

    def test_import_attaches_the_coach_when_given(self):
        coach = make_coach()
        athlete = services.import_application(self.application, coach=coach)
        self.assertEqual(athlete.coach, coach)

    def test_notes_carry_the_information_that_has_no_profile_field(self):
        self.application.personal_best = "100m 11.42"
        self.application.medical_conditions = "哮喘"
        self.application.save()
        athlete = services.import_application(self.application)
        self.assertIn("100m 11.42", athlete.notes)
        self.assertIn("哮喘", athlete.notes)
        self.assertIn(self.project.title, athlete.notes)

    def test_username_is_derived_from_name_and_deduplicated(self):
        User.objects.create_user(username="chan_tai_man", password="x")
        athlete = services.import_application(self.application)
        self.assertEqual(athlete.user.username, "chan_tai_man2")

    def test_password_is_not_guessable(self):
        """匯入時給隨機密碼，不能用姓名或電郵登入。"""
        athlete = services.import_application(self.application)
        for guess in ("chan_tai_man", "taiman@example.com", "password", ""):
            self.assertFalse(athlete.user.check_password(guess))

    def test_event_falls_back_to_the_category_default(self):
        self.assertIsNone(self.application.primary_event)
        athlete = services.import_application(self.application)
        self.assertEqual(athlete.primary_event.code, "100M")

    def test_explicit_primary_event_wins(self):
        event = make_event(code="400M", name="400 公尺", distance=400)
        self.application.primary_event = event
        self.application.save()
        athlete = services.import_application(self.application)
        self.assertEqual(athlete.primary_event, event)


class SeedProjectsTests(TestCase):
    def test_creates_the_dbsac_project(self):
        call_command("seed_projects")
        project = Project.objects.get(slug="dbsac-sc-2026")
        self.assertEqual(project.status, ProjectStatus.OPEN)
        self.assertEqual(project.capacity_per_session, 5)
        self.assertEqual(project.session_count, 10)
        self.assertEqual(float(project.price_hkd), 320.0)
        self.assertIn("退款", project.important_note)

    def test_creates_the_polyu_project(self):
        call_command("seed_projects")
        project = Project.objects.get(slug="polyu-sc-2026")
        self.assertEqual(project.title, "PolyU Athletics Team - S&C session for Athletics")
        self.assertEqual(project.status, ProjectStatus.OPEN)
        self.assertEqual(project.start_date, date(2026, 9, 1))
        self.assertEqual(project.end_date, date(2026, 11, 24))
        self.assertEqual(project.session_count, 13)
        self.assertEqual(project.capacity_per_session, 8)
        self.assertEqual(float(project.price_hkd), 0.0)
        self.assertEqual(project.trainer, "Lai Chun Ho")
        self.assertIn("X202", project.venue_address)
        self.assertEqual(
            project.default_school_or_club, "The Hong Kong Polytechnic University"
        )
        self.assertIn("6531 2212", project.contact_note)

    def test_polyu_project_is_listed_and_open_for_applications(self):
        call_command("seed_projects")
        listing = self.client.get(reverse("programs:list"))
        self.assertContains(listing, "PolyU Athletics Team")
        detail = self.client.get(reverse("programs:detail", args=["polyu-sc-2026"]))
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.context["accepting"])

    def test_rerun_does_not_duplicate_or_overwrite(self):
        call_command("seed_projects")
        Project.objects.filter(slug="dbsac-sc-2026").update(title="教練改過的名稱")
        call_command("seed_projects")
        self.assertEqual(Project.objects.filter(slug="dbsac-sc-2026").count(), 1)
        self.assertEqual(Project.objects.get(slug="dbsac-sc-2026").title, "教練改過的名稱")

    def test_force_restores_the_original_content(self):
        call_command("seed_projects")
        Project.objects.filter(slug="dbsac-sc-2026").update(title="改過")
        call_command("seed_projects", "--force")
        self.assertIn("Strength", Project.objects.get(slug="dbsac-sc-2026").title)


class AdminActionTests(TestCase):
    """後台的匯入動作是這個功能的核心操作，要確保它真的接得上。"""

    def setUp(self):
        make_event()
        self.project = make_project()
        self.client.post(reverse("programs:apply", args=[self.project.slug]), VALID_FORM)
        self.admin = User.objects.create_superuser(
            username="root", password="test-pw-12345", email="root@example.com"
        )
        self.client.force_login(self.admin)

    def test_import_action_creates_the_athlete(self):
        url = reverse("admin:programs_application_changelist")
        r = self.client.post(
            url,
            {
                "action": "import_to_atm",
                "_selected_action": [str(Application.objects.get().pk)],
            },
            follow=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(AthleteProfile.objects.count(), 1)

    def test_export_csv_returns_a_file(self):
        url = reverse("admin:programs_application_changelist")
        r = self.client.post(
            url,
            {
                "action": "export_csv",
                "_selected_action": [str(Application.objects.get().pk)],
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
        self.assertIn("Chan Tai Man", r.content.decode("utf-8-sig"))

    def test_application_change_page_renders(self):
        application = Application.objects.get()
        r = self.client.get(
            reverse("admin:programs_application_change", args=[application.pk])
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "報名摘要")

    def test_project_change_page_renders(self):
        r = self.client.get(
            reverse("admin:programs_project_change", args=[self.project.pk])
        )
        self.assertEqual(r.status_code, 200)

"""課表模板與 fixture 資料完整性的測試。"""

from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from core.models import SessionType
from core.test_factories import TODAY, make_athlete, make_coach
from injury.models import BodyPart, ExerciseModification
from planning.management.commands.seed_templates import TEMPLATES
from planning.models import SessionTemplate
from training.models import Exercise


class ExerciseModificationFixtureTests(TestCase):
    """替代動作表是教練的核心工具，fixture 壞掉會靜默失效，所以直接驗資料。"""

    fixtures = ["exercises", "exercise_modifications"]

    def test_every_modification_points_at_a_real_exercise(self):
        for mod in ExerciseModification.objects.select_related(
            "original_exercise", "substitute_exercise"
        ):
            with self.subTest(mod=mod.pk):
                self.assertIsNotNone(mod.original_exercise)
                self.assertTrue(
                    mod.substitute_exercise or mod.substitute_name,
                    "沒有替代動作時至少要寫 substitute_name（或明示暫停）",
                )

    def test_substitute_is_never_the_original(self):
        for mod in ExerciseModification.objects.all():
            with self.subTest(mod=mod.pk):
                self.assertNotEqual(
                    mod.original_exercise_id, mod.substitute_exercise_id
                )

    def test_body_parts_are_valid_choices(self):
        valid = set(BodyPart.values)
        for mod in ExerciseModification.objects.all():
            with self.subTest(mod=mod.pk):
                self.assertTrue(mod.contraindicated_body_parts, "禁忌部位不可為空")
                self.assertLessEqual(set(mod.contraindicated_body_parts), valid)

    def test_every_body_part_has_at_least_one_substitute(self):
        """任何一個部位受傷，教練都要查得到替代動作——這是這次擴充的目的。"""
        covered = set()
        for parts in ExerciseModification.objects.values_list(
            "contraindicated_body_parts", flat=True
        ):
            covered.update(parts)
        missing = set(BodyPart.values) - covered
        self.assertEqual(missing, set(), f"這些部位還沒有替代動作：{sorted(missing)}")

    def test_pain_thresholds_are_within_scale(self):
        for mod in ExerciseModification.objects.all():
            with self.subTest(mod=mod.pk):
                self.assertGreaterEqual(mod.max_pain_level, 0)
                self.assertLessEqual(mod.max_pain_level, 10)


class SeedTemplatesTests(TestCase):
    fixtures = ["exercises"]

    def setUp(self):
        self.coach = make_coach()

    def run_seed(self, *args):
        out = StringIO()
        call_command("seed_templates", *args, stdout=out)
        return out.getvalue()

    def test_creates_all_templates_for_existing_coach(self):
        self.run_seed()
        self.assertEqual(
            SessionTemplate.objects.filter(coach=self.coach).count(), len(TEMPLATES)
        )

    def test_is_idempotent(self):
        self.run_seed()
        self.run_seed()
        self.assertEqual(
            SessionTemplate.objects.filter(coach=self.coach).count(), len(TEMPLATES)
        )

    def test_unknown_coach_raises(self):
        with self.assertRaises(CommandError):
            call_command("seed_templates", "--coach", "no-such-coach")

    def test_skip_if_empty_is_quiet_without_coaches(self):
        SessionTemplate.objects.all().delete()
        self.coach.user.delete()
        self.run_seed("--skip-if-empty")
        self.assertEqual(SessionTemplate.objects.count(), 0)

    def test_missing_coach_without_flag_raises(self):
        self.coach.user.delete()
        with self.assertRaises(CommandError):
            call_command("seed_templates")


class TemplatePayloadTests(TestCase):
    """payload 的欄位名要和 TrackSet / StrengthSet 對得上，否則 clone 會爆或靜默漏資料。"""

    fixtures = ["exercises"]

    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        call_command("seed_templates", stdout=StringIO())

    def test_all_exercise_codes_exist_in_the_dictionary(self):
        codes = set()
        for spec in TEMPLATES:
            for row in spec["payload"].get("strength_sets", []):
                codes.add(row["exercise_code"])
        known = set(Exercise.objects.values_list("code", flat=True))
        self.assertEqual(codes - known, set(), "模板引用了不存在的動作代碼")

    def test_every_template_has_content(self):
        for tpl in SessionTemplate.objects.all():
            with self.subTest(name=tpl.name):
                payload = tpl.payload
                self.assertTrue(
                    payload.get("track_sets") or payload.get("strength_sets"),
                    "模板不能是空殼",
                )
                self.assertTrue(tpl.description)

    def test_clone_creates_a_session_with_all_sets(self):
        for tpl in SessionTemplate.objects.all():
            with self.subTest(name=tpl.name):
                session = tpl.clone_to_session(self.athlete, TODAY)
                self.assertEqual(session.athlete, self.athlete)
                self.assertEqual(session.session_type, tpl.session_type)
                self.assertEqual(session.assigned_by, self.coach)
                self.assertEqual(
                    session.track_sets.count(), len(tpl.payload.get("track_sets", []))
                )
                self.assertEqual(
                    session.strength_sets.count(),
                    len(tpl.payload.get("strength_sets", [])),
                    "有動作代碼查不到就會被靜默略過",
                )

    def test_track_templates_prescribe_sprint_distances(self):
        """短跑專項：專項課的單趟距離不應該出現長跑距離。"""
        for tpl in SessionTemplate.objects.filter(session_type=SessionType.TRACK):
            for row in tpl.payload["track_sets"]:
                with self.subTest(name=tpl.name, row=row["description"]):
                    self.assertLessEqual(row["distance_m"], 400)

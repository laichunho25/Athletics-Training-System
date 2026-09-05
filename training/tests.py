"""訓練活動庫的測試。"""
import io

from django.core.management import call_command
from django.test import TestCase

from analytics.models import (
    MetricCategory,
    MetricDomain,
    domain_for_activity,
    metric_category_for_activity,
)
from core.models import SessionType
from core.test_factories import make_admin, make_athlete, make_coach
from training.library import library_groups, visible_definitions
from training.management.commands.seed_activities import NOTES
from training.models import (
    ActivityCategory,
    ActivityDefinition,
    Discipline,
    LibraryStatus,
    MovementKind,
    SportType,
)


class PlyometricLibraryTests(TestCase):
    """增強式訓練分成四大部份，每個動作都有一句動作說明。"""

    #: 四大部份 → 一定要在清單裡的代表動作
    GROUPS = {
        ActivityCategory.PLYO_BASIC: ["抱膝跳", "深跳", "深蹲跳", "下蹲跳", "分腿跳",
                                      "立定跳遠"],
        ActivityCategory.PLYO_TRACK: ["跨欄架跳", "跨步跳", "單腳跨步跳", "側向欄架跳",
                                      "落下跳接欄架跳", "高遠衝力跳躍步"],
        ActivityCategory.PLYO_UPPER: ["藥球胸前推球", "藥球過頭砸球", "增強式俯臥撐"],
        ActivityCategory.PLYO_POGO: ["雙腳踝彈跳", "單腳踝彈跳", "原地踝彈跳",
                                     "直線前進踝彈跳", "側向踝彈跳", "旋轉踝彈跳",
                                     "低振幅踝彈跳", "高振幅踝彈跳"],
    }

    def setUp(self):
        call_command("seed_activities", verbosity=0, stdout=io.StringIO())

    def test_the_four_groups_are_all_there(self):
        for category, names in self.GROUPS.items():
            rows = ActivityDefinition.objects.filter(category=category)
            self.assertEqual(
                set(names) - set(rows.values_list("name", flat=True)),
                set(),
                f"{category} 少了動作",
            )

    def test_every_plyometric_movement_has_a_description(self):
        for category in self.GROUPS:
            for row in ActivityDefinition.objects.filter(category=category):
                self.assertTrue(row.note, f"{row.name} 沒有動作說明")
                self.assertTrue(row.name_en, f"{row.name} 沒有英文名")

    def test_pogo_descriptions_are_the_ones_the_coach_wrote(self):
        row = ActivityDefinition.objects.get(name="單腳踝彈跳")
        self.assertEqual(row.note, NOTES["單腳踝彈跳"])
        self.assertIn("單側穩定度", row.note)

    def test_running_the_seed_twice_does_not_duplicate_or_overwrite(self):
        row = ActivityDefinition.objects.get(name="抱膝跳")
        row.note = "教練自己改的說明"
        row.save(update_fields=["note"])
        before = ActivityDefinition.objects.count()

        call_command("seed_activities", verbosity=0, stdout=io.StringIO())

        self.assertEqual(ActivityDefinition.objects.count(), before)
        row.refresh_from_db()
        self.assertEqual(row.note, "教練自己改的說明")

    def test_the_old_plyo_activities_moved_into_the_new_groups(self):
        """舊的「增強式／爆發力」項目分到四大部份裡，不留一個雜項分類。"""
        self.assertFalse(
            ActivityDefinition.objects.filter(
                category=ActivityCategory.PLYO, is_builtin=True
            ).exists()
        )

    def test_the_groups_land_under_the_plyometric_discipline(self):
        """四大部份的動作在項目庫裡都掛在「體能訓練 · 增強式與爆發力訓練」底下。"""
        for category, names in self.GROUPS.items():
            for name in names:
                row = ActivityDefinition.objects.get(name=name)
                self.assertEqual(row.category, category.value)
                self.assertEqual(row.discipline.name, "增強式與爆發力訓練")
                self.assertEqual(row.discipline.sport.name, "體能訓練")

    def test_the_discipline_shows_up_as_its_own_heading(self):
        library = list(ActivityDefinition.objects.filter(is_active=True))
        labels = {g["label"] for g in library_groups(library)}
        self.assertIn("體能訓練 · 增強式與爆發力訓練", labels)

    def test_plyometric_data_still_lands_in_the_strength_domain(self):
        for category in self.GROUPS:
            self.assertEqual(
                metric_category_for_activity(category.value), MetricCategory.PLYO.value
            )
            self.assertEqual(
                domain_for_activity(SessionType.STRENGTH, category.value),
                MetricDomain.STRENGTH.value,
            )


class ExerciseLibraryStructureTests(TestCase):
    """運動練習項目庫：三層目錄、挑選清單的來源、以及等管理員確認的流程。"""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_activities", verbosity=0, stdout=io.StringIO())
        cls.coach = make_coach(username="lib-coach").user
        cls.admin = make_admin(username="lib-admin")

    def test_the_seeded_catalogue_has_the_sports_the_coach_asked_for(self):
        self.assertEqual(
            [s.name for s in SportType.objects.order_by("order")],
            ["田徑", "體能訓練", "共通基礎"],
        )
        track = SportType.objects.get(name="田徑")
        self.assertEqual(
            [d.name for d in track.disciplines.order_by("order")],
            ["短跑", "中長跑", "跨欄", "跳部", "投擲", "接力"],
        )
        conditioning = SportType.objects.get(name="體能訓練")
        self.assertEqual(
            [d.name for d in conditioning.disciplines.order_by("order")],
            ["有氧訓練（心肺耐力）", "肌力與重量訓練", "核心與穩定性訓練",
             "增強式與爆發力訓練"],
        )
        self.assertIn("熱身", [k.name for k in MovementKind.objects.all()])
        self.assertIn("專項動作", [k.name for k in MovementKind.objects.all()])

    def test_every_seeded_movement_is_filed_under_a_discipline(self):
        """挑選清單是照運動項目分組的，沒歸類的動作會掉進「其他」堆。"""
        self.assertFalse(
            ActivityDefinition.objects.filter(is_builtin=True, discipline=None).exists()
        )

    def test_relay_and_middle_distance_movements_are_not_filed_as_sprints(self):
        self.assertEqual(
            ActivityDefinition.objects.get(name="間歇跑").discipline.name, "中長跑"
        )
        self.assertEqual(
            ActivityDefinition.objects.get(name="接力交棒練習").discipline.name, "接力"
        )

    def test_event_specific_movements_carry_no_preset_distance(self):
        """專項動作的距離是排課那天才填的，項目庫裡不預設、名字裡也不寫米數。"""
        rows = ActivityDefinition.objects.filter(
            is_builtin=True,
            category__in=(ActivityCategory.TRACK, ActivityCategory.PLYO_TRACK),
        )
        self.assertTrue(rows.exists())
        for row in rows:
            with self.subTest(name=row.name):
                self.assertEqual(row.default_distance, "")
                self.assertNotRegex(row.name, r"\d+\s*(m|米|公尺)")

    def test_a_coach_submission_waits_for_an_admin(self):
        """教練加的動作先掛待確認：只有自己看得到，別人的挑選清單裡沒有。"""
        discipline = Discipline.objects.get(name="短跑")
        row = ActivityDefinition.objects.create(
            name="沙地加速跑", discipline=discipline, created_by=self.coach,
            status=LibraryStatus.PENDING,
        )
        self.assertIn(row, visible_definitions(self.coach))
        self.assertIn(row, visible_definitions(self.admin))
        self.assertNotIn(row, visible_definitions(make_athlete(username="lib-other").user))

    def test_an_approved_submission_shows_up_for_everyone(self):
        discipline = Discipline.objects.get(name="短跑")
        row = ActivityDefinition.objects.create(
            name="沙地加速跑", discipline=discipline, created_by=self.coach,
            status=LibraryStatus.APPROVED,
        )
        self.assertIn(row, visible_definitions(make_athlete(username="lib-other2").user))

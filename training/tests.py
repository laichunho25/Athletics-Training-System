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
from training.library import library_groups
from training.management.commands.seed_activities import NOTES
from training.models import ActivityCategory, ActivityDefinition


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

    def test_the_groups_show_up_as_their_own_headings(self):
        library = list(ActivityDefinition.objects.filter(is_active=True))
        labels = {g["value"] for g in library_groups(library)}
        for category in self.GROUPS:
            self.assertIn(category.value, labels)

    def test_plyometric_data_still_lands_in_the_strength_domain(self):
        for category in self.GROUPS:
            self.assertEqual(
                metric_category_for_activity(category.value), MetricCategory.PLYO.value
            )
            self.assertEqual(
                domain_for_activity(SessionType.STRENGTH, category.value),
                MetricDomain.STRENGTH.value,
            )

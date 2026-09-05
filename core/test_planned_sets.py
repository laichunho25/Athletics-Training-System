"""課表寫了組數 → 自動開好同樣筆數的空白紀錄。

流程上這是最花時間的一段：教練在課表寫「深蹲 3 組 × 5 次 @ 100kg」，
以前運動員練完要把同一批數字在「本課數據紀錄」再打一次（3 組共 21 格）。
現在加活動時就先開好 3 組，練完只要填「完成數值」。
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from analytics.models import MetricItem, MetricRecord, ensure_builtin_items
from analytics.recording import _rest_seconds, planned_sets_for
from core.models import SessionType
from core.test_factories import make_athlete, make_session
from training.models import ActivityDefinition, BlockType, SessionActivity

TODAY = date(2026, 6, 1)


class RestParsingTests(TestCase):
    """休息時間那一格是自由文字，看得懂的才換算成秒。"""

    def test_units(self):
        self.assertEqual(_rest_seconds("30s"), 30)
        self.assertEqual(_rest_seconds("30 秒"), 30)
        self.assertEqual(_rest_seconds("2 分鐘"), 120)
        self.assertEqual(_rest_seconds("1 分 30 秒"), 90)
        self.assertEqual(_rest_seconds("90"), 90)

    def test_only_the_first_segment_counts(self):
        # 「每次 5 分鐘 / 每組 15 分鐘」一格寫了兩件事，取斜線前那一段
        self.assertEqual(_rest_seconds("每次 5 分鐘 / 每組 15 分鐘"), 300)

    def test_text_without_numbers_is_unknown(self):
        self.assertIsNone(_rest_seconds("walk back"))
        self.assertIsNone(_rest_seconds(""))


class PlannedSetsTests(TestCase):
    def row(self, **kwargs):
        return SessionActivity(**{"block": BlockType.MAIN, "name": "深蹲", **kwargs})

    def test_sets_decide_how_many_rows(self):
        rows = planned_sets_for(
            self.row(sets="3 組", reps="5 次", weight="100kg", rest="2 分鐘")
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["set_no"] for r in rows], [1, 2, 3])
        self.assertEqual(rows[0]["reps"], 5)
        self.assertEqual(rows[0]["weight_kg"], Decimal("100"))
        self.assertEqual(rows[0]["rest_sec"], 120)

    def test_a_single_set_has_no_set_number(self):
        rows = planned_sets_for(self.row(sets="1 組"))
        self.assertEqual([r["set_no"] for r in rows], [None])

    def test_no_sets_means_no_rows(self):
        # 教練還沒定組數就不要先開空列，免得課表上一堆用不到的紀錄
        self.assertEqual(planned_sets_for(self.row(sets="")), [])
        self.assertEqual(planned_sets_for(self.row(sets="視情況")), [])

    def test_body_weight_leaves_the_weight_empty(self):
        rows = planned_sets_for(self.row(sets="2 組", weight="body weight"))
        self.assertIsNone(rows[0]["weight_kg"])

    def test_a_silly_number_of_sets_is_capped(self):
        self.assertEqual(len(planned_sets_for(self.row(sets="99 組"))), 20)


class AddActivityOpensRecordsTests(TestCase):
    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a1")
        self.client.force_login(self.athlete.user)
        self.session = make_session(
            self.athlete, TODAY, session_type=SessionType.STRENGTH
        )

    def url(self):
        return reverse("web:session_detail", args=[self.session.id])

    def add_activity(self, **extra):
        data = {
            "action": "add_activity",
            "block": BlockType.MAIN,
            "name": "槓鈴深蹲",
            "sets": "3 組",
            "reps": "5 次",
            "weight": "100kg",
            "rest": "2 分鐘",
        }
        data.update(extra)
        return self.client.post(self.url(), data)

    def test_adding_an_activity_opens_one_record_per_set(self):
        self.assertEqual(self.add_activity().status_code, 302)

        records = list(MetricRecord.objects.order_by("set_no"))
        self.assertEqual(len(records), 3)
        self.assertEqual([r.set_no for r in records], [1, 2, 3])
        self.assertEqual(records[0].item.name, "槓鈴深蹲")
        self.assertEqual(records[0].session, self.session)
        self.assertEqual(records[0].block, BlockType.MAIN)
        self.assertEqual(records[0].reps, 5)
        self.assertEqual(records[0].weight_kg, Decimal("100"))
        self.assertEqual(records[0].rest_sec, 120)
        # 完成數值留白——那正是運動員練完唯一要填的東西
        self.assertTrue(all(r.value is None for r in records))

    def test_an_activity_without_sets_opens_nothing(self):
        self.add_activity(sets="", reps="", weight="", rest="")
        self.assertEqual(MetricRecord.objects.count(), 0)
        # 但項目照樣開好，之後手動登數據挑得到
        self.assertTrue(MetricItem.objects.filter(name="槓鈴深蹲").exists())

    def test_adding_the_same_activity_again_does_not_duplicate_records(self):
        self.add_activity()
        self.add_activity()
        self.assertEqual(MetricRecord.objects.count(), 3)

    def test_already_recorded_sets_are_never_overwritten(self):
        self.add_activity()
        first = MetricRecord.objects.order_by("set_no").first()
        first.value = Decimal("102.5")
        first.save()

        self.add_activity()
        first.refresh_from_db()
        self.assertEqual(first.value, Decimal("102.5"))
        self.assertEqual(MetricRecord.objects.count(), 3)

    def test_same_movement_in_two_blocks_gets_its_own_sets(self):
        self.add_activity(block=BlockType.WARMUP, sets="2 組", weight="40kg")
        self.add_activity(block=BlockType.MAIN)
        self.assertEqual(MetricRecord.objects.filter(block=BlockType.WARMUP).count(), 2)
        self.assertEqual(MetricRecord.objects.filter(block=BlockType.MAIN).count(), 3)


class PlanSetsActionTests(TestCase):
    """「依課表開組」：先加了活動、之後才補組數的行，可以再補開一次。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a1")
        self.client.force_login(self.athlete.user)
        self.session = make_session(
            self.athlete, TODAY, session_type=SessionType.STRENGTH
        )
        self.activity = SessionActivity.objects.create(
            session=self.session, block=BlockType.MAIN, order=1, name="臥推"
        )

    def url(self):
        return reverse("web:session_detail", args=[self.session.id])

    def run_action(self):
        return self.client.post(self.url(), {"action": "plan_sets"})

    def test_nothing_to_open_when_no_sets_are_written(self):
        self.run_action()
        self.assertEqual(MetricRecord.objects.count(), 0)

    def test_filling_in_the_sets_afterwards_then_opening(self):
        self.activity.sets = "4 組"
        self.activity.reps = "6"
        self.activity.save()

        self.run_action()
        records = MetricRecord.objects.order_by("set_no")
        self.assertEqual([r.set_no for r in records], [1, 2, 3, 4])
        self.assertEqual(records[0].reps, 6)

    def test_running_it_twice_is_safe(self):
        self.activity.sets = "4 組"
        self.activity.save()
        self.run_action()
        self.run_action()
        self.assertEqual(MetricRecord.objects.count(), 4)

    def test_a_stranger_cannot_open_sets_on_someone_elses_session(self):
        other = make_athlete("a2")
        self.client.force_login(other.user)
        self.activity.sets = "4 組"
        self.activity.save()
        self.assertEqual(self.run_action().status_code, 404)
        self.assertEqual(MetricRecord.objects.count(), 0)


class ActivityDefaultsFlowTests(TestCase):
    """從項目庫挑一個有預設值的動作，一路帶到紀錄列。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a1")
        self.client.force_login(self.athlete.user)
        self.session = make_session(
            self.athlete, TODAY, session_type=SessionType.STRENGTH
        )
        ActivityDefinition.objects.create(
            name="保加利亞分腿蹲",
            name_en="Bulgarian Split Squat",
            category="LOWER",
            default_block=BlockType.SUPPLEMENT,
            default_sets="3 組",
            default_reps="左/右腳 8 次",
            default_weight="20kg",
            default_rest="60 秒",
        )

    def test_library_defaults_reach_the_record_rows(self):
        # 一次加多項時，逐項細節照活動庫的預設值走
        self.client.post(
            reverse("web:session_detail", args=[self.session.id]),
            {
                "action": "add_activity",
                "block": BlockType.SUPPLEMENT,
                "name": "保加利亞分腿蹲\n臥推",
            },
        )
        records = MetricRecord.objects.filter(item__name="保加利亞分腿蹲").order_by(
            "set_no"
        )
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].reps, 8)  # 「左/右腳 8 次」→ 8
        self.assertEqual(records[0].weight_kg, Decimal("20"))
        self.assertEqual(records[0].rest_sec, 60)
        # 沒有預設組數的那一項不會開空列
        self.assertFalse(MetricRecord.objects.filter(item__name="臥推").exists())

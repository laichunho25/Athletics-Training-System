"""從課表哪一段（熱身／正課／補充／恢復）加進數據分析，以及 kg ↔ 秒 的單位切換。"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from analytics.models import (
    MetricDomain,
    MetricItem,
    MetricRecord,
    ensure_builtin_items,
)
from core.models import SessionType
from core.test_factories import make_athlete, make_session
from training.models import BlockType, SessionActivity

TODAY = date(2026, 6, 1)


class PushedBlockTests(TestCase):
    """課表某一區加進數據分析之後，那一段的身分有跟著過去。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a1")
        self.client.force_login(self.athlete.user)
        self.session = make_session(
            self.athlete, TODAY, session_type=SessionType.STRENGTH
        )
        SessionActivity.objects.create(
            session=self.session,
            block=BlockType.MAIN,
            order=1,
            name="槓鈴深蹲",
            sets="2 組",
            weight="100kg",
        )

    def url(self):
        return reverse("web:session_detail", args=[self.session.id])

    def analytics_url(self):
        return reverse("web:analytics")

    def push(self, block=BlockType.MAIN, domain=MetricDomain.STRENGTH):
        return self.client.post(
            self.url(),
            {"action": "push_metrics", "block": block, "domain": domain},
        )

    def test_the_block_travels_with_the_records(self):
        self.assertEqual(self.push().status_code, 302)
        recs = list(MetricRecord.objects.order_by("set_no"))
        self.assertEqual([r.block for r in recs], [BlockType.MAIN, BlockType.MAIN])
        self.assertEqual(recs[0].block_label, "正課")

    def test_the_session_page_says_whether_a_block_was_pushed(self):
        page = self.client.get(self.url())
        self.assertContains(page, "加入本課訓練到數據分析")
        self.assertContains(page, "這一區還沒加進數據分析")

        self.push()
        page = self.client.get(self.url())
        self.assertContains(page, "到數據分析填")

    def test_an_unknown_block_is_refused(self):
        self.push(block="NOT_A_BLOCK")
        self.assertEqual(MetricRecord.objects.count(), 0)

    def test_the_block_can_be_changed_from_the_analytics_page(self):
        self.push()
        rec = MetricRecord.objects.order_by("set_no").first()
        r = self.client.post(self.analytics_url(), {
            "action": "edit_record",
            "domain": MetricDomain.STRENGTH,
            "item_id": rec.item_id,
            "only": rec.id,
            f"block_{rec.id}": BlockType.WARMUP,
        })
        self.assertEqual(r.status_code, 302)
        rec.refresh_from_db()
        self.assertEqual(rec.block, BlockType.WARMUP)

    def test_move_record_reorders_the_pushed_sets(self):
        self.push()
        first, second = list(MetricRecord.objects.order_by("set_no"))
        r = self.client.post(
            self.analytics_url(), {"action": "move_record", "down": first.id}
        )
        self.assertEqual(r.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.set_no, second.set_no), (2, 1))

    def test_item_unit_switches_between_kg_and_seconds(self):
        self.push()
        item = MetricItem.objects.get(domain=MetricDomain.STRENGTH, name="槓鈴深蹲")
        self.assertEqual(item.unit, "kg")

        r = self.client.post(self.analytics_url(), {
            "action": "item_unit",
            "domain": MetricDomain.STRENGTH,
            "item_id": item.id,
            "unit": "秒",
        })
        self.assertEqual(r.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.unit, "秒")
        # 撐時間的動作：撐得越久越好
        self.assertTrue(item.higher_is_better)

        self.client.post(self.analytics_url(), {
            "action": "item_unit",
            "domain": MetricDomain.STRENGTH,
            "item_id": item.id,
            "unit": "kg",
        })
        item.refresh_from_db()
        self.assertEqual(item.unit, "kg")

    def test_item_unit_rejects_other_units(self):
        self.push()
        item = MetricItem.objects.get(domain=MetricDomain.STRENGTH, name="槓鈴深蹲")
        self.client.post(self.analytics_url(), {
            "action": "item_unit",
            "domain": MetricDomain.STRENGTH,
            "item_id": item.id,
            "unit": "公里",
        })
        item.refresh_from_db()
        self.assertEqual(item.unit, "kg")


class AnalyticsBlockTests(TestCase):
    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a2")
        self.client.force_login(self.athlete.user)
        self.item = MetricItem.objects.filter(
            domain=MetricDomain.STRENGTH, unit="kg"
        ).first()

    def test_add_record_keeps_the_block(self):
        url = reverse("web:analytics")
        self.client.post(url, {
            "action": "add_record",
            "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id,
            "date": TODAY.isoformat(),
            "value": ["100", "105"],
            "completed": ["1", "1"],
            "block": BlockType.SUPPLEMENT,
        })
        self.assertEqual(
            {r.block for r in MetricRecord.objects.all()}, {BlockType.SUPPLEMENT}
        )

        page = self.client.get(
            f"{url}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}&item={self.item.id}"
        )
        self.assertContains(page, "補充練習")

    def test_program_can_be_changed_from_the_detail_table(self):
        url = reverse("web:analytics")
        self.client.post(url, {
            "action": "add_record",
            "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id,
            "date": TODAY.isoformat(),
            "value": "100",
            "completed": "1",
        })
        rec = MetricRecord.objects.get()
        self.assertIsNone(rec.session_id)

        s = make_session(self.athlete, TODAY, session_type=SessionType.STRENGTH)
        r = self.client.post(url, {
            "action": "edit_record",
            "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id,
            "only": rec.id,
            f"session_{rec.id}": s.id,
        })
        self.assertEqual(r.status_code, 302)
        rec.refresh_from_db()
        self.assertEqual(rec.session_id, s.id)

        # 清空就變成不對應課表
        self.client.post(url, {
            "action": "edit_record",
            "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id,
            "only": rec.id,
            f"session_{rec.id}": "",
        })
        rec.refresh_from_db()
        self.assertIsNone(rec.session_id)

    def test_program_of_a_wrong_session_type_is_refused(self):
        url = reverse("web:analytics")
        self.client.post(url, {
            "action": "add_record",
            "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id,
            "date": TODAY.isoformat(),
            "value": "100", "completed": "1",
        })
        rec = MetricRecord.objects.get()
        track = make_session(self.athlete, TODAY, session_type=SessionType.TRACK)
        self.client.post(url, {
            "action": "edit_record",
            "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id,
            "only": rec.id,
            f"session_{rec.id}": track.id,
        })
        rec.refresh_from_db()
        self.assertIsNone(rec.session_id)

    def test_another_athletes_program_cannot_be_attached(self):
        url = reverse("web:analytics")
        self.client.post(url, {
            "action": "add_record",
            "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id,
            "date": TODAY.isoformat(),
            "value": "100", "completed": "1",
        })
        rec = MetricRecord.objects.get()
        other = make_session(
            make_athlete("a9"), TODAY, session_type=SessionType.STRENGTH
        )
        self.client.post(url, {
            "action": "edit_record",
            "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id,
            "only": rec.id,
            f"session_{rec.id}": other.id,
        })
        rec.refresh_from_db()
        self.assertIsNone(rec.session_id)

    def test_unit_switch_from_the_analytics_page(self):
        url = reverse("web:analytics")
        r = self.client.post(url, {
            "action": "item_unit",
            "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id,
            "unit": "秒",
        })
        self.assertEqual(r.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.unit, "秒")

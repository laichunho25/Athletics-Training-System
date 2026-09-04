"""數據紀錄放回課表的哪一段（熱身／正課／補充／恢復），以及 kg ↔ 秒 的單位切換。"""
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
from training.models import BlockType

TODAY = date(2026, 6, 1)


class MetricBlockTests(TestCase):
    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a1")
        self.client.force_login(self.athlete.user)
        self.session = make_session(
            self.athlete, TODAY, session_type=SessionType.STRENGTH
        )

    def url(self):
        return reverse("web:session_detail", args=[self.session.id])

    def add(self, **extra):
        data = {
            "action": "add_metric",
            "domain": MetricDomain.STRENGTH,
            "item_name": "槓鈴深蹲",
            "date": TODAY.isoformat(),
            "value": ["100", "105"],
            "completed": ["1", "1"],
        }
        data.update(extra)
        return self.client.post(self.url(), data)

    def test_block_is_stored_and_shown_on_the_session_page(self):
        self.assertEqual(self.add(block=BlockType.MAIN).status_code, 302)
        recs = list(MetricRecord.objects.order_by("set_no"))
        self.assertEqual([r.block for r in recs], [BlockType.MAIN, BlockType.MAIN])
        self.assertEqual(recs[0].block_label, "正課")

        page = self.client.get(self.url())
        self.assertContains(page, "正課")
        self.assertContains(page, "課表區塊")

    def test_unknown_block_is_treated_as_unset(self):
        self.add(block="NOT_A_BLOCK")
        self.assertEqual({r.block for r in MetricRecord.objects.all()}, {""})

    def test_block_can_be_changed_on_an_existing_record(self):
        self.add(block=BlockType.MAIN)
        rec = MetricRecord.objects.order_by("set_no").first()
        r = self.client.post(self.url(), {
            "action": "edit_metric",
            "only": rec.id,
            f"block_{rec.id}": BlockType.WARMUP,
        })
        self.assertEqual(r.status_code, 302)
        rec.refresh_from_db()
        self.assertEqual(rec.block, BlockType.WARMUP)

    def test_records_in_different_blocks_are_listed_separately(self):
        self.add(block=BlockType.WARMUP, value=["40"], completed=["1"])
        self.add(block=BlockType.MAIN, value=["100"], completed=["1"])

        page = self.client.get(self.url())
        groups = page.context["metric_groups"]
        self.assertEqual(len(groups), 2)
        # 熱身排在正課前面
        self.assertEqual([g["block"] for g in groups], [BlockType.WARMUP, BlockType.MAIN])

    def test_move_metric_reorders_the_sets(self):
        self.add(block=BlockType.MAIN)
        first, second = list(MetricRecord.objects.order_by("set_no"))
        r = self.client.post(self.url(), {"action": "move_metric", "down": first.id})
        self.assertEqual(r.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.set_no, second.set_no), (2, 1))

    def test_item_unit_switches_between_kg_and_seconds(self):
        self.add()
        item = MetricItem.objects.get(domain=MetricDomain.STRENGTH, name="槓鈴深蹲")
        self.assertEqual(item.unit, "kg")

        r = self.client.post(self.url(), {
            "action": "item_unit", "item_id": item.id, "unit": "秒",
        })
        self.assertEqual(r.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.unit, "秒")
        # 撐時間的動作：撐得越久越好
        self.assertTrue(item.higher_is_better)

        self.client.post(self.url(), {
            "action": "item_unit", "item_id": item.id, "unit": "kg",
        })
        item.refresh_from_db()
        self.assertEqual(item.unit, "kg")

    def test_item_unit_rejects_other_units(self):
        self.add()
        item = MetricItem.objects.get(domain=MetricDomain.STRENGTH, name="槓鈴深蹲")
        self.client.post(self.url(), {
            "action": "item_unit", "item_id": item.id, "unit": "公里",
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

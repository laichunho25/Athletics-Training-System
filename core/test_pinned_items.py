"""主要必看的訓練項目（📌）——數據分析頁最上面那一張卡。"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from analytics.models import (
    MetricDomain,
    MetricItem,
    MetricRecord,
    ensure_builtin_items,
    pinned_items,
)
from core.test_factories import make_athlete

TODAY = date(2026, 6, 1)


class PinTests(TestCase):
    """釘出來的項目就是「主要必看的訓練項目」那一張卡要看的東西。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("p1")
        self.client.force_login(self.athlete.user)
        self.item = MetricItem.objects.get(
            domain=MetricDomain.STRENGTH, name="平板支撐"
        )
        MetricRecord.objects.create(
            athlete=self.athlete, item=self.item, date=TODAY, value=60
        )

    def url(self):
        return reverse("web:analytics")

    def page(self):
        return self.client.get(
            f"{self.url()}?athlete={self.athlete.id}&domain={MetricDomain.STRENGTH}"
        )

    def pin(self, action="pin_item"):
        return self.client.post(
            self.url(),
            {
                "action": action,
                "domain": MetricDomain.STRENGTH,
                "item_id": self.item.id,
            },
        )

    def test_pinning_puts_the_item_on_the_must_see_card(self):
        self.assertEqual(self.pin().status_code, 302)
        self.assertEqual(pinned_items(self.athlete), [self.item])

        page = self.page()
        self.assertContains(page, "主要必看的訓練項目")
        self.assertEqual([t["item"] for t in page.context["tops"]], [self.item])
        self.assertTrue(page.context["has_pins"])

    def test_pinning_twice_keeps_one_pin(self):
        self.pin()
        self.pin()
        self.assertEqual(self.athlete.pinned_items.count(), 1)

    def test_unpinning_takes_it_off_again(self):
        self.pin()
        self.pin("unpin_item")
        self.assertEqual(pinned_items(self.athlete), [])
        self.assertFalse(self.page().context["has_pins"])

    def test_without_pins_the_card_falls_back_to_the_most_used(self):
        page = self.page()
        self.assertFalse(page.context["has_pins"])
        # 沒釘任何東西時，卡片還是有內容（最常做的動作）
        self.assertEqual([t["item"] for t in page.context["tops"]], [self.item])

    def test_a_pinned_item_without_records_is_still_listed(self):
        empty = MetricItem.objects.create(
            domain=MetricDomain.STRENGTH, name="單腳硬舉", unit="kg"
        )
        self.client.post(self.url(), {
            "action": "pin_item",
            "domain": MetricDomain.STRENGTH,
            "item_id": empty.id,
        })
        tops = self.page().context["tops"]
        self.assertIn(empty, [t["item"] for t in tops])

    def test_pins_are_per_athlete(self):
        self.pin()
        other = make_athlete("p2")
        self.assertEqual(pinned_items(other), [])

    def test_pins_are_kept_apart_by_domain(self):
        self.pin()
        self.assertEqual(pinned_items(self.athlete, MetricDomain.STRENGTH), [self.item])
        self.assertEqual(pinned_items(self.athlete, MetricDomain.TRACK), [])

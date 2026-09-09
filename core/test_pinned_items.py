"""主要必看的訓練項目（📌），以及數據分析頁上「從日曆加入的當日訓練」那一欄。"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from analytics import services as an
from analytics.models import (
    MetricDomain,
    MetricItem,
    MetricRecord,
    ensure_builtin_items,
    pinned_items,
)
from core.models import SessionType
from core.test_factories import make_athlete, make_session
from training.models import BlockType, SessionActivity

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


class PushedSessionPanelTests(TestCase):
    """數據分析頁要看得到「哪幾天的課已經加進來了、還有多少格沒填」。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("p3")
        self.client.force_login(self.athlete.user)
        self.session = make_session(
            self.athlete, TODAY, session_type=SessionType.TRACK
        )
        SessionActivity.objects.create(
            session=self.session, block=BlockType.MAIN, order=1,
            name="150m 反覆跑", sets="2 組",
        )
        self.client.post(
            reverse("web:session_detail", args=[self.session.id]),
            {
                "action": "push_metrics",
                "block": BlockType.MAIN,
                "domain": MetricDomain.TRACK,
            },
        )

    def test_the_pushed_day_is_listed_with_what_is_still_missing(self):
        days = an.pushed_sessions(self.athlete, MetricDomain.TRACK)
        self.assertEqual(len(days), 1)
        day = days[0]
        self.assertEqual(day["session"], self.session)
        self.assertEqual(day["date"], TODAY)
        self.assertEqual(day["sets"], 2)
        self.assertEqual(day["filled"], 0)
        self.assertEqual(day["pending"], 2)
        self.assertEqual([i.name for i in day["items"]], ["150m 反覆跑"])

    def test_filling_a_set_moves_it_out_of_pending(self):
        rec = MetricRecord.objects.order_by("set_no").first()
        MetricRecord.objects.filter(pk=rec.pk).update(value="19.5")
        day = an.pushed_sessions(self.athlete, MetricDomain.TRACK)[0]
        self.assertEqual((day["filled"], day["pending"]), (1, 1))

    def test_the_panel_shows_up_on_the_analytics_page(self):
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.TRACK}"
        )
        self.assertContains(page, "從日曆加入的當日訓練")
        self.assertEqual(len(page.context["day_sessions"]), 1)

    def test_a_day_that_was_never_pushed_is_not_listed(self):
        make_session(self.athlete, date(2026, 6, 2), session_type=SessionType.TRACK)
        self.assertEqual(len(an.pushed_sessions(self.athlete, MetricDomain.TRACK)), 1)

    def test_another_domain_does_not_borrow_the_day(self):
        self.assertEqual(
            an.pushed_sessions(self.athlete, MetricDomain.STRENGTH), []
        )

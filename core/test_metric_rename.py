"""田徑練習訓練紀錄：項目可以改名、可以刪掉，相關的項目會問要不要一起分析。

項目是登記錄時照課表的活動名稱開出來的（「150m 反覆跑」），
名字打錯或想寫清楚一點，不該只能刪掉重記——紀錄要留在同一個項目底下。
另外同一件事常常散在好幾個項目（150m 節奏跑／150m 反覆跑），
畫面上要先問一句「數據分析已經有相關紀錄，要不要加在一起分析」。
"""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from analytics.models import (
    MetricDomain,
    MetricItem,
    MetricRecord,
    TrackMethod,
    ensure_builtin_items,
    rename_item,
    track_item_for,
)
from analytics.services import name_core, related_items
from core.models import SessionType
from core.test_factories import make_athlete, make_session
from training.models import BlockType, SessionActivity

TODAY = date(2026, 6, 1)


class TrackItemBase(TestCase):
    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("track1")
        self.client.force_login(self.athlete.user)
        self.item = track_item_for(TrackMethod.REPEAT, 150)
        self.session = make_session(
            self.athlete, TODAY, session_type=SessionType.TRACK
        )
        MetricRecord.objects.create(
            athlete=self.athlete,
            item=self.item,
            session=self.session,
            date=TODAY,
            value=18,
        )

    def url(self):
        return reverse("web:analytics")

    def post(self, **extra):
        data = {"action": "rename_item", "domain": MetricDomain.TRACK}
        data.update(extra)
        return self.client.post(self.url(), data)


class RenameTests(TrackItemBase):
    def test_renaming_keeps_the_records(self):
        response = self.post(item_id=self.item.id, name="150m 反覆跑（彎道）")
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "150m 反覆跑（彎道）")
        self.assertEqual(
            MetricRecord.objects.filter(athlete=self.athlete, item=self.item).count(), 1
        )

    def test_renaming_also_fixes_the_plan_row(self):
        # 課表上叫舊名字的那一行也一起改，不然下次按「登記錄」又開出第二個項目
        activity = SessionActivity.objects.create(
            session=self.session, block=BlockType.MAIN, order=1, name=self.item.name
        )
        self.post(item_id=self.item.id, name="150m 彎道反覆跑")
        activity.refresh_from_db()
        self.assertEqual(activity.name, "150m 彎道反覆跑")

    def test_a_name_already_used_is_refused(self):
        other = track_item_for(TrackMethod.TEMPO, 150)
        self.post(item_id=self.item.id, name=other.name)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "150m 反覆跑")

    def test_an_empty_name_changes_nothing(self):
        changed, _text = rename_item(self.item, "   ")
        self.assertFalse(changed)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "150m 反覆跑")

    def test_renaming_a_builtin_item_makes_it_a_custom_one(self):
        # 內建項目改了名就算自訂項目；內建的那一個下次開頁補回來（空的）
        builtin = MetricItem.objects.get(domain=MetricDomain.TRACK, name="30m 衝刺")
        changed, _text = rename_item(builtin, "30m 起跑衝刺")
        self.assertTrue(changed)
        builtin.refresh_from_db()
        self.assertFalse(builtin.is_builtin)
        self.assertEqual(builtin.name_en, "")
        ensure_builtin_items()
        self.assertTrue(
            MetricItem.objects.filter(
                domain=MetricDomain.TRACK, name="30m 衝刺"
            ).exists()
        )

    def test_the_list_offers_a_rename_button(self):
        page = self.client.get(
            f"{self.url()}?athlete={self.athlete.id}&domain={MetricDomain.TRACK}"
        )
        self.assertContains(page, 'value="rename_item"')
        self.assertContains(page, "itemedit")

    def test_deleting_a_custom_item_takes_its_records(self):
        response = self.client.post(
            self.url(),
            {
                "action": "delete_item",
                "domain": MetricDomain.TRACK,
                "item_id": self.item.id,
                "confirm": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MetricItem.objects.filter(pk=self.item.pk).exists())
        self.assertEqual(MetricRecord.objects.filter(athlete=self.athlete).count(), 0)


class RelatedItemsTests(TrackItemBase):
    """同一件事散在好幾個項目時，才問「要不要加在一起分析」。"""

    def other_item(self, method=TrackMethod.TEMPO, distance=150, value=19):
        item = track_item_for(method, distance)
        MetricRecord.objects.create(
            athlete=self.athlete, item=item, date=TODAY, value=value
        )
        return item

    def test_name_core_ignores_distance_and_brackets(self):
        self.assertEqual(name_core("150m 反覆跑"), "反覆跑")
        self.assertEqual(name_core("30m 衝刺"), "衝刺")
        self.assertEqual(name_core("反覆跑（彎道）"), "反覆跑")

    def test_same_distance_counts_as_related(self):
        other = self.other_item()
        rows = related_items(self.athlete, self.item)
        self.assertEqual([r["item"] for r in rows], [other])
        self.assertEqual(rows[0]["count"], 1)

    def test_same_method_counts_as_related(self):
        other = self.other_item(method=TrackMethod.REPEAT, distance=120)
        self.assertEqual(
            [r["item"] for r in related_items(self.athlete, self.item)], [other]
        )

    def test_an_item_without_records_is_not_asked_about(self):
        track_item_for(TrackMethod.TEMPO, 150)  # 開了項目但沒登過任何一組
        self.assertEqual(related_items(self.athlete, self.item), [])

    def test_the_page_asks_and_offers_to_analyse_together(self):
        other = self.other_item()
        page = self.client.get(
            f"{self.url()}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.TRACK}&item={self.item.id}"
        )
        self.assertContains(page, "是同一件事")
        self.assertContains(page, "加在一起分析")
        self.assertEqual(
            page.context["related_csv"], f"{self.item.id},{other.id}"
        )

    def test_it_stops_asking_once_they_are_analysed_together(self):
        other = self.other_item()
        page = self.client.get(
            f"{self.url()}?athlete={self.athlete.id}&domain={MetricDomain.TRACK}"
            f"&item={self.item.id}&items={self.item.id},{other.id}"
        )
        self.assertEqual(page.context["related"], [])

    def test_the_plan_page_asks_after_logging_an_activity(self):
        other = self.other_item()
        activity = SessionActivity.objects.create(
            session=self.session, block=BlockType.MAIN, order=1, name=self.item.name
        )
        page = self.client.get(
            reverse("web:session_detail", args=[self.session.id])
            + f"?rdomain={MetricDomain.TRACK}&log={activity.id}"
        )
        self.assertEqual(
            [r["item"] for r in page.context["log_related"]], [other]
        )
        self.assertEqual(
            page.context["log_related_csv"], f"{self.item.id},{other.id}"
        )
        self.assertContains(page, "加在一起分析")

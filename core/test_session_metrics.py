"""課表頁登的數據＝數據分析那一份，而且課別限制了能登哪個範疇。"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from analytics.models import (
    MetricCategory,
    MetricDomain,
    MetricItem,
    MetricRecord,
    ensure_builtin_items,
)
from core.models import SessionType
from training.models import ActivityCategory, ActivityDefinition
from core.test_factories import make_athlete, make_session

TODAY = date(2026, 6, 1)


class SessionMetricTests(TestCase):
    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a1")
        self.client.force_login(self.athlete.user)

    def url(self, session):
        return reverse("web:session_detail", args=[session.id])

    def test_strength_session_writes_the_same_records_as_analytics(self):
        s = make_session(self.athlete, TODAY, session_type=SessionType.STRENGTH)
        r = self.client.post(self.url(s), {
            "action": "add_metric",
            "domain": MetricDomain.STRENGTH,
            "item_name": "槓鈴深蹲",
            "date": TODAY.isoformat(),
            "value": ["100", "105"],
            "reps": ["5", "3"],
            "completed": ["1", "0"],
        })
        self.assertEqual(r.status_code, 302)

        item = MetricItem.objects.get(domain=MetricDomain.STRENGTH, name="槓鈴深蹲")
        recs = list(MetricRecord.objects.filter(item=item).order_by("set_no"))
        self.assertEqual(len(recs), 2)
        self.assertEqual([x.session_id for x in recs], [s.id, s.id])
        # 單位是 kg 的項目，重量自動沿用數值，噸位才算得出來
        self.assertEqual([float(x.weight_kg) for x in recs], [100.0, 105.0])

        # 同一份資料在數據分析頁看得到，不用再輸入一次
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}&item={item.id}"
        )
        self.assertContains(page, "槓鈴深蹲")

    def test_track_session_cannot_log_strength(self):
        s = make_session(self.athlete, TODAY, session_type=SessionType.TRACK)
        item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH).first()
        self.client.post(self.url(s), {
            "action": "add_metric", "domain": MetricDomain.STRENGTH,
            "item_id": item.id, "date": TODAY.isoformat(), "value": "80",
        })
        self.assertFalse(MetricRecord.objects.filter(session=s).exists())

    def test_rehab_session_offers_both_domains(self):
        s = make_session(self.athlete, TODAY, session_type=SessionType.REHAB)
        body = self.client.get(self.url(s)).content.decode()
        self.assertIn("田徑練習訓練紀錄", body)
        self.assertIn("重量訓練紀錄", body)

    def test_delete_metric_from_the_session_page(self):
        s = make_session(self.athlete, TODAY, session_type=SessionType.STRENGTH)
        item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH).first()
        self.client.post(self.url(s), {
            "action": "add_metric", "domain": MetricDomain.STRENGTH,
            "item_id": item.id, "date": TODAY.isoformat(), "value": "80",
        })
        rec = MetricRecord.objects.get(session=s)
        self.client.post(self.url(s), {"action": "delete_metric", "record_id": rec.id})
        self.assertFalse(MetricRecord.objects.filter(id=rec.id).exists())


class ComparisonTests(TestCase):
    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a2")
        self.client.force_login(self.athlete.user)
        self.item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH).first()
        for on_date, value in [(date(2025, 6, 1), 90), (date(2026, 6, 1), 110)]:
            MetricRecord.objects.create(
                athlete=self.athlete, item=self.item, date=on_date,
                value=value, weight_kg=value, reps=3,
            )

    def test_year_comparison_lists_both_years(self):
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}&item={self.item.id}&compare=year"
        )
        body = page.content.decode()
        self.assertIn("2025 年", body)
        self.assertIn("2026 年", body)

    def test_phase_comparison_falls_back_to_the_unphased_bucket(self):
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}&item={self.item.id}&compare=phase"
        )
        self.assertContains(page, "未分期")

    def test_top_movements_card_is_shown(self):
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}&domain={MetricDomain.STRENGTH}"
        )
        self.assertContains(page, "最常做的動作")


class ItemListTests(TestCase):
    """項目清單：只列挑出來／登過的，並依動作分類分組。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a3")
        self.client.force_login(self.athlete.user)
        self.squat = MetricItem.objects.get(
            domain=MetricDomain.STRENGTH, name="背蹲舉 1RM"
        )
        MetricRecord.objects.create(
            athlete=self.athlete, item=self.squat, date=TODAY, value=120, weight_kg=120
        )

    def page(self):
        return self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}"
        ).content.decode()

    def test_only_items_with_records_are_listed(self):
        body = self.page()
        self.assertIn("背蹲舉 1RM", body)
        self.assertNotIn("反向跳 CMJ", body)  # 沒挑也沒登過就不佔版面

    def test_items_are_grouped_by_category(self):
        body = self.page()
        # 分類標題（不是「新增項目」表單裡那個下拉的選項）
        self.assertIn('class="itemcat">下身動作（Lower Body Movement）', body)
        self.assertNotIn('class="itemcat">核心肌群', body)  # 這一組還沒有項目

    def test_picking_from_the_activity_library_adds_an_item(self):
        definition = ActivityDefinition.objects.create(
            name="啞鈴肩推", name_en="Shoulder Press (Dumbbell)",
            category=ActivityCategory.UPPER,
        )
        r = self.client.post(reverse("web:analytics"), {
            "action": "add_item",
            "domain": MetricDomain.STRENGTH,
            "definition": definition.id,
        })
        item = MetricItem.objects.get(domain=MetricDomain.STRENGTH, name="啞鈴肩推")
        self.assertEqual(item.category, MetricCategory.UPPER)
        self.assertIn(f"item={item.id}", r["Location"])
        self.assertIn("啞鈴肩推", self.page())  # 挑出來的就算還沒紀錄也留在清單


class ActivityLibraryTests(TestCase):
    """課表加活動：可挑活動庫、可一次加多個，並自動開好數據項目。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a4")
        self.client.force_login(self.athlete.user)
        self.session = make_session(
            self.athlete, TODAY, session_type=SessionType.STRENGTH
        )
        self.squat = ActivityDefinition.objects.create(
            name="槓鈴深蹲", name_en="Squat (Barbell)",
            category=ActivityCategory.LOWER, default_sets="4 組", default_reps="5 次",
        )
        self.plank = ActivityDefinition.objects.create(
            name="平板支撐", name_en="Plank", category=ActivityCategory.CORE,
        )

    def url(self):
        return reverse("web:session_detail", args=[self.session.id])

    def test_picking_one_activity_brings_its_defaults_and_opens_a_metric_item(self):
        self.client.post(self.url(), {
            "action": "add_activity", "block": "MAIN",
            "definition": self.squat.id, "name": "槓鈴深蹲",
            "sets": "4 組", "reps": "5 次",
        })
        activity = self.session.activities.get()
        self.assertEqual(activity.definition_id, self.squat.id)
        self.assertEqual(activity.sets, "4 組")
        item = MetricItem.objects.get(domain=MetricDomain.STRENGTH, name="槓鈴深蹲")
        self.assertEqual(item.category, MetricCategory.LOWER)

    def test_many_activities_in_one_go(self):
        self.client.post(self.url(), {
            "action": "add_activity", "block": "MAIN",
            "name": "槓鈴深蹲\n平板支撐\n自己想的動作",
        })
        names = list(self.session.activities.order_by("order").values_list("name", flat=True))
        self.assertEqual(names, ["槓鈴深蹲", "平板支撐", "自己想的動作"])
        # 名字對得上活動庫的，預設值一起帶進來
        self.assertEqual(self.session.activities.get(name="槓鈴深蹲").reps, "5 次")
        self.assertEqual(
            set(MetricItem.objects.filter(
                domain=MetricDomain.STRENGTH, name__in=names
            ).values_list("name", flat=True)),
            set(names),
        )

    def test_track_session_activities_open_track_items(self):
        session = make_session(self.athlete, TODAY, session_type=SessionType.TRACK)
        self.client.post(reverse("web:session_detail", args=[session.id]), {
            "action": "add_activity", "block": "MAIN", "name": "150m 計時",
        })
        self.assertTrue(
            MetricItem.objects.filter(
                domain=MetricDomain.TRACK, name="150m 計時"
            ).exists()
        )

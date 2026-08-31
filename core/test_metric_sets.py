"""煙霧測試：多組新增紀錄 + 分析頁渲染。跑在 django test runner 的暫時資料庫上。"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from analytics.models import MetricDomain, MetricItem, MetricRecord, ensure_builtin_items
from core.test_factories import make_athlete


class MultiSetRecordTests(TestCase):
    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a1")
        self.user = self.athlete.user
        self.item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH).first()
        self.client.force_login(self.user)

    def test_add_multiple_sets(self):
        url = reverse("web:analytics")
        r = self.client.post(url, {
            "action": "add_record",
            "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id,
            "date": date.today().isoformat(),
            "value": ["100", "105", "110"],
            "weight": ["100", "105", "110"],
            "reps": ["5", "5", "3"],
            "rest_sec": ["120", "150", "180"],
            "completed": ["1", "1", "0"],
            "context": "深蹲日",
        })
        self.assertEqual(r.status_code, 302)
        recs = list(MetricRecord.objects.filter(athlete=self.athlete).order_by("set_no"))
        self.assertEqual(len(recs), 3)
        self.assertEqual([r.set_no for r in recs], [1, 2, 3])
        self.assertEqual([r.reps for r in recs], [5, 5, 3])
        self.assertEqual([r.rest_sec for r in recs], [120, 150, 180])
        self.assertEqual([r.completed for r in recs], [True, True, False])
        self.assertEqual(recs[2].tonnage, 330.0)

        page = self.client.get(f"{url}?domain={MetricDomain.STRENGTH}&item={self.item.id}")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn("紀錄分析圖", body)
        self.assertIn("setChart", body)
        self.assertIn("未完成", body)
        self.assertIn("66.7%", body)  # 完成率 2/3

    def test_single_set_keeps_no_set_no(self):
        url = reverse("web:analytics")
        self.client.post(url, {
            "action": "add_record", "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id, "date": date.today().isoformat(),
            "value": "80", "weight": "", "reps": "", "rest_sec": "", "completed": "1",
        })
        rec = MetricRecord.objects.get()
        self.assertIsNone(rec.set_no)
        self.assertIsNone(rec.weight_kg)
        self.assertTrue(rec.completed)

    def test_blank_rows_are_skipped(self):
        url = reverse("web:analytics")
        self.client.post(url, {
            "action": "add_record", "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id, "date": date.today().isoformat(),
            "value": ["90", "", ""], "weight": ["90", "", ""],
            "reps": ["6", "", ""], "rest_sec": ["90", "", ""],
            "completed": ["1", "1", "1"],
        })
        self.assertEqual(MetricRecord.objects.count(), 1)

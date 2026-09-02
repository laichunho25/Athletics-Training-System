"""煙霧測試：多組新增紀錄 + 分析頁渲染。跑在 django test runner 的暫時資料庫上。"""
from datetime import date, timedelta

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
            # 休息時間預設以分鐘填（1.5 這種小數也可以），存進去一律是秒
            "rest_sec": ["2", "2.5", "3"],
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
        self.assertIn('<option value="min" selected>分鐘</option>', body)

    def test_single_set_keeps_no_set_no(self):
        url = reverse("web:analytics")
        self.client.post(url, {
            "action": "add_record", "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id, "date": date.today().isoformat(),
            "value": "80", "reps": "", "rest_sec": "", "completed": "1",
        })
        rec = MetricRecord.objects.get()
        self.assertIsNone(rec.set_no)
        self.assertTrue(rec.completed)

    def test_kg_item_takes_weight_from_the_value(self):
        """單位是 kg 的項目，表單只問一次數值，重量自動跟著它走。"""
        url = reverse("web:analytics")
        item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH, unit="kg").first()

        self.client.post(url, {
            "action": "add_record", "domain": MetricDomain.STRENGTH,
            "item_id": item.id, "date": date.today().isoformat(),
            "value": "80", "reps": "5", "rest_sec": "", "completed": "1",
        })

        rec = MetricRecord.objects.get()
        self.assertEqual(float(rec.weight_kg), 80.0)
        self.assertEqual(rec.tonnage, 400.0)

        page = self.client.get(f"{url}?domain={MetricDomain.STRENGTH}&item={item.id}")
        body = page.content.decode()
        self.assertNotIn('name="weight"', body)   # 重複的重量欄已經拿掉

    def test_track_item_asks_for_intensity_instead_of_weight(self):
        """田徑練習跑的是強度要求（90%、全力），不是重量。"""
        item = MetricItem.objects.filter(domain=MetricDomain.TRACK, unit="秒").first()
        url = reverse("web:analytics")

        self.client.post(url, {
            "action": "add_record", "domain": MetricDomain.TRACK,
            "item_id": item.id, "date": date.today().isoformat(),
            "value": "7.2", "intensity": "90%", "reps": "", "rest_sec": "",
            "completed": "1",
        })

        rec = MetricRecord.objects.get()
        self.assertIsNone(rec.weight_kg)
        self.assertEqual(rec.intensity, "90%")

        body = self.client.get(f"{url}?domain={MetricDomain.TRACK}&item={item.id}").content.decode()
        self.assertIn('name="intensity"', body)
        self.assertNotIn('name="weight"', body)     # 重量欄換成了強度要求

    def test_strength_item_keeps_its_weight_field(self):
        """重量訓練不受影響：非 kg 單位的項目照樣有自己的重量欄。"""
        item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH, unit="秒").first()
        url = reverse("web:analytics")

        self.client.post(url, {
            "action": "add_record", "domain": MetricDomain.STRENGTH,
            "item_id": item.id, "date": date.today().isoformat(),
            "value": "60", "weight": "20", "reps": "", "rest_sec": "", "completed": "1",
        })

        self.assertEqual(float(MetricRecord.objects.get().weight_kg), 20.0)
        body = self.client.get(
            f"{url}?domain={MetricDomain.STRENGTH}&item={item.id}"
        ).content.decode()
        self.assertIn('name="weight"', body)
        self.assertNotIn('name="intensity"', body)


class TrackIntensityTests(TestCase):
    """田徑練習：強度要求存得進去，紀錄分析圖與比較都可以照強度分開看。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a_track")
        self.item = MetricItem.objects.get(
            domain=MetricDomain.TRACK, name="150m 計時"
        )
        self.client.force_login(self.athlete.user)
        self.url = reverse("web:analytics")

    def _add(self, on_date, values, intensities):
        self.client.post(self.url, {
            "action": "add_record", "domain": MetricDomain.TRACK,
            "item_id": self.item.id, "date": on_date.isoformat(),
            "value": values, "intensity": intensities,
            "completed": ["1"] * len(values),
        })

    def test_each_set_keeps_its_own_intensity(self):
        self._add(date.today(), ["18.5", "19.2"], ["95%", "90%"])
        records = MetricRecord.objects.order_by("set_no")
        self.assertEqual([r.intensity for r in records], ["95%", "90%"])

    def test_chart_and_comparison_offer_intensity_views(self):
        self._add(date.today() - timedelta(days=2), ["18.5", "19.2"], ["95%", "90%"])
        self._add(date.today(), ["18.3", "19.0"], ["95%", "90%"])

        page = self.client.get(f"{self.url}?domain={MetricDomain.TRACK}&item={self.item.id}")
        body = page.content.decode()
        self.assertIn("不同強度比較", body)      # 紀錄分析圖的看法選單
        self.assertIn("分強度", body)            # 比較分頁
        self.assertIn("compare=intensity", body)

        grouped = self.client.get(
            f"{self.url}?domain={MetricDomain.TRACK}&item={self.item.id}&compare=intensity"
        ).context["comparison"]
        self.assertEqual([g["label"] for g in grouped["groups"]], ["強度 95%", "強度 90%"])
        self.assertEqual([g["count"] for g in grouped["groups"]], [2, 2])
        self.assertEqual(grouped["groups"][0]["best"], 18.3)   # 計時項目取最小值

    def test_strength_page_has_no_intensity_comparison(self):
        page = self.client.get(f"{self.url}?domain={MetricDomain.STRENGTH}")
        self.assertNotIn("分強度", page.content.decode())


class DailyDetailTests(TestCase):
    """紀錄明細以「一天一列」呈現，列上是當日最重／最輕，點開才看每一組。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a2")
        self.item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH, unit="kg").first()
        self.client.force_login(self.athlete.user)
        self.url = reverse("web:analytics")

    def _add(self, on_date, values):
        self.client.post(self.url, {
            "action": "add_record", "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id, "date": on_date.isoformat(),
            "value": values, "reps": ["5"] * len(values),
            "completed": ["1"] * len(values),
        })

    def test_days_carry_high_and_low_of_that_day(self):
        from analytics.services import metric_analysis

        self._add(date(2026, 6, 1), ["100", "110", "95"])
        self._add(date(2026, 6, 8), ["120", "105"])

        days = metric_analysis(self.athlete, self.item)["days"]

        self.assertEqual([d["date"] for d in days], [date(2026, 6, 8), date(2026, 6, 1)])
        self.assertEqual(days[0]["count"], 2)
        self.assertEqual((days[0]["high"], days[0]["low"]), (120.0, 105.0))
        self.assertEqual((days[1]["high"], days[1]["low"]), (110.0, 95.0))
        self.assertTrue(days[0]["unit_is_weight"])
        self.assertEqual([float(r.value) for r in days[1]["records"]], [100.0, 110.0, 95.0])

    def test_detail_page_lists_one_row_per_day(self):
        self._add(date(2026, 6, 1), ["100", "110"])
        self._add(date(2026, 6, 8), ["120"])

        body = self.client.get(
            f"{self.url}?domain={MetricDomain.STRENGTH}&item={self.item.id}"
        ).content.decode()

        self.assertEqual(body.count('<details class="dayrow">'), 2)
        self.assertIn("最重", body)
        self.assertIn("最輕", body)
        self.assertIn("2026-06-08", body)

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

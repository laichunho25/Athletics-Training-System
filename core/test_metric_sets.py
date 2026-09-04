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

        self.assertEqual(body.count('class="dayrow"'), 2)
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


class SetOrderTests(TestCase):
    """組數次序：↑ ↓ 挪一格，或直接把組號改成想要的數字。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a3")
        self.item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH, unit="kg").first()
        self.client.force_login(self.athlete.user)
        self.url = reverse("web:analytics")
        self.day = date(2026, 6, 1)
        self.client.post(self.url, {
            "action": "add_record", "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id, "date": self.day.isoformat(),
            "value": ["100", "105", "110"], "reps": ["5", "5", "5"],
            "completed": ["1", "1", "1"],
        })

    def order(self):
        rows = MetricRecord.objects.filter(athlete=self.athlete).order_by("set_no")
        return [(r.set_no, float(r.value)) for r in rows]

    def record(self, set_no):
        return MetricRecord.objects.get(athlete=self.athlete, set_no=set_no)

    def move(self, record, direction):
        return self.client.post(self.url, {
            "action": "move_record", "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id, direction: record.id,
        })

    def test_moving_a_set_up_swaps_it_with_the_one_before(self):
        self.move(self.record(3), "up")
        self.assertEqual(self.order(), [(1, 100.0), (2, 110.0), (3, 105.0)])

    def test_moving_a_set_down_swaps_it_with_the_one_after(self):
        self.move(self.record(1), "down")
        self.assertEqual(self.order(), [(1, 105.0), (2, 100.0), (3, 110.0)])

    def test_the_first_set_cannot_go_up(self):
        r = self.move(self.record(1), "up")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.order(), [(1, 100.0), (2, 105.0), (3, 110.0)])

    def test_the_last_set_cannot_go_down(self):
        self.move(self.record(3), "down")
        self.assertEqual(self.order(), [(1, 100.0), (2, 105.0), (3, 110.0)])

    def test_another_athletes_record_cannot_be_moved(self):
        stranger = make_athlete("a3x")
        theirs = MetricRecord.objects.create(
            athlete=stranger, item=self.item, date=self.day, value=90, set_no=1
        )
        r = self.move(theirs, "up")
        self.assertEqual(r.status_code, 404)

    def test_editing_the_set_number_reorders_that_day(self):
        third = self.record(3)
        self.client.post(self.url, {
            "action": "edit_record", "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id, f"set_no_{third.id}": "1",
        })
        # 110 排到最前面，其餘往後補成 1、2、3
        self.assertEqual(self.order(), [(1, 110.0), (2, 100.0), (3, 105.0)])

    def test_a_set_number_that_is_not_a_number_is_reported(self):
        first = self.record(1)
        r = self.client.post(self.url, {
            "action": "edit_record", "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id, f"set_no_{first.id}": "0",
        }, follow=True)
        self.assertIn("組號要填 1 以上的整數", r.content.decode())
        self.assertEqual(self.order(), [(1, 100.0), (2, 105.0), (3, 110.0)])

    def test_deleting_a_middle_set_renumbers_the_rest(self):
        self.client.post(self.url, {
            "action": "delete_record", "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id, "record_id": self.record(2).id,
        })
        self.assertEqual(self.order(), [(1, 100.0), (2, 110.0)])

    def test_the_detail_table_offers_the_order_controls_and_the_fill_row(self):
        body = self.client.get(
            f"{self.url}?domain={MetricDomain.STRENGTH}&item={self.item.id}"
        ).content.decode()
        self.assertIn('name="up"', body)
        self.assertIn('name="down"', body)
        self.assertIn('data-fill="value"', body)
        self.assertIn("fillall", body)
        self.assertIn(f'name="set_no_{self.record(1).id}"', body)


class MainChartModeTests(TestCase):
    """主圖可以切整體／年份／年月／時期／狀態，所以每一筆都要帶分組標籤。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a4")
        self.item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH, unit="kg").first()
        self.client.force_login(self.athlete.user)
        self.url = reverse("web:analytics")

    def test_points_carry_year_month_phase_and_status(self):
        from analytics.services import metric_analysis

        MetricRecord.objects.create(
            athlete=self.athlete, item=self.item, date=date.today(),
            value=100, status="INJURY",
        )
        point = metric_analysis(self.athlete, self.item)["points"][0]

        self.assertEqual(point["year"], str(date.today().year))
        self.assertEqual(point["month"], f"{date.today().year}-{date.today().month:02d}")
        self.assertEqual(point["phase"], "未分期")      # 沒排備戰計劃就是未分期
        self.assertEqual(point["status"], "傷害治療期")

    def test_a_record_inside_a_phase_is_labelled_with_that_phase(self):
        from planning.models import Competition, Macrocycle, Phase

        macro = Macrocycle.objects.create(
            athlete=self.athlete,
            target_competition=Competition.objects.create(
                name="2026 全國賽", date=date(2026, 6, 20)
            ),
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )
        Phase.objects.create(
            macrocycle=macro, phase_type="TAPER_COMP", week_start=22, week_end=26,
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
        )
        MetricRecord.objects.create(
            athlete=self.athlete, item=self.item, date=date(2026, 6, 10), value=120
        )
        from analytics.services import metric_analysis

        self.assertEqual(
            metric_analysis(self.athlete, self.item)["points"][0]["phase"], "比賽期"
        )

    def test_the_page_offers_the_four_main_chart_views(self):
        MetricRecord.objects.create(
            athlete=self.athlete, item=self.item, date=date.today(), value=100
        )
        body = self.client.get(
            f"{self.url}?domain={MetricDomain.STRENGTH}&item={self.item.id}"
        ).content.decode()
        self.assertIn('id="mainMode"', body)
        for label in ("整體（每一筆）", "分年份", "分年份和月份", "分時期", "分狀態"):
            self.assertIn(label, body)


class ItemDeleteButtonTests(TestCase):
    """清單上每一列都有 ×，不用先點進去才刪得掉項目。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a5")
        self.item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH, unit="kg").first()
        self.client.force_login(self.athlete.user)
        self.url = reverse("web:analytics")
        MetricRecord.objects.create(
            athlete=self.athlete, item=self.item, date=date.today(), value=100
        )

    def test_every_row_carries_a_delete_button(self):
        body = self.client.get(f"{self.url}?domain={MetricDomain.STRENGTH}").content.decode()
        self.assertIn('id="itemDel"', body)
        self.assertIn(f'class="itemdel" type="submit" form="itemDel" name="item_id" '
                      f'value="{self.item.id}"', body)

    def test_the_button_clears_the_records_of_a_builtin_item(self):
        self.client.post(self.url, {
            "action": "delete_item", "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id, "confirm": "1",
        })
        self.assertEqual(MetricRecord.objects.filter(athlete=self.athlete).count(), 0)
        self.assertTrue(MetricItem.objects.filter(pk=self.item.pk).exists())

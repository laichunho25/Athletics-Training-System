"""田徑練習訓練紀錄清單：一頁 15 筆的分頁，與表頭點一下的排序。"""
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from analytics import track_log as tlog
from analytics.models import MetricDomain, MetricRecord, TrackMethod, track_item_for
from core.test_factories import make_athlete, make_session

TODAY = date(2026, 6, 1)


class TrackLogListTests(TestCase):
    """清單本身：切頁、排序、關鍵字。"""

    @classmethod
    def setUpTestData(cls):
        cls.athlete = make_athlete("logger")
        cls.i150 = track_item_for(TrackMethod.REPEAT, 150)
        cls.i80 = track_item_for(TrackMethod.TEMPO, 80)
        cls.session = make_session(cls.athlete, TODAY, title="週一正課")
        # 20 天、每天一組：奇數天跑 150m、偶數天跑 80m，完成數值一天比一天慢
        for n in range(20):
            MetricRecord.objects.create(
                athlete=cls.athlete,
                item=cls.i150 if n % 2 else cls.i80,
                session=cls.session if n % 2 else None,
                date=TODAY - timedelta(days=n),
                set_no=n + 1,
                distance_m=150 if n % 2 else 80,
                value=10 + n,
                completed=n != 3,
            )

    def rows(self, **kwargs):
        return tlog.search_records(self.athlete, **kwargs)

    def test_one_page_holds_fifteen(self):
        first = self.rows()
        self.assertEqual(tlog.PAGE_SIZE, 15)
        self.assertEqual(first["total"], 20)
        self.assertEqual(first["shown"], 15)
        self.assertEqual((first["page"], first["pages"]), (1, 2))
        self.assertEqual((first["start_index"], first["end_index"]), (1, 15))

        second = self.rows(page=2)
        self.assertEqual(second["shown"], 5)
        self.assertEqual((second["start_index"], second["end_index"]), (16, 20))
        self.assertFalse(second["has_next"])
        # 兩頁加起來剛好是全部，沒有重複也沒有漏掉
        ids = [r.id for r in first["rows"]] + [r.id for r in second["rows"]]
        self.assertEqual(len(set(ids)), 20)

    def test_page_out_of_range_falls_back_to_the_last_page(self):
        self.assertEqual(self.rows(page=99)["page"], 2)
        self.assertEqual(self.rows(page=0)["page"], 1)

    def test_default_sort_is_newest_first(self):
        rows = self.rows()["rows"]
        self.assertEqual(rows[0].date, TODAY)
        self.assertEqual([r.date for r in rows], sorted((r.date for r in rows), reverse=True))

    def test_sorting_by_value_both_ways(self):
        up = [float(r.value) for r in self.rows(sort="value", direction="asc")["rows"]]
        self.assertEqual(up, sorted(up))
        down = [float(r.value) for r in self.rows(sort="value", direction="desc")["rows"]]
        self.assertEqual(down, sorted(down, reverse=True))
        self.assertEqual(down[0], 29)

    def test_sorting_by_distance_uses_the_record_distance(self):
        rows = self.rows(sort="dist", direction="asc")["rows"]
        self.assertEqual(float(rows[0].distance_m), 80)

    def test_blank_program_sinks_to_the_bottom(self):
        """沒掛 program 的那幾筆一律排最後，兩個方向都一樣。"""
        rows = self.rows(sort="program", direction="desc")["rows"]
        self.assertIsNotNone(rows[0].session_id)

    def test_unknown_sort_falls_back_to_date(self):
        self.assertEqual(self.rows(sort="nonsense")["sort"], "date")
        self.assertEqual(self.rows(direction="sideways")["direction"], "desc")

    def test_keyword_finds_one_distance_across_days(self):
        found = self.rows(query="150")
        self.assertEqual(found["total"], 10)
        self.assertTrue(all(float(r.distance_m) == 150 for r in found["rows"]))


class TrackLogPageTests(TestCase):
    """數據分析頁：分頁與排序的參數走得通，紀錄明細也切得開。"""

    @classmethod
    def setUpTestData(cls):
        cls.athlete = make_athlete("pager")
        item = track_item_for(TrackMethod.REPEAT, 150)
        cls.item = item
        for n in range(18):
            MetricRecord.objects.create(
                athlete=cls.athlete,
                item=item,
                date=TODAY - timedelta(days=n),
                set_no=1,
                distance_m=150,
                value=18 + n,
            )

    def setUp(self):
        self.client.force_login(self.athlete.user)

    def get(self, **params):
        params.setdefault("domain", MetricDomain.TRACK.value)
        return self.client.get(reverse("web:analytics"), params)

    def test_list_page_two_shows_the_rest(self):
        page = self.get(tp=2)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["log"]["shown"], 3)
        self.assertEqual(page.context["log"]["page"], 2)

    def test_sort_parameters_reach_the_list(self):
        page = self.get(sort="value", sdir="asc")
        self.assertEqual(page.context["log_sort"], "value")
        self.assertEqual(page.context["log_sdir"], "asc")
        self.assertEqual(float(page.context["log"]["rows"][0].value), 18)

    def test_bad_sort_parameter_is_ignored(self):
        page = self.get(sort="drop table", sdir="up")
        self.assertEqual(page.context["log_sort"], tlog.DEFAULT_SORT)
        self.assertEqual(page.context["log_sdir"], tlog.DEFAULT_DIR)

    def test_record_detail_is_paged_by_fifteen(self):
        page = self.get(item=self.item.id)
        detail = page.context["detail"]
        self.assertEqual(detail["pages"], 2)
        self.assertEqual(detail["count"], 15)
        self.assertEqual(page.context["detail_qs"].count("dp"), 0)

        second = self.get(item=self.item.id, dp=2).context["detail"]
        self.assertEqual(second["count"], 3)
        self.assertFalse(second["has_next"])

"""訓練紀錄清單：一頁 15 筆的分頁、表頭點一下的排序，三個範疇都走同一套。"""
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from analytics import record_log as rlog
from analytics.models import (
    MetricDomain,
    MetricItem,
    MetricRecord,
    TrackMethod,
    track_item_for,
)
from core.test_factories import make_athlete, make_session
from planning.models import Competition

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
        return rlog.search_records(self.athlete, **kwargs)

    def test_one_page_holds_fifteen(self):
        first = self.rows()
        self.assertEqual(rlog.PAGE_SIZE, 15)
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
        self.assertEqual(page.context["log_sort"], rlog.DEFAULT_SORT)
        self.assertEqual(page.context["log_sdir"], rlog.DEFAULT_DIR)

    def test_record_detail_is_paged_by_fifteen(self):
        page = self.get(item=self.item.id)
        detail = page.context["detail"]
        self.assertEqual(detail["pages"], 2)
        self.assertEqual(detail["count"], 15)
        self.assertEqual(page.context["detail_qs"].count("dp"), 0)

        second = self.get(item=self.item.id, dp=2).context["detail"]
        self.assertEqual(second["count"], 3)
        self.assertFalse(second["has_next"])


class StrengthLogTests(TestCase):
    """重量訓練紀錄：同一張清單，字眼與「越大越好」換成舉的那一套。"""

    @classmethod
    def setUpTestData(cls):
        cls.athlete = make_athlete("lifter")
        cls.squat = MetricItem.objects.create(
            domain=MetricDomain.STRENGTH, name="背蹲舉", unit="kg"
        )
        cls.bench = MetricItem.objects.create(
            domain=MetricDomain.STRENGTH, name="臥推", unit="kg"
        )
        cls.track_item = track_item_for(TrackMethod.REPEAT, 150)
        MetricRecord.objects.create(
            athlete=cls.athlete,
            item=cls.track_item,
            date=TODAY,
            distance_m=150,
            value=18,
        )
        for n, (item, weight) in enumerate(
            [(cls.squat, 100), (cls.squat, 110), (cls.bench, 60)]
        ):
            MetricRecord.objects.create(
                athlete=cls.athlete,
                item=item,
                date=TODAY - timedelta(days=n),
                set_no=n + 1,
                value=weight,
                weight_kg=weight,
                reps=5,
            )

    def test_the_list_only_holds_this_domain(self):
        rows = rlog.search_records(self.athlete, domain=MetricDomain.STRENGTH)
        self.assertEqual(rows["total"], 3)
        self.assertNotIn(self.track_item.id, {r.item_id for r in rows["rows"]})

    def test_heavier_is_better_and_volume_is_tonnage(self):
        records = list(
            rlog.search_records(self.athlete, domain=MetricDomain.STRENGTH)["rows"]
        )
        stat = rlog.summarise(records, MetricDomain.STRENGTH)
        self.assertEqual(stat["best"], 110)
        # 噸位＝重量 × 次數：(100 + 110 + 60) × 5
        self.assertEqual(stat["volume"], 1350)
        self.assertEqual(stat["volume_unit"], "kg")

    def test_periods_group_by_movement(self):
        records = list(
            rlog.search_records(self.athlete, domain=MetricDomain.STRENGTH)["rows"]
        )
        report = rlog.period_view(
            self.athlete, records, "month", MetricDomain.STRENGTH
        )
        self.assertEqual({r["label"] for r in report["rows"]}, {"背蹲舉", "臥推"})

    def test_keyword_finds_a_movement(self):
        rows = rlog.search_records(
            self.athlete, query="臥推", domain=MetricDomain.STRENGTH
        )
        self.assertEqual(rows["total"], 1)

    def test_the_page_shows_the_weight_wording(self):
        self.client.force_login(self.athlete.user)
        page = self.client.get(
            reverse("web:analytics"), {"domain": MetricDomain.STRENGTH.value}
        )
        self.assertEqual(page.context["log"]["total"], 3)
        self.assertFalse(page.context["log_lower_better"])
        self.assertContains(page, "重量訓練紀錄")
        self.assertContains(page, "完成重量 (kg)")
        self.assertContains(page, "同動作跨時段")


class CompetitionLogTests(TestCase):
    """比賽數據：清單多了「賽事」一欄，字眼換成比賽那一套。"""

    @classmethod
    def setUpTestData(cls):
        cls.athlete = make_athlete("racer")
        cls.item = MetricItem.objects.create(
            domain=MetricDomain.COMPETITION, name="100m", unit="秒"
        )
        cls.meet = Competition.objects.create(
            athlete=cls.athlete, name="學界田徑錦標賽", date=TODAY
        )
        MetricRecord.objects.create(
            athlete=cls.athlete,
            item=cls.item,
            competition=cls.meet,
            date=TODAY,
            distance_m=100,
            target_value=11,
            value=11.24,
        )
        MetricRecord.objects.create(
            athlete=cls.athlete,
            item=cls.item,
            date=TODAY - timedelta(days=30),
            distance_m=100,
            value=11.5,
        )

    def test_keyword_finds_the_meet(self):
        rows = rlog.search_records(
            self.athlete, query="學界", domain=MetricDomain.COMPETITION
        )
        self.assertEqual(rows["total"], 1)
        self.assertEqual(rows["rows"][0].competition_id, self.meet.id)

    def test_faster_is_better_and_splits_are_by_meet(self):
        records = list(
            rlog.search_records(self.athlete, domain=MetricDomain.COMPETITION)["rows"]
        )
        report = rlog.performance_view(
            self.athlete, records, domain=MetricDomain.COMPETITION
        )
        self.assertEqual(report["summary"]["best"], 11.24)
        self.assertEqual(
            {r["label"] for r in report["by_split"]}, {"學界田徑錦標賽", "未指定賽事"}
        )

    def test_the_page_shows_the_competition_wording(self):
        self.client.force_login(self.athlete.user)
        page = self.client.get(
            reverse("web:analytics"), {"domain": MetricDomain.COMPETITION.value}
        )
        self.assertEqual(page.context["log"]["total"], 2)
        self.assertContains(page, "學界田徑錦標賽")
        self.assertContains(page, "同項目跨時段")
        self.assertContains(page, "目標成績（秒）")

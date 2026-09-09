"""課表明細下面幾張分範疇的表：可以就地改、可以刪，數據分析立刻跟著變。

以前那幾張表只看得到、改不動——要改一組數字得先回上面挑活動、再進紀錄明細。
現在每一格都是輸入格：按該列的 ✓ 存單筆、按下面的按鈕一次過存整張表、× 刪那一組。
順便測「這一課的紀錄歸到哪一個範疇」有沒有一律寫出來。
"""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from analytics.models import (
    MetricDomain,
    MetricRecord,
    TrackMethod,
    ensure_builtin_items,
    track_item_for,
)
from analytics.services import metric_analysis
from core.models import SessionType
from core.test_factories import make_admin, make_athlete, make_session

TODAY = date(2026, 6, 1)


class SessionDomainTableTests(TestCase):
    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("track2")
        self.client.force_login(self.athlete.user)
        self.item = track_item_for(TrackMethod.REPEAT, 150)
        self.session = make_session(self.athlete, TODAY, session_type=SessionType.TRACK)
        self.record = MetricRecord.objects.create(
            athlete=self.athlete,
            item=self.item,
            session=self.session,
            date=TODAY,
            set_no=1,
            value=18,
        )

    def url(self):
        return reverse("web:session_detail", args=[self.session.id])

    def post(self, **extra):
        data = {"rdomain": MetricDomain.TRACK, "anchor": f"dom-{MetricDomain.TRACK}"}
        data.update(extra)
        return self.client.post(self.url(), data)

    def test_the_table_shows_input_boxes_and_a_delete_button(self):
        page = self.client.get(self.url())
        self.assertContains(page, f'name="value_{self.record.id}"')
        self.assertContains(page, f'id="dom-{MetricDomain.TRACK}"')
        self.assertContains(page, "儲存全部更改")

    def test_editing_one_row_writes_back_and_shows_up_in_the_analysis(self):
        response = self.post(
            action="edit_record",
            only=self.record.id,
            **{f"value_{self.record.id}": "17.4"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"#dom-{MetricDomain.TRACK}", response["Location"])
        self.record.refresh_from_db()
        self.assertEqual(float(self.record.value), 17.4)
        analysis = metric_analysis(self.athlete, self.item)
        self.assertEqual(analysis["points"][-1]["value"], 17.4)

    def test_deleting_a_row_takes_it_out_of_the_analysis_too(self):
        response = self.post(
            action="delete_record", record_id=self.record.id
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MetricRecord.objects.filter(pk=self.record.pk).exists())
        self.assertEqual(metric_analysis(self.athlete, self.item)["points"], [])

    def test_a_bad_anchor_falls_back_to_the_record_section(self):
        # anchor 是網址的一部分，使用者改得到——不乾淨的就當沒填
        response = self.post(
            action="delete_record", record_id=self.record.id, anchor="javascript:alert(1)"
        )
        self.assertTrue(response["Location"].endswith("#rec"))

    def test_someone_elses_record_cannot_be_touched(self):
        other = make_athlete("track3")
        theirs = MetricRecord.objects.create(
            athlete=other, item=self.item, date=TODAY, value=20
        )
        response = self.post(action="delete_record", record_id=theirs.id)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(MetricRecord.objects.filter(pk=theirs.pk).exists())

    def test_a_reader_gets_the_table_without_the_buttons(self):
        stranger = make_athlete("track4")
        self.client.force_login(stranger.user)
        page = self.client.get(self.url())
        if page.status_code == 200:
            self.assertNotContains(page, "儲存全部更改")

    def test_an_admin_can_edit_the_table(self):
        self.client.force_login(make_admin("admin_dom"))
        self.post(
            action="edit_record",
            only=self.record.id,
            **{f"value_{self.record.id}": "16.9"},
        )
        self.record.refresh_from_db()
        self.assertEqual(float(self.record.value), 16.9)

    def test_the_page_says_which_domain_this_session_logs_into(self):
        page = self.client.get(self.url())
        self.assertContains(page, "這一課登的數字歸到")
        self.assertContains(page, "田徑練習訓練紀錄")

    def test_a_session_with_two_domains_still_offers_the_picker(self):
        session = make_session(self.athlete, TODAY, session_type=SessionType.REHAB)
        page = self.client.get(reverse("web:session_detail", args=[session.id]))
        self.assertContains(page, "登哪一個範疇")

"""課表頁登的數據＝數據分析那一份，而且課別限制了能登哪個範疇。"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from analytics.models import MetricDomain, MetricItem, MetricRecord, ensure_builtin_items
from core.models import SessionType
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

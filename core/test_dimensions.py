"""多面向分析：動作重量 × 肌肉脂肪比例 × 訓練時間。

單看一條曲線不知道「舉得起來」是練回來的還是輕出來的，所以同一段時間的
體組成與實際訓練時數要擺在一起；分訓練時期或分年份切開才看得出哪一段有效。
順便測數據分析頁的排序（田徑練習→重量訓練→比賽）與
「體組成 × 重量訓練」只出現在重量訓練範疇。
"""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from accounts.models import BodyMetricLog
from analytics.dimensions import multi_dimension_report
from analytics.models import (
    MetricDomain,
    MetricItem,
    MetricRecord,
    ensure_builtin_items,
)
from core.models import PhaseType, SessionStatus, SessionType
from core.test_factories import make_athlete, make_session
from planning.models import Competition, Macrocycle, Phase


class DimensionBase(TestCase):
    """兩段時間：早的一段舉得輕、體脂高；晚的一段舉得重、體脂低。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("dim1")
        self.client.force_login(self.athlete.user)
        self.item = MetricItem.objects.filter(
            domain=MetricDomain.STRENGTH, unit="kg"
        ).first()
        self.old_day = date.today() - timedelta(days=400)
        self.new_day = date.today() - timedelta(days=30)
        self.add_block(self.old_day, weight=80, fat=14, weight_kg=70, minutes=90)
        self.add_block(self.new_day, weight=100, fat=11, weight_kg=70, minutes=60)

    def add_block(self, day, weight, fat, weight_kg, minutes, reps=3):
        session = make_session(self.athlete, day, session_type=SessionType.STRENGTH)
        session.status = SessionStatus.COMPLETED
        session.actual_duration_min = minutes
        session.session_rpe = 7
        session.save()
        MetricRecord.objects.create(
            athlete=self.athlete,
            item=self.item,
            session=session,
            date=day,
            value=weight,
            weight_kg=weight,
            reps=reps,
            completed=True,
        )
        BodyMetricLog.objects.create(
            athlete=self.athlete, date=day, weight_kg=weight_kg, body_fat_pct=fat
        )
        return session

    def add_phases(self):
        cycle = Macrocycle.objects.create(
            athlete=self.athlete,
            target_competition=Competition.objects.create(
                name="測試賽", date=self.new_day + timedelta(days=20)
            ),
            start_date=self.old_day - timedelta(days=10),
            end_date=self.new_day + timedelta(days=10),
        )
        Phase.objects.create(
            macrocycle=cycle,
            phase_type=PhaseType.GENERAL_PREP,
            week_start=1,
            week_end=8,
            start_date=self.old_day - timedelta(days=10),
            end_date=self.old_day + timedelta(days=10),
        )
        Phase.objects.create(
            macrocycle=cycle,
            phase_type=PhaseType.PRE_COMP,
            week_start=9,
            week_end=16,
            start_date=self.new_day - timedelta(days=10),
            end_date=self.new_day + timedelta(days=10),
        )


class ReportTests(DimensionBase):
    def test_year_mode_puts_each_year_on_its_own_row(self):
        report = multi_dimension_report(self.athlete, "year")
        labels = [g["label"] for g in report["groups"]]
        self.assertEqual(len(labels), 2)
        self.assertIn(str(self.old_day.year), labels[0])
        self.assertIn(str(self.new_day.year), labels[1])

    def test_each_row_carries_all_three_dimensions(self):
        older, newer = multi_dimension_report(self.athlete, "year")["groups"]
        # 訓練時間
        self.assertEqual(older["hours"], 1.5)
        self.assertEqual(newer["hours"], 1.0)
        self.assertEqual(older["sessions"], 1)
        # 體組成
        self.assertEqual(older["fat_pct"], 14.0)
        self.assertEqual(newer["fat_pct"], 11.0)
        self.assertEqual(newer["muscle_pct"], 89.0)
        # 力量：80kg × 3 下 → e1RM 85.3，除以 70kg 體重
        self.assertEqual(older["best_lift"]["best_e1rm"], 85.3)
        self.assertEqual(older["avg_per_bw"], 1.22)
        self.assertGreater(newer["avg_per_bw"], older["avg_per_bw"])
        self.assertEqual(newer["tonnage"], 300.0)

    def test_each_movement_gets_a_row_with_the_head_to_tail_change(self):
        row = multi_dimension_report(self.athlete, "year")["lifts"][0]
        self.assertEqual(row["item"], self.item)
        self.assertEqual(len(row["cells"]), 2)
        self.assertEqual(row["change_pct"], 25.1)

    def test_it_says_in_words_what_changed(self):
        lines = multi_dimension_report(self.athlete, "year")["insights"]
        self.assertTrue(any("每公斤體重" in line for line in lines))
        self.assertTrue(any("訓練時數" in line for line in lines))
        self.assertTrue(any("體脂率" in line for line in lines))

    def test_phase_mode_groups_by_training_phase(self):
        self.add_phases()
        report = multi_dimension_report(self.athlete, "phase")
        self.assertEqual(
            [g["label"] for g in report["groups"]], ["一般準備期", "賽前期"]
        )

    def test_without_phases_it_says_so_instead_of_showing_nothing(self):
        report = multi_dimension_report(self.athlete, "phase")
        self.assertEqual(report["groups"], [])
        self.assertTrue(report["notes"])

    def test_an_unknown_mode_falls_back_to_phase(self):
        self.assertEqual(multi_dimension_report(self.athlete, "月")["mode"], "phase")

    def test_an_athlete_with_nothing_logged_gets_an_empty_report(self):
        report = multi_dimension_report(make_athlete("dim2"), "year")
        self.assertFalse(report["has_data"])
        self.assertEqual(report["insights"], [])


class AnalyticsPageTests(DimensionBase):
    def url(self, **params):
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{reverse('web:analytics')}?athlete={self.athlete.id}&{query}"

    def test_the_default_domain_is_the_track_one(self):
        page = self.client.get(reverse("web:analytics"))
        self.assertEqual(page.context["domain"], MetricDomain.TRACK)

    def test_the_domains_are_ordered_track_strength_competition(self):
        self.assertEqual(
            [v for v, _label in MetricDomain.choices],
            ["TRACK", "STRENGTH", "COMPETITION"],
        )

    def test_body_composition_only_shows_in_the_strength_domain(self):
        page = self.client.get(self.url(domain=MetricDomain.STRENGTH))
        self.assertTrue(page.context["is_strength"])
        self.assertContains(page, "體組成 × 重量訓練")

        page = self.client.get(self.url(domain=MetricDomain.TRACK))
        self.assertFalse(page.context["is_strength"])
        self.assertNotContains(page, "體組成 × 重量訓練")
        self.assertIsNone(page.context["dims"])

    def test_the_multi_dimension_panel_shows_up_with_the_strength_records(self):
        page = self.client.get(self.url(domain=MetricDomain.STRENGTH, dmode="year"))
        self.assertContains(page, "多面向分析")
        self.assertEqual(page.context["dims"]["mode"], "year")
        self.assertTrue(page.context["dims"]["has_data"])
        self.assertIn("每小時噸位", page.content.decode())

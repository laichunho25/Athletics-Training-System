"""體組成 × 重量訓練：相對力量比值、情境推演、方向建議與兩個頁面的呈現。"""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from accounts.models import BodyMetricLog
from analytics import body_strength as bs
from analytics.models import MetricDomain, MetricItem, MetricRecord
from core.test_factories import make_athlete, make_coach
from nutrition import services as nu

TODAY = date.today()


def add_body(athlete, on_date, weight, fat_pct):
    return BodyMetricLog.objects.create(
        athlete=athlete, date=on_date, weight_kg=weight, body_fat_pct=fat_pct
    )


def squat_item():
    return MetricItem.objects.create(
        domain=MetricDomain.STRENGTH, name="背蹲舉", unit="kg", higher_is_better=True
    )


def add_lift(athlete, item, on_date, weight, reps=1):
    return MetricRecord.objects.create(
        athlete=athlete,
        item=item,
        date=on_date,
        value=weight,
        weight_kg=weight,
        reps=reps,
        completed=True,
    )


class RatioMathTests(TestCase):
    def test_epley_estimate(self):
        self.assertEqual(bs.estimate_1rm(100, 5), 113.3)
        self.assertEqual(bs.estimate_1rm(100, None), 100.0)
        # 次數太多換算誤差過大，一律按上限 12 次算
        self.assertEqual(bs.estimate_1rm(60, 30), bs.estimate_1rm(60, 12))

    def test_ratios_use_weight_and_lean_mass(self):
        athlete = make_athlete("ratio1")
        add_body(athlete, TODAY, 70, 10)      # 去脂體重 63.0
        item = squat_item()
        add_lift(athlete, item, TODAY, 140, 1)

        report = bs.strength_ratio_report(athlete)

        self.assertTrue(report["has_body"] and report["has_strength"])
        self.assertEqual(report["body"]["lean"], 63.0)
        self.assertEqual(report["body"]["muscle_pct"], 90.0)
        focus = report["focus"]
        self.assertEqual(focus["e1rm"], 140.0)
        self.assertEqual(focus["per_bw"], 2.0)          # 140 / 70
        self.assertEqual(focus["per_lean"], 2.22)       # 140 / 63

    def test_non_kg_items_are_skipped(self):
        athlete = make_athlete("ratio2")
        add_body(athlete, TODAY, 70, 10)
        plank = MetricItem.objects.create(
            domain=MetricDomain.STRENGTH, name="平板支撐", unit="秒", higher_is_better=True
        )
        add_lift(athlete, plank, TODAY, 90, 1)

        report = bs.strength_ratio_report(athlete)

        self.assertFalse(report["has_strength"])
        self.assertEqual(report["lifts"], [])


class ScenarioTests(TestCase):
    def setUp(self):
        self.athlete = make_athlete("scene1")
        add_body(self.athlete, TODAY, 80, 20)   # 去脂 64.0 / 脂肪 16.0
        self.item = squat_item()
        add_lift(self.athlete, self.item, TODAY, 160, 1)
        self.report = bs.strength_ratio_report(self.athlete)

    def test_cut_keeps_absolute_strength_and_lifts_the_ratio(self):
        cut = [s for s in self.report["scenarios"] if s["kind"] == "CUT"][0]

        self.assertEqual(cut["lean_delta"], 0.0)
        self.assertEqual(cut["e1rm"], 160.0)            # 肌肉守住＝絕對力量不變
        self.assertLess(cut["weight"], 80)
        self.assertGreater(cut["per_bw"], self.report["focus"]["per_bw"])
        self.assertGreater(cut["gain_pct"], 0)

    def test_lean_gain_raises_absolute_strength_allometrically(self):
        gain = [s for s in self.report["scenarios"] if s["kind"] == "GAIN"][0]

        expected = round(160 * (65 / 64) ** bs.LEAN_EXPONENT, 1)
        self.assertEqual(gain["lean"], 65.0)
        self.assertEqual(gain["e1rm"], expected)
        self.assertEqual(gain["weight"], 81.0)          # 脂肪不動，體重跟著加

    def test_first_scenario_is_the_current_state(self):
        now = self.report["scenarios"][0]
        self.assertEqual(now["kind"], "NOW")
        self.assertEqual(now["weight"], 80.0)
        self.assertEqual(now["gain_pct"], 0.0)


class DirectionTests(TestCase):
    def _report(self, username, weight, fat_pct):
        athlete = make_athlete(username)
        add_body(athlete, TODAY, weight, fat_pct)
        add_lift(athlete, squat_item(), TODAY, 140, 1)
        return athlete, bs.strength_ratio_report(athlete)

    def test_high_fat_recommends_a_cut_with_a_daily_deficit(self):
        _athlete, report = self._report("dir_cut", 80, 18)  # 男生參考帶 6–12%
        rec = report["recommendation"]

        self.assertEqual(rec["direction"], "CUT")
        self.assertEqual(rec["goal"], "LOSE")
        self.assertEqual(rec["target_fat_pct"], 12.0)
        self.assertLess(rec["target_weight"], 80)
        self.assertLess(rec["kcal_delta"], 0)
        self.assertGreaterEqual(rec["weeks"], 1)
        # 減脂期蛋白按去脂體重拉高，才守得住肌肉
        self.assertEqual(rec["protein_per_kg_lean"], 2.4)
        self.assertGreater(rec["payoff"]["gain_pct"], 0)

    def test_low_fat_recommends_eating_more(self):
        _athlete, report = self._report("dir_fuel", 65, 4)
        rec = report["recommendation"]

        self.assertEqual(rec["direction"], "FUEL")
        self.assertEqual(rec["goal"], "GAIN")
        self.assertGreater(rec["kcal_delta"], 0)
        self.assertGreater(rec["target_weight"], 65)

    def test_in_band_recommends_building_lean_mass(self):
        _athlete, report = self._report("dir_gain", 70, 8)
        rec = report["recommendation"]

        self.assertEqual(rec["direction"], "GAIN")
        self.assertEqual(rec["lean_delta"], bs.LEAN_GAIN_TARGET_KG)
        self.assertEqual(rec["kcal_delta"], bs.LEAN_GAIN_KCAL)
        # 脂肪量不動、體重多了去脂的部分，體脂率會低一點
        self.assertLess(rec["target_fat_pct"], 8)

    def test_no_body_metric_means_no_recommendation(self):
        athlete = make_athlete("dir_none")
        add_lift(athlete, squat_item(), TODAY, 140, 1)

        report = bs.strength_ratio_report(athlete)

        self.assertFalse(report["has_body"])
        self.assertIsNone(report["recommendation"])
        self.assertTrue(report["notes"])


class TrendReadingTests(TestCase):
    def test_weight_up_but_ratio_flat_is_called_out(self):
        athlete = make_athlete("trend1")
        item = squat_item()
        old = TODAY - timedelta(days=120)
        add_body(athlete, old, 70, 12)
        add_lift(athlete, item, old, 140, 1)          # 2.00 × BW
        add_body(athlete, TODAY, 76, 17)
        add_lift(athlete, item, TODAY, 151, 1)        # 1.99 × BW

        report = bs.strength_ratio_report(athlete)

        self.assertEqual(len(report["series"]), 2)
        self.assertTrue(any("體重" in str(n) for n in report["notes"]))


class NutritionPlanTests(TestCase):
    def test_plan_turns_the_direction_into_daily_numbers(self):
        athlete = make_athlete("plan1")
        add_body(athlete, TODAY, 80, 18)
        add_lift(athlete, squat_item(), TODAY, 140, 1)
        target = nu.calculate_targets(athlete, TODAY)

        plan = nu.body_goal_plan(athlete, target=target)

        self.assertTrue(plan["has_plan"])
        self.assertEqual(plan["goal_choice"], "LOSE")
        self.assertEqual(plan["kcal_goal"], target.target_kcal + plan["kcal_delta"])
        self.assertLess(plan["kcal_goal"], target.target_kcal)
        # 碳水是訓練的燃料，方向再怎麼走都不動它
        self.assertEqual(plan["carb_g"], target.carb_g)
        self.assertTrue(plan["actions"])
        self.assertTrue(plan["why"])

    def test_plan_without_data_says_so_instead_of_failing(self):
        athlete = make_athlete("plan2")
        plan = nu.body_goal_plan(athlete)
        self.assertFalse(plan["has_plan"])


class PageTests(TestCase):
    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete("page1", coach=self.coach)
        add_body(self.athlete, TODAY, 80, 18)
        add_lift(self.athlete, squat_item(), TODAY, 140, 3)
        self.client.force_login(self.coach.user)

    def test_analytics_page_shows_the_ratio_and_the_what_if(self):
        res = self.client.get(
            reverse("web:analytics"), {"athlete": self.athlete.id, "domain": "STRENGTH"}
        )

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "體組成 × 重量訓練")
        self.assertContains(res, "如果體脂／肌肉改變")
        report = res.context["body_strength"]
        self.assertTrue(report["scenarios"])
        self.assertEqual(report["recommendation"]["direction"], "CUT")

    def test_nutrition_page_shows_the_matching_direction(self):
        res = self.client.get(reverse("web:nutrition"), {"athlete": self.athlete.id})

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "體重與體脂方向")
        plan = res.context["body_goal"]
        self.assertTrue(plan["has_plan"])
        self.assertEqual(plan["goal_choice"], "LOSE")

    def test_pages_survive_an_athlete_with_no_data(self):
        empty = make_athlete("page2", coach=self.coach)
        for url in (reverse("web:analytics"), reverse("web:nutrition")):
            with self.subTest(url=url):
                self.assertEqual(
                    self.client.get(url, {"athlete": empty.id}).status_code, 200
                )

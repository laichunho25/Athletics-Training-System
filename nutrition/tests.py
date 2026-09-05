"""nutrition/services.py 的計算測試（BMR / TDEE / 三大營養素）。"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse

from accounts.models import BodyMetricLog
from core.models import Sex
from core.test_factories import TODAY, make_athlete
from nutrition import services as nu
from nutrition import vision
from nutrition.models import AnalysisSource, MealLog, MealType, NutritionGoal


class MifflinStJeorTests(TestCase):
    """Mifflin-St Jeor：男 10w + 6.25h − 5a + 5；女同式 − 161。"""

    def test_male_formula(self):
        expected = round(10 * 70 + 6.25 * 178 - 5 * 20 + 5)
        self.assertEqual(nu.mifflin_st_jeor(70, 178, 20, Sex.MALE), expected)

    def test_female_formula(self):
        expected = round(10 * 55 + 6.25 * 165 - 5 * 20 - 161)
        self.assertEqual(nu.mifflin_st_jeor(55, 165, 20, Sex.FEMALE), expected)

    def test_female_bmr_is_lower_than_male_at_same_size(self):
        self.assertLess(
            nu.mifflin_st_jeor(65, 170, 20, Sex.FEMALE),
            nu.mifflin_st_jeor(65, 170, 20, Sex.MALE),
        )


class CalculateTargetsTests(TestCase):
    def setUp(self):
        self.athlete = make_athlete(weight_kg=68, height_cm=175)

    def test_macro_kcal_split_matches_target_kcal(self):
        """碳水 4 + 蛋白 4 + 脂肪 9 kcal/g 應該加總回目標熱量（容許四捨五入誤差）。"""
        t = nu.calculate_targets(self.athlete, TODAY, save=False)
        total = t["carb_g"] * 4 + t["protein_g"] * 4 + t["fat_g"] * 9
        self.assertAlmostEqual(total, t["target_kcal"], delta=t["target_kcal"] * 0.03)

    def test_tdee_is_above_bmr(self):
        t = nu.calculate_targets(self.athlete, TODAY, save=False)
        self.assertGreater(t["tdee_kcal"], t["bmr_kcal"])

    def test_fat_never_below_floor(self):
        """脂肪不得低於 0.8 g/kg，否則影響荷爾蒙。"""
        t = nu.calculate_targets(
            self.athlete, TODAY, goal=NutritionGoal.LOSE, save=False
        )
        self.assertGreaterEqual(
            t["fat_g"], round(nu.MIN_FAT_G_PER_KG * float(self.athlete.weight_kg)) - 1
        )

    def test_lose_is_below_maintain_and_gain_is_above(self):
        cut = nu.calculate_targets(
            self.athlete, TODAY, goal=NutritionGoal.LOSE, save=False
        )["target_kcal"]
        keep = nu.calculate_targets(
            self.athlete, TODAY, goal=NutritionGoal.MAINTAIN, save=False
        )["target_kcal"]
        gain = nu.calculate_targets(
            self.athlete, TODAY, goal=NutritionGoal.GAIN, save=False
        )["target_kcal"]
        self.assertLess(cut, keep)
        self.assertGreater(gain, keep)

    def test_save_false_writes_nothing(self):
        from nutrition.models import NutritionTarget

        nu.calculate_targets(self.athlete, TODAY, save=False)
        self.assertFalse(NutritionTarget.objects.filter(athlete=self.athlete).exists())

    def test_save_true_is_idempotent(self):
        from nutrition.models import NutritionTarget

        nu.calculate_targets(self.athlete, TODAY, save=True)
        nu.calculate_targets(self.athlete, TODAY, save=True)
        self.assertEqual(
            NutritionTarget.objects.filter(athlete=self.athlete, date=TODAY).count(), 1
        )


class ReadinessTests(TestCase):
    """準備度：睡眠 30 + 痠痛 25 + 壓力 15 + 疼痛 20 + 神經肌肉 10 = 100。"""

    def setUp(self):
        self.athlete = make_athlete()

    def test_score_is_bounded_0_to_100(self):
        from analytics import services as an
        from nutrition.models import RecoveryLog

        for sleep, sore, stress in [(9.0, 1, 1), (4.0, 9, 5), (7.5, 4, 3)]:
            with self.subTest(sleep=sleep):
                RecoveryLog.objects.update_or_create(
                    athlete=self.athlete,
                    date=TODAY,
                    defaults={
                        "sleep_hours": sleep,
                        "sleep_quality": 3,
                        "soreness_level": sore,
                        "stress_level": stress,
                    },
                )
                score = an.readiness_score(self.athlete, TODAY)["score"]
                self.assertGreaterEqual(score, 0)
                self.assertLessEqual(score, 100)

    def test_good_recovery_scores_higher_than_bad(self):
        from analytics import services as an
        from nutrition.models import RecoveryLog

        RecoveryLog.objects.update_or_create(
            athlete=self.athlete,
            date=TODAY,
            defaults={
                "sleep_hours": 9.0,
                "sleep_quality": 5,
                "soreness_level": 1,
                "stress_level": 1,
            },
        )
        good = an.readiness_score(self.athlete, TODAY)["score"]

        RecoveryLog.objects.update_or_create(
            athlete=self.athlete,
            date=TODAY,
            defaults={
                "sleep_hours": 4.0,
                "sleep_quality": 1,
                "soreness_level": 9,
                "stress_level": 5,
            },
        )
        bad = an.readiness_score(self.athlete, TODAY)["score"]
        self.assertGreater(good, bad)


class KatchMcArdleTests(TestCase):
    def test_formula(self):
        self.assertEqual(nu.katch_mcardle(60), round(370 + 21.6 * 60))

    def test_more_lean_mass_means_higher_bmr(self):
        self.assertGreater(nu.katch_mcardle(62), nu.katch_mcardle(58))


class BodyCompositionInsightTests(TestCase):
    """InBody × 營養：沒資料要說沒資料，有資料要算得出 Katch-McArdle 與 g/kg LBM。"""

    def setUp(self):
        self.athlete = make_athlete(weight_kg=68, height_cm=175)

    def log(self, day, weight=68, fat_pct=10, **kwargs):
        return BodyMetricLog.objects.create(
            athlete=self.athlete, date=day, weight_kg=weight,
            body_fat_pct=fat_pct, **kwargs
        )

    def test_no_measurement_means_no_data(self):
        self.assertFalse(nu.body_composition_insight(self.athlete)["has_data"])

    def test_katch_uses_lean_mass_from_the_latest_log(self):
        log = self.log(TODAY)
        insight = nu.body_composition_insight(self.athlete)
        self.assertTrue(insight["has_data"])
        self.assertEqual(insight["katch_bmr"], nu.katch_mcardle(log.lean_mass_kg))

    def test_delta_compares_against_the_previous_measurement(self):
        self.log(TODAY - timedelta(days=30), weight=70)
        self.log(TODAY, weight=68)
        rows = {r["label"]: r for r in nu.body_composition_insight(self.athlete)["rows"]}
        self.assertEqual(rows["體重"]["delta"]["value"], -2.0)

    def test_body_fat_above_the_band_is_flagged(self):
        self.log(TODAY, fat_pct=20)
        notes = nu.body_composition_insight(self.athlete)["notes"]
        self.assertTrue(any("競賽參考帶" in n for n in notes))

    def test_body_fat_below_the_band_warns_about_low_energy_availability(self):
        self.log(TODAY, fat_pct=4)
        notes = nu.body_composition_insight(self.athlete)["notes"]
        self.assertTrue(any("RED-S" in n for n in notes))

    def test_leg_asymmetry_over_five_percent_is_flagged(self):
        self.log(TODAY, muscle_leg_r=10, muscle_leg_l=9)
        notes = nu.body_composition_insight(self.athlete)["notes"]
        self.assertTrue(any("左右差" in n for n in notes))

    def test_protein_is_expressed_per_kg_of_lean_mass(self):
        log = self.log(TODAY)
        target = nu.calculate_targets(self.athlete, TODAY)
        insight = nu.body_composition_insight(self.athlete, target=target)
        self.assertEqual(
            insight["protein"]["per_kg_lean"],
            round(target.protein_g / log.lean_mass_kg, 2),
        )


class SupplementPlanTests(TestCase):
    """補充餐單：差多少就補多少，補完的量不該離缺口太遠。"""

    def setUp(self):
        self.athlete = make_athlete(weight_kg=68, height_cm=175)

    def test_eating_nothing_leaves_the_whole_target_as_a_gap(self):
        plan = nu.supplement_plan(self.athlete, TODAY)
        self.assertEqual(plan["gaps"]["kcal"], plan["target"].target_kcal)
        self.assertTrue(plan["picks"])
        self.assertFalse(plan["on_track"])

    def test_picks_do_not_wildly_overshoot_the_gap(self):
        plan = nu.supplement_plan(self.athlete, TODAY)
        self.assertLessEqual(plan["picked_kcal"], plan["gaps"]["kcal"] * 1.5)

    def test_hitting_the_target_needs_no_supplements(self):
        target = nu.calculate_targets(self.athlete, TODAY)
        MealLog.objects.create(
            athlete=self.athlete, date=TODAY, meal_type=MealType.LUNCH,
            description="全日", kcal=target.target_kcal, carb_g=target.carb_g,
            protein_g=target.protein_g, fat_g=target.fat_g,
        )
        plan = nu.supplement_plan(self.athlete, TODAY)
        self.assertTrue(plan["on_track"])
        self.assertEqual(plan["picks"], [])

    def test_rest_day_timing_advice_differs_from_training_day(self):
        plan = nu.supplement_plan(self.athlete, TODAY)
        self.assertTrue(any("沒有排訓練" in line for line in plan["timing"]))


class MealVisionFallbackTests(TestCase):
    """沒有 API 金鑰時，一律退回食物字典比對，不能整個壞掉。"""

    fixtures = ["food_items"]

    def test_named_food_with_grams_is_matched(self):
        result = vision.analyze_meal(description="白飯 200g")
        self.assertEqual(result["source"], AnalysisSource.DICTIONARY)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["grams"], 200)

    def test_food_without_grams_uses_the_typical_serving(self):
        result = vision.analyze_meal(description="雞胸肉")
        self.assertEqual(result["items"][0]["grams"], 150)

    def test_alias_in_english_is_matched(self):
        result = vision.analyze_meal(description="banana")
        self.assertEqual(result["items"][0]["name"], "香蕉")

    def test_unknown_food_yields_no_items_but_still_returns(self):
        result = vision.analyze_meal(description="外星料理")
        self.assertEqual(result["items"], [])
        self.assertEqual(vision.totals(result["items"])["kcal"], 0)

    def test_photo_without_api_key_falls_back_with_a_message(self):
        result = vision.analyze_meal(
            image_bytes=b"not-a-real-photo", filename="a.jpg", description="白飯 200g"
        )
        self.assertEqual(result["source"], AnalysisSource.DICTIONARY)
        self.assertTrue(result["error"])
        self.assertTrue(result["items"])

    def test_totals_sum_every_macro(self):
        result = vision.analyze_meal(description="白飯 200g、雞胸肉 150g")
        total = vision.totals(result["items"])
        self.assertEqual(
            total["kcal"], sum(round(i["kcal"]) for i in result["items"])
        )
        self.assertGreater(total["protein_g"], 40)


class NutritionPageTests(TestCase):
    """營養頁的新動作：加一餐、改份量、刪除。"""

    fixtures = ["food_items"]

    def setUp(self):
        self.athlete = make_athlete("nutpage", weight_kg=68, height_cm=175)
        self.client.login(username="nutpage", password="test-pw-12345")
        self.url = reverse("web:nutrition")

    def test_page_renders_plan_and_inbody_panels(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertIn("plan", r.context)
        self.assertFalse(r.context["insight"]["has_data"])

    def test_meal_add_from_text_stores_items_and_totals(self):
        self.client.post(self.url, {
            "action": "meal_add", "meal_type": MealType.LUNCH,
            "description": "白飯 200g、雞胸肉 150g",
        })
        meal = MealLog.objects.get(athlete=self.athlete)
        self.assertEqual(len(meal.items), 2)
        self.assertEqual(meal.analysis_source, AnalysisSource.DICTIONARY)
        self.assertEqual(meal.kcal, vision.totals(meal.items)["kcal"])

    def test_meal_add_without_anything_is_rejected(self):
        self.client.post(self.url, {"action": "meal_add", "description": ""})
        self.assertFalse(MealLog.objects.exists())

    def test_regrams_rescales_the_whole_meal(self):
        self.client.post(self.url, {
            "action": "meal_add", "meal_type": MealType.LUNCH, "description": "白飯 200g",
        })
        meal = MealLog.objects.get(athlete=self.athlete)
        before = meal.kcal
        self.client.post(self.url, {
            "action": "meal_regrams", "meal_id": meal.id, "grams_0": 100,
        })
        meal.refresh_from_db()
        self.assertEqual(meal.items[0]["grams"], 100)
        self.assertAlmostEqual(meal.kcal, before / 2, delta=2)

    def test_meal_delete_removes_the_row(self):
        self.client.post(self.url, {
            "action": "meal_add", "meal_type": MealType.SNACK, "description": "香蕉",
        })
        meal = MealLog.objects.get(athlete=self.athlete)
        self.client.post(self.url, {"action": "meal_delete", "meal_id": meal.id})
        self.assertFalse(MealLog.objects.exists())

    def test_meals_feed_the_supplement_plan_gaps(self):
        r = self.client.get(self.url)
        empty_gap = r.context["plan"]["gaps"]["kcal"]
        self.client.post(self.url, {
            "action": "meal_add", "meal_type": MealType.LUNCH,
            "description": "白飯 200g、雞胸肉 150g",
        })
        r = self.client.get(self.url)
        self.assertLess(r.context["plan"]["gaps"]["kcal"], empty_gap)

"""nutrition/services.py 的計算測試（BMR / TDEE / 三大營養素）。"""

from django.test import TestCase

from core.models import Sex
from core.test_factories import TODAY, make_athlete
from nutrition import services as nu
from nutrition.models import NutritionGoal


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

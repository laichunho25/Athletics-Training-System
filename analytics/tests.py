"""analytics/services.py 的計算邏輯測試。"""

from datetime import date, timedelta

from django.test import TestCase

from analytics import services as an
from analytics.models import RiskFlag
from core.models import SessionStatus
from core.test_factories import TODAY, fill_days, make_athlete, make_session


class SessionLoadTests(TestCase):
    """Foster sRPE：負荷 = RPE × 實際時長。"""

    def setUp(self):
        self.athlete = make_athlete()

    def test_load_is_rpe_times_duration(self):
        s = make_session(self.athlete, TODAY, rpe=7, minutes=90)
        self.assertEqual(s.session_load, 630)

    def test_load_is_zero_without_rpe(self):
        s = make_session(self.athlete, TODAY, rpe=None, minutes=60)
        self.assertEqual(s.session_load, 0)

    def test_load_is_zero_without_actual_duration(self):
        s = make_session(self.athlete, TODAY, rpe=8, minutes=None)
        self.assertEqual(s.session_load, 0)


class AcuteChronicLoadTests(TestCase):
    def setUp(self):
        self.athlete = make_athlete()

    def test_acute_load_sums_last_seven_days(self):
        fill_days(self.athlete, TODAY, days=7, rpe=5, minutes=60)  # 每天 300 AU
        self.assertEqual(an.acute_load(self.athlete, TODAY), 7 * 300)

    def test_acute_load_excludes_day_eight(self):
        fill_days(self.athlete, TODAY, days=7, rpe=5, minutes=60)
        make_session(self.athlete, TODAY - timedelta(days=8), rpe=10, minutes=120)
        self.assertEqual(an.acute_load(self.athlete, TODAY), 7 * 300)

    def test_chronic_load_is_28_day_total_divided_by_four(self):
        fill_days(self.athlete, TODAY, days=28, rpe=5, minutes=60)
        # 28 天 × 300 = 8400，÷ 4 = 2100（一週平均）
        self.assertEqual(an.chronic_load(self.athlete, TODAY), 2100)


class AcwrTests(TestCase):
    def setUp(self):
        self.athlete = make_athlete()

    def test_returns_none_before_28_days_of_history(self):
        fill_days(self.athlete, TODAY, days=20)
        self.assertFalse(an.has_enough_history(self.athlete, TODAY))
        self.assertIsNone(an.calculate_acwr(self.athlete, TODAY))

    def test_steady_load_gives_acwr_of_one(self):
        fill_days(self.athlete, TODAY, days=28, rpe=5, minutes=60)
        self.assertTrue(an.has_enough_history(self.athlete, TODAY))
        self.assertAlmostEqual(an.calculate_acwr(self.athlete, TODAY), 1.0, places=2)

    def test_spike_in_last_week_raises_acwr(self):
        # 前 21 天輕量，最近 7 天加倍 → ACWR 應明顯 > 1
        for i in range(7, 28):
            make_session(self.athlete, TODAY - timedelta(days=i), rpe=5, minutes=60)
        for i in range(7):
            make_session(self.athlete, TODAY - timedelta(days=i), rpe=10, minutes=60)
        acwr = an.calculate_acwr(self.athlete, TODAY)
        self.assertGreater(acwr, 1.30)
        self.assertIn(
            an.classify_acwr(acwr), {RiskFlag.ELEVATED, RiskFlag.HIGH}
        )

    def test_chronic_zero_returns_none_not_division_error(self):
        """慢性負荷為 0 時不可拋 ZeroDivisionError。"""
        for i in range(28):
            make_session(
                self.athlete,
                TODAY - timedelta(days=i),
                rpe=0,
                minutes=0,
                status=SessionStatus.SKIPPED,
            )
        self.assertIsNone(an.calculate_acwr(self.athlete, TODAY))


class ClassifyAcwrTests(TestCase):
    """燈號的邊界值——甜蜜點是 0.80–1.30（含端點）。"""

    def test_boundaries(self):
        cases = [
            (None, RiskFlag.INSUFFICIENT),
            (0.79, RiskFlag.UNDER),
            (0.80, RiskFlag.OPTIMAL),
            (1.00, RiskFlag.OPTIMAL),
            (1.30, RiskFlag.OPTIMAL),
            (1.31, RiskFlag.ELEVATED),
            (1.50, RiskFlag.ELEVATED),
            (1.51, RiskFlag.HIGH),
            (2.40, RiskFlag.HIGH),
        ]
        for value, expected in cases:
            with self.subTest(acwr=value):
                self.assertEqual(an.classify_acwr(value), expected)

    def test_every_flag_has_advice(self):
        for flag in RiskFlag:
            self.assertIn(flag, an.ACWR_ADVICE)


class MonotonyStrainTests(TestCase):
    def setUp(self):
        self.athlete = make_athlete()
        self.week = an.monday_of(TODAY)

    def test_monday_of_returns_monday(self):
        self.assertEqual(self.week.weekday(), 0)
        self.assertEqual(an.monday_of(self.week), self.week)

    def test_identical_daily_loads_return_none(self):
        """完全一樣的日負荷 → 標準差為 0 → 回傳 None 而非除以零。"""
        for i in range(7):
            make_session(self.athlete, self.week + timedelta(days=i), rpe=6, minutes=60)
        self.assertIsNone(an.calculate_monotony(self.athlete, self.week))
        self.assertIsNone(an.calculate_strain(self.athlete, self.week))

    def test_flat_week_with_one_rest_day_flags_high_monotony(self):
        """六天一樣、一天休息 → 標準差很小 → 單調度 > 2，正是要警示的情況。"""
        for i in range(6):
            make_session(self.athlete, self.week + timedelta(days=i), rpe=6, minutes=60)
        monotony = an.calculate_monotony(self.athlete, self.week)
        self.assertIsNotNone(monotony)
        self.assertGreater(monotony, 2.0)

    def test_varied_loads_give_lower_monotony(self):
        for i, rpe in enumerate([9, 3, 8, 2, 9, 5, 0]):
            make_session(self.athlete, self.week + timedelta(days=i), rpe=rpe, minutes=60)
        self.assertLess(an.calculate_monotony(self.athlete, self.week), 2.0)

    def test_strain_is_weekly_load_times_monotony(self):
        for i, rpe in enumerate([9, 3, 8, 2, 9, 5, 1]):
            make_session(self.athlete, self.week + timedelta(days=i), rpe=rpe, minutes=60)
        monotony = an.calculate_monotony(self.athlete, self.week)
        weekly = sum(rpe * 60 for rpe in [9, 3, 8, 2, 9, 5, 1])
        self.assertAlmostEqual(
            an.calculate_strain(self.athlete, self.week), weekly * monotony, places=1
        )


class TrendTests(TestCase):
    def test_slope_of_improving_times_is_negative(self):
        """時間項目成績變快 → 斜率為負 → 系統應判定為進步。"""
        xs = [0, 30, 60, 90]
        ys = [12.40, 12.30, 12.20, 12.05]
        self.assertLess(an._linear_slope(xs, ys), 0)

    def test_slope_is_zero_for_flat_series(self):
        self.assertAlmostEqual(an._linear_slope([0, 1, 2, 3], [11.0] * 4), 0.0, places=6)

    def test_slope_needs_at_least_two_points(self):
        self.assertIsNone(an._linear_slope([1], [11.0]))


class WeeklyProgressionTests(TestCase):
    """weekly_load_progression 以「今天」為基準，所以測試資料也要以今天往回填。"""

    def setUp(self):
        self.athlete = make_athlete()

    def test_returns_requested_number_of_weeks_in_order(self):
        fill_days(self.athlete, date.today(), days=56, rpe=5, minutes=60)
        rows = an.weekly_load_progression(self.athlete, weeks=8)
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r["total_load"] > 0 for r in rows))
        weeks = [r["week_start"] for r in rows]
        self.assertEqual(weeks, sorted(weeks), "應由舊到新排列")

    def test_week_over_week_change_is_percentage(self):
        this_week = an.monday_of(date.today())
        last_week = this_week - timedelta(days=7)
        for i in range(7):
            make_session(self.athlete, last_week + timedelta(days=i), rpe=5, minutes=60)
            make_session(self.athlete, this_week + timedelta(days=i), rpe=6, minutes=60)
        # 上週 7×300=2100，本週 7×360=2520 → +20%
        self.assertAlmostEqual(
            an.week_over_week_change(self.athlete, this_week), 20.0, places=1
        )

    def test_week_over_week_change_is_none_without_baseline(self):
        this_week = an.monday_of(date.today())
        make_session(self.athlete, this_week, rpe=6, minutes=60)
        self.assertIsNone(an.week_over_week_change(self.athlete, this_week))

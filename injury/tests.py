"""傷患封鎖與課表自動調整的測試。"""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from core.models import AthleteStatus, SessionStatus, SessionType
from core.test_factories import TODAY, make_athlete, make_session
from injury import services as inj
from injury.models import Injury, InjuryStatus, PainLog, TrainingMode


def make_injury(athlete, body_part="HAMSTRING", pain=0, status=InjuryStatus.ACUTE):
    injury = Injury.objects.create(
        athlete=athlete,
        body_part=body_part,
        injury_type="STRAIN",
        onset_date=TODAY,
        severity=2,
        status=status,
    )
    PainLog.objects.create(
        injury=injury, date=TODAY, pain_at_rest=max(pain - 2, 0), pain_during_activity=pain
    )
    return injury


class PainBlockTests(TestCase):
    """活動時疼痛 ≥ 6 才封鎖高強度，5 分不封鎖——邊界要精準。"""

    def setUp(self):
        self.athlete = make_athlete()

    def test_no_injury_no_block(self):
        blocked, _ = inj.should_block_high_intensity(self.athlete, TODAY)
        self.assertFalse(blocked)

    def test_pain_five_does_not_block(self):
        make_injury(self.athlete, pain=5, status=InjuryStatus.REHAB)
        blocked, _ = inj.should_block_high_intensity(self.athlete, TODAY)
        self.assertFalse(blocked)

    def test_pain_six_blocks(self):
        make_injury(self.athlete, pain=6)
        blocked, reason = inj.should_block_high_intensity(self.athlete, TODAY)
        self.assertTrue(blocked)
        self.assertTrue(reason)

    def test_worst_pain_takes_the_maximum_across_injuries(self):
        make_injury(self.athlete, body_part="HAMSTRING", pain=3)
        make_injury(self.athlete, body_part="ANKLE", pain=8)
        self.assertEqual(inj.worst_pain_today(self.athlete, TODAY), 8)

    def test_resolved_injury_pain_log_does_not_block(self):
        """已結案傷患當天留下的舊疼痛紀錄，不應再封鎖訓練。"""
        make_injury(self.athlete, pain=9, status=InjuryStatus.RESOLVED)
        self.assertIsNone(inj.worst_pain_today(self.athlete, TODAY))
        blocked, _ = inj.should_block_high_intensity(self.athlete, TODAY)
        self.assertFalse(blocked)

    def test_threshold_matches_settings(self):
        from django.conf import settings

        self.assertEqual(inj.PAIN_BLOCK_THRESHOLD, settings.ATM_PAIN_BLOCK_THRESHOLD)


class ActiveInjuryTests(TestCase):
    def setUp(self):
        self.athlete = make_athlete()

    def test_resolved_injury_is_not_active(self):
        make_injury(self.athlete, pain=9, status=InjuryStatus.RESOLVED)
        self.assertEqual(list(inj.active_injuries(self.athlete)), [])
        blocked, _ = inj.should_block_high_intensity(self.athlete, TODAY)
        self.assertFalse(blocked)

    def test_affected_body_parts_lists_active_only(self):
        make_injury(self.athlete, body_part="HAMSTRING", pain=4, status=InjuryStatus.REHAB)
        make_injury(self.athlete, body_part="ANKLE", pain=4, status=InjuryStatus.RESOLVED)
        self.assertEqual(set(inj.affected_body_parts(self.athlete)), {"HAMSTRING"})


class ApplyModificationsTests(TestCase):
    def setUp(self):
        self.athlete = make_athlete()

    def test_high_intensity_session_is_downgraded_to_recovery(self):
        make_injury(self.athlete, pain=8)
        session = make_session(
            self.athlete,
            TODAY,
            session_type=SessionType.TRACK,
            minutes=90,
            status=SessionStatus.PLANNED,
        )
        inj.apply_modifications(session)
        session.refresh_from_db()
        self.assertEqual(session.session_type, SessionType.RECOVERY)
        self.assertTrue(session.is_modified)

    def test_downgraded_session_duration_is_capped(self):
        make_injury(self.athlete, pain=8)
        session = make_session(
            self.athlete,
            TODAY,
            session_type=SessionType.STRENGTH,
            minutes=120,
            status=SessionStatus.PLANNED,
        )
        inj.apply_modifications(session)
        session.refresh_from_db()
        self.assertLessEqual(session.planned_duration_min, 45)

    def test_recovery_session_is_left_alone(self):
        make_injury(self.athlete, pain=8)
        session = make_session(
            self.athlete,
            TODAY,
            session_type=SessionType.RECOVERY,
            minutes=40,
            status=SessionStatus.PLANNED,
        )
        inj.apply_modifications(session)
        session.refresh_from_db()
        self.assertEqual(session.session_type, SessionType.RECOVERY)
        self.assertEqual(session.planned_duration_min, 40)

    def test_no_pain_means_no_modification(self):
        make_injury(self.athlete, pain=2, status=InjuryStatus.REHAB)
        session = make_session(
            self.athlete,
            TODAY,
            session_type=SessionType.TRACK,
            minutes=90,
            status=SessionStatus.PLANNED,
        )
        inj.apply_modifications(session)
        session.refresh_from_db()
        self.assertEqual(session.session_type, SessionType.TRACK)
        self.assertFalse(session.is_modified)


class SyncStatusTests(TestCase):
    def setUp(self):
        self.athlete = make_athlete()

    def test_healthy_without_injuries(self):
        inj.sync_athlete_status(self.athlete)
        self.athlete.refresh_from_db()
        self.assertEqual(self.athlete.status, AthleteStatus.HEALTHY)

    def test_high_pain_marks_injured(self):
        make_injury(self.athlete, pain=8)
        inj.sync_athlete_status(self.athlete)
        self.athlete.refresh_from_db()
        self.assertEqual(self.athlete.status, AthleteStatus.INJURED)

    def test_return_to_run_marks_niggle_not_injured(self):
        """急性期/復健中才算 INJURED，回歸跑動階段只是輕微不適。"""
        make_injury(self.athlete, pain=2, status=InjuryStatus.RETURN_TO_RUN)
        inj.sync_athlete_status(self.athlete)
        self.athlete.refresh_from_db()
        self.assertEqual(self.athlete.status, AthleteStatus.NIGGLE)


class RtpChecklistTests(TestCase):
    def test_checklist_is_not_empty(self):
        athlete = make_athlete()
        injury = make_injury(athlete, pain=3)
        report = inj.rtp_checklist(injury)
        self.assertTrue(report["criteria"])
        self.assertTrue(report["note"])


class LoadVerdictTests(TestCase):
    """傷後加減量的三大標準：當下 ≤3、運動後不加劇、隔天早上完全恢復。"""

    def setUp(self):
        self.athlete = make_athlete()
        self.injury = Injury.objects.create(
            athlete=self.athlete,
            body_part="SHOULDER",
            injury_type="TENDINOPATHY",
            onset_date=TODAY,
            severity=2,
            status=InjuryStatus.REHAB,
        )

    def log(self, day, before=2, during=2, after=2, **kwargs):
        return PainLog.objects.create(
            injury=self.injury,
            date=day,
            pain_before=before,
            pain_at_rest=before,
            pain_during_activity=during,
            pain_after_session=after,
            **kwargs,
        )

    def test_without_any_log_there_is_no_verdict(self):
        v = inj.load_verdict(self.injury, TODAY)
        self.assertFalse(v["has_data"])

    def test_pain_over_three_during_activity_means_cut_back(self):
        self.log(TODAY, before=2, during=5, after=2)
        v = inj.load_verdict(self.injury, TODAY)
        self.assertEqual(v["verdict"], "減量")
        self.assertFalse(v["checks"][0]["ok"])

    def test_pain_higher_after_session_means_cut_back(self):
        self.log(TODAY, before=2, during=3, after=5)
        v = inj.load_verdict(self.injury, TODAY)
        self.assertEqual(v["verdict"], "減量")
        self.assertFalse(v["checks"][1]["ok"])

    def test_missing_next_morning_is_not_enough_data(self):
        """第三條要拿隔天早上的數字比，今天填完還判斷不出來。"""
        self.log(TODAY, before=2, during=2, after=2)
        v = inj.load_verdict(self.injury, TODAY)
        self.assertEqual(v["verdict"], "資料不足")
        self.assertIsNone(v["checks"][2]["ok"])

    def test_all_three_passed_allows_a_small_increase(self):
        self.log(TODAY, before=2, during=3, after=2, load_intensity=7, load_volume="投 30 球")
        self.log(TODAY + timedelta(days=1), before=2, during=2, after=2)
        v = inj.load_verdict(self.injury, TODAY)
        self.assertEqual(v["verdict"], "可小幅加量")
        self.assertTrue(all(c["ok"] for c in v["checks"]))

    def test_next_morning_worse_than_before_means_cut_back(self):
        self.log(TODAY, before=2, during=3, after=2)
        self.log(TODAY + timedelta(days=1), before=5, during=2, after=2)
        v = inj.load_verdict(self.injury, TODAY)
        self.assertEqual(v["verdict"], "減量")
        self.assertFalse(v["checks"][2]["ok"])


class PeaceLoveTests(TestCase):
    def setUp(self):
        self.athlete = make_athlete()

    def test_fresh_acute_injury_gets_peace(self):
        injury = make_injury(self.athlete, status=InjuryStatus.ACUTE)
        injury.onset_date = date.today()
        guide = inj.peace_love_guide(injury)
        self.assertEqual(guide["phase"], "PEACE")
        self.assertEqual(len(guide["steps"]), 5)

    def test_rehab_phase_gets_love(self):
        injury = make_injury(self.athlete, status=InjuryStatus.REHAB)
        injury.onset_date = date.today() - timedelta(days=20)
        guide = inj.peace_love_guide(injury)
        self.assertEqual(guide["phase"], "LOVE")
        self.assertEqual(len(guide["steps"]), 4)


class MultiInjuryBoardTests(TestCase):
    """多處受傷時：總覽依急性程度排序，當日處理方式取最保守的一級。"""

    def setUp(self):
        self.athlete = make_athlete()

    def test_board_puts_the_most_urgent_first(self):
        mild = make_injury(self.athlete, body_part="ANKLE", pain=1,
                           status=InjuryStatus.RETURN_TO_RUN)
        bad = make_injury(self.athlete, body_part="HAMSTRING", pain=8,
                          status=InjuryStatus.ACUTE)
        rows = inj.injury_board([mild, bad])
        self.assertEqual(rows[0]["injury"], bad)
        self.assertEqual(rows[0]["pain"], 8)

    def test_team_mode_takes_the_most_conservative(self):
        a = make_injury(self.athlete, body_part="ANKLE")
        b = make_injury(self.athlete, body_part="KNEE")
        a.training_mode = TrainingMode.GRADUAL
        b.training_mode = TrainingMode.FULL_REST
        self.assertEqual(inj.team_training_mode([a, b]), TrainingMode.FULL_REST)

    def test_team_mode_is_none_without_injuries(self):
        self.assertIsNone(inj.team_training_mode([]))


class RtpProgressTests(TestCase):
    def setUp(self):
        self.injury = make_injury(make_athlete())

    def test_nothing_checked_is_zero_percent(self):
        rtp = inj.rtp_checklist(self.injury)
        self.assertEqual(rtp["met"], 0)
        self.assertFalse(rtp["cleared"])

    def test_all_checked_clears_return_to_play(self):
        rtp = inj.rtp_checklist(self.injury)
        self.injury.rtp_progress = list(range(rtp["total"]))
        rtp = inj.rtp_checklist(self.injury)
        self.assertTrue(rtp["cleared"])
        self.assertEqual(rtp["percent"], 100)


class InjuryPageTests(TestCase):
    """傷患頁的新動作：一次回報、切換處理方式、RTP 勾選。"""

    def setUp(self):
        self.athlete = make_athlete("injpage")
        self.client.login(username="injpage", password="test-pw-12345")
        self.a = make_injury(self.athlete, body_part="HAMSTRING", pain=2)
        self.b = make_injury(self.athlete, body_part="ANKLE", pain=1)
        self.url = reverse("web:injuries")

    def test_page_renders_the_board_for_multiple_injuries(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["board"]), 2)
        self.assertEqual(len(r.context["detail"]), 2)

    def test_daily_report_writes_one_log_per_filled_row(self):
        self.client.post(self.url, {
            "action": "daily_report",
            f"pain_before_{self.a.id}": 2,
            f"pain_during_activity_{self.a.id}": 4,
            f"pain_after_session_{self.a.id}": 3,
            f"load_intensity_{self.a.id}": 7,
            f"load_volume_{self.a.id}": "慢跑 3km",
            # b 沒填「運動當下」，不該被寫入
            f"pain_before_{self.b.id}": 1,
        })
        log = self.a.pain_logs.get(date=date.today())
        self.assertEqual(log.pain_during_activity, 4)
        self.assertEqual(log.load_volume, "慢跑 3km")
        self.assertFalse(self.b.pain_logs.filter(date=date.today()).exists())

    def test_set_training_mode_is_saved(self):
        self.client.post(self.url, {
            "action": "set_training_mode",
            "injury_id": self.a.id,
            "training_mode": TrainingMode.FULL_REST,
            "training_note": "改水中跑",
        })
        self.a.refresh_from_db()
        self.assertEqual(self.a.training_mode, TrainingMode.FULL_REST)
        self.assertEqual(self.a.training_note, "改水中跑")

    def test_team_mode_takes_the_most_conservative_of_the_two(self):
        self.a.training_mode = TrainingMode.FULL_REST
        self.a.save(update_fields=["training_mode"])
        r = self.client.get(self.url)
        self.assertEqual(r.context["team_mode"], TrainingMode.FULL_REST)

    def test_rtp_checkboxes_persist(self):
        self.client.post(self.url, {
            "action": "rtp_toggle", "injury_id": self.a.id, "rtp": ["0", "2"],
        })
        self.a.refresh_from_db()
        self.assertEqual(self.a.rtp_progress, [0, 2])

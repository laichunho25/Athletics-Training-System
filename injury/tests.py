"""傷患封鎖與課表自動調整的測試。"""

from django.test import TestCase

from core.models import AthleteStatus, SessionStatus, SessionType
from core.test_factories import TODAY, make_athlete, make_session
from injury import services as inj
from injury.models import Injury, InjuryStatus, PainLog


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

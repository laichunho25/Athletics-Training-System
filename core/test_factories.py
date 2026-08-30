"""測試共用的資料工廠——各 app 的 tests.py 都從這裡建資料。"""

from datetime import date, timedelta

from accounts.models import AthleteProfile, CoachProfile, Event, User
from core.models import (
    EventCategory,
    MeasureUnit,
    Role,
    SessionStatus,
    SessionType,
    Sex,
)
from planning.models import TrainingSession

TODAY = date(2026, 6, 1)  # 固定日期，避免測試因「今天」而飄動


def make_event(code="100M", name="100 公尺", unit=MeasureUnit.TIME, distance=100):
    return Event.objects.get_or_create(
        code=code,
        defaults={
            "name_zh": name,
            "name_en": code,
            "category": EventCategory.SPRINT,
            "unit": unit,
            "distance_m": distance,
        },
    )[0]


def make_coach(username="coach1", squad="測試隊"):
    user = User.objects.create_user(
        username=username, password="test-pw-12345", role=Role.COACH
    )
    return CoachProfile.objects.create(user=user, squad_name=squad)


def make_athlete(username="ath1", coach=None, event=None, **kwargs):
    user = User.objects.create_user(
        username=username, password="test-pw-12345", role=Role.ATHLETE
    )
    defaults = {
        "birth_date": date(2006, 3, 15),
        "sex": Sex.MALE,
        "height_cm": 175,
        "weight_kg": 68,
        "primary_event": event or make_event(),
        "coach": coach,
    }
    defaults.update(kwargs)
    return AthleteProfile.objects.create(user=user, **defaults)


def make_admin(username="admin1"):
    return User.objects.create_user(
        username=username,
        password="test-pw-12345",
        role=Role.ADMIN,
        is_staff=True,
        is_superuser=True,
    )


def make_session(
    athlete,
    on_date,
    rpe=6,
    minutes=60,
    session_type=SessionType.TRACK,
    status=SessionStatus.COMPLETED,
    title="測試課表",
):
    """建立一堂已完成的課，負荷 = rpe × minutes。"""
    return TrainingSession.objects.create(
        athlete=athlete,
        date=on_date,
        session_type=session_type,
        title=title,
        planned_duration_min=minutes if minutes is not None else 60,
        actual_duration_min=minutes,
        session_rpe=rpe,
        status=status,
    )


def fill_days(athlete, end_date, days, rpe=6, minutes=60):
    """
    往回填滿連續 days 天、每天一堂固定負荷的課。
    用來讓 ACWR 通過「28 天資料」門檻。
    """
    for i in range(days):
        make_session(athlete, end_date - timedelta(days=i), rpe=rpe, minutes=minutes)

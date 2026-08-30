"""
建立示範資料：1 名教練 + 1 名 400m 運動員 + 16 週備戰計劃 + 近 6 週訓練紀錄。

    python manage.py seed_demo
    python manage.py seed_demo --reset
"""

import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import AthleteProfile, CoachProfile, Event, PersonalBest, User
from analytics.services import monday_of, rebuild_all
from core.models import Role, SessionStatus, SessionType, Sex
from nutrition.models import RecoveryLog, RecoveryMethod
from nutrition.services import calculate_targets
from planning.models import Competition, Macrocycle, TrainingSession
from training.models import Exercise, OneRepMax, StrengthSet, TrackSet

TARGET_COMPETITION = ("全港田徑公開賽", date(2026, 11, 29))
DEMO_START = date(2026, 8, 10)  # 16 週計劃起點（週一）


class Command(BaseCommand):
    help = "建立 ATM 示範資料"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="先刪除現有示範帳號")
        parser.add_argument("--weeks", type=int, default=6, help="回填幾週的訓練紀錄")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            User.objects.filter(username__in=["coach_chan", "athlete_lai"]).delete()
            self.stdout.write("已清除舊示範帳號。")

        # 管理員（可進 /admin/）
        admin_user, created = User.objects.get_or_create(
            username="admin",
            defaults={"role": Role.ADMIN, "is_staff": True, "is_superuser": True},
        )
        if created:
            admin_user.set_password("admin12345")
            admin_user.is_staff = True
            admin_user.is_superuser = True
            admin_user.save()

        coach_user, _ = User.objects.get_or_create(
            username="coach_chan",
            defaults={"first_name": "大文", "last_name": "陳", "role": Role.COACH},
        )
        coach_user.set_password("atm12345")
        coach_user.is_staff = True  # 教練可進 admin 後台管理課表
        coach_user.save()
        coach, _ = CoachProfile.objects.get_or_create(
            user=coach_user,
            defaults={"squad_name": "短跑組", "specialties": "短跑 / 跨欄", "years_of_experience": 8},
        )

        athlete_user, _ = User.objects.get_or_create(
            username="athlete_lai",
            defaults={"first_name": "俊豪", "last_name": "黎", "role": Role.ATHLETE},
        )
        athlete_user.set_password("atm12345")
        athlete_user.save()

        e400 = Event.objects.get(code="400M")
        e200 = Event.objects.get(code="200M")
        athlete, _ = AthleteProfile.objects.get_or_create(
            user=athlete_user,
            defaults={
                "coach": coach,
                "birth_date": date(2009, 3, 14),
                "sex": Sex.MALE,
                "height_cm": 175,
                "weight_kg": 65,
                "primary_event": e400,
                "training_days_per_week": 5,
                "strength_experience_years": 1.5,
                "school_or_club": "DBS",
            },
        )
        athlete.secondary_events.set([e200])

        PersonalBest.objects.get_or_create(
            athlete=athlete, event=e400, date=date(2026, 4, 18),
            defaults={"mark": 51.20, "competition_name": "學界田徑賽", "is_current": True},
        )
        PersonalBest.objects.get_or_create(
            athlete=athlete, event=e200, date=date(2026, 4, 19),
            defaults={"mark": 23.45, "competition_name": "學界田徑賽", "is_current": True},
        )

        comp, _ = Competition.objects.get_or_create(
            name=TARGET_COMPETITION[0],
            date=TARGET_COMPETITION[1],
            defaults={"level": "REGIONAL", "is_target": True, "venue": "香港大球場"},
        )

        macro, created = Macrocycle.objects.get_or_create(
            athlete=athlete,
            target_competition=comp,
            defaults={
                "start_date": DEMO_START,
                "end_date": TARGET_COMPETITION[1],
                "total_weeks": 16,
                "baseline_weekly_load": 1800,
            },
        )
        macro.generate_phases()
        macro.generate_microcycles()
        self.stdout.write(f"已建立 16 週備戰計劃：{macro}")

        # 1RM 基準
        for code, kg in [("BACK_SQUAT", 100), ("POWER_CLEAN", 70), ("BENCH_PRESS", 65),
                         ("RDL", 90), ("HIP_THRUST", 120)]:
            OneRepMax.objects.get_or_create(
                athlete=athlete,
                exercise=Exercise.objects.get(code=code),
                test_date=date(2026, 8, 8),
                defaults={"value_kg": kg, "is_estimated": False},
            )

        weeks = options["weeks"]
        self.stdout.write(f"回填 {weeks} 週訓練紀錄…")
        self._seed_sessions(athlete, coach, macro, weeks)

        rebuild_all(athlete, days=weeks * 7 + 7)

        methods = list(RecoveryMethod.objects.all()[:4])
        for i in range(weeks * 7):
            d = date.today() - timedelta(days=i)
            log, _ = RecoveryLog.objects.get_or_create(
                athlete=athlete,
                date=d,
                defaults={
                    "sleep_hours": round(random.uniform(6.0, 8.5), 1),
                    "sleep_quality": random.randint(3, 5),
                    "water_intake_ml": random.randint(2000, 3500),
                    "soreness_level": random.randint(2, 6),
                    "stress_level": random.randint(1, 3),
                    "mood": random.randint(3, 5),
                    "resting_hr": random.randint(48, 58),
                },
            )
            if methods:
                log.methods.set(random.sample(methods, k=2))

        for i in range(7):
            calculate_targets(athlete, date.today() + timedelta(days=i))

        self.stdout.write(self.style.SUCCESS("\n✅ 示範資料建立完成"))
        self.stdout.write(f"   教練帳號：coach_chan / atm12345")
        self.stdout.write(f"   運動員帳號：athlete_lai / atm12345")
        self.stdout.write(f"   目標賽事：{comp.name} {comp.date}（{comp.countdown_display}）")

    def _seed_sessions(self, athlete, coach, macro, weeks):
        squat = Exercise.objects.get(code="BACK_SQUAT")
        clean = Exercise.objects.get(code="POWER_CLEAN")
        rdl = Exercise.objects.get(code="RDL")
        one_rm = {e.code: OneRepMax.latest_for(athlete, e) for e in [squat, clean, rdl]}

        today = date.today()
        start = monday_of(today - timedelta(weeks=weeks - 1))

        plan = {
            0: (SessionType.TRACK, "加速度 + 速度", 90, [(30, 6, 4.2), (60, 4, 7.6)]),
            1: (SessionType.STRENGTH, "最大力量 (下肢)", 75, None),
            3: (SessionType.TRACK, "專項耐力 400m", 100, [(200, 6, 26.5), (150, 2, 19.8)]),
            4: (SessionType.STRENGTH, "爆發力 + 核心", 70, None),
            5: (SessionType.TRACK, "節奏跑 + 技術", 80, [(120, 8, 16.5)]),
            6: (SessionType.REST, "休息", 0, None),
        }

        for w in range(weeks):
            week_start = start + timedelta(weeks=w)
            micro = macro.microcycles.filter(
                start_date__lte=week_start, start_date__gte=week_start - timedelta(days=6)
            ).first()

            for dow, (stype, title, minutes, track_plan) in plan.items():
                d = week_start + timedelta(days=dow)
                if d > today:
                    continue
                if TrainingSession.objects.filter(athlete=athlete, date=d).exists():
                    continue

                is_rest = stype == SessionType.REST
                session = TrainingSession.objects.create(
                    athlete=athlete,
                    microcycle=micro,
                    date=d,
                    time_slot="PM",
                    session_type=stype,
                    title=title,
                    assigned_by=coach,
                    planned_duration_min=minutes,
                    status=SessionStatus.PLANNED if is_rest else SessionStatus.COMPLETED,
                    completion_pct=0 if is_rest else random.choice([90, 100, 100]),
                    actual_duration_min=None if is_rest else minutes + random.randint(-10, 15),
                    session_rpe=None if is_rest else random.randint(5, 9),
                )

                if track_plan:
                    for i, (dist, reps, base_time) in enumerate(track_plan, start=1):
                        TrackSet.objects.create(
                            session=session,
                            order=i,
                            description=f"{reps} × {dist}m",
                            distance_m=dist,
                            reps=reps,
                            sets=1,
                            target_time_sec=base_time,
                            actual_time_sec=round(base_time + random.uniform(-0.4, 0.6), 2),
                            rest_between_reps_sec=180 if dist >= 150 else 90,
                            rpe=random.randint(6, 9),
                            technical_focus="起跑角度、擺臂節奏" if dist <= 60 else "維持步頻、放鬆上肢",
                            spikes_used=dist <= 200,
                        )

                if stype == SessionType.STRENGTH:
                    lifts = [(squat, 4, 5, 80), (rdl, 3, 6, 70)] if dow == 1 else [
                        (clean, 5, 3, 75), (squat, 3, 3, 85)
                    ]
                    for order, (ex, sets_n, reps, pct) in enumerate(lifts, start=1):
                        rm = one_rm.get(ex.code)
                        weight = rm.load_at(pct) if rm else 60
                        for s in range(1, sets_n + 1):
                            StrengthSet.objects.create(
                                session=session,
                                exercise=ex,
                                order=order,
                                set_number=s,
                                reps=reps,
                                weight_kg=weight,
                                target_1rm_pct=pct,
                                rest_sec=180,
                                rir=random.randint(1, 3),
                                rpe=random.randint(7, 9),
                            )

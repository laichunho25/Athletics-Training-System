from datetime import date, timedelta

from django.db import models

from accounts.models import AthleteProfile, CoachProfile, Event
from core.models import PhaseType, SessionStatus, SessionType, TimeStampedModel


class CompetitionLevel(models.TextChoices):
    SCHOOL = "SCHOOL", "校際"
    REGIONAL = "REGIONAL", "地區/公開賽"
    NATIONAL = "NATIONAL", "全國錦標賽"
    INTL = "INTL", "國際賽"


class Competition(TimeStampedModel):
    name = models.CharField("賽事名稱", max_length=150)
    date = models.DateField("比賽日期")
    end_date = models.DateField("結束日期", null=True, blank=True)
    venue = models.CharField("場地", max_length=150, blank=True)
    level = models.CharField(
        "層級", max_length=10, choices=CompetitionLevel.choices, default=CompetitionLevel.REGIONAL
    )
    is_target = models.BooleanField("主目標賽事", default=False)

    class Meta:
        verbose_name = "賽事"
        verbose_name_plural = "賽事"
        ordering = ["date"]

    def __str__(self):
        return f"{self.name} ({self.date})"

    @property
    def days_remaining(self):
        return (self.date - date.today()).days

    @property
    def weeks_remaining(self):
        return self.days_remaining // 7

    @property
    def countdown_display(self):
        d = self.days_remaining
        if d < 0:
            return f"已結束 {abs(d)} 天"
        return f"剩餘 {d} 天 / 約 {self.weeks_remaining} 週"


class CompetitionEntry(TimeStampedModel):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="entries")
    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="competition_entries"
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    target_mark = models.DecimalField("目標成績", max_digits=8, decimal_places=2, null=True, blank=True)
    result_mark = models.DecimalField("實際成績", max_digits=8, decimal_places=2, null=True, blank=True)
    placing = models.PositiveSmallIntegerField("名次", null=True, blank=True)
    notes = models.TextField("備註", blank=True)

    class Meta:
        verbose_name = "參賽項目"
        verbose_name_plural = "參賽項目"
        unique_together = ("competition", "athlete", "event")

    def __str__(self):
        return f"{self.athlete} @ {self.competition.name} - {self.event.code}"


# 16 週預設分期模板：(期別, 起始週, 結束週, 重心, 週負荷係數)
DEFAULT_16W_TEMPLATE = [
    (PhaseType.GENERAL_PREP, 1, 5, "有氧基礎、一般力量、技術重建、傷患修復", 1.00),
    (PhaseType.SPECIFIC_PREP, 6, 11, "專項速度/耐力、最大力量→爆發力轉化", 1.15),
    (PhaseType.PRE_COMP, 12, 14, "強度提升、量下降、模擬賽與熱身賽", 0.90),
    (PhaseType.TAPER_COMP, 15, 16, "減量調整 (Taper)、神經激活、賽前恢復", 0.55),
]


class Macrocycle(TimeStampedModel):
    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="macrocycles"
    )
    target_competition = models.ForeignKey(
        Competition, on_delete=models.CASCADE, related_name="macrocycles"
    )
    start_date = models.DateField("開始日期")
    end_date = models.DateField("結束日期")
    total_weeks = models.PositiveSmallIntegerField("總週數", default=16)
    baseline_weekly_load = models.PositiveIntegerField(
        "基準週負荷 (AU)", default=1800, help_text="準備期的目標週負荷，其餘期別按係數換算"
    )
    is_active = models.BooleanField("使用中", default=True)

    class Meta:
        verbose_name = "備戰大週期"
        verbose_name_plural = "備戰大週期"
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.athlete} → {self.target_competition.name} ({self.total_weeks}週)"

    @property
    def current_week_number(self):
        today = date.today()
        if today < self.start_date:
            return 0
        return min((today - self.start_date).days // 7 + 1, self.total_weeks)

    @property
    def current_phase(self):
        return self.phases.filter(
            week_start__lte=self.current_week_number, week_end__gte=self.current_week_number
        ).first()

    def generate_phases(self, template=None):
        """依模板建立分期。已存在的分期會先清除。"""
        template = template or DEFAULT_16W_TEMPLATE
        self.phases.all().delete()
        created = []
        for phase_type, w_start, w_end, focus, factor in template:
            if w_start > self.total_weeks:
                continue
            w_end = min(w_end, self.total_weeks)
            created.append(
                Phase(
                    macrocycle=self,
                    phase_type=phase_type,
                    week_start=w_start,
                    week_end=w_end,
                    start_date=self.start_date + timedelta(weeks=w_start - 1),
                    end_date=self.start_date + timedelta(weeks=w_end, days=-1),
                    focus=focus,
                    target_weekly_load=int(self.baseline_weekly_load * factor),
                )
            )
        return Phase.objects.bulk_create(created)

    def generate_microcycles(self):
        """為每一週建立 Microcycle。"""
        existing = set(self.microcycles.values_list("week_number", flat=True))
        created = []
        for week in range(1, self.total_weeks + 1):
            if week in existing:
                continue
            phase = self.phases.filter(week_start__lte=week, week_end__gte=week).first()
            created.append(
                Microcycle(
                    macrocycle=self,
                    phase=phase,
                    week_number=week,
                    start_date=self.start_date + timedelta(weeks=week - 1),
                    planned_load=phase.target_weekly_load if phase else 0,
                )
            )
        return Microcycle.objects.bulk_create(created)


class Phase(models.Model):
    macrocycle = models.ForeignKey(Macrocycle, on_delete=models.CASCADE, related_name="phases")
    phase_type = models.CharField("期別", max_length=20, choices=PhaseType.choices)
    week_start = models.PositiveSmallIntegerField("起始週")
    week_end = models.PositiveSmallIntegerField("結束週")
    start_date = models.DateField("開始日期")
    end_date = models.DateField("結束日期")
    focus = models.TextField("訓練重心", blank=True)
    target_weekly_load = models.PositiveIntegerField("目標週負荷 (AU)", default=0)

    class Meta:
        verbose_name = "分期"
        verbose_name_plural = "分期"
        ordering = ["week_start"]

    def __str__(self):
        return f"{self.get_phase_type_display()} W{self.week_start}-W{self.week_end}"


class Microcycle(TimeStampedModel):
    macrocycle = models.ForeignKey(
        Macrocycle, on_delete=models.CASCADE, related_name="microcycles"
    )
    phase = models.ForeignKey(
        Phase, on_delete=models.SET_NULL, null=True, blank=True, related_name="microcycles"
    )
    week_number = models.PositiveSmallIntegerField("週次")
    start_date = models.DateField("週一日期")
    planned_load = models.PositiveIntegerField("計劃負荷 (AU)", default=0)
    actual_load = models.PositiveIntegerField("實際負荷 (AU)", default=0)
    notes = models.TextField("週計劃備註", blank=True)

    class Meta:
        verbose_name = "週計劃"
        verbose_name_plural = "週計劃"
        unique_together = ("macrocycle", "week_number")
        ordering = ["week_number"]

    def __str__(self):
        return f"W{self.week_number} ({self.start_date})"

    @property
    def end_date(self):
        return self.start_date + timedelta(days=6)

    @property
    def completion_rate(self):
        if not self.planned_load:
            return None
        return round(self.actual_load / self.planned_load * 100, 1)

    def recalculate_actual_load(self):
        total = sum(s.session_load or 0 for s in self.sessions.all())
        if total != self.actual_load:
            self.actual_load = int(total)
            self.save(update_fields=["actual_load", "updated_at"])
        return self.actual_load


class TrainingSession(TimeStampedModel):
    """系統核心表：所有專項/力量紀錄都掛在這裡。"""

    athlete = models.ForeignKey(
        AthleteProfile, on_delete=models.CASCADE, related_name="sessions"
    )
    microcycle = models.ForeignKey(
        Microcycle, on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions"
    )
    date = models.DateField("日期")
    time_slot = models.CharField(
        "時段", max_length=2, choices=[("AM", "上午"), ("PM", "下午")], default="PM"
    )
    session_type = models.CharField("課別", max_length=20, choices=SessionType.choices)
    title = models.CharField("課表名稱", max_length=150)
    description = models.TextField("課表內容", blank=True)
    assigned_by = models.ForeignKey(
        CoachProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_sessions",
        verbose_name="派發教練",
        help_text="留空表示運動員自訂",
    )
    planned_duration_min = models.PositiveSmallIntegerField("計劃時長 (分)", default=90)
    actual_duration_min = models.PositiveSmallIntegerField("實際時長 (分)", null=True, blank=True)
    status = models.CharField(
        "狀態", max_length=10, choices=SessionStatus.choices, default=SessionStatus.PLANNED
    )
    completion_pct = models.PositiveSmallIntegerField("完成度 (%)", default=0)
    session_rpe = models.PositiveSmallIntegerField("課後 RPE (1-10)", null=True, blank=True)
    is_modified = models.BooleanField("傷患調整後課表", default=False)
    athlete_feedback = models.TextField("運動員反饋", blank=True)
    coach_comment = models.TextField("教練評語", blank=True)
    satisfaction = models.PositiveSmallIntegerField(
        "訓練滿意度 (1-5)",
        null=True,
        blank=True,
        help_text="完成訓練後自評：這一課練得滿不滿意",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sessions",
        verbose_name="建立者",
        help_text="誰把這堂課寫進日曆的；只有他自己（和管理員）能改課表本身",
    )

    class Meta:
        verbose_name = "訓練課"
        verbose_name_plural = "訓練課"
        ordering = ["-date", "time_slot"]
        indexes = [
            models.Index(fields=["athlete", "date"]),
            models.Index(fields=["athlete", "status"]),
        ]

    def __str__(self):
        return f"{self.date} {self.time_slot} {self.title} - {self.athlete}"

    @property
    def session_load(self):
        """Foster sRPE 負荷 (AU) = RPE × 實際時長。"""
        if self.session_rpe and self.actual_duration_min:
            return self.session_rpe * self.actual_duration_min
        return 0

    @property
    def is_self_assigned(self):
        return self.assigned_by_id is None

    @property
    def total_track_volume_m(self):
        return sum(ts.total_volume_m for ts in self.track_sets.all())

    @property
    def total_tonnage_kg(self):
        return sum(ss.tonnage for ss in self.strength_sets.all())

    def activities_by_block(self):
        """回傳 [(區塊 value, 區塊名稱, [活動…]), …]，永遠四區都在（空的也在）。"""
        from training.models import BLOCK_ORDER, BlockType

        buckets = {b.value: [] for b in BLOCK_ORDER}
        for a in self.activities.select_related("created_by", "definition"):
            buckets.setdefault(a.block, []).append(a)
        return [
            (b.value, BlockType(b).label, buckets.get(b.value, []))
            for b in BLOCK_ORDER
        ]

    @property
    def activity_count(self):
        return self.activities.count()

    @property
    def avg_activity_satisfaction(self):
        agg = self.activities.aggregate(avg=models.Avg("satisfaction"))["avg"]
        return round(float(agg), 1) if agg else None

    @property
    def content_version(self):
        """課表內容的版本指紋：任何一格改動都會變，前端用它判斷要不要刷新。"""
        from training.models import SessionActivity

        stamps = [self.updated_at]
        for qs in (
            SessionActivity.objects.filter(session=self),
            SessionNote.objects.filter(session=self),
        ):
            agg = qs.aggregate(last=models.Max("updated_at"), n=models.Count("id"))
            if agg["last"]:
                stamps.append(agg["last"])
            stamps.append(agg["n"])
        return "-".join(
            str(int(s.timestamp() * 1000)) if hasattr(s, "timestamp") else str(s)
            for s in stamps
        )

    def mark_complete(self, duration_min, rpe, completion_pct=100, feedback=""):
        self.actual_duration_min = duration_min
        self.session_rpe = rpe
        self.completion_pct = completion_pct
        self.status = (
            SessionStatus.COMPLETED if completion_pct >= 90 else SessionStatus.PARTIAL
        )
        if feedback:
            self.athlete_feedback = feedback
        self.save()
        return self


class NoteKind(models.TextChoices):
    POINT = "POINT", "訓練要點"
    NOTE = "NOTE", "當日備注"
    FEEDBACK = "FEEDBACK", "訓練反饋"


class SessionNote(TimeStampedModel):
    """課表底下的共同記事：教練、運動員、管理員都寫在同一個版面。

    大家看得到彼此寫了什麼，但每一則只有作者本人（和管理員）改得動——
    權限判斷統一在 core.liveedit.can_edit 裡做。
    """

    session = models.ForeignKey(
        TrainingSession, on_delete=models.CASCADE, related_name="notes"
    )
    author = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="session_notes",
        verbose_name="寫入者",
    )
    kind = models.CharField(
        "類別", max_length=10, choices=NoteKind.choices, default=NoteKind.NOTE
    )
    body = models.TextField("內容")

    class Meta:
        verbose_name = "課表記事"
        verbose_name_plural = "課表記事"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.author} · {self.get_kind_display()}"


class SessionTemplate(TimeStampedModel):
    """教練可重用的課表模板，payload 存 drills/sets 結構。"""

    coach = models.ForeignKey(
        CoachProfile, on_delete=models.CASCADE, related_name="session_templates"
    )
    name = models.CharField("模板名稱", max_length=150)
    session_type = models.CharField("課別", max_length=20, choices=SessionType.choices)
    planned_duration_min = models.PositiveSmallIntegerField("計劃時長 (分)", default=90)
    description = models.TextField("課表內容", blank=True)
    payload = models.JSONField("結構化內容", default=dict, blank=True)

    class Meta:
        verbose_name = "課表模板"
        verbose_name_plural = "課表模板"
        ordering = ["name"]

    def __str__(self):
        return f"[{self.get_session_type_display()}] {self.name}"

    def clone_to_session(self, athlete, on_date, microcycle=None, time_slot="PM"):
        """把模板複製成一堂實際課（含 track_sets / strength_sets）。"""
        from training.models import Exercise, StrengthSet, TrackSet

        session = TrainingSession.objects.create(
            athlete=athlete,
            microcycle=microcycle,
            date=on_date,
            time_slot=time_slot,
            session_type=self.session_type,
            title=self.name,
            description=self.description,
            assigned_by=self.coach,
            planned_duration_min=self.planned_duration_min,
        )

        for i, item in enumerate(self.payload.get("track_sets", []), start=1):
            TrackSet.objects.create(session=session, order=i, **item)

        for i, item in enumerate(self.payload.get("strength_sets", []), start=1):
            data = dict(item)
            code = data.pop("exercise_code", None)
            exercise = Exercise.objects.filter(code=code).first() if code else None
            if exercise is None:
                continue
            StrengthSet.objects.create(session=session, exercise=exercise, order=i, **data)

        return session


class ProjectAssignment(TimeStampedModel):
    """把一個已有的報名項目（programs.Project）分配給教練。

    管理員在「計劃」頁面建立這筆關係之後，該教練登入時就會在同一頁
    看到自己被分配到的項目，點進去可以看到項目裡所有運動員的狀況。
    用獨立的表而不是 Project 上的 M2M，是因為要記錄「誰分配的、什麼時候、備註」。
    """

    project = models.ForeignKey(
        "programs.Project",
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name="報名項目",
    )
    coach = models.ForeignKey(
        CoachProfile,
        on_delete=models.CASCADE,
        related_name="project_assignments",
        verbose_name="負責教練",
    )
    assigned_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="project_assignments_made",
        verbose_name="分配者",
    )
    is_active = models.BooleanField("生效中", default=True)
    note = models.TextField("分配備註", blank=True, help_text="例：只負責短跑組、每週二四帶課")

    class Meta:
        verbose_name = "項目分配"
        verbose_name_plural = "項目分配"
        unique_together = ("project", "coach")
        ordering = ["project__display_order", "coach__user__username"]

    def __str__(self):
        return f"{self.project.title} → {self.coach}"


def project_athletes(project):
    """報名項目裡「已匯入 ATM」的運動員 queryset。"""
    from accounts.models import AthleteProfile

    return (
        AthleteProfile.objects.filter(applications__project=project)
        .select_related("user", "primary_event", "coach__user")
        .distinct()
    )


def projects_for(user):
    """依角色回傳這個使用者在「計劃」頁面看得到的報名項目。"""
    from programs.models import Project

    from core.models import Role

    qs = Project.objects.all().order_by("display_order", "-created_at")
    if not user.is_authenticated:
        return qs.none()
    if user.is_superuser or user.role == Role.ADMIN:
        return qs
    if user.role == Role.COACH:
        coach = getattr(user, "coach_profile", None)
        if coach is None:
            return qs.none()
        return qs.filter(assignments__coach=coach, assignments__is_active=True).distinct()
    # 運動員：只看得到自己有報名的項目
    return qs.filter(applications__athlete__user=user).distinct()

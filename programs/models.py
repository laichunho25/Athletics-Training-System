"""
公開報名模組：Project（訓練項目）+ Application（報名表）。

設計原則：
- Project 的內容欄位保持彈性（每個項目的日期／組別寫法都不同），
  但「是否開放」「報名期限」「名額」是結構化的，後台才控制得住。
- Application 收到的資料要能一鍵轉成 ATM 的 AthleteProfile，
  所以欄位盡量對齊 accounts.AthleteProfile。
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import AthleteProfile, Event
from core.models import EventCategory, Sex, TimeStampedModel


class ProjectStatus(models.TextChoices):
    DRAFT = "DRAFT", _("草稿（不公開）")
    OPEN = "OPEN", _("開放報名")
    CLOSED = "CLOSED", _("已截止")
    ARCHIVED = "ARCHIVED", _("已封存")


class ApplicationStatus(models.TextChoices):
    NEW = "NEW", _("待處理")
    CONFIRMED = "CONFIRMED", _("已確認")
    WAITLIST = "WAITLIST", _("候補")
    CANCELLED = "CANCELLED", _("已取消")


class Project(TimeStampedModel):
    """一個可供報名的訓練項目（課程／訓練營／測驗日）。"""

    slug = models.SlugField(_("網址代碼"), max_length=60, unique=True, help_text=_("例：dbsac-sc-2026"))
    title = models.CharField(_("項目名稱"), max_length=150)
    subtitle = models.CharField(_("副標"), max_length=200, blank=True)
    organiser = models.CharField(_("主辦"), max_length=100, blank=True, default="DBSAC")
    default_school_or_club = models.CharField(
        _("預設學校 / 體育會"),
        max_length=100,
        blank=True,
        help_text=_("報名表「學校 / 體育會」的預設值，留空＝沿用 DBSAC；報名者仍可自行修改"),
    )
    description = models.TextField(_("項目說明"), help_text=_("開頭段落，說明這個項目的背景與目的"))

    # ---- 時間與規模 ----
    schedule_text = models.CharField(
        _("上課時間"), max_length=200, blank=True, help_text=_("例：每週一，2026 年 9 月 9 日至 11 月 9 日")
    )
    start_date = models.DateField(_("開始日期"), null=True, blank=True)
    end_date = models.DateField(_("結束日期"), null=True, blank=True)
    session_count = models.PositiveSmallIntegerField(_("課堂數"), null=True, blank=True)
    group_note = models.CharField(
        _("分組方式"), max_length=200, blank=True, help_text=_("例：共 10 堂，分 2 組、每組 5 堂")
    )
    capacity_per_session = models.PositiveSmallIntegerField(_("每堂人數上限"), null=True, blank=True)
    capacity_total = models.PositiveSmallIntegerField(
        _("總名額"), null=True, blank=True, help_text=_("留空＝不限；額滿後新報名自動列為候補")
    )

    # ---- 內容與場地 ----
    trainer = models.CharField(_("教練"), max_length=100, blank=True)
    coaches = models.ManyToManyField(
        "accounts.CoachProfile",
        blank=True,
        related_name="coached_projects",
        verbose_name=_("負責教練"),
        help_text=_("這個計劃由哪些教練帶；同一名運動員在不同計劃可以由不同教練負責，每位負責教練都看得到他的狀態總覽"),
    )
    recommended_for = models.CharField(
        _("建議對象"), max_length=200, blank=True, help_text=_("例：短跑、跨欄及中距離運動員")
    )
    focus = models.TextField(_("訓練重點"), blank=True)
    venue_name = models.CharField(_("場地"), max_length=120, blank=True)
    venue_address = models.CharField(_("地址"), max_length=200, blank=True)
    venue_note = models.CharField(_("交通"), max_length=200, blank=True)

    # ---- 費用與條款 ----
    price_hkd = models.DecimalField(
        _("費用 (HK$)"), max_digits=8, decimal_places=2, null=True, blank=True
    )
    price_note = models.CharField(_("費用說明"), max_length=200, blank=True)
    important_note = models.TextField(_("重要事項"), blank=True, help_text=_("退款條款等，會以警示樣式顯示"))
    contact_note = models.CharField(
        _("查詢方式"), max_length=200, blank=True, help_text=_("例：WhatsApp +852 6531 2212")
    )

    # ---- 報名開關 ----
    status = models.CharField(
        _("狀態"), max_length=10, choices=ProjectStatus.choices, default=ProjectStatus.DRAFT
    )
    opens_at = models.DateTimeField(_("報名開始"), null=True, blank=True, help_text=_("留空＝立即開放"))
    closes_at = models.DateTimeField(_("報名截止"), null=True, blank=True, help_text=_("留空＝不設限"))
    display_order = models.SmallIntegerField(_("排序"), default=0, help_text=_("數字小的排前面"))

    class Meta:
        verbose_name = _("報名項目")
        verbose_name_plural = _("報名項目")
        ordering = ["display_order", "-start_date", "-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("programs:detail", args=[self.slug])

    # ---- 開放狀態 ----

    @property
    def is_public(self):
        """草稿與封存不在公開列表出現。"""
        return self.status in {ProjectStatus.OPEN, ProjectStatus.CLOSED}

    @property
    def is_full(self):
        if self.capacity_total is None:
            return False
        return self.confirmed_count >= self.capacity_total

    @property
    def confirmed_count(self):
        """佔用名額的報名：待處理與已確認都算，取消與候補不算。"""
        return self.applications.filter(
            status__in=[ApplicationStatus.NEW, ApplicationStatus.CONFIRMED]
        ).count()

    @property
    def seats_left(self):
        if self.capacity_total is None:
            return None
        return max(self.capacity_total - self.confirmed_count, 0)

    def accepting_reason(self, now=None):
        """回傳 (可否報名, 原因)——原因會直接顯示給使用者。"""
        now = now or timezone.now()
        if self.status != ProjectStatus.OPEN:
            return False, "此項目目前不接受報名"
        if self.opens_at and now < self.opens_at:
            return False, f"報名將於 {timezone.localtime(self.opens_at):%Y 年 %m 月 %d 日} 開始"
        if self.closes_at and now > self.closes_at:
            return False, "報名已經截止"
        return True, ""

    @property
    def is_accepting(self):
        return self.accepting_reason()[0]


class Application(TimeStampedModel):
    """一份報名表。額滿時仍可送出，但會被標記為候補。"""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="applications", verbose_name=_("報名項目")
    )

    # ---- 個人資料 ----
    name_en = models.CharField(_("英文姓名"), max_length=100)
    name_zh = models.CharField(_("中文姓名"), max_length=60, blank=True)
    sex = models.CharField(_("性別"), max_length=1, choices=Sex.choices)
    birth_date = models.DateField(_("出生日期"))
    phone = models.CharField(_("聯絡電話 / WhatsApp"), max_length=30)
    email = models.EmailField(_("電郵"))
    school_or_club = models.CharField(
        _("學校 / 體育會"),
        max_length=100,
        default="DBSAC",
        help_text=_("預設為 DBSAC，教練可在後台修改"),
    )
    graduation_year = models.PositiveSmallIntegerField(
        _("學校畢業年份"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1950), MaxValueValidator(2100)],
        help_text=_("預計或實際的中學畢業年份"),
    )

    # ---- 運動背景 ----
    has_track_training = models.BooleanField(
        _("現正參與田徑訓練"), default=True, help_text=_("目前有恆常隊際或個人田徑訓練")
    )
    event_category = models.CharField(
        _("項目分類"), max_length=15, choices=EventCategory.choices, default=EventCategory.SPRINT
    )
    primary_event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applications",
        verbose_name=_("主項"),
    )
    personal_best = models.CharField(
        _("個人最佳成績"), max_length=100, blank=True, help_text=_("例：100m 11.42（2026 年 4 月）")
    )
    training_years = models.DecimalField(
        _("田徑訓練年資 (年)"), max_digits=4, decimal_places=1, default=0
    )
    training_days_per_week = models.PositiveSmallIntegerField(
        _("每週訓練日數"), default=4, validators=[MinValueValidator(0), MaxValueValidator(14)]
    )
    strength_experience_years = models.DecimalField(
        _("重量訓練年資 (年)"), max_digits=4, decimal_places=1, default=0
    )
    current_coach = models.CharField(_("現任教練"), max_length=100, blank=True)

    # ---- KYC / 健康申報 ----
    height_cm = models.DecimalField(_("身高 (cm)"), max_digits=5, decimal_places=1)
    weight_kg = models.DecimalField(_("體重 (kg)"), max_digits=5, decimal_places=1)
    emergency_contact_name = models.CharField(_("緊急聯絡人"), max_length=100)
    emergency_contact_phone = models.CharField(_("緊急聯絡電話"), max_length=30)
    emergency_contact_relation = models.CharField(_("關係"), max_length=40, blank=True)
    has_current_injury = models.BooleanField(_("目前有傷患或痛症"), default=False)
    injury_detail = models.TextField(_("傷患描述"), blank=True, help_text=_("部位、發生時間、目前狀況"))
    injury_history = models.TextField(_("過往重大傷患"), blank=True)
    medical_conditions = models.TextField(
        _("長期病患"), blank=True, help_text=_("哮喘、心臟／血壓問題、癲癇等")
    )
    medications = models.CharField(_("長期服用藥物"), max_length=200, blank=True)
    allergies = models.CharField(_("敏感 / 過敏"), max_length=200, blank=True)
    doctor_clearance = models.BooleanField(
        _("已取得醫生許可參與訓練"), default=True, help_text=_("若有長期病患或傷患，須先諮詢醫生")
    )
    health_declaration = models.BooleanField(_("健康申報屬實"), default=False)
    consent_terms = models.BooleanField(_("已閱讀並同意項目條款（包括不設退款）"), default=False)
    consent_data = models.BooleanField(_("同意資料用於訓練管理與聯絡"), default=False)
    remarks = models.TextField(_("其他想讓教練知道的事"), blank=True)

    # ---- 後台處理 ----
    status = models.CharField(
        _("處理狀態"), max_length=10, choices=ApplicationStatus.choices, default=ApplicationStatus.NEW
    )
    internal_note = models.TextField(_("內部備註"), blank=True, help_text=_("只有後台看得到"))
    athlete = models.ForeignKey(
        AthleteProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applications",
        verbose_name=_("已匯入的運動員"),
        help_text=_("同一名運動員可以報多個項目，全部報名表都指向同一份檔案"),
    )
    imported_at = models.DateTimeField(_("匯入 ATM 時間"), null=True, blank=True)

    class Meta:
        verbose_name = _("報名表")
        verbose_name_plural = _("報名表")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "email"], name="unique_application_per_project_email"
            )
        ]

    def __str__(self):
        return f"{self.name_en}／{self.project.title}"

    @property
    def full_name(self):
        return f"{self.name_en}（{self.name_zh}）" if self.name_zh else self.name_en

    @property
    def age(self):
        today = timezone.localdate()
        return (
            today.year
            - self.birth_date.year
            - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        )

    @property
    def is_minor(self):
        return self.age < 18

    @property
    def is_imported(self):
        return self.athlete_id is not None

    # ---- 重複登記檢查 ----

    @property
    def existing_athlete(self):
        """尚未匯入時：用全名／出生日期／電郵找出已在其他計劃登記過的檔案。"""
        from programs.services import find_existing_athlete

        if self.athlete_id:
            return None
        match = find_existing_athlete(self)
        return match.athlete if match else None

    @property
    def match_summary(self):
        """已註冊運動員的比對理由，例：「電郵、出生日期相符」。"""
        from programs.services import describe_match, find_existing_athlete

        if self.athlete_id:
            return ""
        match = find_existing_athlete(self)
        return describe_match(match) if match else ""

    @property
    def is_returning_athlete(self):
        """這份報名屬於「已註冊運動員」——匯入前是比對出來的，匯入後看檔案是否本來就在。"""
        if self.athlete_id:
            athlete = self.athlete
            if athlete.created_at < self.created_at:
                return True
            return athlete.applications.exclude(pk=self.pk).exists()
        return self.existing_athlete is not None

    @property
    def health_flags(self):
        """後台一眼看出要不要跟進的紅旗。"""
        flags = []
        if self.has_current_injury:
            flags.append("現有傷患")
        if self.medical_conditions.strip():
            flags.append("長期病患")
        if not self.doctor_clearance:
            flags.append("未取得醫生許可")
        return flags

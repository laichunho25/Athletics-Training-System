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

from accounts.models import AthleteProfile, Event
from core.models import EventCategory, Sex, TimeStampedModel


class ProjectStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿（不公開）"
    OPEN = "OPEN", "開放報名"
    CLOSED = "CLOSED", "已截止"
    ARCHIVED = "ARCHIVED", "已封存"


class ApplicationStatus(models.TextChoices):
    NEW = "NEW", "待處理"
    CONFIRMED = "CONFIRMED", "已確認"
    WAITLIST = "WAITLIST", "候補"
    CANCELLED = "CANCELLED", "已取消"


class Project(TimeStampedModel):
    """一個可供報名的訓練項目（課程／訓練營／測驗日）。"""

    slug = models.SlugField("網址代碼", max_length=60, unique=True, help_text="例：dbsac-sc-2026")
    title = models.CharField("項目名稱", max_length=150)
    subtitle = models.CharField("副標", max_length=200, blank=True)
    organiser = models.CharField("主辦", max_length=100, blank=True, default="DBSAC")
    default_school_or_club = models.CharField(
        "預設學校 / 體育會",
        max_length=100,
        blank=True,
        help_text="報名表「學校 / 體育會」的預設值，留空＝沿用 DBSAC；報名者仍可自行修改",
    )
    description = models.TextField("項目說明", help_text="開頭段落，說明這個項目的背景與目的")

    # ---- 時間與規模 ----
    schedule_text = models.CharField(
        "上課時間", max_length=200, blank=True, help_text="例：每週一，2026 年 9 月 9 日至 11 月 9 日"
    )
    start_date = models.DateField("開始日期", null=True, blank=True)
    end_date = models.DateField("結束日期", null=True, blank=True)
    session_count = models.PositiveSmallIntegerField("課堂數", null=True, blank=True)
    group_note = models.CharField(
        "分組方式", max_length=200, blank=True, help_text="例：共 10 堂，分 2 組、每組 5 堂"
    )
    capacity_per_session = models.PositiveSmallIntegerField("每堂人數上限", null=True, blank=True)
    capacity_total = models.PositiveSmallIntegerField(
        "總名額", null=True, blank=True, help_text="留空＝不限；額滿後新報名自動列為候補"
    )

    # ---- 內容與場地 ----
    trainer = models.CharField("教練", max_length=100, blank=True)
    recommended_for = models.CharField(
        "建議對象", max_length=200, blank=True, help_text="例：短跑、跨欄及中距離運動員"
    )
    focus = models.TextField("訓練重點", blank=True)
    venue_name = models.CharField("場地", max_length=120, blank=True)
    venue_address = models.CharField("地址", max_length=200, blank=True)
    venue_note = models.CharField("交通", max_length=200, blank=True)

    # ---- 費用與條款 ----
    price_hkd = models.DecimalField(
        "費用 (HK$)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    price_note = models.CharField("費用說明", max_length=200, blank=True)
    important_note = models.TextField("重要事項", blank=True, help_text="退款條款等，會以警示樣式顯示")
    contact_note = models.CharField(
        "查詢方式", max_length=200, blank=True, help_text="例：WhatsApp +852 6531 2212"
    )

    # ---- 報名開關 ----
    status = models.CharField(
        "狀態", max_length=10, choices=ProjectStatus.choices, default=ProjectStatus.DRAFT
    )
    opens_at = models.DateTimeField("報名開始", null=True, blank=True, help_text="留空＝立即開放")
    closes_at = models.DateTimeField("報名截止", null=True, blank=True, help_text="留空＝不設限")
    display_order = models.SmallIntegerField("排序", default=0, help_text="數字小的排前面")

    class Meta:
        verbose_name = "報名項目"
        verbose_name_plural = "報名項目"
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
        Project, on_delete=models.CASCADE, related_name="applications", verbose_name="報名項目"
    )

    # ---- 個人資料 ----
    name_en = models.CharField("英文姓名", max_length=100)
    name_zh = models.CharField("中文姓名", max_length=60, blank=True)
    sex = models.CharField("性別", max_length=1, choices=Sex.choices)
    birth_date = models.DateField("出生日期")
    phone = models.CharField("聯絡電話 / WhatsApp", max_length=30)
    email = models.EmailField("電郵")
    school_or_club = models.CharField(
        "學校 / 體育會",
        max_length=100,
        default="DBSAC",
        help_text="預設為 DBSAC，教練可在後台修改",
    )
    graduation_year = models.PositiveSmallIntegerField(
        "學校畢業年份",
        null=True,
        blank=True,
        validators=[MinValueValidator(1950), MaxValueValidator(2100)],
        help_text="預計或實際的中學畢業年份",
    )

    # ---- 運動背景 ----
    has_track_training = models.BooleanField(
        "現正參與田徑訓練", default=True, help_text="目前有恆常隊際或個人田徑訓練"
    )
    event_category = models.CharField(
        "項目分類", max_length=15, choices=EventCategory.choices, default=EventCategory.SPRINT
    )
    primary_event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applications",
        verbose_name="主項",
    )
    personal_best = models.CharField(
        "個人最佳成績", max_length=100, blank=True, help_text="例：100m 11.42（2026 年 4 月）"
    )
    training_years = models.DecimalField(
        "田徑訓練年資 (年)", max_digits=4, decimal_places=1, default=0
    )
    training_days_per_week = models.PositiveSmallIntegerField(
        "每週訓練日數", default=4, validators=[MinValueValidator(0), MaxValueValidator(14)]
    )
    strength_experience_years = models.DecimalField(
        "重量訓練年資 (年)", max_digits=4, decimal_places=1, default=0
    )
    current_coach = models.CharField("現任教練", max_length=100, blank=True)

    # ---- KYC / 健康申報 ----
    height_cm = models.DecimalField("身高 (cm)", max_digits=5, decimal_places=1)
    weight_kg = models.DecimalField("體重 (kg)", max_digits=5, decimal_places=1)
    emergency_contact_name = models.CharField("緊急聯絡人", max_length=100)
    emergency_contact_phone = models.CharField("緊急聯絡電話", max_length=30)
    emergency_contact_relation = models.CharField("關係", max_length=40, blank=True)
    has_current_injury = models.BooleanField("目前有傷患或痛症", default=False)
    injury_detail = models.TextField("傷患描述", blank=True, help_text="部位、發生時間、目前狀況")
    injury_history = models.TextField("過往重大傷患", blank=True)
    medical_conditions = models.TextField(
        "長期病患", blank=True, help_text="哮喘、心臟／血壓問題、癲癇等"
    )
    medications = models.CharField("長期服用藥物", max_length=200, blank=True)
    allergies = models.CharField("敏感 / 過敏", max_length=200, blank=True)
    doctor_clearance = models.BooleanField(
        "已取得醫生許可參與訓練", default=True, help_text="若有長期病患或傷患，須先諮詢醫生"
    )
    health_declaration = models.BooleanField("健康申報屬實", default=False)
    consent_terms = models.BooleanField("已閱讀並同意項目條款（包括不設退款）", default=False)
    consent_data = models.BooleanField("同意資料用於訓練管理與聯絡", default=False)
    remarks = models.TextField("其他想讓教練知道的事", blank=True)

    # ---- 後台處理 ----
    status = models.CharField(
        "處理狀態", max_length=10, choices=ApplicationStatus.choices, default=ApplicationStatus.NEW
    )
    internal_note = models.TextField("內部備註", blank=True, help_text="只有後台看得到")
    athlete = models.OneToOneField(
        AthleteProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="application",
        verbose_name="已匯入的運動員",
    )
    imported_at = models.DateTimeField("匯入 ATM 時間", null=True, blank=True)

    class Meta:
        verbose_name = "報名表"
        verbose_name_plural = "報名表"
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

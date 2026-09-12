"""後台 Accounts 區塊。

刻意只留四張表：管理員（帳號）、教練檔案、田徑項目、運動員檔案。
個人最佳與體測紀錄改成掛在運動員檔案底下的 inline——資料還是編得到，
但後台首頁不會再被一堆明細表塞滿。
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from accounts.models import (
    AthleteProfile,
    BodyMetricLog,
    CoachProfile,
    Event,
    PersonalBest,
    User,
)
from programs.models import Application


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "full_name", "role", "email", "is_active", "is_superuser")
    list_filter = ("role", "is_active", "is_superuser")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("role", "username")
    fieldsets = BaseUserAdmin.fieldsets + (("ATM", {"fields": ("role", "phone", "avatar")}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("ATM", {"fields": ("role", "first_name", "last_name", "email")}),
    )

    @admin.display(description=_("姓名"), ordering="first_name")
    def full_name(self, obj):
        return obj.get_full_name() or "—"


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("code", "name_zh", "name_en", "category", "unit", "distance_m")
    list_filter = ("category", "unit")
    search_fields = ("code", "name_zh", "name_en")
    list_per_page = 50


@admin.register(CoachProfile)
class CoachProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "squad_name", "specialties", "years_of_experience", "athlete_count")
    search_fields = ("user__username", "user__first_name", "user__last_name", "squad_name")
    autocomplete_fields = ["user"]


class PersonalBestInline(admin.TabularInline):
    model = PersonalBest
    extra = 0
    fields = ("event", "mark", "wind", "date", "competition_name", "is_current")
    autocomplete_fields = ["event"]
    verbose_name = _("個人最佳")
    verbose_name_plural = _("個人最佳")


class BodyMetricLogInline(admin.TabularInline):
    model = BodyMetricLog
    extra = 0
    fields = (
        "date",
        "brand",
        "weight_kg",
        "body_fat_pct",
        "muscle_mass_kg",
        "body_water_pct",
        "visceral_fat_level",
        "bmr_kcal",
        "source",
    )
    ordering = ("-date",)
    verbose_name = _("體組成紀錄")
    verbose_name_plural = _("體組成紀錄")


class ProjectApplicationInline(admin.TabularInline):
    """這名運動員參加過的報名項目——已註冊運動員報新項目時，這裡會多一列。"""

    model = Application
    extra = 0
    can_delete = False
    fields = ("project", "status", "school_or_club", "created_at", "imported_at")
    readonly_fields = fields
    show_change_link = True
    verbose_name = _("報名項目")
    verbose_name_plural = _("參加中的項目")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AthleteProfile)
class AthleteProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user", "age", "sex", "primary_event", "coach", "status", "height_cm", "weight_kg",
        "video_plan", "video_usage",
    )
    list_filter = ("coach", "status", "sex", "primary_event", "video_plan")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ["user", "primary_event"]
    filter_horizontal = ("secondary_events",)
    inlines = [ProjectApplicationInline, PersonalBestInline, BodyMetricLogInline]
    fieldsets = (
        (_("帳號與教練"), {"fields": ("user", "coach", "status")}),
        (_("基本資料"), {"fields": (("birth_date", "sex"), ("height_cm", "weight_kg"), "school_or_club")}),
        (_("項目"), {"fields": ("primary_event", "secondary_events")}),
        (_("訓練背景"), {"fields": (("training_days_per_week", "strength_experience_years"), "notes")}),
        (_("影片額度"), {
            "fields": ("video_plan", ("video_max_videos", "video_max_mb")),
            "description": _(
                "兩個上限留空就跟方案走（方案的預設值在「影片額度設定」那一頁改）；"
                "填了就是只給這位運動員的特例。條數與容量兩道閘都要過。"
            ),
        }),
    )

    def get_queryset(self, request):
        """用量在清單上是一欄，所以要一次 annotate 出來。

        逐列呼叫 `quota_for` 的話，一百個運動員就是兩百次查詢——這一頁是後台
        最常開的一張表，不值得為了一欄數字慢成那樣。
        """
        from django.db.models import Count, Sum

        return super().get_queryset(request).annotate(
            _video_n=Count("videos", distinct=True),
            _video_b=Sum("videos__size_bytes"),
        )

    @admin.display(description=_("影片用量"), ordering="_video_b")
    def video_usage(self, obj):
        from video.models import VideoQuotaConfig

        # 每一列都讀一次設定表沒意義，整張清單共用同一份
        if not hasattr(self, "_quota_config"):
            self._quota_config = VideoQuotaConfig.load()
        max_videos, max_bytes, _days = self._quota_config.limits_for(obj.video_plan)
        if obj.video_max_videos is not None:
            max_videos = obj.video_max_videos
        if obj.video_max_mb is not None:
            max_bytes = obj.video_max_mb * 1024 * 1024

        count = f"{obj._video_n}/{max_videos}" if max_videos else f"{obj._video_n}/∞"
        used_mb = (obj._video_b or 0) / 1024 / 1024
        size = f"{used_mb:.0f}/{max_bytes / 1024 / 1024:.0f} MB" if max_bytes else f"{used_mb:.0f} MB"
        return f"{count} 條 · {size}"

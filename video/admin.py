from django.contrib import admin, messages

from django.utils.translation import gettext_lazy as _

from video.models import (
    PlanUpgradeRequest,
    TrainingVideo,
    UpgradeStatus,
    VideoNote,
    VideoQuotaConfig,
)


class VideoNoteInline(admin.TabularInline):
    model = VideoNote
    extra = 0
    fields = ("at_sec", "body", "author")


@admin.register(TrainingVideo)
class TrainingVideoAdmin(admin.ModelAdmin):
    list_display = (
        "athlete", "date", "kind", "display_title", "duration_display",
        "size_display", "is_keeper", "uploaded_by",
    )
    list_filter = ("kind", "is_keeper", "athlete")
    search_fields = ("title", "note")
    date_hierarchy = "date"
    autocomplete_fields = ()
    raw_id_fields = ("record", "activity")
    inlines = [VideoNoteInline]

    def delete_queryset(self, request, queryset):
        """後台批次刪除也要把實體檔案收掉，否則 R2 會留下一堆孤兒物件。"""
        for video in queryset:
            video.drop_file()
        super().delete_queryset(request, queryset)

    def delete_model(self, request, obj):
        obj.drop_file()
        super().delete_model(request, obj)


@admin.register(VideoNote)
class VideoNoteAdmin(admin.ModelAdmin):
    list_display = ("video", "at_display", "body", "author", "created_at")
    list_filter = ("author",)
    search_fields = ("body",)


@admin.register(VideoQuotaConfig)
class VideoQuotaConfigAdmin(admin.ModelAdmin):
    """只有一行的設定表——後台把「新增」與「刪除」都收起來，只留「修改」。"""

    fieldsets = (
        (_("免費方案"), {"fields": ("free_max_videos", "free_max_mb", "free_retain_days")}),
        (_("進階會員"), {"fields": ("pro_max_videos", "pro_max_mb", "pro_retain_days")}),
    )

    def has_add_permission(self, request):
        return not VideoQuotaConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        """點進「影片額度設定」直接開那一行，不要先看一張只有一列的清單。"""
        from django.shortcuts import redirect
        from django.urls import reverse

        config = VideoQuotaConfig.load()
        return redirect(
            reverse("admin:video_videoquotaconfig_change", args=[config.pk])
        )


@admin.register(PlanUpgradeRequest)
class PlanUpgradeRequestAdmin(admin.ModelAdmin):
    """想升級的人排的隊。

    收錢發生在系統外面（電話／WhatsApp），所以這一頁的工作流程是：
    看到「待聯絡」→ 打電話收錢 → 回來選「開通進階會員」。
    「開通」會直接把運動員的 `video_plan` 翻成進階，不用再去 accounts 那邊改。
    """

    list_display = ("athlete", "status", "current_plan", "contact_display", "note",
                    "created_at", "handled_by")
    list_filter = ("status",)
    search_fields = (
        "athlete__user__username", "athlete__user__first_name",
        "athlete__user__last_name", "contact", "note",
    )
    date_hierarchy = "created_at"
    actions = ["approve_selected", "decline_selected"]
    readonly_fields = ("athlete", "requested_by", "contact", "note",
                       "handled_by", "handled_at", "created_at")
    fieldsets = (
        (_("申請內容"), {"fields": ("athlete", "requested_by", "contact", "note", "created_at")}),
        (_("處理"), {"fields": ("status", "admin_note", "handled_by", "handled_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "athlete__user", "requested_by", "handled_by"
        )

    def has_add_permission(self, request):
        """申請一律由運動員在影片庫按出來，後台不代開——代開就沒有申請人了。"""
        return False

    @admin.display(description=_("目前方案"))
    def current_plan(self, obj):
        return obj.athlete.get_video_plan_display()

    @admin.display(description=_("聯絡方式"))
    def contact_display(self, obj):
        return obj.contact_display

    @admin.action(description=_("開通進階會員（收到費用之後才按）"))
    def approve_selected(self, request, queryset):
        done = 0
        for req in queryset.exclude(status=UpgradeStatus.APPROVED):
            req.approve(request.user)
            done += 1
        self.message_user(
            request, _("已開通 %(v0)s 位運動員的進階會員。") % {"v0": done}, messages.SUCCESS
        )

    @admin.action(description=_("婉拒"))
    def decline_selected(self, request, queryset):
        for req in queryset.filter(status=UpgradeStatus.NEW):
            req.decline(request.user)

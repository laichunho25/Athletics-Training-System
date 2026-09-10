from django.contrib import admin

from video.models import TrainingVideo, VideoNote


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

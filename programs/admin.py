"""後台：建立項目、控制開放與否、審視報名資料、一鍵匯入 ATM。"""

import csv

from django.contrib import admin, messages
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from programs.models import Application, ApplicationStatus, Project, ProjectStatus
from programs.services import ImportError_, import_application


class ApplicationInline(admin.TabularInline):
    model = Application
    extra = 0
    can_delete = False
    fields = ("name_en", "school_or_club", "event_category", "status", "flags", "created_at")
    readonly_fields = fields
    show_change_link = True

    def flags(self, obj):
        return "、".join(obj.health_flags) or "—"

    flags.short_description = "需留意"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "title", "status", "open_window", "seats", "application_count", "public_link",
    )
    list_filter = ("status", "organiser")
    search_fields = ("title", "slug", "description")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ApplicationInline]
    actions = ["open_enrollment", "close_enrollment"]
    fieldsets = (
        (
            "基本資料",
            {"fields": ("title", "subtitle", "slug", "organiser", "default_school_or_club", "description")},
        ),
        (
            "時間與規模",
            {
                "fields": (
                    "schedule_text", ("start_date", "end_date"),
                    ("session_count", "group_note"),
                    ("capacity_per_session", "capacity_total"),
                )
            },
        ),
        (
            "內容與場地",
            {"fields": ("trainer", "recommended_for", "focus", "venue_name", "venue_address", "venue_note")},
        ),
        ("費用與條款", {"fields": (("price_hkd", "price_note"), "important_note", "contact_note")}),
        (
            "報名開關",
            {
                "fields": ("status", ("opens_at", "closes_at"), "display_order"),
                "description": "狀態設為「開放報名」且在時間範圍內，公開網站才會出現報名按鈕。",
            },
        ),
    )

    @admin.display(description="報名期間")
    def open_window(self, obj):
        start = f"{obj.opens_at:%Y-%m-%d}" if obj.opens_at else "即時"
        end = f"{obj.closes_at:%Y-%m-%d}" if obj.closes_at else "不設限"
        return f"{start} → {end}"

    @admin.display(description="名額")
    def seats(self, obj):
        if obj.capacity_total is None:
            return f"{obj.confirmed_count} 人（不限）"
        return f"{obj.confirmed_count} / {obj.capacity_total}"

    @admin.display(description="報名數")
    def application_count(self, obj):
        url = reverse("admin:programs_application_changelist")
        return format_html(
            '<a href="{}?project__id__exact={}">{} 份</a>',
            url, obj.pk, obj.applications.count(),
        )

    @admin.display(description="公開頁")
    def public_link(self, obj):
        return format_html('<a href="{}" target="_blank">開啟</a>', obj.get_absolute_url())

    @admin.action(description="開放報名")
    def open_enrollment(self, request, queryset):
        n = queryset.update(status=ProjectStatus.OPEN)
        self.message_user(request, f"已開放 {n} 個項目的報名。")

    @admin.action(description="關閉報名")
    def close_enrollment(self, request, queryset):
        n = queryset.update(status=ProjectStatus.CLOSED)
        self.message_user(request, f"已關閉 {n} 個項目的報名。")


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "name_en", "project", "school_or_club", "event_category",
        "age_display", "flags", "status", "imported", "created_at",
    )
    list_filter = (
        "project", "status", "event_category", "has_track_training",
        "has_current_injury", "sex",
    )
    search_fields = ("name_en", "name_zh", "email", "phone", "school_or_club")
    list_editable = ("status",)
    date_hierarchy = "created_at"
    actions = ["import_to_atm", "mark_confirmed", "mark_waitlist", "export_csv"]
    autocomplete_fields = ["primary_event"]
    readonly_fields = (
        "created_at", "updated_at", "imported_at", "athlete", "summary_card",
    )
    fieldsets = (
        ("摘要", {"fields": ("summary_card",)}),
        ("報名項目", {"fields": ("project",)}),
        (
            "個人資料",
            {
                "fields": (
                    ("name_en", "name_zh"), ("sex", "birth_date"),
                    ("phone", "email"), ("school_or_club", "graduation_year"),
                )
            },
        ),
        (
            "運動背景",
            {
                "fields": (
                    "has_track_training", ("event_category", "primary_event"),
                    "personal_best",
                    ("training_years", "training_days_per_week", "strength_experience_years"),
                    "current_coach",
                )
            },
        ),
        (
            "身體狀況與緊急聯絡",
            {
                "fields": (
                    ("height_cm", "weight_kg"),
                    ("emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation"),
                    "has_current_injury", "injury_detail", "injury_history",
                    "medical_conditions", "medications", "allergies", "doctor_clearance",
                )
            },
        ),
        (
            "聲明",
            {"fields": ("health_declaration", "consent_terms", "consent_data", "remarks")},
        ),
        (
            "後台處理",
            {"fields": ("status", "internal_note", "athlete", "imported_at", "created_at", "updated_at")},
        ),
    )

    @admin.display(description="年齡")
    def age_display(self, obj):
        return f"{obj.age} 歲{'（未成年）' if obj.is_minor else ''}"

    @admin.display(description="需留意")
    def flags(self, obj):
        if not obj.health_flags:
            return "—"
        return format_html(
            '<span style="color:#b3261e;font-weight:600">{}</span>',
            "、".join(obj.health_flags),
        )

    @admin.display(description="已匯入 ATM", boolean=True)
    def imported(self, obj):
        return obj.is_imported

    @admin.display(description="報名摘要")
    def summary_card(self, obj):
        if obj.pk is None:
            return "—"
        rows = [
            ("姓名", obj.full_name),
            ("年齡", f"{obj.age} 歲（{obj.birth_date:%Y-%m-%d}）"),
            ("學校 / 體育會", f"{obj.school_or_club}｜畢業年份 {obj.graduation_year or '未填'}"),
            ("田徑訓練", "有" if obj.has_track_training else "沒有"),
            (
                "項目",
                f"{obj.get_event_category_display()}"
                + (f"｜{obj.primary_event}" if obj.primary_event else ""),
            ),
            ("年資", f"田徑 {obj.training_years} 年｜重訓 {obj.strength_experience_years} 年"),
            ("身型", f"{obj.height_cm} cm / {obj.weight_kg} kg"),
            (
                "緊急聯絡",
                f"{obj.emergency_contact_name} {obj.emergency_contact_phone}"
                f"（{obj.emergency_contact_relation or '—'}）",
            ),
            ("需留意", "、".join(obj.health_flags) or "無"),
        ]
        if obj.athlete_id:
            url = reverse("admin:accounts_athleteprofile_change", args=[obj.athlete_id])
            rows.append(("ATM 檔案", format_html('<a href="{}">{}</a>', url, obj.athlete)))
        # 值來自報名者輸入，一律走 format_html 轉義（已是 SafeString 的連結不受影響）
        body = format_html_join(
            "",
            '<tr><th style="text-align:left;padding:4px 16px 4px 0;white-space:nowrap;'
            'color:#666">{}</th><td style="padding:4px 0">{}</td></tr>',
            rows,
        )
        return format_html('<table style="border-collapse:collapse">{}</table>', body)

    @admin.action(description="匯入 ATM，建立運動員檔案")
    def import_to_atm(self, request, queryset):
        created = skipped = 0
        for application in queryset:
            if application.is_imported:
                skipped += 1
                continue
            try:
                athlete = import_application(application)
            except ImportError_ as exc:
                self.message_user(request, f"{application.name_en}：{exc}", messages.ERROR)
                continue
            created += 1
            self.message_user(
                request,
                f"已建立運動員 {athlete}（帳號 {athlete.user.username}，"
                f"密碼為隨機值，請用後台的『重設密碼』給對方）。",
                messages.SUCCESS,
            )
        if skipped:
            self.message_user(request, f"{skipped} 份報名先前已匯入，略過。", messages.WARNING)
        if not created and not skipped:
            self.message_user(request, "沒有任何報名被匯入。", messages.WARNING)

    @admin.action(description="匯出 CSV")
    def export_csv(self, request, queryset):
        columns = [
            ("報名時間", lambda a: f"{a.created_at:%Y-%m-%d %H:%M}"),
            ("項目", lambda a: a.project.title),
            ("狀態", lambda a: a.get_status_display()),
            ("英文姓名", lambda a: a.name_en),
            ("中文姓名", lambda a: a.name_zh),
            ("性別", lambda a: a.get_sex_display()),
            ("出生日期", lambda a: a.birth_date),
            ("年齡", lambda a: a.age),
            ("電話", lambda a: a.phone),
            ("電郵", lambda a: a.email),
            ("學校/體育會", lambda a: a.school_or_club),
            ("畢業年份", lambda a: a.graduation_year or ""),
            ("有田徑訓練", lambda a: "是" if a.has_track_training else "否"),
            ("項目分類", lambda a: a.get_event_category_display()),
            ("主項", lambda a: a.primary_event or ""),
            ("個人最佳", lambda a: a.personal_best),
            ("田徑年資", lambda a: a.training_years),
            ("每週訓練日", lambda a: a.training_days_per_week),
            ("重訓年資", lambda a: a.strength_experience_years),
            ("現任教練", lambda a: a.current_coach),
            ("身高", lambda a: a.height_cm),
            ("體重", lambda a: a.weight_kg),
            ("緊急聯絡人", lambda a: a.emergency_contact_name),
            ("緊急聯絡電話", lambda a: a.emergency_contact_phone),
            ("關係", lambda a: a.emergency_contact_relation),
            ("現有傷患", lambda a: a.injury_detail if a.has_current_injury else ""),
            ("過往傷患", lambda a: a.injury_history),
            ("長期病患", lambda a: a.medical_conditions),
            ("藥物", lambda a: a.medications),
            ("敏感", lambda a: a.allergies),
            ("醫生許可", lambda a: "是" if a.doctor_clearance else "否"),
            ("備註", lambda a: a.remarks),
            ("已匯入 ATM", lambda a: "是" if a.is_imported else "否"),
        ]
        response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = 'attachment; filename="applications.csv"'
        response.write("﻿")  # 讓 Excel 正確辨識 UTF-8
        writer = csv.writer(response)
        writer.writerow([label for label, _ in columns])
        for application in queryset.select_related("project", "primary_event"):
            writer.writerow([getter(application) for _, getter in columns])
        return response

    @admin.action(description="標記為已確認")
    def mark_confirmed(self, request, queryset):
        n = queryset.update(status=ApplicationStatus.CONFIRMED)
        self.message_user(request, f"已確認 {n} 份報名。")

    @admin.action(description="標記為候補")
    def mark_waitlist(self, request, queryset):
        n = queryset.update(status=ApplicationStatus.WAITLIST)
        self.message_user(request, f"已將 {n} 份報名列為候補。")

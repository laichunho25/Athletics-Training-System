"""後台：建立項目、控制開放與否、審視報名資料、一鍵匯入 ATM。"""

import csv

from django.contrib import admin, messages
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext as _

from programs.models import Application, ApplicationStatus, Project, ProjectStatus
from programs.services import (
    ImportError_,
    describe_match,
    find_existing_athlete,
    find_existing_athletes,
    import_application,
)


def registered_badge(application, matches=None):
    """報名名單上的「已註冊運動員」標記：匯入前是比對結果，匯入後是實際檔案。"""
    if application.athlete_id:
        if not application.is_returning_athlete:
            return format_html('<span style="color:#1b7f3b">{}</span>', _("新運動員"))
        url = reverse("admin:accounts_athleteprofile_change", args=[application.athlete_id])
        return format_html(
            _('<a href="{}" style="color:#0b5cad;font-weight:600">已註冊運動員</a><div style="color:#666;font-size:11px">沿用原有檔案</div>'),
            url,
        )

    match = matches.get(application.pk) if matches is not None else find_existing_athlete(application)
    if not match:
        return format_html('<span style="color:#999">{}</span>', "—")
    url = reverse("admin:accounts_athleteprofile_change", args=[match.athlete.pk])
    return format_html(
        _('<a href="{}" style="color:#b26a00;font-weight:600">已註冊運動員</a><div style="color:#666;font-size:11px">{}｜{}</div>'),
        url, match.athlete, describe_match(match),
    )


class ApplicationInline(admin.TabularInline):
    model = Application
    extra = 0
    can_delete = False
    fields = (
        "name_en", "school_or_club", "event_category", "status", "registered", "flags",
        "created_at",
    )
    readonly_fields = fields
    show_change_link = True

    def flags(self, obj):
        return "、".join(obj.health_flags) or "—"

    flags.short_description = _("需留意")

    @admin.display(description=_("重複登記"))
    def registered(self, obj):
        return registered_badge(obj)

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
    filter_horizontal = ("coaches",)
    inlines = [ApplicationInline]
    actions = ["open_enrollment", "close_enrollment"]
    fieldsets = (
        (
            _("基本資料"),
            {"fields": ("title", "subtitle", "slug", "organiser", "default_school_or_club", "description", "coaches")},
        ),
        (
            _("時間與規模"),
            {
                "fields": (
                    "schedule_text", ("start_date", "end_date"),
                    ("session_count", "group_note"),
                    ("capacity_per_session", "capacity_total"),
                )
            },
        ),
        (
            _("內容與場地"),
            {"fields": ("trainer", "recommended_for", "focus", "venue_name", "venue_address", "venue_note")},
        ),
        (_("費用與條款"), {"fields": (("price_hkd", "price_note"), "important_note", "contact_note")}),
        (
            _("報名開關"),
            {
                "fields": ("status", ("opens_at", "closes_at"), "display_order"),
                "description": _("狀態設為「開放報名」且在時間範圍內，公開網站才會出現報名按鈕。"),
            },
        ),
    )

    @admin.display(description=_("報名期間"))
    def open_window(self, obj):
        start = f"{obj.opens_at:%Y-%m-%d}" if obj.opens_at else _("即時")
        end = f"{obj.closes_at:%Y-%m-%d}" if obj.closes_at else _("不設限")
        return f"{start} → {end}"

    @admin.display(description=_("名額"))
    def seats(self, obj):
        if obj.capacity_total is None:
            return _("%(v0)s 人（不限）") % {"v0": obj.confirmed_count}
        return f"{obj.confirmed_count} / {obj.capacity_total}"

    @admin.display(description=_("報名數"))
    def application_count(self, obj):
        url = reverse("admin:programs_application_changelist")
        return format_html(
            _('<a href="{}?project__id__exact={}">{} 份</a>'),
            url, obj.pk, obj.applications.count(),
        )

    @admin.display(description=_("公開頁"))
    def public_link(self, obj):
        return format_html(_('<a href="{}" target="_blank">開啟</a>'), obj.get_absolute_url())

    @admin.action(description=_("開放報名"))
    def open_enrollment(self, request, queryset):
        n = queryset.update(status=ProjectStatus.OPEN)
        self.message_user(request, _("已開放 %(v0)s 個項目的報名。") % {"v0": n})

    @admin.action(description=_("關閉報名"))
    def close_enrollment(self, request, queryset):
        n = queryset.update(status=ProjectStatus.CLOSED)
        self.message_user(request, _("已關閉 %(v0)s 個項目的報名。") % {"v0": n})


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "name_en", "project", "school_or_club", "event_category",
        "age_display", "registered", "flags", "status", "imported", "created_at",
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
        (_("摘要"), {"fields": ("summary_card",)}),
        (_("報名項目"), {"fields": ("project",)}),
        (
            _("個人資料"),
            {
                "fields": (
                    ("name_en", "name_zh"), ("sex", "birth_date"),
                    ("phone", "email"), ("school_or_club", "graduation_year"),
                )
            },
        ),
        (
            _("運動背景"),
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
            _("身體狀況與緊急聯絡"),
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
            _("聲明"),
            {"fields": ("health_declaration", "consent_terms", "consent_data", "remarks")},
        ),
        (
            _("後台處理"),
            {"fields": ("status", "internal_note", "athlete", "imported_at", "created_at", "updated_at")},
        ),
    )

    def get_queryset(self, request):
        """列表頁一次比對完未匯入的報名表，避免每一列各查一次資料庫。"""
        qs = super().get_queryset(request).select_related("project", "athlete__user")
        self._matches = find_existing_athletes(Application.objects.filter(athlete__isnull=True))
        return qs

    @admin.display(description=_("重複登記"))
    def registered(self, obj):
        return registered_badge(obj, getattr(self, "_matches", None))

    @admin.display(description=_("年齡"))
    def age_display(self, obj):
        return f"{obj.age} 歲{'（未成年）' if obj.is_minor else ''}"

    @admin.display(description=_("需留意"))
    def flags(self, obj):
        if not obj.health_flags:
            return "—"
        return format_html(
            '<span style="color:#b3261e;font-weight:600">{}</span>',
            "、".join(obj.health_flags),
        )

    @admin.display(description=_("已匯入 ATM"), boolean=True)
    def imported(self, obj):
        return obj.is_imported

    @admin.display(description=_("報名摘要"))
    def summary_card(self, obj):
        if obj.pk is None:
            return "—"
        rows = [
            (_("姓名"), obj.full_name),
            (_("年齡"), f"{obj.age} 歲（{obj.birth_date:%Y-%m-%d}）"),
            (_("學校 / 體育會"), f"{obj.school_or_club}｜畢業年份 {obj.graduation_year or '未填'}"),
            (_("田徑訓練"), _("有") if obj.has_track_training else _("沒有")),
            (
                _("項目"),
                f"{obj.get_event_category_display()}"
                + (f"｜{obj.primary_event}" if obj.primary_event else ""),
            ),
            (_("年資"), _("田徑 %(v0)s 年｜重訓 %(v1)s 年") % {"v0": obj.training_years, "v1": obj.strength_experience_years}),
            (_("身型"), f"{obj.height_cm} cm / {obj.weight_kg} kg"),
            (
                _("緊急聯絡"),
                f"{obj.emergency_contact_name} {obj.emergency_contact_phone}"
                f"（{obj.emergency_contact_relation or '—'}）",
            ),
            (_("需留意"), "、".join(obj.health_flags) or _("無")),
        ]
        if obj.athlete_id:
            url = reverse("admin:accounts_athleteprofile_change", args=[obj.athlete_id])
            rows.append((_("ATM 檔案"), format_html('<a href="{}">{}</a>', url, obj.athlete)))
            others = obj.athlete.applications.exclude(pk=obj.pk).select_related("project")
            if others:
                rows.append(
                    (_("其他計劃"), "、".join(a.project.title for a in others)),
                )
        else:
            match = find_existing_athlete(obj)
            if match:
                url = reverse(
                    "admin:accounts_athleteprofile_change", args=[match.athlete.pk]
                )
                rows.append(
                    (
                        _("已註冊運動員"),
                        format_html(
                            _('<a href="{}">{}</a>（{}）——匯入時會沿用這份檔案，不會另開帳號'),
                            url, match.athlete, describe_match(match),
                        ),
                    )
                )
        # 值來自報名者輸入，一律走 format_html 轉義（已是 SafeString 的連結不受影響）
        body = format_html_join(
            "",
            '<tr><th style="text-align:left;padding:4px 16px 4px 0;white-space:nowrap;'
            'color:#666">{}</th><td style="padding:4px 0">{}</td></tr>',
            rows,
        )
        return format_html('<table style="border-collapse:collapse">{}</table>', body)

    @admin.action(description=_("匯入 ATM，建立運動員檔案"))
    def import_to_atm(self, request, queryset):
        created = skipped = 0
        for application in queryset:
            if application.is_imported:
                skipped += 1
                continue
            match = find_existing_athlete(application)
            try:
                athlete = import_application(application)
            except ImportError_ as exc:
                self.message_user(request, f"{application.name_en}：{exc}", messages.ERROR)
                continue
            created += 1
            if match:
                self.message_user(
                    request,
                    _("%(v0)s 是已註冊運動員（%(v1)s），已把「%(v2)s」加到原有檔案 %(v3)s，不另開帳號。") % {"v0": application.name_en, "v1": describe_match(match), "v2": application.project.title, "v3": athlete},
                    messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    _("已建立運動員 %(v0)s（帳號 %(v1)s，密碼為隨機值，請用後台的『重設密碼』給對方）。") % {"v0": athlete, "v1": athlete.user.username},
                    messages.SUCCESS,
                )
        if skipped:
            self.message_user(request, _("%(v0)s 份報名先前已匯入，略過。") % {"v0": skipped}, messages.WARNING)
        if not created and not skipped:
            self.message_user(request, _("沒有任何報名被匯入。"), messages.WARNING)

    @admin.action(description=_("匯出 CSV"))
    def export_csv(self, request, queryset):
        columns = [
            (_("報名時間"), lambda a: f"{a.created_at:%Y-%m-%d %H:%M}"),
            (_("項目"), lambda a: a.project.title),
            (_("狀態"), lambda a: a.get_status_display()),
            (_("英文姓名"), lambda a: a.name_en),
            (_("中文姓名"), lambda a: a.name_zh),
            (_("性別"), lambda a: a.get_sex_display()),
            (_("出生日期"), lambda a: a.birth_date),
            (_("年齡"), lambda a: a.age),
            (_("電話"), lambda a: a.phone),
            (_("電郵"), lambda a: a.email),
            (_("學校/體育會"), lambda a: a.school_or_club),
            (_("畢業年份"), lambda a: a.graduation_year or ""),
            (_("有田徑訓練"), lambda a: _("是") if a.has_track_training else _("否")),
            (_("項目分類"), lambda a: a.get_event_category_display()),
            (_("主項"), lambda a: a.primary_event or ""),
            (_("個人最佳"), lambda a: a.personal_best),
            (_("田徑年資"), lambda a: a.training_years),
            (_("每週訓練日"), lambda a: a.training_days_per_week),
            (_("重訓年資"), lambda a: a.strength_experience_years),
            (_("現任教練"), lambda a: a.current_coach),
            (_("身高"), lambda a: a.height_cm),
            (_("體重"), lambda a: a.weight_kg),
            (_("緊急聯絡人"), lambda a: a.emergency_contact_name),
            (_("緊急聯絡電話"), lambda a: a.emergency_contact_phone),
            (_("關係"), lambda a: a.emergency_contact_relation),
            (_("現有傷患"), lambda a: a.injury_detail if a.has_current_injury else ""),
            (_("過往傷患"), lambda a: a.injury_history),
            (_("長期病患"), lambda a: a.medical_conditions),
            (_("藥物"), lambda a: a.medications),
            (_("敏感"), lambda a: a.allergies),
            (_("醫生許可"), lambda a: _("是") if a.doctor_clearance else _("否")),
            (_("備註"), lambda a: a.remarks),
            (_("已匯入 ATM"), lambda a: _("是") if a.is_imported else _("否")),
            (_("已註冊運動員"), lambda a: _("是") if a.is_returning_athlete else _("否")),
        ]
        response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = 'attachment; filename="applications.csv"'
        response.write("﻿")  # 讓 Excel 正確辨識 UTF-8
        writer = csv.writer(response)
        writer.writerow([label for label, _ in columns])
        for application in queryset.select_related("project", "primary_event"):
            writer.writerow([getter(application) for _, getter in columns])
        return response

    @admin.action(description=_("標記為已確認"))
    def mark_confirmed(self, request, queryset):
        n = queryset.update(status=ApplicationStatus.CONFIRMED)
        self.message_user(request, _("已確認 %(v0)s 份報名。") % {"v0": n})

    @admin.action(description=_("標記為候補"))
    def mark_waitlist(self, request, queryset):
        n = queryset.update(status=ApplicationStatus.WAITLIST)
        self.message_user(request, _("已將 %(v0)s 份報名列為候補。") % {"v0": n})

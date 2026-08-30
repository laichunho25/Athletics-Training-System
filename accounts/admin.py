from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import (
    AthleteProfile,
    BodyMetricLog,
    CoachProfile,
    Event,
    PersonalBest,
    User,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "first_name", "last_name", "role", "email", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = BaseUserAdmin.fieldsets + (("ATM", {"fields": ("role", "phone", "avatar")}),)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("code", "name_zh", "name_en", "category", "unit", "distance_m")
    list_filter = ("category", "unit")
    search_fields = ("code", "name_zh", "name_en")


@admin.register(CoachProfile)
class CoachProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "squad_name", "specialties", "athlete_count")
    search_fields = ("user__username", "squad_name")


class PersonalBestInline(admin.TabularInline):
    model = PersonalBest
    extra = 0


@admin.register(AthleteProfile)
class AthleteProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "age", "sex", "primary_event", "coach", "status", "height_cm", "weight_kg")
    list_filter = ("coach", "status", "sex", "primary_event")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    filter_horizontal = ("secondary_events",)
    inlines = [PersonalBestInline]


@admin.register(PersonalBest)
class PersonalBestAdmin(admin.ModelAdmin):
    list_display = ("athlete", "event", "mark_display", "wind", "date", "is_current")
    list_filter = ("event", "is_current")


@admin.register(BodyMetricLog)
class BodyMetricLogAdmin(admin.ModelAdmin):
    list_display = ("athlete", "date", "weight_kg", "body_fat_pct", "resting_hr")
    list_filter = ("athlete",)

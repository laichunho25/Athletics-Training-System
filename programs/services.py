"""把報名表轉成 ATM 的運動員檔案。"""

import re
import secrets

from django.db import transaction
from django.utils import timezone

from accounts.models import AthleteProfile, Event, User
from core.models import Role

# 沒有指定主項時，依項目分類挑一個代表項目
DEFAULT_EVENT_BY_CATEGORY = {
    "SPRINT": "100M",
    "HURDLES": "110MH",
    "MIDDLE": "800M",
    "DISTANCE": "3000M",
    "JUMP": "LJ",
    "THROW": "SP",
    "COMBINED": "DEC",
    "RELAY": "4X100M",
}


def suggest_username(application):
    """由英文姓名產生可用的帳號，衝突時加數字。"""
    base = re.sub(r"[^a-z0-9]+", "_", application.name_en.strip().lower()).strip("_")
    base = base[:24] or f"athlete{application.pk or ''}"
    username = base
    n = 1
    while User.objects.filter(username=username).exists():
        n += 1
        username = f"{base}{n}"
    return username


def resolve_event(application):
    """報名表沒填主項時，用項目分類推一個，再退回任何一個項目。"""
    if application.primary_event_id:
        return application.primary_event

    code = DEFAULT_EVENT_BY_CATEGORY.get(application.event_category)
    event = Event.objects.filter(code=code).first()
    if event is None:
        event = Event.objects.filter(category=application.event_category).first()
    return event or Event.objects.first()


def build_notes(application):
    """把不進 AthleteProfile 欄位、但教練需要看到的資訊寫進備註。"""
    lines = [f"由報名表匯入：{application.project.title}"]
    if application.personal_best:
        lines.append(f"個人最佳：{application.personal_best}")
    if application.current_coach:
        lines.append(f"現任教練：{application.current_coach}")
    if application.emergency_contact_name:
        lines.append(
            f"緊急聯絡：{application.emergency_contact_name} "
            f"{application.emergency_contact_phone}"
            f"（{application.emergency_contact_relation or '未填關係'}）"
        )
    if application.has_current_injury and application.injury_detail:
        lines.append(f"報名時傷患：{application.injury_detail}")
    if application.injury_history:
        lines.append(f"過往傷患：{application.injury_history}")
    if application.medical_conditions:
        lines.append(f"長期病患：{application.medical_conditions}")
    if application.medications:
        lines.append(f"服用藥物：{application.medications}")
    if application.allergies:
        lines.append(f"敏感：{application.allergies}")
    if not application.doctor_clearance:
        lines.append("⚠ 尚未取得醫生許可")
    if application.is_minor and application.guardian_name:
        lines.append(f"家長：{application.guardian_name} {application.guardian_phone}")
    if application.remarks:
        lines.append(f"報名備註：{application.remarks}")
    return "\n".join(lines)


class ImportError_(Exception):
    """匯入失敗（缺少項目字典等），訊息會顯示在後台。"""


@transaction.atomic
def import_application(application, coach=None):
    """
    建立 User + AthleteProfile。可重複呼叫：已匯入過就直接回傳原本的檔案。

    密碼設為隨機值（使用者需自行重設），避免產生可預測的登入憑證。
    """
    if application.athlete_id:
        return application.athlete

    event = resolve_event(application)
    if event is None:
        raise ImportError_("項目字典是空的，請先執行 loaddata events")

    first_name, _, last_name = application.name_en.strip().partition(" ")
    user = User.objects.create_user(
        username=suggest_username(application),
        email=application.email,
        password=secrets.token_urlsafe(24),
        first_name=first_name[:150],
        last_name=last_name[:150],
        role=Role.ATHLETE,
        phone=application.phone,
    )

    athlete = AthleteProfile.objects.create(
        user=user,
        coach=coach,
        birth_date=application.birth_date,
        sex=application.sex,
        height_cm=application.height_cm,
        weight_kg=application.weight_kg,
        primary_event=event,
        training_days_per_week=application.training_days_per_week,
        strength_experience_years=application.strength_experience_years,
        school_or_club=application.school_or_club,
        notes=build_notes(application),
    )

    application.athlete = athlete
    application.imported_at = timezone.now()
    application.save(update_fields=["athlete", "imported_at", "updated_at"])
    return athlete

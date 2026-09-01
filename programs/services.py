"""把報名表轉成 ATM 的運動員檔案，並檢查報名者是否已在其他計劃登記過。"""

import re
import secrets
from collections import namedtuple

from django.db import transaction
from django.db.models import Q
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
    if application.remarks:
        lines.append(f"報名備註：{application.remarks}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 重複登記檢查

#: 比對用的三個欄位。三項中有兩項相符就當作同一個人——
#: 只靠電郵會把共用家長信箱的兄弟姊妹誤判，只靠姓名或生日則太鬆。
MATCH_LABELS = {"name": "全名", "birth_date": "出生日期", "email": "電郵"}
MATCH_THRESHOLD = 2

#: 比對結果：athlete＝已存在的檔案，fields＝相符的欄位（MATCH_LABELS 的 key）
AthleteMatch = namedtuple("AthleteMatch", "athlete fields")


def normalise_name(value):
    """姓名比對：忽略大小寫、空格與標點，中英文都適用。"""
    return re.sub(r"[^0-9a-z一-鿿]+", "", (value or "").lower())


def normalise_email(value):
    return (value or "").strip().lower()


def describe_match(match):
    if not match:
        return ""
    order = [k for k in MATCH_LABELS if k in match.fields]
    return "、".join(MATCH_LABELS[k] for k in order) + "相符"


def _application_names(application):
    return {
        n
        for n in (normalise_name(application.name_en), normalise_name(application.name_zh))
        if n
    }


def _athlete_names(athlete):
    """檔案上的姓名，加上這名運動員過往報名表填過的姓名。"""
    user = athlete.user
    names = {normalise_name(user.get_full_name()), normalise_name(user.username)}
    for past in athlete.applications.all():
        names |= _application_names(past)
    return {n for n in names if n}


def _athlete_emails(athlete):
    emails = {normalise_email(athlete.user.email)}
    emails |= {normalise_email(past.email) for past in athlete.applications.all()}
    return {e for e in emails if e}


def matched_fields(application, athlete):
    """回傳全名／出生日期／電郵之中，這份報名與該檔案相符的欄位。"""
    fields = []
    if _application_names(application) & _athlete_names(athlete):
        fields.append("name")
    if athlete.birth_date == application.birth_date:
        fields.append("birth_date")
    email = normalise_email(application.email)
    if email and email in _athlete_emails(athlete):
        fields.append("email")
    return fields


def find_existing_athletes(applications):
    """
    批次比對，回傳 {application_id: AthleteMatch}——列表頁用這個避免 N+1。

    只撈「電郵或出生日期對得上」的檔案當候選：任何達標的組合都至少含這兩項之一。
    """
    applications = [a for a in applications if a is not None and not a.athlete_id]
    if not applications:
        return {}

    emails = {normalise_email(a.email) for a in applications} - {""}
    births = {a.birth_date for a in applications if a.birth_date}

    candidates = (
        AthleteProfile.objects.filter(
            Q(user__email__in=emails) | Q(applications__email__in=emails) | Q(birth_date__in=births)
        )
        .select_related("user")
        .prefetch_related("applications__project")
        .distinct()
    )
    candidates = list(candidates)
    if not candidates:
        return {}

    results = {}
    for application in applications:
        best = None
        for athlete in candidates:
            fields = matched_fields(application, athlete)
            if len(fields) < MATCH_THRESHOLD:
                continue
            if best is None or len(fields) > len(best.fields):
                best = AthleteMatch(athlete, fields)
        if best:
            results[application.pk] = best
    return results


def find_existing_athlete(application):
    """單筆比對：已登記過就回傳 AthleteMatch，否則 None。"""
    return find_existing_athletes([application]).get(application.pk)


def annotate_matches(applications):
    """給樣板用：在每份報名表掛上 existing_match / existing_reason。"""
    applications = list(applications)
    matches = find_existing_athletes(applications)
    for application in applications:
        match = matches.get(application.pk)
        application.existing_match = match.athlete if match else None
        application.existing_reason = describe_match(match)
    return applications


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

    match = find_existing_athlete(application)
    if match:
        return link_to_existing_athlete(application, match.athlete)

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


@transaction.atomic
def link_to_existing_athlete(application, athlete):
    """
    已註冊運動員報新項目：不開新帳號，沿用原有檔案，只把報名表帶來的新資料補上。

    身高體重等「當下數值」以新報名表為準（比舊紀錄新），教練、主項、狀態一律不動——
    那些是教練在 ATM 裡調過的，報名表不應該蓋掉。
    """
    changes = []
    for field, label in (
        ("height_cm", "身高"),
        ("weight_kg", "體重"),
        ("training_days_per_week", "每週訓練日數"),
        ("strength_experience_years", "重訓年資"),
    ):
        new_value = getattr(application, field)
        if new_value is not None and getattr(athlete, field) != new_value:
            changes.append(f"{label} {getattr(athlete, field)} → {new_value}")
            setattr(athlete, field, new_value)

    if application.school_or_club and application.school_or_club != athlete.school_or_club:
        changes.append(f"學校／體育會 {athlete.school_or_club or '未填'} → {application.school_or_club}")
        athlete.school_or_club = application.school_or_club

    lines = [
        "",
        f"加入項目：{application.project.title}"
        f"（{timezone.localtime(application.created_at):%Y-%m-%d} 報名）",
    ]
    if changes:
        lines.append("報名表更新：" + "；".join(changes))
    if application.personal_best:
        lines.append(f"個人最佳：{application.personal_best}")
    if application.has_current_injury and application.injury_detail:
        lines.append(f"報名時傷患：{application.injury_detail}")
    if application.remarks:
        lines.append(f"報名備註：{application.remarks}")
    athlete.notes = (athlete.notes.rstrip() + "\n" + "\n".join(lines)).strip()
    athlete.save()

    # 新項目的主項若與檔案上的主項不同，收進副項，不覆蓋教練設定的主項
    if application.primary_event_id and application.primary_event_id != athlete.primary_event_id:
        athlete.secondary_events.add(application.primary_event)

    if application.phone and not athlete.user.phone:
        athlete.user.phone = application.phone
        athlete.user.save(update_fields=["phone"])

    application.athlete = athlete
    application.imported_at = timezone.now()
    application.save(update_fields=["athlete", "imported_at", "updated_at"])

    # 比對時預先載入過 applications，重新讀一次才看得到剛加上的這份報名
    athlete.refresh_from_db()
    return athlete

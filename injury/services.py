"""傷患調整引擎：依當前傷患與疼痛程度，過濾/替換訓練內容。"""

from datetime import date

from core.models import AthleteStatus, SessionType
from injury.models import ExerciseModification, Injury, InjuryStatus, PainLog

# 疼痛 ≥ 此值 → 封鎖高強度訓練
PAIN_BLOCK_THRESHOLD = 6

HIGH_INTENSITY_TYPES = {SessionType.TRACK, SessionType.STRENGTH, SessionType.COMPETITION}


def active_injuries(athlete):
    return Injury.objects.filter(athlete=athlete).exclude(status=InjuryStatus.RESOLVED)


def affected_body_parts(athlete):
    return list(active_injuries(athlete).values_list("body_part", flat=True))


def worst_pain_today(athlete, on_date=None):
    """今日各傷患中最高的活動時疼痛值。"""
    on_date = on_date or date.today()
    logs = PainLog.objects.filter(injury__athlete=athlete, date=on_date)
    values = [l.pain_during_activity for l in logs]
    return max(values) if values else None


def should_block_high_intensity(athlete, on_date=None):
    """回傳 (是否封鎖, 原因)。"""
    pain = worst_pain_today(athlete, on_date)
    if pain is not None and pain >= PAIN_BLOCK_THRESHOLD:
        return True, f"今日活動時疼痛達 {pain}/10（門檻 {PAIN_BLOCK_THRESHOLD}），已封鎖高強度課表。"
    acute = active_injuries(athlete).filter(status=InjuryStatus.ACUTE)
    if acute.exists():
        parts = "、".join(i.get_body_part_display() for i in acute)
        return True, f"{parts} 處於急性期，禁止高強度訓練。"
    return False, ""


def alternatives_for(exercise, body_parts, pain_level=0):
    """某動作在指定傷患部位下的可用替代方案。"""
    out = []
    for mod in ExerciseModification.objects.filter(
        original_exercise=exercise
    ).select_related("substitute_exercise"):
        if not any(mod.applies_to(bp) for bp in body_parts):
            continue
        out.append(
            {
                "substitute": mod.substitute_display,
                "substitute_id": mod.substitute_exercise_id,
                "rationale": mod.rationale,
                "max_pain_level": mod.max_pain_level,
                "allowed": pain_level <= mod.max_pain_level,
            }
        )
    return out


def injury_alternatives_report(injury):
    """某筆傷患的完整替代動作建議（給前端傷患頁）。"""
    pain = injury.current_pain_level or 0
    mods = ExerciseModification.objects.select_related(
        "original_exercise", "substitute_exercise"
    )
    rows = []
    for mod in mods:
        if not mod.applies_to(injury.body_part):
            continue
        rows.append(
            {
                "original": mod.original_exercise.name_zh,
                "original_id": mod.original_exercise_id,
                "substitute": mod.substitute_display,
                "rationale": mod.rationale,
                "allowed": pain <= mod.max_pain_level,
                "max_pain_level": mod.max_pain_level,
            }
        )
    return {
        "injury": str(injury),
        "body_part": injury.get_body_part_display(),
        "status": injury.get_status_display(),
        "current_pain": pain,
        "alternatives": rows,
    }


def apply_modifications(session):
    """
    把一堂課依運動員當前傷患調整：
    - 高強度被封鎖 → 整堂改為恢復課
    - 個別力量動作 → 換成替代動作
    回傳調整說明清單。
    """
    athlete = session.athlete
    parts = affected_body_parts(athlete)
    if not parts:
        return []

    changes = []
    blocked, reason = should_block_high_intensity(athlete, session.date)
    pain = worst_pain_today(athlete, session.date) or 0

    if blocked and session.session_type in HIGH_INTENSITY_TYPES:
        session.session_type = SessionType.RECOVERY
        session.title = f"[傷患調整] {session.title}"
        session.is_modified = True
        session.planned_duration_min = min(session.planned_duration_min, 45)
        session.description = (
            f"{session.description}\n\n⚠️ 系統自動調整：{reason}\n"
            "建議改為：上肢循環、水中跑、活動度與核心穩定訓練。"
        ).strip()
        session.save()
        session.track_sets.all().delete()
        changes.append({"type": "SESSION_DOWNGRADED", "detail": reason})

    for s_set in session.strength_sets.select_related("exercise"):
        options = alternatives_for(s_set.exercise, parts, pain)
        usable = [o for o in options if o["allowed"] and o["substitute_id"]]
        if not options:
            continue
        if usable:
            new_id = usable[0]["substitute_id"]
            changes.append(
                {
                    "type": "EXERCISE_SUBSTITUTED",
                    "from": s_set.exercise.name_zh,
                    "to": usable[0]["substitute"],
                    "rationale": usable[0]["rationale"],
                    "set_id": s_set.id,
                }
            )
            s_set.note = f"傷患替代：原 {s_set.exercise.name_zh}"
            s_set.exercise_id = new_id
            s_set.save()
            session.is_modified = True
        else:
            changes.append(
                {
                    "type": "EXERCISE_REMOVED",
                    "from": s_set.exercise.name_zh,
                    "rationale": "疼痛超過所有替代方案的容許值，建議暫停此動作。",
                    "set_id": s_set.id,
                }
            )

    if session.is_modified:
        session.save(update_fields=["is_modified", "updated_at"])
    return changes


def sync_athlete_status(athlete):
    """依現有傷患自動更新運動員狀態燈號。"""
    injuries = active_injuries(athlete)
    if injuries.filter(status__in=[InjuryStatus.ACUTE, InjuryStatus.REHAB]).exists():
        new_status = AthleteStatus.INJURED
    elif injuries.exists():
        new_status = AthleteStatus.NIGGLE
    else:
        new_status = AthleteStatus.HEALTHY
    if athlete.status != new_status:
        athlete.status = new_status
        athlete.save(update_fields=["status", "updated_at"])
    return new_status


RTP_CRITERIA = [
    "無痛全速跑（疼痛 0/10，連續 3 次訓練）",
    "患側 / 健側等長力量差異 < 10%",
    "CMJ 恢復至個人基線的 90% 以上",
    "完成專項技術動作無代償",
    "連續 7 天靜態疼痛為 0",
    "醫療人員 / 物理治療師書面同意",
]


def rtp_checklist(injury):
    return {
        "injury": str(injury),
        "status": injury.get_status_display(),
        "days_since_onset": injury.days_since_onset,
        "criteria": [{"item": c, "met": None} for c in RTP_CRITERIA],
        "note": "全部條件達標方可回歸完整訓練；任一未達標請維持 RTP 階段。",
    }

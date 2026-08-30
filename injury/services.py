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
    # 只看仍在追蹤中的傷患；已康復傷患的舊紀錄不應繼續封鎖訓練
    logs = PainLog.objects.filter(
        injury__athlete=athlete, date=on_date
    ).exclude(injury__status=InjuryStatus.RESOLVED)
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


# ------------------------------------------------------------------ 治療方向

# 依「治療進度」給出這一階段的目標、可用手段與注意事項。
# 這不是醫療建議，是給教練一個共同語言：現在在哪一階、下一步要看到什麼才過關。
STAGE_PLAYBOOK = {
    "ASSESS": {
        "goal": "先確定是什麼傷、能不能練",
        "actions": [
            "48 小時內找醫生或物理治療師做一次評估",
            "必要時安排影像檢查（X 光 / 超聲波 / MRI）",
            "先停掉所有會誘發疼痛的動作，改做不痛的替代動作",
        ],
        "modalities": ["DOCTOR", "IMAGING", "REST", "ICE"],
        "next_when": "拿到診斷、知道禁忌動作之後 → 進入消炎止痛",
    },
    "RELIEVE": {
        "goal": "把靜態疼痛與腫脹壓下來",
        "actions": [
            "急性期 72 小時：相對休息、冰敷、加壓、抬高",
            "維持不痛範圍內的關節活動，避免完全不動",
            "用替代動作維持其他部位的體能與有氧",
        ],
        "modalities": ["ICE", "PHYSIO", "MEDICATION", "TAPING", "REST"],
        "next_when": "靜態疼痛 ≤ 2、腫脹消退 → 進入恢復功能",
    },
    "RESTORE": {
        "goal": "把活動度與基本肌力拿回來",
        "actions": [
            "每日等長 → 向心 → 離心的漸進負荷",
            "處理代償：對側與鄰近關節一併訓練",
            "手法治療或針灸處理殘留的緊繃點",
        ],
        "modalities": ["PHYSIO", "STRENGTH", "MANUAL", "ACUPUNCTURE", "STRETCH"],
        "next_when": "活動度對稱、患側肌力達健側 80% → 進入重建體能",
    },
    "RECONDITION": {
        "goal": "把專項強度加回去，準備回歸",
        "actions": [
            "跑動由慢到快分級：慢跑 → 節奏跑 → 加速 → 全速",
            "加入離心負荷與增強式，重建肌腱耐受度",
            "每次加量後 24 小時內疼痛不得回升超過 2 分",
        ],
        "modalities": ["STRENGTH", "PHYSIO", "STRETCH", "TAPING"],
        "next_when": "通過 RTP 檢核表全部條件 → 結案回歸完整訓練",
    },
}

# 不同傷型會多一條要特別留意的事
TYPE_CAUTION = {
    "STRAIN": "肌肉拉傷最常在「還會痛就衝刺」時復發，離心負荷要練足。",
    "SPRAIN": "扭傷後本體感覺會下降，單腳平衡與變向訓練不能省。",
    "TENDINOPATHY": "肌腱病變怕的是完全休息，要用可忍受的疼痛（≤3/10）持續加載。",
    "PERIOSTITIS": "骨膜炎先減衝擊量與換場地／鞋，止痛只是治標。",
    "STRESS_FRACTURE": "應力性骨折必須由醫生決定何時負重，不可自行加量。",
    "CONTUSION": "挫傷早期避免熱敷與強力按摩，慎防骨化性肌炎。",
    "OVERUSE": "過度使用是訓練量的問題，回歸前要一併修正課表安排。",
}


def suggest_treatment_direction(injury):
    """回傳這筆傷患目前該走的治療方向（階段目標 / 手段 / 過關條件）。"""
    from injury.models import TreatmentStage, TreatmentType

    stage = injury.treatment_status or TreatmentStage.ASSESS
    book = STAGE_PLAYBOOK.get(str(stage), STAGE_PLAYBOOK["ASSESS"])
    labels = dict(TreatmentType.choices)
    return {
        "stage": stage,
        "stage_label": injury.get_treatment_status_display(),
        "goal": book["goal"],
        "actions": book["actions"],
        "modalities": [labels.get(m, m) for m in book["modalities"]],
        "next_when": book["next_when"],
        "caution": TYPE_CAUTION.get(injury.injury_type, ""),
        "custom": injury.treatment_direction,
    }


def treatment_summary(injury, limit=8):
    """治療紀錄的統計：做了幾次、哪種手段最有效、最近一次是什麼時候。"""
    from injury.models import TreatmentEffect, TreatmentType

    logs = list(injury.treatments.all())
    labels = dict(TreatmentType.choices)
    by_type = {}
    for log in logs:
        row = by_type.setdefault(
            log.treatment_type,
            {"type": labels.get(log.treatment_type, log.treatment_type), "count": 0, "improved": 0},
        )
        row["count"] += 1
        if log.effect in (TreatmentEffect.MUCH_BETTER, TreatmentEffect.BETTER):
            row["improved"] += 1

    for row in by_type.values():
        row["rate"] = round(row["improved"] / row["count"] * 100) if row["count"] else 0

    ranked = sorted(by_type.values(), key=lambda r: (-r["rate"], -r["count"]))
    total_cost = sum(float(log.cost_hkd) for log in logs if log.cost_hkd)

    return {
        "total": len(logs),
        "latest": logs[0] if logs else None,
        "recent": logs[:limit],
        "by_type": ranked,
        "best": ranked[0] if ranked and ranked[0]["improved"] else None,
        "total_cost": round(total_cost, 2) if total_cost else 0,
    }

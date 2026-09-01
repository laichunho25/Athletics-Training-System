from django.db import models


class TimeStampedModel(models.Model):
    """全專案共用基底：建立/更新時間。"""

    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        abstract = True


class Role(models.TextChoices):
    COACH = "COACH", "教練"
    ATHLETE = "ATHLETE", "運動員"
    ADMIN = "ADMIN", "管理員"


class Sex(models.TextChoices):
    MALE = "M", "男"
    FEMALE = "F", "女"


class AthleteStatus(models.TextChoices):
    HEALTHY = "HEALTHY", "健康"
    NIGGLE = "NIGGLE", "輕微不適"
    INJURED = "INJURED", "傷患中"


class EventCategory(models.TextChoices):
    SPRINT = "SPRINT", "短跑"
    HURDLES = "HURDLES", "跨欄"
    MIDDLE = "MIDDLE", "中距離"
    DISTANCE = "DISTANCE", "長距離"
    JUMP = "JUMP", "跳部"
    THROW = "THROW", "投擲"
    COMBINED = "COMBINED", "全能"
    RELAY = "RELAY", "接力"


class MeasureUnit(models.TextChoices):
    TIME = "TIME", "時間 (秒)"
    DISTANCE = "DISTANCE", "距離 (公尺)"
    POINTS = "POINTS", "分數"


class PhaseType(models.TextChoices):
    """田徑年度訓練的分期。名稱沿用教科書上的四個主要時期。"""

    GENERAL_PREP = "GENERAL_PREP", "一般準備期"
    SPECIFIC_PREP = "SPECIFIC_PREP", "專項準備期"
    PRE_COMP = "PRE_COMP", "賽前期"
    TAPER_COMP = "TAPER_COMP", "比賽期"
    TRANSITION = "TRANSITION", "過渡期"


#: 每個時期在做什麼——比較不同時期的數據時，畫面上直接把定義放旁邊，
#: 免得看的人要自己回想「專項準備期本來就該強度高、量少」。
PHASE_GUIDE = {
    PhaseType.GENERAL_PREP.value: {
        "goal": "發展基礎身體素質（GPP）",
        "feature": "高訓練量、低訓練強度",
        "content": "有氧耐力、基礎力量（肌肉肥大）、核心穩定性及全面身體協調",
    },
    PhaseType.SPECIFIC_PREP.value: {
        "goal": "把基礎體能轉化為專項能力（SPP）",
        "feature": "訓練量逐漸減少、訓練強度逐漸提升",
        "content": "專項速度、爆發力（最大力量轉化）、專項耐力與完整技術動作定型",
    },
    PhaseType.PRE_COMP.value: {
        "goal": "以模擬賽與熱身賽把狀態推向高峰前緣",
        "feature": "強度續升、量續降",
        "content": "專項速度、賽前模擬、技術與戰術微調",
    },
    PhaseType.TAPER_COMP.value: {
        "goal": "在核心賽事中發揮最佳運動表現",
        "feature": "低訓練量、高訓練強度",
        "content": "專項速度、賽前減量（Tapering）、戰術模擬，讓體能達到高峰（Peaking）",
    },
    PhaseType.TRANSITION.value: {
        "goal": "消除生理與心理的長期疲勞",
        "feature": "極低訓練量、極低訓練強度",
        "content": "積極性恢復（游泳、自行車等非專項低強度運動）、修補運動損傷、防止過度訓練",
    },
}


def phase_guide(phase_type):
    return PHASE_GUIDE.get(phase_type, {})


class SessionType(models.TextChoices):
    """課別（program 分類）。

    PROGRAM_SESSION_TYPES 裡的幾項是教練在訓練日曆上「按日期新增 program」
    時會看到的選項，其餘留著是為了讓舊資料仍然顯示得出中文名稱。
    """

    TRACK = "TRACK", "田徑場訓練"
    STRENGTH = "STRENGTH", "重量訓練"
    RECOVERY = "RECOVERY", "恢復訓練"
    REHAB = "REHAB", "治療康復"
    COMPETITION = "COMPETITION", "比賽"
    OTHER = "OTHER", "其他"
    # ---- 舊資料相容（不出現在新增 program 的選單）----
    TECHNIQUE = "TECHNIQUE", "技術訓練"
    CROSS_TRAINING = "CROSS_TRAINING", "交叉訓練"
    REST = "REST", "休息"


#: 訓練日曆上可以新增的 program 類別（依教練實際使用的五大類）
PROGRAM_SESSION_TYPES = [
    SessionType.TRACK,
    SessionType.STRENGTH,
    SessionType.REHAB,
    SessionType.RECOVERY,
    SessionType.COMPETITION,
    SessionType.OTHER,
]


def program_type_choices():
    """給表單用的 (value, label) 清單。"""
    return [(t.value, t.label) for t in PROGRAM_SESSION_TYPES]


class SessionStatus(models.TextChoices):
    PLANNED = "PLANNED", "已排定"
    COMPLETED = "COMPLETED", "已完成"
    PARTIAL = "PARTIAL", "部分完成"
    SKIPPED = "SKIPPED", "未執行"


class DayType(models.TextChoices):
    HARD = "HARD", "高強度日"
    MODERATE = "MODERATE", "中強度日"
    EASY = "EASY", "輕度日"
    REST = "REST", "休息日"
    COMPETITION = "COMPETITION", "比賽日"


def format_mark(value, unit):
    """依項目單位格式化成績：51.20 / 1:52.34 / 6.42m"""
    if value is None:
        return "-"
    value = float(value)
    if unit == MeasureUnit.TIME:
        if value >= 60:
            minutes, seconds = divmod(value, 60)
            if minutes >= 60:
                hours, minutes = divmod(minutes, 60)
                return f"{int(hours)}:{int(minutes):02d}:{seconds:05.2f}"
            return f"{int(minutes)}:{seconds:05.2f}"
        return f"{value:.2f}"
    if unit == MeasureUnit.DISTANCE:
        return f"{value:.2f}m"
    return f"{value:.0f}"

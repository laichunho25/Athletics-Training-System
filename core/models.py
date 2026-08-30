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
    GENERAL_PREP = "GENERAL_PREP", "準備期"
    SPECIFIC_PREP = "SPECIFIC_PREP", "專項期"
    PRE_COMP = "PRE_COMP", "賽前期"
    TAPER_COMP = "TAPER_COMP", "比賽期"
    TRANSITION = "TRANSITION", "恢復期"


class SessionType(models.TextChoices):
    """課別（program 分類）。

    前五項是教練在訓練日曆上「按日期新增 program」時會看到的選項，
    其餘幾項留著是為了讓舊資料仍然顯示得出中文名稱。
    """

    TRACK = "TRACK", "田徑場訓練"
    STRENGTH = "STRENGTH", "重量訓練"
    RECOVERY = "RECOVERY", "恢復訓練"
    REHAB = "REHAB", "治療康復"
    OTHER = "OTHER", "其他"
    # ---- 舊資料相容（不出現在新增 program 的選單）----
    TECHNIQUE = "TECHNIQUE", "技術訓練"
    CROSS_TRAINING = "CROSS_TRAINING", "交叉訓練"
    COMPETITION = "COMPETITION", "比賽"
    REST = "REST", "休息"


#: 訓練日曆上可以新增的 program 類別（依教練實際使用的五大類）
PROGRAM_SESSION_TYPES = [
    SessionType.TRACK,
    SessionType.STRENGTH,
    SessionType.REHAB,
    SessionType.RECOVERY,
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

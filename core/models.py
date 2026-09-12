from django.db import models
from django.utils.translation import get_language, gettext_lazy as _


class TimeStampedModel(models.Model):
    """全專案共用基底：建立/更新時間。"""

    created_at = models.DateTimeField(_("建立時間"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新時間"), auto_now=True)

    class Meta:
        abstract = True


class Role(models.TextChoices):
    COACH = "COACH", _("教練")
    ATHLETE = "ATHLETE", _("運動員")
    ADMIN = "ADMIN", _("管理員")


class Sex(models.TextChoices):
    MALE = "M", _("男")
    FEMALE = "F", _("女")


class AthleteStatus(models.TextChoices):
    HEALTHY = "HEALTHY", _("健康")
    NIGGLE = "NIGGLE", _("輕微不適")
    INJURED = "INJURED", _("傷患中")


class VideoPlan(models.TextChoices):
    """影片庫的方案。

    免費額度的存在不是為了省那幾塊錢——R2 一個月的帳單就算全隊塞爆也只是零頭——
    而是為了讓儲存量**可預測**：沒有上限的話，一條 500MB 的廢片乘以一百個人
    就是一筆沒人看得見的帳。進階會員買的是空間、保留期，以及更深的分析。
    """

    FREE = "FREE", _("免費")
    PRO = "PRO", _("進階會員")


class EventCategory(models.TextChoices):
    SPRINT = "SPRINT", _("短跑")
    HURDLES = "HURDLES", _("跨欄")
    MIDDLE = "MIDDLE", _("中距離")
    DISTANCE = "DISTANCE", _("長距離")
    JUMP = "JUMP", _("跳部")
    THROW = "THROW", _("投擲")
    COMBINED = "COMBINED", _("全能")
    RELAY = "RELAY", _("接力")


class MeasureUnit(models.TextChoices):
    TIME = "TIME", _("時間 (秒)")
    DISTANCE = "DISTANCE", _("距離 (公尺)")
    POINTS = "POINTS", _("分數")


class PhaseType(models.TextChoices):
    """田徑年度訓練的分期。名稱沿用教科書上的四個主要時期。"""

    GENERAL_PREP = "GENERAL_PREP", _("一般準備期")
    SPECIFIC_PREP = "SPECIFIC_PREP", _("專項準備期")
    PRE_COMP = "PRE_COMP", _("賽前期")
    TAPER_COMP = "TAPER_COMP", _("比賽期")
    TRANSITION = "TRANSITION", _("過渡期")


#: 每個時期在做什麼——比較不同時期的數據時，畫面上直接把定義放旁邊，
#: 免得看的人要自己回想「專項準備期本來就該強度高、量少」。
PHASE_GUIDE = {
    PhaseType.GENERAL_PREP.value: {
        "goal": _("發展基礎身體素質（GPP）"),
        "feature": _("高訓練量、低訓練強度"),
        "content": _("有氧耐力、基礎力量（肌肉肥大）、核心穩定性及全面身體協調"),
    },
    PhaseType.SPECIFIC_PREP.value: {
        "goal": _("把基礎體能轉化為專項能力（SPP）"),
        "feature": _("訓練量逐漸減少、訓練強度逐漸提升"),
        "content": _("專項速度、爆發力（最大力量轉化）、專項耐力與完整技術動作定型"),
    },
    PhaseType.PRE_COMP.value: {
        "goal": _("以模擬賽與熱身賽把狀態推向高峰前緣"),
        "feature": _("強度續升、量續降"),
        "content": _("專項速度、賽前模擬、技術與戰術微調"),
    },
    PhaseType.TAPER_COMP.value: {
        "goal": _("在核心賽事中發揮最佳運動表現"),
        "feature": _("低訓練量、高訓練強度"),
        "content": _("專項速度、賽前減量（Tapering）、戰術模擬，讓體能達到高峰（Peaking）"),
    },
    PhaseType.TRANSITION.value: {
        "goal": _("消除生理與心理的長期疲勞"),
        "feature": _("極低訓練量、極低訓練強度"),
        "content": _("積極性恢復（游泳、自行車等非專項低強度運動）、修補運動損傷、防止過度訓練"),
    },
}


def phase_guide(phase_type):
    return PHASE_GUIDE.get(phase_type, {})


class SessionType(models.TextChoices):
    """課別（program 分類）。

    PROGRAM_SESSION_TYPES 裡的幾項是教練在訓練日曆上「按日期新增 program」
    時會看到的選項，其餘留著是為了讓舊資料仍然顯示得出中文名稱。
    """

    TRACK = "TRACK", _("田徑場訓練")
    STRENGTH = "STRENGTH", _("重量訓練")
    RECOVERY = "RECOVERY", _("恢復訓練")
    REHAB = "REHAB", _("治療康復")
    COMPETITION = "COMPETITION", _("比賽")
    OTHER = "OTHER", _("其他")
    # ---- 舊資料相容（不出現在新增 program 的選單）----
    TECHNIQUE = "TECHNIQUE", _("技術訓練")
    CROSS_TRAINING = "CROSS_TRAINING", _("交叉訓練")
    REST = "REST", _("休息")


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
    PLANNED = "PLANNED", _("已排定")
    COMPLETED = "COMPLETED", _("已完成")
    PARTIAL = "PARTIAL", _("部分完成")
    SKIPPED = "SKIPPED", _("未執行")


class DayType(models.TextChoices):
    HARD = "HARD", _("高強度日")
    MODERATE = "MODERATE", _("中強度日")
    EASY = "EASY", _("輕度日")
    REST = "REST", _("休息日")
    COMPETITION = "COMPETITION", _("比賽日")


def bilingual_name(name_zh, name_en=""):
    """名字要怎麼寫出來：中文介面「中文（English）」，英文介面只留英文。

    英文名沒填就退回中文——寧可看到中文，也好過畫面上空一格。
    """
    if not name_en:
        return name_zh
    if (get_language() or "").lower().startswith("en"):
        return name_en
    return f"{name_zh}（{name_en}）"


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

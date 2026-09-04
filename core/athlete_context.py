"""目前檢視中的運動員——挑一次，之後每一頁都跟著同一位。

以前每一頁各自讀 ?athlete=，側欄一按就掉回名單第一位，教練看完 A 的狀態總覽
再按「訓練日曆」會莫名其妙變成 B。現在挑過的人記在 session 裡，
換頁、按側欄、按麵包屑都留在同一位身上，不用每一頁重挑。
"""

from accounts.models import AthleteProfile
from core.models import Role
from core.permissions import athlete_ids_visible_to

SESSION_KEY = "atm_athlete_id"

#: 會跟著「目前運動員」走的頁面（側欄連結要帶上 ?athlete=）
ATHLETE_SCOPED_PAGES = ("dashboard", "calendar", "analytics", "nutrition", "injuries")


def _as_id(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _base_qs(visible):
    return AthleteProfile.objects.select_related("user", "primary_event").filter(id__in=visible)


def remember(request, athlete_id):
    """把目前檢視的運動員寫進 session（不存在的 session 就跳過，例如 API 呼叫）。"""
    session = getattr(request, "session", None)
    if session is None:
        return
    if session.get(SESSION_KEY) != athlete_id:
        session[SESSION_KEY] = athlete_id


def remembered_id(request):
    """上一次挑過、而且現在還看得到的運動員 id；沒有就 None。"""
    session = getattr(request, "session", None)
    if session is None:
        return None
    picked = session.get(SESSION_KEY)
    if picked is None:
        return None
    return picked if picked in set(athlete_ids_visible_to(request.user)) else None


def current_athlete(request):
    """
    決定目前檢視的運動員，依序：
    1. 網址上的 ?athlete=<id>（看得到才算）
    2. session 記住的上一位
    3. 名單第一位

    看不到的 id 一律忽略，也不會被記住——權限判斷跟以前一樣嚴。
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None

    visible = list(athlete_ids_visible_to(user))
    if not visible:
        return None
    qs = _base_qs(visible)

    picked = _as_id(request.GET.get("athlete"))
    if picked is not None and picked in visible:
        found = qs.filter(id=picked).first()
        if found is not None:
            remember(request, found.id)
            return found

    kept = _as_id(remembered_id(request))
    if kept is not None:
        found = qs.filter(id=kept).first()
        if found is not None:
            return found

    first = qs.first()
    if first is not None:
        remember(request, first.id)
    return first


def athlete_switcher(request):
    """教練／管理員用的切換清單；運動員本人不需要切換。"""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or user.role == Role.ATHLETE:
        return AthleteProfile.objects.none()
    return (
        AthleteProfile.objects.select_related("user", "primary_event")
        .filter(id__in=athlete_ids_visible_to(user))
        .order_by("user__first_name", "user__username")
    )

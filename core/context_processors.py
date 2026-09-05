"""樣板全域變數。"""

from django.conf import settings

from core.admin import user_may_use_admin
from core.athlete_context import ATHLETE_SCOPED_PAGES, athlete_switcher, current_athlete


def site_flags(request):
    """開發模式旗標，以及後台入口（網址可設定，權限要另外判斷）。"""
    return {
        "DEBUG": settings.DEBUG,
        # 後台網址可被 DJANGO_ADMIN_URL 換掉，樣板不可以再寫死 /admin/
        "ADMIN_URL": "/" + settings.ADMIN_URL,
        "CAN_USE_ADMIN": user_may_use_admin(getattr(request, "user", None)),
    }


#: 麵包屑與側欄共用的一份頁面清單：頁代號 → (模組, 頁名)
NAV_PAGES = {
    "athletes": ("運動員", "運動員列表"),
    "team": ("運動員", "全隊燈號總覽"),
    "dashboard": ("運動員", "運動員狀態總覽"),
    "plan": ("訓練管理", "計劃"),
    "calendar": ("訓練管理", "訓練日曆"),
    "session": ("訓練管理", "課表明細"),
    "library": ("訓練管理", "運動練習項目庫"),
    "analytics": ("數據與健康", "數據分析"),
    "nutrition": ("數據與健康", "營養與恢復"),
    "injuries": ("數據與健康", "傷患管理"),
}


def athlete_nav(request):
    """
    目前檢視中的運動員，供整個外框（頂欄切換器、側欄連結、麵包屑）共用。

    有了這一份，側欄連結才帶得上 ?athlete=，換頁不會掉回名單第一位；
    各頁也不用再自己 include 一次切換器。
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"nav_athlete": None, "nav_athletes": (), "nav_athlete_qs": "", "nav_pages": NAV_PAGES}

    athlete = current_athlete(request)
    return {
        "nav_athlete": athlete,
        "nav_athletes": athlete_switcher(request),
        # 側欄連結直接接在 url 後面：?athlete=12（沒有運動員時是空字串）
        "nav_athlete_qs": f"?athlete={athlete.id}" if athlete else "",
        "nav_scoped_pages": ATHLETE_SCOPED_PAGES,
        "nav_pages": NAV_PAGES,
    }

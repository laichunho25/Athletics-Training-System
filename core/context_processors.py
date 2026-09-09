"""樣板全域變數。"""

from django.conf import settings
from django.utils.translation import gettext_lazy as _

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
    "athletes": (_("運動員"), _("運動員列表")),
    "team": (_("運動員"), _("全隊燈號總覽")),
    "dashboard": (_("運動員"), _("運動員狀態總覽")),
    "plan": (_("訓練管理"), _("計劃")),
    "calendar": (_("訓練管理"), _("訓練日曆")),
    "session": (_("訓練管理"), _("課表明細")),
    "library": (_("訓練管理"), _("運動練習項目庫")),
    "analytics": (_("數據與健康"), _("數據分析")),
    "nutrition": (_("數據與健康"), _("營養與恢復")),
    "injuries": (_("數據與健康"), _("傷患管理")),
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

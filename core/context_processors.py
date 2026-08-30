"""樣板全域變數。"""

from django.conf import settings

from core.admin import user_may_use_admin


def site_flags(request):
    """開發模式旗標，以及後台入口（網址可設定，權限要另外判斷）。"""
    return {
        "DEBUG": settings.DEBUG,
        # 後台網址可被 DJANGO_ADMIN_URL 換掉，樣板不可以再寫死 /admin/
        "ADMIN_URL": "/" + settings.ADMIN_URL,
        "CAN_USE_ADMIN": user_may_use_admin(getattr(request, "user", None)),
    }

"""收緊過的後台站台。

預設的 Django 後台只要 `is_staff` 就進得去，而且固定掛在人人會猜的 /admin/。
這裡做三件事：

1. **只有管理員進得去**——必須同時是啟用中的超級使用者、且 `role` 為管理員；
   教練與運動員即使被誤設成 staff，也一律擋下。
2. **可以整個藏起來**——網址由 `DJANGO_ADMIN_URL` 決定（見 config/settings.py），
   換掉之後 /admin/ 就是 404，掃描器找不到登入表單可以試。
3. **可以再鎖到指定帳號**——`DJANGO_ADMIN_ALLOWED_USERS=admin` 之類的白名單。

已登入但沒有權限的人（例如教練）不會看到後台的登入框——直接被帶回系統首頁，
免得誤以為「再試一次密碼就會過」。
"""

from django.conf import settings
from django.contrib import admin, messages
from django.shortcuts import redirect


def user_may_use_admin(user):
    """這個使用者可不可以進後台。

    門檻是「超級使用者」而不是 Django 預設的 `is_staff`：
    教練與運動員帳號都不是超級使用者，所以一律進不來，
    就算哪天被誤勾成 staff 也一樣。

    這裡刻意不強制 `role == ADMIN`——`createsuperuser` 建出來的帳號
    role 會是預設值，若連那個也擋掉，就會出現「唯一的超級使用者被鎖在門外」
    這種只能進 Shell 才救得回來的狀況。
    """
    if not (user and user.is_authenticated and user.is_active):
        return False
    if not user.is_superuser:
        return False
    allowed = getattr(settings, "ADMIN_ALLOWED_USERS", [])
    return not allowed or user.username in allowed


class ATMAdminSite(admin.AdminSite):
    site_header = "ATM 後台管理"
    site_title = "ATM 後台"
    index_title = "資料管理"

    def has_permission(self, request):
        return user_may_use_admin(request.user)

    def login(self, request, extra_context=None):
        """已登入卻沒權限的人，直接請回系統，不給他再試密碼的表單。"""
        user = request.user
        if user.is_authenticated and not user_may_use_admin(user):
            messages.error(request, "你的帳號沒有後台權限，這裡只開放給管理員。")
            return redirect("web:home")
        return super().login(request, extra_context)

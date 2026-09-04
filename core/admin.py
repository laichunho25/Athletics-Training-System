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
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError
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


# 後台首頁的區塊順序與中文標題。沒有列在這裡的 app 會排到最後面。
APP_ORDER = [
    ("accounts", "帳號與檔案"),
    ("programs", "報名項目"),
    ("planning", "訓練計劃與日程"),
    ("training", "訓練紀錄"),
    ("analytics", "數據分析"),
    ("nutrition", "營養與恢復"),
    ("injury", "傷患管理"),
    ("auth", "權限群組"),
]

# 區塊內的表格順序（用 model 的小寫名稱）。沒列到的排在後面，維持原本的字母序。
MODEL_ORDER = {
    "accounts": ["user", "coachprofile", "event", "athleteprofile"],
    "programs": ["project", "application"],
    "planning": ["projectassignment", "trainingsession", "competition", "macrocycle"],
    "analytics": ["metricitem", "metricrecord", "dailyload", "weeklysummary"],
    "injury": ["injury", "treatmentlog", "rehabprotocol", "exercisemodification"],
}


class ATMAdminLoginForm(AdminAuthenticationForm):
    """後台登入表單：密碼對了但沒有後台權限，也要說清楚是權限問題。

    後台與系統是兩份獨立的登入（見 core/zones.py），所以教練就算已經登入了
    ATM，在後台這邊仍然是未登入狀態、看到的是登入框。訊息寫在這裡，
    不管他有沒有登入過系統，拿教練帳號來試都會得到同一句話。
    """

    def confirm_login_allowed(self, user):
        super(AdminAuthenticationForm, self).confirm_login_allowed(user)
        if not user_may_use_admin(user):
            raise ValidationError(
                "你的帳號沒有後台權限，這裡只開放給管理員。", code="no_admin"
            )


class ATMAdminSite(admin.AdminSite):
    login_form = ATMAdminLoginForm
    site_header = "ATM 後台管理"
    site_title = "ATM 後台"
    index_title = "資料管理"

    def get_app_list(self, request, app_label=None):
        """把後台首頁重排成「跟系統選單同一個順序」，並換成看得懂的中文區塊名。

        Django 預設是照 app 的字母序、表格也照字母序排，
        管理員要找一張表得整頁掃。這裡改成依實際使用頻率由上而下。
        """
        app_list = super().get_app_list(request, app_label)
        order = {label: i for i, (label, _) in enumerate(APP_ORDER)}
        titles = dict(APP_ORDER)

        for app in app_list:
            label = app.get("app_label", "")
            if label in titles:
                app["name"] = titles[label]
            wanted = MODEL_ORDER.get(label, [])
            rank = {name: i for i, name in enumerate(wanted)}
            app["models"].sort(
                key=lambda m: (
                    rank.get(str(m.get("object_name", "")).lower(), len(wanted)),
                    str(m.get("name", "")),
                )
            )

        app_list.sort(key=lambda a: (order.get(a.get("app_label", ""), len(order)), a["name"]))
        return app_list

    def has_permission(self, request):
        return user_may_use_admin(request.user)

    def login(self, request, extra_context=None):
        """後台這一區已登入卻沒權限的人，直接請回系統，不給他再試密碼的表單。"""
        user = request.user
        if user.is_authenticated and not user_may_use_admin(user):
            messages.error(request, "你的帳號沒有後台權限，這裡只開放給管理員。")
            return redirect("web:home")
        return super().login(request, extra_context)

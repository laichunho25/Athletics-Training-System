"""把 Django 預設的後台站台換成 ATM 自己的（只放行管理員）。

放在專案套件裡而不是 core/apps.py：同一個模組不能同時宣告兩個 default AppConfig。
"""

from django.contrib.admin.apps import AdminConfig


class ATMAdminConfig(AdminConfig):
    # 各 app 既有的 @admin.register 全部會掛到這個站台，不用逐一改寫
    default_site = "core.admin.ATMAdminSite"

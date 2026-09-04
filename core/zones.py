"""後台與系統各用一份登入狀態，兩邊可以同時掛著不同帳號。

Django 預設整個網站共用一個 `sessionid` cookie，所以在同一個瀏覽器裡
先登入後台、再登入 ATM，後面那一次會把前面那一次頂掉——反過來也一樣，
等於被逼著兩邊都用同一個帳號。

這裡把後台那一段路徑（settings.ADMIN_URL）的 cookie 換個名字：

    sessionid  ←→  adm_sessionid
    csrftoken  ←→  adm_csrftoken

作法是在最外層「進來時改回原名、出去時再改成後台專用的名字」，
中間的 SessionMiddleware / CsrfViewMiddleware 一行都不用動，
也不必自己重寫 session 的存取邏輯。

兩邊因此是各自獨立的登入：後台登出不會把系統那邊踢掉，反之亦然；
代價是同一個人若兩邊都要用，就得各登入一次。
"""

from django.conf import settings

#: 後台專用 cookie 的字首。改動它等於讓所有人的後台登入失效（要重新登入）。
ADMIN_PREFIX = "adm_"


def admin_aliases():
    """後台那一區要改名的 cookie：{原本的名字: 後台專用的名字}。

    每次呼叫都重讀 settings，測試裡用 override_settings 換 cookie 名稱也跟得上。
    """
    return {
        settings.SESSION_COOKIE_NAME: ADMIN_PREFIX + settings.SESSION_COOKIE_NAME,
        settings.CSRF_COOKIE_NAME: ADMIN_PREFIX + settings.CSRF_COOKIE_NAME,
    }


def is_admin_zone(path):
    """這個路徑算不算後台那一區（網址由 DJANGO_ADMIN_URL 決定）。"""
    return path.startswith("/" + settings.ADMIN_URL)


def _rename_incoming(request):
    """把 adm_* cookie 還原成 Django 認得的名字；沒有的話就當作沒帶 cookie。"""
    for base, alias in admin_aliases().items():
        if alias in request.COOKIES:
            request.COOKIES[base] = request.COOKIES[alias]
        else:
            # 系統那邊的 cookie 在後台一律不算數，否則又變回共用一份登入
            request.COOKIES.pop(base, None)


def _rename_outgoing(response):
    """把這次回應要寫回去的 cookie 改成後台專用的名字（連同刪除指令一起）。"""
    cookies = getattr(response, "cookies", None)
    if not cookies:
        return
    for base, alias in admin_aliases().items():
        morsel = cookies.pop(base, None)
        if morsel is None:
            continue
        cookies[alias] = morsel.value
        renamed = cookies[alias]
        # path / expires / max-age / secure / httponly / samesite 原樣搬過去，
        # 登出時的「立刻過期」也是靠這幾個屬性，不能漏。
        for key, value in morsel.items():
            if value != "":
                renamed[key] = value


class SplitAdminSessionMiddleware:
    """後台與系統各自記各自的登入。必須放在 MIDDLEWARE 最上面（最外層）。

    進來的時候要比 SessionMiddleware 早改名，出去的時候要比
    CsrfViewMiddleware 晚改名——放最外層剛好兩邊都滿足。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        in_admin = is_admin_zone(request.path)
        if in_admin:
            _rename_incoming(request)
        response = self.get_response(request)
        if in_admin:
            _rename_outgoing(response)
        return response

"""介面語言：帳號存一個，未登入的人存 cookie。

Django 4 之後 LocaleMiddleware 只看 cookie 與 Accept-Language，沒有 session 那條路，
所以登入之後要自己再蓋一次——不然換一台電腦登入，語言又跳回瀏覽器猜的那個。

順序（config.settings.MIDDLEWARE）：
    LocaleMiddleware          → 未登入的人（首頁／登入頁／公開報名）
    AuthenticationMiddleware
    UserLanguageMiddleware    → 登入的人以帳號上的設定為準
"""

from django.conf import settings
from django.utils import translation


def supported(code):
    """把傳進來的語言碼收斂成 settings.LANGUAGES 裡真的有的那個，否則回 None。"""
    if not code:
        return None
    codes = {c for c, _ in settings.LANGUAGES}
    if code in codes:
        return code
    # zh-hant-hk / en-us 這種也認得
    base = code.split("-")[0].lower()
    for c in codes:
        if c.split("-")[0].lower() == base:
            return c
    return None


class UserLanguageMiddleware:
    """登入的使用者一律用帳號上存的語言。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        lang = supported(getattr(user, "language", None)) if user and user.is_authenticated else None
        if lang:
            translation.activate(lang)
            request.LANGUAGE_CODE = lang
        response = self.get_response(request)
        if lang:
            response.setdefault("Content-Language", lang)
        return response

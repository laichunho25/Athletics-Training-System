"""樣板全域變數。"""

from django.conf import settings


def site_flags(request):
    """讓樣板能判斷是否為開發模式（示範帳密只在本機顯示）。"""
    return {"DEBUG": settings.DEBUG}

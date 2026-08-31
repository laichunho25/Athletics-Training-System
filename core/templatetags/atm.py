"""課表頁用到的小工具 filter。"""

from django import template

register = template.Library()


@register.filter
def get_field(obj, name):
    """在 {% for name, label in activity_fields %} 裡取出 obj 的那個欄位。

    六個必要欄位（組數/次數/距離/重量/強度/休息時間）都是同一種顯示方式，
    有了這個就不用把同一段 HTML 抄六遍。
    """
    return getattr(obj, name, "")


@register.filter
def lookup(mapping, key):
    """dict[key]，取不到回 None（模板裡沒有下標語法）。"""
    try:
        return mapping.get(key)
    except AttributeError:
        return None

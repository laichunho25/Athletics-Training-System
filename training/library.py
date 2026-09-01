"""訓練活動庫的自動補齊。

活動庫是「課表寫得出的動作」與「數據分析追蹤得到的項目」共用的來源，
空的話兩邊都會變成一片空白的下拉，所以第一次用到就把預設清單種進去
（種子指令本身可重覆執行，這裡只在完全空的時候呼叫）。
"""

import io

from django.core.management import call_command

from training.models import ActivityDefinition


def ensure_activity_library():
    """活動庫是空的就載入預設清單；回傳目前的活動數。"""
    if ActivityDefinition.objects.exists():
        return ActivityDefinition.objects.count()
    # 種子指令會印一行結果，這裡是背景補資料，不用吵到畫面／測試輸出
    call_command("seed_activities", verbosity=0, stdout=io.StringIO())
    return ActivityDefinition.objects.count()


def library_groups(definitions):
    """把活動庫依分類分組（空的分類不出現，免得下拉裡都是點不到的標題）。"""
    from training.models import ActivityCategory

    groups = []
    for value, label in ActivityCategory.choices:
        rows = [d for d in definitions if d.category == value]
        if rows:
            groups.append({"value": value, "label": label, "rows": rows})
    other = [d for d in definitions if d.category not in dict(ActivityCategory.choices)]
    if other:
        groups.append({"value": "", "label": "其他", "rows": other})
    return groups

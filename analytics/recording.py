"""登一筆（或一整堂課的很多組）數據紀錄。

數據分析頁和訓練日曆的課表頁都會用到這一份：
兩邊寫進去的是同一張 MetricRecord，所以在哪邊登都一樣，不用重打第二次。
"""

from decimal import Decimal, InvalidOperation

from analytics.models import (
    MetricRecord,
    domains_for_session_type,
)


class RecordError(Exception):
    """表單填的東西有問題（訊息直接給使用者看）。"""


def _raw(seq, i):
    return (seq[i] if i < len(seq) else "").strip()


def _num(seq, i, cast):
    raw = _raw(seq, i)
    if not raw:
        return None
    try:
        return cast(raw)
    except (TypeError, ValueError, InvalidOperation):
        return None


def _decimal(seq, i, label, problems):
    """一格數值：空的回 None，填錯的記一筆問題（不擋掉整列）。"""
    raw = _raw(seq, i)
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        problems.append(f"第 {i + 1} 組的{label}不是有效數字。")
        return None


def session_allows(session, item):
    """這堂課的課別，能不能登這個範疇的數據。"""
    if session is None:
        return True
    return item.domain in domains_for_session_type(session.session_type)


def create_records(*, athlete, item, session, post, on_date, competition=None):
    """把表單上的每一列（每一組）各存成一筆紀錄。

    數值不是必填：挑好項目就登得進來，先留一組空的、之後在數據分析補值也可以。
    回傳 (建立的紀錄, 提示訊息)。
    """
    if session is not None and not session_allows(session, item):
        raise RecordError(
            f"「{session.get_session_type_display()}」的課表不能登{item.get_domain_display()}。"
        )

    context = post.get("context", "")
    note = post.get("note", "")
    targets = post.getlist("target_value")
    values = post.getlist("value")
    weights = post.getlist("weight")
    reps_list = post.getlist("reps")
    rests = post.getlist("rest_sec")
    # 田徑練習用「強度要求」取代重量：一列一組，各組可以要求不同強度
    intensities = post.getlist("intensity")
    dones = post.getlist("completed")
    # 休息時間可以用分鐘（預設）或秒填，資料庫一律存秒
    rest_factor = 1 if post.get("rest_unit") == "sec" else 60

    columns = (targets, values, weights, intensities, reps_list, rests)
    row_count = max([len(c) for c in columns] + [1])
    # 數值不是必填——只要挑了項目就登得進來，所以「這一列有沒有填東西」
    # 決定它算不算一組；整張表都空白就當成一組空紀錄（之後再回來補值）。
    rows = [i for i in range(row_count) if any(_raw(c, i) for c in columns)] or [0]
    multi = len(rows) > 1

    # 單位本身就是 kg 的項目（背蹲舉、臥推…），表單只留「數值」一格，
    # 重量就是那個數值，這裡自動補上去，噸位與圖表照樣算得出來。
    unit_is_weight = (item.unit or "").strip().lower() == "kg"

    created, problems = [], []
    for position, i in enumerate(rows):
        target = _decimal(targets, i, "目標數值", problems)
        value = _decimal(values, i, "完成數值", problems)
        weight = _num(weights, i, Decimal)
        if weight is None and unit_is_weight:
            weight = value
        # 分鐘可以填 1.5 這種小數，換算成秒之後才取整數
        rest = _num(rests, i, float)
        created.append(
            MetricRecord.objects.create(
                athlete=athlete,
                item=item,
                session=session,
                competition=competition,
                date=on_date,
                target_value=target,
                value=value,
                set_no=(position + 1) if multi else None,
                weight_kg=weight,
                intensity=_raw(intensities, i)[:20],
                reps=_num(reps_list, i, int),
                rest_sec=None if rest is None else round(rest * rest_factor),
                completed=(dones[i] if i < len(dones) else "1") != "0",
                context=context,
                note=note,
            )
        )

    if len(created) == 1:
        r = created[0]
        shown = f"{r.value}{item.unit}" if r.value is not None else "（未填數值）"
        message = f"已記錄 {item.name} {shown}（{r.date}）。"
    else:
        failed = sum(1 for r in created if not r.completed)
        message = (
            f"已記錄 {item.name} {len(created)} 組（{created[0].date}）"
            + (f"，其中 {failed} 組未成功完成。" if failed else "。")
        )
    if problems:
        message += " " + "；".join(problems)
    return created, message

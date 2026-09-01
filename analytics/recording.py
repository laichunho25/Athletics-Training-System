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


def _num(seq, i, cast):
    raw = (seq[i] if i < len(seq) else "").strip()
    if not raw:
        return None
    try:
        return cast(raw)
    except (TypeError, ValueError, InvalidOperation):
        return None


def session_allows(session, item):
    """這堂課的課別，能不能登這個範疇的數據。"""
    if session is None:
        return True
    return item.domain in domains_for_session_type(session.session_type)


def create_records(*, athlete, item, session, post, on_date, competition=None):
    """把表單上的每一列（每一組）各存成一筆紀錄。

    回傳 (建立的紀錄, 提示訊息)；一列都沒填就丟 RecordError。
    """
    if session is not None and not session_allows(session, item):
        raise RecordError(
            f"「{session.get_session_type_display()}」的課表不能登{item.get_domain_display()}。"
        )

    context = post.get("context", "")
    note = post.get("note", "")
    values = post.getlist("value")
    weights = post.getlist("weight")
    reps_list = post.getlist("reps")
    rests = post.getlist("rest_sec")
    dones = post.getlist("completed")
    multi = len(values) > 1

    # 單位本身就是 kg 的項目（背蹲舉、臥推…），表單只留「數值」一格，
    # 重量就是那個數值，這裡自動補上去，噸位與圖表照樣算得出來。
    unit_is_weight = (item.unit or "").strip().lower() == "kg"

    created, problems = [], []
    for i, raw_value in enumerate(values):
        raw_value = raw_value.strip()
        if not raw_value:
            continue  # 空白列＝加了組卻沒填，跳過
        try:
            value = Decimal(raw_value)
        except (InvalidOperation, ValueError):
            problems.append(f"第 {i + 1} 組的數值不是有效數字。")
            continue
        weight = _num(weights, i, Decimal)
        if weight is None and unit_is_weight:
            weight = value
        created.append(
            MetricRecord.objects.create(
                athlete=athlete,
                item=item,
                session=session,
                competition=competition,
                date=on_date,
                value=value,
                set_no=(i + 1) if multi else None,
                weight_kg=weight,
                reps=_num(reps_list, i, int),
                rest_sec=_num(rests, i, int),
                completed=(dones[i] if i < len(dones) else "1") != "0",
                context=context,
                note=note,
            )
        )

    if not created:
        raise RecordError(
            "；".join(problems) if problems else "沒有記錄到任何一組，請至少填一個數值。"
        )

    if len(created) == 1:
        r = created[0]
        message = f"已記錄 {item.name} {r.value}{item.unit}（{r.date}）。"
    else:
        failed = sum(1 for r in created if not r.completed)
        message = (
            f"已記錄 {item.name} {len(created)} 組（{created[0].date}）"
            + (f"，其中 {failed} 組未成功完成。" if failed else "。")
        )
    if problems:
        message += " " + "；".join(problems)
    return created, message

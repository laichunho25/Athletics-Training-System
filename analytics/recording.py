"""登一筆（或一整堂課的很多組）數據紀錄。

數據分析頁和訓練日曆的課表頁都會用到這一份：
兩邊寫進去的是同一張 MetricRecord，所以在哪邊登都一樣，不用重打第二次。
"""

from decimal import Decimal, InvalidOperation

from django.db.models import F

from analytics.models import (
    MetricRecord,
    TrainingStatus,
    block_choices,
    domains_for_session_type,
)


def _clean_block(raw):
    """課表區塊：不認得的值一律當成「沒指定」。"""
    raw = (raw or "").strip()
    return raw if raw in [v for v, _ in block_choices()] else ""


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
    # 這次所有組共用同一個狀態註記（那一天就是同一個狀態）
    status = post.get("status", "")
    if status not in TrainingStatus.values:
        status = ""
    # 這一整批是課表上哪一段做的（熱身／正課／補充練習／恢復練習）——
    # 同一個動作放在熱身和放在正課本來就不是同一件事，分開記才看得準
    block = _clean_block(post.get("block"))
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
                status=status,
                block=block,
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


# ------------------------------------------------ 修改已經登進去的紀錄
#
# 課表頁與數據分析頁改的是同一張 MetricRecord，所以這一份兩邊共用：
# 表單欄位名一律是「欄位_紀錄id」（例 value_37），一張表可以同時送很多筆，
# 按某一列的 ✓ 就多送一個 only=37，只改那一列。


#: 表單上改得動的欄位
EDITABLE_FIELDS = (
    "set_no", "target_value", "value", "weight", "intensity", "reps",
    "rest_sec", "completed", "status", "block", "session", "context",
)


def _field(post, name, record_id):
    """讀「欄位_id」這一格；表單沒送這一格就回 None（代表不要動這個欄位）。"""
    key = f"{name}_{record_id}"
    return post.get(key) if key in post else None


def _edit_decimal(raw, label, record_id, problems):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        problems.append(f"第 {record_id} 筆的{label}不是有效數字")
        return "skip"


def update_records(post, records, only=None, session_lookup=None):
    """把表單上的內容寫回這些紀錄。

    records 是這一頁列得出來的紀錄（限定範圍，避免別人的紀錄被改到）。
    only 有值就只改那一筆。回傳 (改了幾筆, 問題清單)。

    session_lookup 給得出來的話，「program」那一格也改得動：
    它收一個 id 回傳那堂課（找不到或不是這名運動員的就回 None）。
    課表頁不給這個參數——那邊的紀錄本來就屬於當下那一堂課。
    """
    if only:
        records = [r for r in records if str(r.pk) == str(only)]
    # 休息時間預設以分鐘填（可填 1.5），只有明說 sec 才當秒
    rest_factor = 1 if post.get("rest_unit") == "sec" else 60

    changed, problems = 0, []
    touched_days = {}
    for record in records:
        rid = record.pk
        # 這一列完全沒被送出來（例如收合起來沒展開）就跳過，不要清空資料
        if not any(f"{name}_{rid}" in post for name in EDITABLE_FIELDS):
            continue

        fields = []

        def take(name, value):
            if getattr(record, name) != value:
                setattr(record, name, value)
                fields.append(name)

        for name, attr, label in (
            ("target_value", "target_value", "目標數值"),
            ("value", "value", "完成數值"),
            ("weight", "weight_kg", "重量"),
        ):
            raw = _field(post, name, rid)
            if raw is None:
                continue
            parsed = _edit_decimal(raw, label, rid, problems)
            if parsed != "skip":
                take(attr, parsed)

        # 組號可以直接改成想要的次序（例：把第 3 組改成 1），
        # 存完之後同一天會重新排成 1、2、3…（見 resequence）
        raw = _field(post, "set_no", rid)
        if raw is not None:
            raw = raw.strip()
            if not raw:
                take("set_no", None)
            else:
                order = _num([raw], 0, int)
                if order is None or order < 1:
                    problems.append(f"第 {rid} 筆的組號要填 1 以上的整數")
                else:
                    take("set_no", order)

        raw = _field(post, "reps", rid)
        if raw is not None:
            reps = _num([raw], 0, int)
            if raw.strip() and reps is None:
                problems.append(f"第 {rid} 筆的次數不是有效數字")
            else:
                take("reps", None if reps is None else max(0, reps))

        raw = _field(post, "rest_sec", rid)
        if raw is not None:
            rest = _num([raw], 0, float)
            if raw.strip() and rest is None:
                problems.append(f"第 {rid} 筆的休息時間不是有效數字")
            else:
                take("rest_sec", None if rest is None else max(0, round(rest * rest_factor)))

        raw = _field(post, "intensity", rid)
        if raw is not None:
            take("intensity", raw.strip()[:20])

        raw = _field(post, "status", rid)
        if raw is not None:
            take("status", raw if raw in TrainingStatus.values else "")

        raw = _field(post, "block", rid)
        if raw is not None:
            take("block", _clean_block(raw))

        # program：登錯課、或事後才想把這一組掛回某一堂課，都在這裡改
        raw = _field(post, "session", rid)
        if raw is not None and session_lookup is not None:
            raw = raw.strip()
            if not raw:
                if record.session_id is not None:
                    record.session = None
                    fields.append("session")
            else:
                found = session_lookup(raw)
                if found is None:
                    problems.append(f"第 {rid} 筆指定的 program 找不到")
                elif not session_allows(found, record.item):
                    problems.append(
                        f"第 {rid} 筆：「{found.get_session_type_display()}」"
                        f"的課不能掛{record.item.get_domain_display()}的紀錄"
                    )
                elif record.session_id != found.pk:
                    record.session = found
                    fields.append("session")

        raw = _field(post, "context", rid)
        if raw is not None:
            take("context", raw[:120])

        raw = _field(post, "completed", rid)
        if raw is not None:
            take("completed", raw != "0")

        if fields:
            record.save(update_fields=fields + ["updated_at"])
            changed += 1
            if "set_no" in fields:
                key = (record.athlete_id, record.item_id, record.date)
                touched_days.setdefault(key, []).append(record.pk)

    for (athlete_id, item_id, on_date), picked in touched_days.items():
        resequence(athlete_id, item_id, on_date, priority=picked)
    return changed, problems


# ------------------------------------------------ 組數次序
#
# 同一天的組是有先後的（第 1 組跑得比第 5 組快是正常的），
# 所以組號要能改：登錯次序、或事後補一組插在中間，都不用刪掉重打。


def _day_rows(athlete_id, item_id, on_date):
    """同一天、同一個項目的所有組，照現在的次序排。"""
    return list(
        MetricRecord.objects.filter(
            athlete_id=athlete_id, item_id=item_id, date=on_date
        ).order_by(F("set_no").asc(nulls_first=True), "id")
    )


def resequence(athlete_id, item_id, on_date, priority=()):
    """把同一天的組號重新排成 1、2、3…（只有一組的日子不動）。

    priority 是「剛剛被改到組號的那幾筆」：兩筆撞到同一個號碼時它排前面，
    這樣把第 3 組改成 1，第 3 組就真的變成第 1 組，其餘往後推。
    """
    rows = _day_rows(athlete_id, item_id, on_date)
    if len(rows) < 2:
        return 0
    picked = set(priority)
    rows.sort(key=lambda r: (r.set_no or 0, 0 if r.pk in picked else 1, r.pk))
    fixed = 0
    for position, record in enumerate(rows, start=1):
        if record.set_no != position:
            record.set_no = position
            record.save(update_fields=["set_no", "updated_at"])
            fixed += 1
    return fixed


def move_record(record, direction):
    """把一組往前／往後挪一格，並重新編號同一天的組。

    回傳有沒有真的挪動（已經在最前面還要往前就回 False）。
    """
    step = -1 if direction == "up" else 1
    rows = _day_rows(record.athlete_id, record.item_id, record.date)
    position = next((i for i, r in enumerate(rows) if r.pk == record.pk), None)
    target = None if position is None else position + step
    if position is None or target is None or not (0 <= target < len(rows)):
        return False
    rows[position], rows[target] = rows[target], rows[position]
    for order, row in enumerate(rows, start=1):
        if row.set_no != order:
            row.set_no = order
            row.save(update_fields=["set_no", "updated_at"])
    return True


def edit_message(changed, problems, scope=""):
    """更新完之後給使用者看的一句話。"""
    if changed:
        text = f"已更新 {changed} 筆紀錄{scope}。"
    else:
        text = "沒有任何一筆需要更新（內容跟原本一樣）。"
    if problems:
        text += "　" + "；".join(problems) + "（這幾格沒有存進去）。"
    return text

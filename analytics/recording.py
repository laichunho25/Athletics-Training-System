"""登一筆（或一整堂課的很多組）數據紀錄。

數據分析頁和訓練日曆的課表頁都會用到這一份：
兩邊寫進去的是同一張 MetricRecord，所以在哪邊登都一樣，不用重打第二次。
"""

import re
from decimal import Decimal, InvalidOperation

from django.db.models import F
from django.utils.translation import gettext_lazy as _

from analytics.models import (
    MetricRecord,
    TrainingStatus,
    block_choices,
    domains_for_session_type,
)


def _clean_block(raw):
    """課表區塊：不認得的值一律當成「沒指定」。"""
    raw = (raw or "").strip()
    return raw if raw in [v for v, _unused in block_choices()] else ""


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
        problems.append(_("第 %(v0)s 組的%(v1)s不是有效數字。") % {"v0": i + 1, "v1": label})
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
            _("「%(v0)s」的課表不能登%(v1)s。") % {"v0": session.get_session_type_display(), "v1": item.get_domain_display()}
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
    # 距離：課表正課那一欄的重點，逐組可以不一樣（第 1 組 150m、第 2 組 120m）
    distances = post.getlist("distance_m")
    dones = post.getlist("completed")
    # 休息時間可以用分鐘（預設）或秒填，資料庫一律存秒
    rest_factor = 1 if post.get("rest_unit") == "sec" else 60

    columns = (targets, values, weights, intensities, distances, reps_list, rests)
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
        target = _decimal(targets, i, _("目標數值"), problems)
        value = _decimal(values, i, _("完成數值"), problems)
        weight = _num(weights, i, Decimal)
        if weight is None and unit_is_weight:
            weight = value
        distance = _decimal(distances, i, _("距離"), problems)
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
                distance_m=distance,
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
        shown = f"{r.value}{item.unit}" if r.value is not None else _("（未填數值）")
        message = _("已記錄 %(v0)s %(v1)s（%(v2)s）。") % {"v0": item.name, "v1": shown, "v2": r.date}
    else:
        failed = sum(1 for r in created if not r.completed)
        message = (
            _("已記錄 %(v0)s %(v1)s 組（%(v2)s）") % {"v0": item.name, "v1": len(created), "v2": created[0].date}
            + (_("，其中 %(v0)s 組未成功完成。") % {"v0": failed} if failed else "。")
        )
    if problems:
        message += " " + "；".join(problems)
    return created, message



# ------------------------------------------- 課表的一行 → 這一行要登的組數
#
# 教練在課表寫了「深蹲 3 組 × 5 次 @ 100kg，休 2 分鐘」，這一行本身已經說明
# 待會兒要記幾組、每一組的目標是什麼。與其叫運動員練完再把同一批數字打第二次，
# 排課的時候就先把那 3 組空白紀錄開好——練完只要填「完成數值」那一格。

#: 一行課表最多先開幾組（寫錯成「30 組」時不要一次塞三十列進去）
MAX_PLANNED_SETS = 20


def _first_int(text):
    """「3 組」「3-4 組」「左/右腳 15 次」→ 3 / 3 / 15；沒有數字回 None。"""
    hit = re.search(r"\d+", text or "")
    return int(hit.group()) if hit else None


def _first_decimal(text):
    """「100kg」「82.5 公斤」→ Decimal；「body weight」這種純文字回 None。"""
    hit = re.search(r"\d+(?:\.\d+)?", text or "")
    return Decimal(hit.group()) if hit else None


#: 休息時間裡的時間單位 → 換算成秒的倍數
_REST_UNITS = {"分鐘": 60, "分": 60, "min": 60, "m": 60, "秒": 1, "sec": 1, "s": 1}


def _rest_seconds(text):
    """「30s」「每組 2 分鐘」「1 分 30 秒」→ 秒數；「walk back」這種回 None。

    「每次 5 分鐘 / 每組 15 分鐘」這種一格寫兩件事的，只取斜線前的第一段。
    """
    text = (text or "").strip()
    if not text:
        return None
    head = re.split(r"[/、;；]", text)[0]
    pairs = re.findall(r"(\d+(?:\.\d+)?)\s*(分鐘|分|秒|min|sec|s|m)", head, re.I)
    if pairs:
        return round(sum(float(n) * _REST_UNITS[u.lower()] for n, u in pairs))
    # 只寫了一個數字（例：90）就當成秒
    hit = re.search(r"\d+(?:\.\d+)?", head)
    return round(float(hit.group())) if hit else None


def plan_distance(activity):
    """課表這一行寫的距離換成數字（「150 米」→ 150）；寫不出數字回 None。

    登記錄時「距離」那一格先帶這個值進去，不用把課表上的米數再打一次。
    """
    return _first_decimal(activity.distance) if activity is not None else None


def _set_row(activity):
    """課表這一行寫了什麼（重量／次數／休息／強度），照抄成一組紀錄的內容。"""
    return {
        "weight_kg": _first_decimal(activity.weight),
        # 課表寫「150 米」「30m」，紀錄留的是數字，登記錄時就先帶過來
        "distance_m": _first_decimal(activity.distance),
        "reps": _first_int(activity.reps),
        "rest_sec": _rest_seconds(activity.rest),
        "intensity": (activity.intensity or "").strip()[:20],
    }


def planned_sets_for(activity):
    """課表這一行要開幾組、每一組先帶什麼進去。

    「組數」那一格看得出數字才會開（教練沒寫組數＝還沒定，不先開空列）。
    """
    count = _first_int(activity.sets)
    if not count or count < 1:
        return []
    count = min(count, MAX_PLANNED_SETS)
    row = _set_row(activity)
    return [dict(row, set_no=i if count > 1 else None) for i in range(1, count + 1)]


def open_planned_records(activity, item, *, athlete, session):
    """依課表這一行的組數，先開好同樣筆數的空白紀錄。

    這一行（同一個項目、同一個區塊）底下已經有紀錄就不動——
    運動員填好的成績永遠不會被排課的動作蓋掉。回傳開了幾筆。
    """
    if item is None:
        return 0
    rows = planned_sets_for(activity)
    if not rows:
        return 0
    if MetricRecord.objects.filter(
        session=session, item=item, block=activity.block
    ).exists():
        return 0
    MetricRecord.objects.bulk_create(
        [
            MetricRecord(
                athlete=athlete,
                item=item,
                session=session,
                date=session.date,
                block=activity.block,
                **row,
            )
            for row in rows
        ]
    )
    return len(rows)


# --------------------------------------- 課表的一行 → 這一行要登的數據項目
#
# 課表只排「今天做什麼」，數字一律填在課表下半部的「訓練紀錄」。
# 按某一行的「登記錄」時走這裡：同名的數據項目沒有就開一個，
# 課表寫了「3 組」就先把 3 組空白紀錄開好，練完只要補「完成數值」那一格。


def ensure_item_for_activity(activity, domain, *, user=None):
    """課表某一行對應的數據項目（必要時建立），順便開好課表寫明的組數。

    回傳 (item, 開了幾組空白紀錄)；範疇不認得就丟 RecordError。
    """
    from analytics.models import (
        MetricDomain,
        item_for_name,
        metric_category_for_activity,
    )

    if domain not in MetricDomain.values:
        raise RecordError(_("不認得的數據範疇。"))

    definition = activity.definition if activity.definition_id else None
    item = item_for_name(
        domain,
        activity.name,
        user=user,
        category=metric_category_for_activity(definition.category if definition else ""),
        name_en=definition.name_en if definition else "",
    )
    if item is None:
        raise RecordError(_("這一行沒有活動名稱，登不了數據。"))

    session = activity.session
    opened = open_planned_records(
        activity, item, athlete=session.athlete, session=session
    )
    if not opened and not MetricRecord.objects.filter(
        session=session, item=item, block=activity.block
    ).exists():
        # 課表沒寫組數的動作也要有一列可以填，不然點進來是一片空白
        MetricRecord.objects.create(
            athlete=session.athlete,
            item=item,
            session=session,
            date=session.date,
            block=activity.block,
            **_set_row(activity),
        )
        opened = 1
    return item, opened


def session_records(session, item, block=""):
    """這堂課、這個項目（可再限定區塊）底下的每一組，照組號排。

    課表頁的「紀錄明細」就是這一份——一堂課只有一天，
    所以不像數據分析那樣要再按日期分組，直接一組一列。
    """
    rows = MetricRecord.objects.filter(session=session, item=item)
    if block:
        rows = rows.filter(block=block)
    return list(rows.order_by(F("set_no").asc(nulls_first=True), "id"))


def session_domain_tables(session):
    """這堂課登了的數據，照範疇（田徑練習訓練紀錄／重量訓練紀錄…）分開列。

    課表頁最底下那幾張表就是這一份：內容全部來自上面「新增一筆紀錄／
    紀錄明細」填進去的東西，不用在課表上再登第二次。
    """
    from analytics.models import MetricDomain

    records = list(
        MetricRecord.objects.filter(session=session)
        .select_related("item")
        .order_by("item__domain", "item__name", F("set_no").asc(nulls_first=True), "id")
    )
    domain_labels = dict(MetricDomain.choices)
    block_labels = dict(block_choices())

    tables = {}
    for r in records:
        table = tables.setdefault(
            r.item.domain,
            {
                "domain": r.item.domain,
                "label": domain_labels.get(r.item.domain, r.item.domain),
                "items": {},
                "sets": 0,
                "filled": 0,
            },
        )
        table["sets"] += 1
        if r.value is not None:
            table["filled"] += 1
        row = table["items"].setdefault(
            r.item_id,
            {"item": r.item, "block_label": block_labels.get(r.block, ""), "records": []},
        )
        row["records"].append(r)

    ordered = []
    for domain in MetricDomain.values:
        table = tables.get(domain)
        if not table:
            continue
        table["items"] = list(table["items"].values())
        ordered.append(table)
    return ordered


# ------------------------------------------------ 修改已經登進去的紀錄
#
# 課表頁與數據分析頁改的是同一張 MetricRecord，所以這一份兩邊共用：
# 表單欄位名一律是「欄位_紀錄id」（例 value_37），一張表可以同時送很多筆，
# 按某一列的 ✓ 就多送一個 only=37，只改那一列。


#: 表單上改得動的欄位
EDITABLE_FIELDS = (
    "set_no", "target_value", "value", "weight", "distance_m", "intensity", "reps",
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
        problems.append(_("第 %(v0)s 筆的%(v1)s不是有效數字") % {"v0": record_id, "v1": label})
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
            ("target_value", "target_value", _("目標數值")),
            ("value", "value", _("完成數值")),
            ("weight", "weight_kg", _("重量")),
            ("distance_m", "distance_m", _("距離")),
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
                    problems.append(_("第 %(v0)s 筆的組號要填 1 以上的整數") % {"v0": rid})
                else:
                    take("set_no", order)

        raw = _field(post, "reps", rid)
        if raw is not None:
            reps = _num([raw], 0, int)
            if raw.strip() and reps is None:
                problems.append(_("第 %(v0)s 筆的次數不是有效數字") % {"v0": rid})
            else:
                take("reps", None if reps is None else max(0, reps))

        raw = _field(post, "rest_sec", rid)
        if raw is not None:
            rest = _num([raw], 0, float)
            if raw.strip() and rest is None:
                problems.append(_("第 %(v0)s 筆的休息時間不是有效數字") % {"v0": rid})
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
                    problems.append(_("第 %(v0)s 筆指定的 program 找不到") % {"v0": rid})
                elif not session_allows(found, record.item):
                    problems.append(
                        _("第 %(v0)s 筆：「%(v1)s」的課不能掛%(v2)s的紀錄") % {"v0": rid, "v1": found.get_session_type_display(), "v2": record.item.get_domain_display()}
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
        text = _("已更新 %(v0)s 筆紀錄%(v1)s。") % {"v0": changed, "v1": scope}
    else:
        text = _("沒有任何一筆需要更新（內容跟原本一樣）。")
    if problems:
        text += "　" + "；".join(problems) + _("（這幾格沒有存進去）。")
    return text

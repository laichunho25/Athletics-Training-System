"""數據紀錄清單：一張平鋪的清單，挑幾筆出來再分析。

三個範疇（田徑練習／重量訓練／比賽數據）共用同一套版面：把課表上登過的
紀錄全部攤成一張清單，用年份月份和關鍵字挑出想看的那幾筆，再挑一個方向：

    perf    表現與時間 —— 這幾筆本身做得怎樣、跟隊上其他人比是什麼水準
    period  同一組跨時段 —— 一樣的距離／動作／項目，在不同年月時期怎麼變
    cross   拼入其他數據 —— 同一段時間的另一種訓練與身體結構一起看

三個範疇看的數字不一樣，字眼也跟著不一樣，全部集中在 SPECS 裡：

    田徑練習  記秒，越小越好；量是總距離 (m)，第二個切法是強度要求
    重量訓練  記公斤，越大越好；量是總噸位 (kg)，第二個切法是次數
    比賽數據  記成績（秒），越小越好；量是總距離 (m)，第二個切法是哪一場比賽
"""

import calendar
import statistics
from datetime import date

from django.db.models import DecimalField, F, Q
from django.db.models.functions import Cast, Coalesce
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from analytics.body_strength import estimate_1rm
from analytics.models import (
    MetricDomain,
    MetricRecord,
    TrainingStatus,
    block_choices,
)

#: 清單一頁列幾筆
PAGE_SIZE = 15

#: 一次最多挑幾筆來分析
MAX_PICKS = 400

#: 跨時段比較時最多列幾組（挑做得最多的那幾組）
MAX_GROUPS = 6

#: 「跟隊上其他人比」最多列幾個人
MAX_PEERS = 8

GROUPINGS = [
    ("month", _lazy("分月份")),
    ("year", _lazy("分年份")),
    ("phase", _lazy("分訓練時期")),
]

DEFAULT_SORT, DEFAULT_DIR = "date", "desc"

#: 強度欄寫「全力」這種字時，當成 100% 來算平均
MAXIMAL_WORDS = {"全力", "全速", "最大", "max", "maximal", "all out", "all-out"}


def _col(key, label, num=False):
    return {"key": key, "label": label, "num": num}


#: 三個範疇各自的欄位、單位與字眼。清單、分析、圖表的字全部從這裡拿。
SPECS = {
    MetricDomain.TRACK: {
        "domain": MetricDomain.TRACK,
        "title": _lazy("田徑練習訓練紀錄"),
        "fold_key": "track-log",
        "lower_better": True,
        "unit_word": _lazy("秒"),
        "row_word": _lazy("組"),
        "picked_label": _lazy("挑出來的組數"),
        "best_label": _lazy("最佳 / 平均（秒）"),
        "value_label": _lazy("完成數值（秒）"),
        "target_label": _lazy("目標數值（秒）"),
        "volume_label": _lazy("訓練量（總距離）"),
        "volume_unit": "m",
        "group_label": _lazy("距離"),
        "split_label": _lazy("強度要求"),
        "group_title": _lazy("照距離分"),
        "split_title": _lazy("照強度分"),
        "search_hint": _lazy("打 150 就出所有 150m；也可以打反覆跑、90%、正課、傷害治療"),
        "empty": _lazy("還沒有田徑練習的紀錄。到課表那一天的活動旁按「登記錄」就可以開始記。"),
        "perf_title": _lazy("表現與時間"),
        "perf_hint": _lazy("挑出來的每一組按日期排開，虛線是課表要求的目標"),
        "period_title": _lazy("同一個距離，在不同時段的變化"),
        "cross_title": _lazy("田徑練習 × 重量訓練 × 身體結構"),
        "peer_hint": _lazy("同樣的距離、同一段日子，看的是水準不是排名"),
        "peer_empty": _lazy("沒有其他運動員在同一段日子練過同樣的距離，或這幾筆還沒填距離。"),
        "change_note": _lazy("秒數越小越好：頭尾變化是負數，表示最後那一段比第一段快。"),
        "main_label": _lazy("田徑：組 / 天"),
        "directions": [
            ("perf", _lazy("表現與時間")),
            ("period", _lazy("同距離跨時段")),
            ("cross", _lazy("拼入重量與身體結構")),
        ],
        "hints": [
            (_lazy("表現與時間"), _lazy("看這幾組本身練得怎樣、在隊裡是什麼水準；")),
            (_lazy("同距離跨時段"), _lazy("看同一個距離在不同年月／時期的量與強度變化；")),
            (_lazy("拼入重量與身體結構"), _lazy("把同一段時間的重量訓練與體組成擺在一起看。")),
        ],
        "columns": [
            _col("date", _lazy("日期")),
            _col("set", _lazy("組數"), True),
            _col("item", _lazy("項目")),
            _col("dist", _lazy("距離 (m)"), True),
            _col("target", _lazy("目標數值（秒）"), True),
            _col("value", _lazy("完成數值（秒）"), True),
            _col("intensity", _lazy("強度要求"), True),
            _col("rest", _lazy("休息（分）"), True),
            _col("done", _lazy("完成與否")),
            _col("status", _lazy("狀態")),
            _col("block", _lazy("區塊")),
            _col("program", _lazy("program")),
            _col("context", _lazy("情境")),
        ],
    },
    MetricDomain.STRENGTH: {
        "domain": MetricDomain.STRENGTH,
        "title": _lazy("重量訓練紀錄"),
        "fold_key": "strength-log",
        "lower_better": False,
        "unit_word": "kg",
        "row_word": _lazy("組"),
        "picked_label": _lazy("挑出來的組數"),
        "best_label": _lazy("最重 / 平均（kg）"),
        "value_label": _lazy("完成重量 (kg)"),
        "target_label": _lazy("目標重量 (kg)"),
        "volume_label": _lazy("訓練量（總噸位）"),
        "volume_unit": "kg",
        "group_label": _lazy("動作"),
        "split_label": _lazy("次數"),
        "group_title": _lazy("照動作分"),
        "split_title": _lazy("照次數分"),
        "search_hint": _lazy("打深蹲就出所有深蹲；也可以打 100（公斤或次數）、正課、傷害治療"),
        "empty": _lazy("還沒有重量訓練的紀錄。到課表那一天的活動旁按「登記錄」就可以開始記。"),
        "perf_title": _lazy("重量與時間"),
        "perf_hint": _lazy("挑出來的每一組按日期排開，虛線是課表要求的目標重量"),
        "period_title": _lazy("同一個動作，在不同時段的變化"),
        "cross_title": _lazy("重量訓練 × 田徑練習 × 身體結構"),
        "peer_hint": _lazy("同樣的動作、同一段日子，看的是水準不是排名"),
        "peer_empty": _lazy("沒有其他運動員在同一段日子做過同樣的動作。"),
        "change_note": _lazy("重量越大越好：頭尾變化是正數，表示最後那一段舉得比第一段重。"),
        "main_label": _lazy("重量：組 / 天"),
        "directions": [
            ("perf", _lazy("重量與時間")),
            ("period", _lazy("同動作跨時段")),
            ("cross", _lazy("拼入田徑與身體結構")),
        ],
        "hints": [
            (_lazy("重量與時間"), _lazy("看這幾組舉得怎樣、在隊裡是什麼水準；")),
            (_lazy("同動作跨時段"), _lazy("看同一個動作在不同年月／時期的重量與噸位變化；")),
            (_lazy("拼入田徑與身體結構"), _lazy("把同一段時間的田徑練習與體組成擺在一起看。")),
        ],
        "columns": [
            _col("date", _lazy("日期")),
            _col("set", _lazy("組數"), True),
            _col("item", _lazy("動作")),
            _col("target", _lazy("目標重量 (kg)"), True),
            _col("value", _lazy("完成重量 (kg)"), True),
            _col("reps", _lazy("次數"), True),
            _col("rest", _lazy("休息（分）"), True),
            _col("done", _lazy("完成與否")),
            _col("status", _lazy("狀態")),
            _col("block", _lazy("區塊")),
            _col("program", _lazy("program")),
            _col("context", _lazy("情境")),
        ],
    },
    MetricDomain.COMPETITION: {
        "domain": MetricDomain.COMPETITION,
        "title": _lazy("比賽數據"),
        "fold_key": "comp-log",
        "lower_better": True,
        "unit_word": _lazy("秒"),
        "row_word": _lazy("項"),
        "picked_label": _lazy("挑出來的項數"),
        "best_label": _lazy("最佳 / 平均（秒）"),
        "value_label": _lazy("成績（秒）"),
        "target_label": _lazy("目標成績（秒）"),
        "volume_label": _lazy("出賽量（總距離）"),
        "volume_unit": "m",
        "group_label": _lazy("比賽項目"),
        "split_label": _lazy("賽事"),
        "group_title": _lazy("照比賽項目分"),
        "split_title": _lazy("照賽事分"),
        "search_hint": _lazy("打 100 就出所有 100m；也可以打校際、賽事名稱、傷害治療"),
        "empty": _lazy("還沒有比賽數據。到課表那一天的活動旁按「登記錄」就可以開始記。"),
        "perf_title": _lazy("成績與時間"),
        "perf_hint": _lazy("挑出來的每一項按比賽日期排開，虛線是賽前定的目標成績"),
        "period_title": _lazy("同一個比賽項目，在不同時段的變化"),
        "cross_title": _lazy("比賽數據 × 平時練習 × 身體結構"),
        "peer_hint": _lazy("同樣的比賽項目、同一段日子，看的是水準不是名次"),
        "peer_empty": _lazy("沒有其他運動員在同一段日子比過同樣的項目。"),
        "change_note": _lazy("秒數越小越好：頭尾變化是負數，表示最後那一場比第一場快。"),
        "main_label": _lazy("比賽：項 / 天"),
        "directions": [
            ("perf", _lazy("成績與時間")),
            ("period", _lazy("同項目跨時段")),
            ("cross", _lazy("拼入練習與身體結構")),
        ],
        "hints": [
            (_lazy("成績與時間"), _lazy("看這幾場比出什麼成績、在隊裡是什麼水準；")),
            (_lazy("同項目跨時段"), _lazy("看同一個比賽項目在不同年月／賽季的成績變化；")),
            (_lazy("拼入練習與身體結構"), _lazy("把賽前那一段時間的練習與體組成擺在一起看。")),
        ],
        "columns": [
            _col("date", _lazy("比賽日期")),
            _col("item", _lazy("比賽項目")),
            _col("meet", _lazy("賽事")),
            _col("dist", _lazy("距離 (m)"), True),
            _col("target", _lazy("目標成績（秒）"), True),
            _col("value", _lazy("成績（秒）"), True),
            _col("done", _lazy("有沒有完成")),
            _col("status", _lazy("狀態")),
            _col("context", _lazy("情境")),
        ],
    },
}

#: 每個欄位排序時真正比的資料庫欄位（距離要先把紀錄與項目上的距離合起來）
SORT_FIELDS = {
    "date": "date",
    "set": "set_no",
    "item": "item__name",
    "meet": "competition__name",
    "dist": "sort_distance",
    "target": "target_value",
    "value": "value",
    "reps": "reps",
    "intensity": "intensity",
    "rest": "rest_sec",
    "done": "completed",
    "status": "status",
    "block": "block",
    "program": "session__title",
    "context": "context",
}

#: 舊名字：田徑練習的欄位與方向（這個檔本來只做田徑）
COLUMNS = SPECS[MetricDomain.TRACK]["columns"]
DIRECTIONS = SPECS[MetricDomain.TRACK]["directions"]


def spec(domain=MetricDomain.TRACK):
    """這個範疇的字眼與欄位；不認得的範疇一律當田徑練習。"""
    return SPECS.get(domain, SPECS[MetricDomain.TRACK])


def columns_for(domain=MetricDomain.TRACK):
    return spec(domain)["columns"]


def sort_keys(domain=MetricDomain.TRACK):
    """這個範疇排得了的欄位（表頭上有的那幾欄）。"""
    return {c["key"] for c in columns_for(domain)}


def directions_for(domain=MetricDomain.TRACK):
    return spec(domain)["directions"]


# ------------------------------------------------------------------ 清單


def _base(athlete, domain=MetricDomain.TRACK):
    """這名運動員在這個範疇的所有紀錄，新的排前面、同一天照組別排。"""
    return (
        MetricRecord.objects.filter(athlete=athlete, item__domain=domain)
        .select_related("item", "session", "competition")
        .order_by("-date", "set_no", "id")
    )


def filter_options(athlete, year=None, domain=MetricDomain.TRACK):
    """清單上面那兩個下拉：有紀錄的年份，以及那一年底下有紀錄的月份。"""
    years, months = {}, {}
    for on_date in _base(athlete, domain).values_list("date", flat=True):
        years[on_date.year] = years.get(on_date.year, 0) + 1
        if year in (None, on_date.year):
            months[on_date.month] = months.get(on_date.month, 0) + 1
    return {
        "years": [
            {"value": y, "count": c} for y, c in sorted(years.items(), reverse=True)
        ],
        "months": [{"value": m, "count": months[m]} for m in sorted(months)],
    }


def _number(term):
    try:
        return float(term)
    except ValueError:
        return None


def _term_filter(term, domain=MetricDomain.TRACK):
    """一個關鍵字要比對的所有欄位。

    打「150」找的是距離（連項目名稱裡的 150m 也算），重量訓練還會找重量與次數；
    打「反覆跑」「深蹲」找項目，打「傷害治療」「正課」找的是狀態與區塊——
    那兩欄存的是代碼，所以先把畫面上的字翻回代碼再比。
    """
    where = (
        Q(item__name__icontains=term)
        | Q(item__name_en__icontains=term)
        | Q(intensity__icontains=term)
        | Q(context__icontains=term)
        | Q(note__icontains=term)
        | Q(session__title__icontains=term)
        | Q(competition__name__icontains=term)
    )
    number = _number(term)
    if number is not None:
        where |= Q(distance_m=number) | Q(item__track_distance_m=int(number))
        if domain == MetricDomain.STRENGTH:
            where |= Q(weight_kg=number) | Q(reps=int(number))
    codes = [v for v, label in TrainingStatus.choices if term in str(label)]
    if codes:
        where |= Q(status__in=codes)
    blocks = [v for v, label in block_choices() if term in str(label)]
    if blocks:
        where |= Q(block__in=blocks)
    return where


def _order(rows, sort, direction):
    """照挑的欄位排；沒填的那幾筆一律沉到最後，再用日期與組別收尾。"""
    field = SORT_FIELDS.get(sort, SORT_FIELDS[DEFAULT_SORT])
    expr = F(field)
    primary = (
        expr.desc(nulls_last=True)
        if direction == "desc"
        else expr.asc(nulls_last=True)
    )
    tail = ["-date", "set_no", "id"] if sort != "date" else ["set_no", "id"]
    return rows.order_by(primary, *tail)


def page_window(page, pages, span=2):
    """分頁只列目前這一頁附近幾個號碼，頭尾一定看得到。"""
    first, last = max(1, page - span), min(pages, page + span)
    out = list(range(first, last + 1))
    if first > 1:
        out = [1] + (["…"] if first > 2 else []) + out
    if last < pages:
        out = out + (["…"] if last < pages - 1 else []) + [pages]
    return out


def search_records(
    athlete,
    year=None,
    month=None,
    query="",
    sort=DEFAULT_SORT,
    direction=DEFAULT_DIR,
    page=1,
    per_page=PAGE_SIZE,
    domain=MetricDomain.TRACK,
):
    """依年份／月份／關鍵字挑出這個範疇的紀錄，排好序、切成一頁一頁。"""
    rows = _base(athlete, domain).annotate(
        sort_distance=Coalesce(
            "distance_m",
            Cast(
                "item__track_distance_m",
                DecimalField(max_digits=8, decimal_places=1),
            ),
        )
    )
    if year:
        rows = rows.filter(date__year=year)
    if month:
        rows = rows.filter(date__month=month)
    for term in (query or "").split():
        rows = rows.filter(_term_filter(term, domain))
    if sort not in sort_keys(domain):
        sort = DEFAULT_SORT
    if direction not in ("asc", "desc"):
        direction = DEFAULT_DIR
    rows = _order(rows, sort, direction)

    total = rows.count()
    per_page = max(1, per_page)
    pages = max(1, -(-total // per_page))
    page = min(max(1, page), pages)
    start = (page - 1) * per_page
    shown = list(rows[start : start + per_page])
    return {
        "rows": shown,
        "total": total,
        "shown": len(shown),
        "sort": sort,
        "direction": direction,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "page_range": page_window(page, pages),
        "start_index": start + 1 if shown else 0,
        "end_index": start + len(shown),
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_page": page - 1,
        "next_page": page + 1,
    }


def picked_records(athlete, ids, domain=MetricDomain.TRACK):
    """挑來分析的那幾筆（只認這名運動員自己、這個範疇的紀錄）。"""
    ids = list(ids)[:MAX_PICKS]
    if not ids:
        return []
    found = {r.id: r for r in _base(athlete, domain).filter(id__in=ids)}
    return sorted(
        (found[i] for i in ids if i in found),
        key=lambda r: (r.date, r.set_no or 0, r.id),
    )


# -------------------------------------------------------------- 共用計算


def _distance(record):
    """這一組跑幾米：紀錄自己有就用自己的，沒有就用項目上的距離。"""
    if record.distance_m is not None:
        return float(record.distance_m)
    if record.item.track_distance_m:
        return float(record.item.track_distance_m)
    return None


def _intensity_pct(record):
    """強度要求換成數字（「90%」→ 90、「全力」→ 100），換不出來就 None。"""
    raw = (record.intensity or "").strip()
    if not raw:
        return None
    if raw.lower() in MAXIMAL_WORDS:
        return 100.0
    digits = "".join(c for c in raw if c.isdigit() or c == ".")
    try:
        value = float(digits)
    except ValueError:
        return None
    return value if 0 < value <= 100 else None


def _avg(values, digits=1):
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), digits) if values else None


def _pct_change(old, new, digits=1):
    if not old or new is None:
        return None
    return round((new - old) / abs(old) * 100, digits)


def _distance_label(value):
    return _("%(v0)s m") % {"v0": int(value)} if value else _("未填距離")


def _group_label(record, domain):
    """跨時段比較時這一筆屬於哪一堆：田徑看距離，重量看動作，比賽看項目。"""
    if domain == MetricDomain.TRACK:
        return _distance_label(_distance(record))
    return record.item.name


def _split_label(record, domain):
    """方向一第二張分堆表的鍵：強度要求／次數／哪一場比賽。"""
    if domain == MetricDomain.STRENGTH:
        return _("%(v0)s 次") % {"v0": record.reps} if record.reps else _("未填次數")
    if domain == MetricDomain.COMPETITION:
        return record.competition.name if record.competition else _("未指定賽事")
    return (record.intensity or "").strip() or _("未填強度")


def _volume(records, domain):
    """這一堆的量：重量訓練算總噸位 (kg)，其餘算總距離 (m)。"""
    if domain == MetricDomain.STRENGTH:
        return round(sum(r.tonnage for r in records if r.tonnage), 1)
    known = [d for d in (_distance(r) for r in records) if d]
    return round(sum(known)) if known else 0


def summarise(records, domain=MetricDomain.TRACK):
    """一批紀錄的摘要：量、強度、成績、完成率都在這裡算好。

    秒數越小越好、公斤越大越好，所以「最佳」與「有沒有做到目標」
    都要看這個範疇是哪一種。
    """
    records = list(records)
    lower_better = spec(domain)["lower_better"]
    values = [float(r.value) for r in records if r.value is not None]
    known = [d for d in (_distance(r) for r in records) if d]
    intens = [i for i in (_intensity_pct(r) for r in records) if i is not None]
    rests = [r.rest_sec for r in records if r.rest_sec is not None]
    reps = [r.reps for r in records if r.reps is not None]
    scored = [r for r in records if r.value is not None and r.target_value is not None]
    if lower_better:
        on_target = sum(1 for r in scored if float(r.value) <= float(r.target_value))
    else:
        on_target = sum(1 for r in scored if float(r.value) >= float(r.target_value))
    dates = sorted({r.date for r in records})
    completed = sum(1 for r in records if r.completed)
    best = (min(values) if lower_better else max(values)) if values else None
    worst = (max(values) if lower_better else min(values)) if values else None
    return {
        "count": len(records),
        "days": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "best": best,
        "worst": worst,
        "average": round(statistics.mean(values), 2) if values else None,
        "scored": len(values),
        "volume": _volume(records, domain),
        "volume_unit": spec(domain)["volume_unit"],
        "distances": sorted({int(d) for d in known}),
        "avg_distance": _avg(known),
        "avg_intensity": _avg(intens),
        "avg_reps": _avg(reps),
        "reps_total": sum(reps) if reps else 0,
        "avg_rest_min": round(statistics.mean(rests) / 60, 1) if rests else None,
        "completed": completed,
        "failed": len(records) - completed,
        "completion_pct": round(completed / len(records) * 100, 1) if records else None,
        "target_count": len(scored),
        "on_target": on_target,
        "on_target_pct": round(on_target / len(scored) * 100, 1) if scored else None,
    }


def _breakdown(records, keyfunc, domain, sortfunc=None):
    """照某一欄（距離／動作／強度／次數／狀態）分堆，每一堆給一份摘要。"""
    buckets = {}
    for record in records:
        buckets.setdefault(keyfunc(record), []).append(record)
    rows = []
    for label, group in buckets.items():
        stat = summarise(group, domain)
        stat["label"] = label
        rows.append(stat)
    rows.sort(key=sortfunc or (lambda r: -r["count"]))
    return rows


# --------------------------------------------------- 方向一：表現與時間


def _peer_rows(athlete, records, viewer, domain):
    """同樣的距離／動作／項目、同一段日子，隊上其他人做出什麼。

    比的是水準不是排名——教練要判斷「這個數字在這個組別算什麼位置」，
    自己一個人的曲線看不出來，擺在同期其他人旁邊才有參照。
    """
    if viewer is None or not records:
        return []
    from core.permissions import athlete_ids_visible_to

    ids = [i for i in athlete_ids_visible_to(viewer) if i != athlete.id]
    if not ids:
        return []
    first = min(r.date for r in records)
    last = max(r.date for r in records)
    others = MetricRecord.objects.filter(
        athlete_id__in=ids,
        item__domain=domain,
        date__gte=first,
        date__lte=last,
        value__isnull=False,
    )
    # 田徑比的是同一個距離（別人的 150m 也算），重量與比賽比的是同一個項目
    wanted = None
    if domain == MetricDomain.TRACK:
        wanted = {int(d) for d in (_distance(r) for r in records) if d}
        if not wanted:
            return []
        ints = sorted(wanted)
        others = others.filter(
            Q(distance_m__in=ints) | Q(item__track_distance_m__in=ints)
        )
    else:
        others = others.filter(item_id__in={r.item_id for r in records})
    others = others.select_related("athlete__user", "item")[: MAX_PICKS * 5]

    buckets = {}
    for record in others:
        if wanted is not None and int(_distance(record) or 0) not in wanted:
            continue
        buckets.setdefault(record.athlete, []).append(record)

    mine = summarise(records, domain)
    rows = [
        {
            "name": _("這名運動員"),
            "is_self": True,
            "count": mine["count"],
            "best": mine["best"],
            "average": mine["average"],
        }
    ]
    for other, group in buckets.items():
        stat = summarise(group, domain)
        rows.append(
            {
                "name": other.user.get_full_name() or other.user.username,
                "is_self": False,
                "count": stat["count"],
                "best": stat["best"],
                "average": stat["average"],
            }
        )
    if spec(domain)["lower_better"]:
        rows.sort(key=lambda r: (r["best"] is None, r["best"] or 0))
    else:
        rows.sort(key=lambda r: (r["best"] is None, -(r["best"] or 0)))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows[: MAX_PEERS + 1]


def _perf_insights(stat, points, domain):
    """幾句白話：做了多少、做得怎樣、有沒有照課表做到。"""
    sp = spec(domain)
    unit, word = sp["unit_word"], sp["row_word"]
    out = []
    if stat["count"]:
        out.append(
            _("挑出來的 %(v0)s %(v1)s分佈在 %(v2)s 天，%(v3)s %(v4)s %(v5)s。")
            % {
                "v0": stat["count"],
                "v1": word,
                "v2": stat["days"],
                "v3": sp["volume_label"],
                "v4": stat["volume"],
                "v5": sp["volume_unit"],
            }
        )
    if stat["best"] is not None:
        out.append(
            _("最佳 %(v0)s %(v2)s、平均 %(v1)s %(v2)s。")
            % {"v0": stat["best"], "v1": stat["average"], "v2": unit}
        )
    scored = [p for p in points if p["value"] is not None]
    if len(scored) >= 4:
        half = len(scored) // 2
        early = _avg([p["value"] for p in scored[:half]], 2)
        late = _avg([p["value"] for p in scored[half:]], 2)
        change = _pct_change(early, late)
        if change is not None:
            better = change < 0 if sp["lower_better"] else change > 0
            if change == 0:
                tail = _("前後沒有分別。")
            elif better:
                tail = _("後面這幾%(v0)s進步了 %(v1)s%%。") % {"v0": word, "v1": abs(change)}
            else:
                tail = _("後面這幾%(v0)s退了 %(v1)s%%，先看是不是累積疲勞。") % {
                    "v0": word,
                    "v1": abs(change),
                }
            out.append(
                _("前半段平均 %(v0)s %(v2)s、後半段 %(v1)s %(v2)s——")
                % {"v0": early, "v1": late, "v2": unit}
                + tail
            )
    if stat["on_target_pct"] is not None:
        out.append(
            _("有目標數值的 %(v0)s %(v2)s裡，做到目標的佔 %(v1)s%%。")
            % {"v0": stat["target_count"], "v1": stat["on_target_pct"], "v2": word}
        )
    if stat["failed"]:
        out.append(
            _("其中 %(v0)s %(v1)s沒有完成，分析成績之前先看那幾天的狀態欄。")
            % {"v0": stat["failed"], "v1": word}
        )
    return out


def performance_view(athlete, records, viewer=None, domain=MetricDomain.TRACK):
    """方向一：不斷收集回來的數據，先看這幾筆本身做得怎樣。"""
    stat = summarise(records, domain)
    points = [
        {
            "date": r.date.isoformat(),
            "label": f"{r.date:%m/%d}" + (f" #{r.set_no}" if r.set_no else ""),
            "item": r.item.name,
            "distance": _distance(r),
            "value": float(r.value) if r.value is not None else None,
            "target": float(r.target_value) if r.target_value is not None else None,
            "intensity": (r.intensity or "").strip(),
            "reps": r.reps,
            "completed": r.completed,
            "status": r.status_label,
            "session": (
                r.session.title
                if r.session
                else (r.competition.name if r.competition else "")
            ),
        }
        for r in records
    ]
    return {
        "summary": stat,
        "points": points,
        "by_group": _breakdown(records, lambda r: _group_label(r, domain), domain),
        "by_split": _breakdown(records, lambda r: _split_label(r, domain), domain),
        "by_status": _breakdown(
            records, lambda r: r.status_label or _("未註記狀態"), domain
        ),
        "peers": _peer_rows(athlete, records, viewer, domain),
        "insights": _perf_insights(stat, points, domain),
    }


# ------------------------------------------------- 方向二：同一組跨時段


def _bucket(mode, on_date, phase_at):
    """一個日期屬於哪一段時間：(排序鍵, 標題, 副標, 起, 訖)。分不出來回 None。"""
    if mode == "year":
        return (
            f"{on_date.year}",
            _("%(v0)s 年") % {"v0": on_date.year},
            "",
            date(on_date.year, 1, 1),
            date(on_date.year, 12, 31),
        )
    if mode == "month":
        last = calendar.monthrange(on_date.year, on_date.month)[1]
        return (
            f"{on_date.year}-{on_date.month:02d}",
            f"{on_date.year}/{on_date.month:02d}",
            "",
            date(on_date.year, on_date.month, 1),
            date(on_date.year, on_date.month, last),
        )
    phase = phase_at(on_date)
    if phase is None:
        return None
    return (
        f"{phase.start_date.isoformat()}#{phase.pk}",
        phase.get_phase_type_display(),
        f"{phase.start_date:%Y/%m/%d} → {phase.end_date:%Y/%m/%d}",
        phase.start_date,
        phase.end_date,
    )


def _periods(records, mode, phase_at):
    """把紀錄切成一段一段的時間，回傳 (時段清單, 紀錄 → 時段鍵, 分不出來的筆數)。"""
    periods, belongs, missed = {}, {}, 0
    for record in records:
        bucket = _bucket(mode, record.date, phase_at)
        if bucket is None:
            missed += 1
            continue
        key, label, sublabel, start, end = bucket
        periods.setdefault(
            key,
            {
                "key": key,
                "label": label,
                "sublabel": sublabel,
                "start": start,
                "end": end,
            },
        )
        belongs[record.id] = key
    return [periods[k] for k in sorted(periods)], belongs, missed


def _period_insights(rows, periods, domain):
    """挑最會講故事的那一兩堆，寫成白話。"""
    sp = spec(domain)
    out = []
    if len(periods) < 2:
        out.append(_("挑出來的紀錄只落在一個時段裡，換一個切法（分月份／分年份）才比得出變化。"))
        return out
    for row in rows[:2]:
        cells = [c for c in row["cells"] if c]
        if len(cells) < 2:
            continue
        first, last = cells[0], cells[-1]
        pieces = [
            _("%(v0)s：%(v1)s → %(v2)s，")
            % {"v0": row["label"], "v1": first["period"], "v2": last["period"]}
        ]
        if first["average"] and last["average"]:
            delta = round(last["average"] - first["average"], 2)
            pieces.append(
                _("平均由 %(v0)s 變成 %(v1)s %(v4)s（%(v2)s%(v3)s）")
                % {
                    "v0": first["average"],
                    "v1": last["average"],
                    "v2": "+" if delta > 0 else "",
                    "v3": delta,
                    "v4": sp["unit_word"],
                }
            )
        volume = _pct_change(first["volume"], last["volume"])
        if volume is not None:
            pieces.append(
                _("；%(v2)s %(v0)s%(v1)s%%")
                % {
                    "v0": "+" if volume > 0 else "",
                    "v1": volume,
                    "v2": sp["volume_label"],
                }
            )
        if first["avg_intensity"] and last["avg_intensity"]:
            pieces.append(
                _("；平均強度 %(v0)s%% → %(v1)s%%")
                % {"v0": first["avg_intensity"], "v1": last["avg_intensity"]}
            )
        out.append("".join(pieces) + "。")
    if not out:
        out.append(
            _("同一個%(v0)s要在兩個以上的時段都做過，才排得出變化。")
            % {"v0": sp["group_label"]}
        )
    return out


def period_view(athlete, records, mode="month", domain=MetricDomain.TRACK):
    """方向二：同一個距離／動作／項目，在不同年／月／時期的變化。"""
    from analytics.services import phase_lookup

    if mode not in {m for m, _unused in GROUPINGS}:
        mode = "month"
    phase_at = phase_lookup(athlete)
    periods, belongs, missed = _periods(records, mode, phase_at)

    by_group = {}
    for record in records:
        key = belongs.get(record.id)
        if key is None:
            continue
        bucket = by_group.setdefault(_group_label(record, domain), {})
        bucket.setdefault(key, []).append(record)

    order = sorted(by_group, key=lambda g: -sum(len(x) for x in by_group[g].values()))[
        :MAX_GROUPS
    ]

    lower_better = spec(domain)["lower_better"]
    rows = []
    for label in order:
        cells = []
        for period in periods:
            group = by_group[label].get(period["key"])
            if not group:
                cells.append(None)
                continue
            stat = summarise(group, domain)
            stat["period"] = period["label"]
            cells.append(stat)
        seen = [c for c in cells if c]
        bests = [c["best"] for c in seen if c["best"] is not None]
        rows.append(
            {
                "label": label,
                "count": sum(c["count"] for c in seen),
                "cells": cells,
                "best": (
                    (min(bests) if lower_better else max(bests)) if bests else None
                ),
                "volume": sum(c["volume"] for c in seen),
                "change_pct": (
                    _pct_change(seen[0]["average"], seen[-1]["average"], 2)
                    if len(seen) > 1
                    else None
                ),
                "volume_change_pct": (
                    _pct_change(seen[0]["volume"], seen[-1]["volume"])
                    if len(seen) > 1
                    else None
                ),
            }
        )

    totals = []
    for period in periods:
        group = [r for r in records if belongs.get(r.id) == period["key"]]
        stat = summarise(group, domain)
        stat.update(period)
        totals.append(stat)

    return {
        "mode": mode,
        "groupings": GROUPINGS,
        "periods": periods,
        "rows": rows,
        "totals": totals,
        "missed": missed,
        "lower_better": lower_better,
        "insights": _period_insights(rows, periods, domain),
    }


# --------------------------------- 方向三：拼入另一種訓練與身體結構


def _domain_in(athlete, domain, start, end):
    """一段時間裡某一個範疇的紀錄。"""
    return list(
        MetricRecord.objects.filter(
            athlete=athlete,
            item__domain=domain,
            date__gte=start,
            date__lte=end,
        )
        .select_related("item")
        .order_by("date", "id")
    )


def _strength_in(athlete, start, end):
    """一段時間裡的重量訓練（只算單位是 kg、標了已完成、有填重量的組）。"""
    rows = (
        MetricRecord.objects.filter(
            athlete=athlete,
            item__domain=MetricDomain.STRENGTH,
            date__gte=start,
            date__lte=end,
            completed=True,
            weight_kg__isnull=False,
        )
        .select_related("item")
        .order_by("date", "id")
    )
    return [r for r in rows if (r.item.unit or "").strip().lower() == "kg"]


def _strength_stat(records, body_weight=None):
    """一段時間的重量訓練摘要：做了多少、最重舉得起多少、每公斤體重幾倍。"""
    if not records:
        return None
    best_by_item, tonnage = {}, 0.0
    for record in records:
        if record.tonnage:
            tonnage += record.tonnage
        e1rm = estimate_1rm(record.weight_kg, record.reps)
        if e1rm is None:
            continue
        current = best_by_item.get(record.item_id)
        if current is None or e1rm > current["e1rm"]:
            best_by_item[record.item_id] = {"name": record.item.name, "e1rm": e1rm}
    best = max(best_by_item.values(), key=lambda x: x["e1rm"]) if best_by_item else None
    per_bw = None
    if best_by_item and body_weight:
        per_bw = _avg([x["e1rm"] / body_weight for x in best_by_item.values()], 2)
    return {
        "sets": len(records),
        "days": len({r.date for r in records}),
        "tonnage": round(tonnage, 1),
        "best": best,
        "lifts": len(best_by_item),
        "avg_per_bw": per_bw,
    }


def _body_stat(athlete, start, end):
    """一段時間裡量過的體組成，取平均。"""
    rows = [b for b in athlete.body_metrics.all() if start <= b.date <= end]
    if not rows:
        return None
    weight = _avg([float(b.weight_kg) for b in rows])
    lean = _avg([b.lean_mass_kg for b in rows])
    return {
        "count": len(rows),
        "weight": weight,
        "fat_pct": _avg(
            [float(b.body_fat_pct) for b in rows if b.body_fat_pct is not None]
        ),
        "lean": lean,
        "muscle_pct": round(lean / weight * 100, 1) if lean and weight else None,
    }


def _cross_insights(rows, domain):
    """把三件事擺在同一句話裡：這個範疇的、另一種訓練的、身體的。"""
    sp = spec(domain)
    out = []
    usable = [r for r in rows if r["main"]["count"]]
    if len(usable) < 2:
        out.append(_("要有兩個以上的時段，才看得出「這幾公斤是練回來的、還是輕了才顯得快」。"))
        return out
    first, last = usable[0], usable[-1]
    delta = None
    if first["main"]["average"] and last["main"]["average"]:
        delta = round(last["main"]["average"] - first["main"]["average"], 2)
        out.append(
            _("%(v0)s → %(v1)s：%(v6)s平均由 %(v2)s 變成 %(v3)s %(v7)s（%(v4)s%(v5)s）。")
            % {
                "v0": first["label"],
                "v1": last["label"],
                "v2": first["main"]["average"],
                "v3": last["main"]["average"],
                "v4": "+" if delta > 0 else "",
                "v5": delta,
                "v6": sp["title"],
                "v7": sp["unit_word"],
            }
        )
    if first["track"] and last["track"] and first["track"]["average"]:
        out.append(
            _("同一段時間的田徑練習：平均由 %(v0)s 秒變成 %(v1)s 秒，總距離 %(v2)s → %(v3)s m。")
            % {
                "v0": first["track"]["average"],
                "v1": last["track"]["average"],
                "v2": first["track"]["volume"],
                "v3": last["track"]["volume"],
            }
        )
    if first["strength"] and last["strength"]:
        change = _pct_change(first["strength"]["tonnage"], last["strength"]["tonnage"])
        line = _("同一段時間的重量訓練：總噸位 %(v0)s → %(v1)s kg") % {
            "v0": first["strength"]["tonnage"],
            "v1": last["strength"]["tonnage"],
        }
        if change is not None:
            line += _("（%(v0)s%(v1)s%%）") % {
                "v0": "+" if change > 0 else "",
                "v1": change,
            }
        if first["strength"]["avg_per_bw"] and last["strength"]["avg_per_bw"]:
            line += _("，每公斤體重舉得起 %(v0)s → %(v1)s 倍") % {
                "v0": first["strength"]["avg_per_bw"],
                "v1": last["strength"]["avg_per_bw"],
            }
        out.append(line + "。")
    if first["body"] and last["body"]:
        line = _("身體結構：體重 %(v0)s → %(v1)s kg") % {
            "v0": first["body"]["weight"],
            "v1": last["body"]["weight"],
        }
        if first["body"]["fat_pct"] and last["body"]["fat_pct"]:
            line += _("、體脂 %(v0)s%% → %(v1)s%%") % {
                "v0": first["body"]["fat_pct"],
                "v1": last["body"]["fat_pct"],
            }
        if first["body"]["muscle_pct"] and last["body"]["muscle_pct"]:
            line += _("、肌肉率 %(v0)s%% → %(v1)s%%") % {
                "v0": first["body"]["muscle_pct"],
                "v1": last["body"]["muscle_pct"],
            }
        out.append(line + "。")
        if delta is not None and first["body"]["weight"] and last["body"]["weight"]:
            better = delta < 0 if sp["lower_better"] else delta > 0
            lighter = last["body"]["weight"] < first["body"]["weight"]
            if better and lighter:
                out.append(_("數字變好、體重也降了——先確認掉的是脂肪不是肌肉，不是每一次變輕都算進步。"))
            elif better:
                out.append(_("重了但數字也變好，這個方向是對的：加上去的是用得上的重量。"))
            else:
                out.append(_("這段時間的數字退了，對照上面的量與強度，看是疲勞、還是身體結構走了方向。"))
    if domain != MetricDomain.STRENGTH and not any(r["strength"] for r in rows):
        out.append(_("這段時間沒有可以算的重量訓練紀錄（要填重量、單位是 kg、而且標了已完成）。"))
    if domain != MetricDomain.TRACK and not any(
        r["track"] and r["track"]["count"] for r in rows
    ):
        out.append(_("這段時間沒有田徑練習的紀錄，拼不出「練得多不多」那一半。"))
    if not any(r["body"] for r in rows):
        out.append(_("這段時間沒有體組成量測；到運動員總覽登一次體測，這一欄才有東西比。"))
    return out


def cross_view(athlete, records, mode="month", domain=MetricDomain.TRACK):
    """方向三：這個範疇 × 另一種訓練 × 身體結構，同一段時間擺在同一列。"""
    from analytics.services import phase_lookup

    if mode not in {m for m, _unused in GROUPINGS}:
        mode = "month"
    phase_at = phase_lookup(athlete)
    periods, belongs, missed = _periods(records, mode, phase_at)

    rows = []
    for period in periods:
        group = [r for r in records if belongs.get(r.id) == period["key"]]
        body = _body_stat(athlete, period["start"], period["end"])
        # 主角是重量訓練時不用再拼一次重量，主角是田徑時不用再拼一次田徑
        strength = (
            None
            if domain == MetricDomain.STRENGTH
            else _strength_stat(
                _strength_in(athlete, period["start"], period["end"]),
                body_weight=body["weight"] if body else None,
            )
        )
        track = (
            None
            if domain == MetricDomain.TRACK
            else summarise(
                _domain_in(athlete, MetricDomain.TRACK, period["start"], period["end"]),
                MetricDomain.TRACK,
            )
        )
        rows.append(
            {
                **period,
                "main": summarise(group, domain),
                "track": track,
                "strength": strength,
                "body": body,
            }
        )
    return {
        "mode": mode,
        "groupings": GROUPINGS,
        "rows": rows,
        "missed": missed,
        "show_track": domain != MetricDomain.TRACK,
        "show_strength": domain != MetricDomain.STRENGTH,
        "lower_better": spec(domain)["lower_better"],
        "insights": _cross_insights(rows, domain),
    }


def analyse(
    athlete,
    records,
    direction="perf",
    mode="month",
    viewer=None,
    domain=MetricDomain.TRACK,
):
    """挑出來的紀錄 ＋ 一個方向 → 一份分析。"""
    if not records:
        return None
    if direction == "period":
        return {
            "direction": "period",
            "period": period_view(athlete, records, mode, domain),
        }
    if direction == "cross":
        return {
            "direction": "cross",
            "cross": cross_view(athlete, records, mode, domain),
        }
    return {
        "direction": "perf",
        "perf": performance_view(athlete, records, viewer=viewer, domain=domain),
    }

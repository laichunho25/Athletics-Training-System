"""把體組成磅匯出的檔案讀成 BodyMetricLog 的欄位。

支援兩種常見形狀，兩種都吃 CSV／TSV／純文字（逗號、tab、全形逗號都算分隔）：

1. 直式（手機 App 那一頁「體組成」直接複製下來）——一行一個項目：

       體重,69.20 kg
       體脂肪率,16.30 %
       肌肉量,54.90 kg

   手機的「實時文字」／Google Lens 會把項目名與數值拆成兩行，這種也讀得懂：

       體重
       69.20 kg
       體脂肪率
       標準
       16.30 %

2. 橫式（HealthPlanet / InBody 匯出的表格）——第一行是欄名，其餘每行一次量測：

       日期,體重,體脂肪率,肌肉量
       2026/06/07,69.2,16.3,54.9

欄名同時認中文（繁／簡）與英文，數值後面的單位、標準／多／高之類的評價字
會被丟掉，只留數字。
"""

import csv
import io
import re
from datetime import date, datetime

#: 檔案裡的欄名 → BodyMetricLog 的欄位名。key 一律先正規化（去空白、轉小寫）。
FIELD_ALIASES = {
    # 全身
    "體重": "weight_kg", "体重": "weight_kg", "weight": "weight_kg",
    "體脂肪率": "body_fat_pct", "体脂肪率": "body_fat_pct", "體脂率": "body_fat_pct",
    "体脂率": "body_fat_pct", "bodyfat": "body_fat_pct", "bodyfat%": "body_fat_pct",
    "bodyfatpercent": "body_fat_pct", "pbf": "body_fat_pct",
    "肌肉量": "muscle_mass_kg", "musclemass": "muscle_mass_kg", "smm": "muscle_mass_kg",
    "骨骼肌重": "muscle_mass_kg",
    "肌肉量判定指數": "muscle_mass_index", "肌肉量判定指数": "muscle_mass_index",
    "bmi": "bmi", "身體質量指數": "bmi",
    "肌肉質量指數": "muscle_quality_score", "肌肉质量指数": "muscle_quality_score",
    "musclequality": "muscle_quality_score", "musclequalityscore": "muscle_quality_score",
    "內臟脂肪等級": "visceral_fat_level", "内脏脂肪等级": "visceral_fat_level",
    "內臟脂肪": "visceral_fat_level", "visceralfat": "visceral_fat_level",
    "visceralfatlevel": "visceral_fat_level",
    "推定骨量": "bone_mass_kg", "骨量": "bone_mass_kg", "bonemass": "bone_mass_kg",
    "體水分率": "body_water_pct", "体水分率": "body_water_pct", "身體水分": "body_water_pct",
    "totalbodywater": "body_water_pct", "bodywater": "body_water_pct", "tbw": "body_water_pct",
    "基礎代謝量": "bmr_kcal", "基础代谢量": "bmr_kcal", "基礎代謝": "bmr_kcal",
    "bmr": "bmr_kcal", "basalmetabolicrate": "bmr_kcal",
    "體內年齡": "metabolic_age", "体内年龄": "metabolic_age", "代謝年齡": "metabolic_age",
    "metabolicage": "metabolic_age", "bodyage": "metabolic_age",
    # 部位肌肉量
    "右上肢肌肉量": "muscle_arm_r", "左上肢肌肉量": "muscle_arm_l",
    "右手肌肉量": "muscle_arm_r", "左手肌肉量": "muscle_arm_l",
    "右腳肌肉量": "muscle_leg_r", "左腳肌肉量": "muscle_leg_l",
    "右脚肌肉量": "muscle_leg_r", "左脚肌肉量": "muscle_leg_l",
    "軀幹部位肌肉量": "muscle_trunk", "軀幹肌肉量": "muscle_trunk",
    "躯干部位肌肉量": "muscle_trunk",
    "rightarmmusclemass": "muscle_arm_r", "leftarmmusclemass": "muscle_arm_l",
    "rightlegmusclemass": "muscle_leg_r", "leftlegmusclemass": "muscle_leg_l",
    "trunkmusclemass": "muscle_trunk",
    # 部位脂肪率
    "右上肢脂肪率": "fat_arm_r", "左上肢脂肪率": "fat_arm_l",
    "右手脂肪率": "fat_arm_r", "左手脂肪率": "fat_arm_l",
    "右腳脂肪率": "fat_leg_r", "左腳脂肪率": "fat_leg_l",
    "右脚脂肪率": "fat_leg_r", "左脚脂肪率": "fat_leg_l",
    "軀幹部位脂肪率": "fat_trunk", "軀幹脂肪率": "fat_trunk", "躯干部位脂肪率": "fat_trunk",
    "rightarmbodyfat": "fat_arm_r", "leftarmbodyfat": "fat_arm_l",
    "rightlegbodyfat": "fat_leg_r", "leftlegbodyfat": "fat_leg_l",
    "trunkbodyfat": "fat_trunk",
    # 部位肌肉品質
    "右上肢肌肉品質點數": "mq_arm_r", "左上肢肌肉品質點數": "mq_arm_l",
    "右腳肌肉品質點數": "mq_leg_r", "左腳肌肉品質點數": "mq_leg_l",
    "右上肢肌肉品质点数": "mq_arm_r", "左上肢肌肉品质点数": "mq_arm_l",
    "右脚肌肉品质点数": "mq_leg_r", "左脚肌肉品质点数": "mq_leg_l",
    # 其他
    "靜息心率": "resting_hr", "静息心率": "resting_hr", "restinghr": "resting_hr",
    "hrv": "hrv",
    "備註": "note", "备注": "note", "note": "note", "memo": "note",
}

#: 文字欄位（不轉數字）
TEXT_FIELDS = {"note"}

#: 這幾個欄位是整數
INT_FIELDS = {
    "muscle_mass_index", "muscle_quality_score", "bmr_kcal", "metabolic_age",
    "mq_arm_r", "mq_arm_l", "mq_leg_r", "mq_leg_l", "resting_hr", "hrv",
}

DATE_KEYS = {"日期", "date", "測量日期", "量測日期", "测量日期", "measurementdate", "datetime"}
TIME_KEYS = {"時間", "时间", "time", "測量時間", "量測時間"}
DEVICE_KEYS = {"機型", "机型", "device", "型號", "model", "裝置"}
MBA_KEYS = {"mba判定", "mba", "mba判定結果"}

#: 磅上的評價字（標準／多／高…），只是文字標籤，解析時要丟掉
RATING_WORDS = ("標準", "标准", "偏低", "偏高", "很高", "很低", "多", "少", "高", "低", "普通")

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _norm_key(raw):
    """欄名正規化：去空白／括號單位／全形符號，英文轉小寫。"""
    key = str(raw or "").strip()
    key = re.sub(r"[（(].*?[)）]", "", key)          # 去掉「體重 (kg)」的括號
    key = re.sub(r"[\s_\-.:：]+", "", key)
    key = key.replace("％", "%")
    return key.lower()


def _to_number(raw):
    """把「16.30 %」「標準 54.90 kg」這種字串裡的數字挖出來。"""
    text = str(raw or "").strip()
    if not text:
        return None
    for word in RATING_WORDS:
        text = text.replace(word, " ")
    match = _NUMBER.search(text.replace(",", ""))
    return float(match.group()) if match else None


def _to_date(raw):
    text = str(raw or "").strip()
    if not text:
        return None
    # 先試「2026年06月07日」這種寫法
    cjk = re.match(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if cjk:
        y, m, d = (int(g) for g in cjk.groups())
        return date(y, m, d)
    text = text.split("(")[0].strip()
    for fmt in (
        "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d/%m/%Y", "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M", "%Y%m%d",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _to_time(raw):
    match = re.search(r"(\d{1,2}):(\d{2})", str(raw or ""))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    return f"{hour:02d}:{minute:02d}" if 0 <= hour < 24 and minute < 60 else None


def _is_rating_only(cell):
    """整格只是「標準」「多」「高」這種評價字（沒有數字）——OCR 常會單獨成一行。"""
    text = str(cell or "").strip()
    if not text or _NUMBER.search(text):
        return False
    for word in RATING_WORDS:
        text = text.replace(word, "")
    return text.strip(" -—·") == ""


def _rows(text):
    """把檔案切成一列一列的欄位（自動判斷逗號 / tab / 全形逗號）。"""
    text = text.replace("﻿", "").replace("，", ",").replace("\t", ",")
    lines = [line for line in text.splitlines() if line.strip()]
    return [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO("\n".join(lines)))
        if any(cell.strip() for cell in row)
    ]


def _assign(record, key, value):
    """把一組欄名／值塞進 record；認得的欄位才收。"""
    norm = _norm_key(key)
    if not norm or value in (None, ""):
        return False
    if norm in DATE_KEYS:
        parsed = _to_date(value)
        if parsed:
            record["date"] = parsed
            record.setdefault("measured_at", _to_time(value))
        return bool(parsed)
    if norm in TIME_KEYS:
        record["measured_at"] = _to_time(value)
        return record["measured_at"] is not None
    if norm in DEVICE_KEYS:
        record["device"] = str(value).strip()[:40]
        return True
    if norm in MBA_KEYS:
        record["mba_rating"] = str(value).strip()[:20]
        return True
    field = FIELD_ALIASES.get(norm)
    if not field:
        return False
    if field in TEXT_FIELDS:
        record[field] = str(value).strip()
        return True
    number = _to_number(value)
    if number is None:
        return False
    record[field] = int(round(number)) if field in INT_FIELDS else number
    return True


def _looks_like_header(row):
    """整列都是認得的欄名 → 這是橫式表格的表頭。"""
    known = sum(
        1
        for cell in row
        if _norm_key(cell) in FIELD_ALIASES
        or _norm_key(cell) in DATE_KEYS | TIME_KEYS | DEVICE_KEYS | MBA_KEYS
    )
    return known >= 2 and known >= len([c for c in row if c]) / 2


def parse_body_composition(text, default_date=None):
    """讀檔案內容，回傳 (紀錄清單, 看不懂的欄名清單)。

    紀錄是 dict，key 就是 BodyMetricLog 的欄位名，一定含 date 與 weight_kg
    （沒有體重的列會被當成無效資料丟掉，由呼叫端報錯）。
    """
    rows = _rows(text)
    if not rows:
        return [], []

    unknown = []
    records = []

    header_at = next((i for i, row in enumerate(rows) if _looks_like_header(row)), None)
    if header_at is not None:
        header = rows[header_at]
        for row in rows[header_at + 1:]:
            record = {}
            for key, value in zip(header, row):
                if not _assign(record, key, value) and value and _norm_key(key) not in (
                    _norm_key(h) for h in unknown
                ):
                    if _norm_key(key) not in FIELD_ALIASES:
                        unknown.append(key)
            if record:
                records.append(record)
    else:
        # 直式：一行一個項目，全部併成同一筆紀錄
        record = {}
        pending = None  # 項目名單獨佔一行時，先記著，等下一行的數值
        for row in rows:
            cells = [c for c in row if c]
            if not cells:
                continue

            if len(cells) >= 2:
                # 同一行就有項目與數值（中間可能還夾著「標準」之類的評價字）
                pending = None
                key, value = cells[0], " ".join(cells[1:])
                if _assign(record, key, value):
                    continue
            else:
                cell = cells[0]
                # 評價字自己一行：跳過，項目名還在等它後面那個數值
                if pending and _is_rating_only(cell):
                    continue
                if pending and _assign(record, pending, cell):
                    pending = None
                    continue
                # 認得的項目名，數值在下一行
                if _norm_key(cell) in FIELD_ALIASES or _norm_key(cell) in (
                    DATE_KEYS | TIME_KEYS | DEVICE_KEYS | MBA_KEYS
                ):
                    pending = cell
                    continue
                key = cell

            # App 的畫面會把量測日期單獨放一行（例：「2026年06月07日 (週日)」）
            on_date = _to_date(key)
            if on_date:
                record["date"] = on_date
                pending = None
                continue
            if key and key not in unknown:
                unknown.append(key)
        if record:
            records.append(record)

    cleaned = []
    for record in records:
        if record.get("weight_kg") is None:
            continue
        record.setdefault("date", default_date or date.today())
        cleaned.append(record)
    return cleaned, unknown

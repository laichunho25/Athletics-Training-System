"""餐點相片辨識：一張相片 → 這一餐有什麼、各種營養有多少。

兩條路，能走哪條看環境：

1. 有設 ANTHROPIC_API_KEY → 把相片交給 Claude 看，回一份結構化的品項清單
   （食物名稱、估計克數、每一項的熱量與三大營養素）。
2. 沒有金鑰 → 退回本地食物字典：把使用者打的文字描述（或 AI 回來的品項名）
   逐字比對 FoodItem，用常見份量估算。估得沒那麼準，但不用連網也不用付錢，
   而且畫面上每一項的克數都可以自己改，改完即時重算。

不論走哪條，結果都是同一個形狀，存進 MealLog.items，之後就只是加總。
"""

import base64
import json
import logging
import os

from nutrition.models import AnalysisSource, FoodItem

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5"

#: 相片最大 5 MB——再大 API 會拒收，也代表使用者傳了原始檔而不是拍照壓縮檔。
MAX_PHOTO_BYTES = 5 * 1024 * 1024

SUPPORTED_MEDIA = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "grams": {"type": "number"},
                    "kcal": {"type": "number"},
                    "carb_g": {"type": "number"},
                    "protein_g": {"type": "number"},
                    "fat_g": {"type": "number"},
                    "fiber_g": {"type": "number"},
                    "sodium_mg": {"type": "number"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": [
                    "name",
                    "grams",
                    "kcal",
                    "carb_g",
                    "protein_g",
                    "fat_g",
                    "fiber_g",
                    "sodium_mg",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
        "assessment": {"type": "string"},
    },
    "required": ["items", "summary", "assessment"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """你是運動營養師，替田徑運動員判讀餐點相片。

規則：
- 只列相片裡看得見的食物，看不出來的不要猜品項。
- grams 是估計的可食部分重量，用常見餐具與餐盤比例推估。
- 熱量與營養素用該食物的常見營養成分推算，數字取整數或一位小數。
- name 用繁體中文，後面可加括號註明煮法（例：雞胸肉（煎））。
- summary 一句話說這一餐是什麼。
- assessment 兩三句：這餐的三大營養素比例對這位運動員的優缺點，缺什麼、多了什麼。
- 分不清楚份量時，confidence 填 low，寧可保守估計。"""


def api_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def media_type_for(filename):
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return SUPPORTED_MEDIA.get(ext)


# ------------------------------------------------------------------ AI 路線


def analyze_with_claude(image_bytes, media_type, hint="", athlete=None):
    """把相片交給 Claude，回 (items, summary, assessment)。失敗時丟例外由呼叫端接。"""
    import anthropic

    client = anthropic.Anthropic()

    who = ""
    if athlete is not None:
        who = (
            f"這位運動員：{athlete.age} 歲 {athlete.get_sex_display()}，"
            f"體重約 {athlete.current_weight_kg} kg，主項 {athlete.primary_event.name_zh}。"
        )
    ask = "這一餐有什麼？請估算各項食物的份量與營養。"
    if hint:
        ask += f"\n使用者補充：{hint}"
    if who:
        ask += f"\n{who}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": ITEM_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.standard_b64encode(image_bytes).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": ask},
                ],
            }
        ],
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return data.get("items", []), data.get("summary", ""), data.get("assessment", "")


# ------------------------------------------------------------- 食物字典路線


def match_food(word):
    """一個詞對到食物字典裡的哪一項（先精準、後包含）。"""
    word = (word or "").strip().lower()
    if not word:
        return None
    foods = list(FoodItem.objects.all())
    for food in foods:
        if word in food.keywords:
            return food
    for food in foods:
        if any(k in word or word in k for k in food.keywords):
            return food
    return None


def split_description(text):
    """把「白飯 雞胸肉、西蘭花」拆成一個個詞。"""
    for sep in ("、", ",", "，", "＋", "+", "\n", ";", "；"):
        text = text.replace(sep, " ")
    return [w for w in text.split() if w]


def analyze_with_dictionary(text):
    """沒有 AI 時的退路：文字比對食物字典，用常見份量估算。"""
    items = []
    missed = []
    for word in split_description(text):
        food = match_food(word)
        if food is None:
            missed.append(word)
            continue
        grams = food.typical_serving_g or 100
        row = {"name": food.name_zh, "grams": grams, "confidence": "low"}
        row.update(food.nutrients_for(grams))
        items.append(row)

    summary = "、".join(i["name"] for i in items) or "沒有比對到食物"
    notes = ["以食物字典的常見份量估算，克數請自己改成實際的份量。"]
    if missed:
        notes.append("字典裡沒有：" + "、".join(missed) + "（可以在後台的食物字典加進去）。")
    return items, summary, " ".join(notes)


# ------------------------------------------------------------------ 對外入口


def analyze_meal(image_bytes=None, filename="", description="", athlete=None):
    """辨識一餐。回傳 dict：items / summary / assessment / source / error。

    有相片又有金鑰就走 AI；其餘情況一律退回食物字典，永遠不會整個失敗。
    """
    if image_bytes and api_available():
        media_type = media_type_for(filename)
        if media_type is None:
            return _fallback(description, "相片格式不支援（要 jpg / png / webp / gif），改用文字估算。")
        if len(image_bytes) > MAX_PHOTO_BYTES:
            return _fallback(description, "相片超過 5 MB，改用文字估算；請用手機拍照的壓縮檔。")
        try:
            items, summary, assessment = analyze_with_claude(
                image_bytes, media_type, hint=description, athlete=athlete
            )
            return {
                "items": items,
                "summary": summary,
                "assessment": assessment,
                "source": AnalysisSource.PHOTO_AI,
                "error": "",
            }
        except Exception as exc:  # 網路、金鑰、額度、回傳格式——都不該讓使用者卡住
            logger.warning("餐點相片辨識失敗，改用食物字典：%s", exc)
            return _fallback(description, f"相片辨識沒成功（{exc.__class__.__name__}），改用文字估算。")

    if image_bytes and not api_available():
        return _fallback(
            description,
            "這台伺服器沒有設定 ANTHROPIC_API_KEY，暫時看不了相片；相片會存起來，營養先用文字估算。",
        )
    return _fallback(description, "")


def _fallback(description, error):
    items, summary, assessment = analyze_with_dictionary(description)
    return {
        "items": items,
        "summary": summary,
        "assessment": assessment,
        "source": AnalysisSource.DICTIONARY,
        "error": error,
    }


def totals(items):
    """把品項清單加總成一餐的營養值。"""
    keys = ("kcal", "carb_g", "protein_g", "fat_g", "fiber_g", "sodium_mg")
    out = {k: 0.0 for k in keys}
    for row in items or []:
        for k in keys:
            try:
                out[k] += float(row.get(k) or 0)
            except (TypeError, ValueError):
                continue
    return {k: round(v) for k, v in out.items()}

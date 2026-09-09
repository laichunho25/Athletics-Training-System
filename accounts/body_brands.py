"""體組成磅的品牌預設：同一個欄位，不同牌子的報告紙叫法不一樣。

香港 24/7 Fitness 現時擺的兩款機——「HOWBODY」與「InBody」——印出來的項目名
跟本來表單用的 Tanita 叫法差很多（例：肌肉量 vs 骨骼肌肉量、右腳 vs 右下肢），
量完照著報告紙抄的時候很容易對不上。

這裡把每個牌子的叫法集中起來：
* ``labels``   —— 表單欄位 → 那個牌子報告紙上的項目名
* ``sections`` —— 分段標題（身體成分分析／節段肌肉分析…）
* ``hidden``   —— 那個牌子沒有印的項目，表單直接收起來（也不會存值）
* ``aliases``  —— 那個牌子的項目名 → 欄位，餵給檔案匯入／貼上文字的解析

品牌只影響「怎麼顯示、怎麼認欄名」，資料庫欄位本身是共用的。
"""

from django.utils.translation import gettext_lazy as _

GENERIC = "GENERIC"
INBODY = "INBODY"
HOWBODY = "HOWBODY"

#: 只有這幾個牌子印的項目，通用（Tanita 之類）表單上不出現
_KOREAN_STYLE_ONLY = [
    "body_fat_mass_kg", "fat_free_mass_kg", "tbw_liters",
    "protein_kg", "mineral_kg", "whr", "ecw_tbw", "score",
]

#: Tanita 系才有的判定分數
_TANITA_ONLY = [
    "muscle_mass_index", "muscle_quality_score", "mba_rating",
    "mq_arm_r", "mq_arm_l", "mq_leg_r", "mq_leg_l",
]

BRAND_PRESETS = {
    GENERIC: {
        "name": _("通用（Tanita 等）"),
        "device_placeholder": _("例：RD-545AS"),
        "hint": "",
        "labels": {},
        "sections": {},
        "hidden": list(_KOREAN_STYLE_ONLY),
        "aliases": {},
    },
    INBODY: {
        "name": "InBody",
        "device_placeholder": _("例：InBody 270 / 570 / 770"),
        "hint": _("欄位已換成 InBody 報告紙上的叫法，由上到下對著抄就行。節段體脂肪若報告紙印的是 kg，這裡的百分比格請留空。"),
        "labels": {
            "weight_kg": _("體重 Weight (kg) *"),
            "muscle_mass_kg": _("骨骼肌肉量 SMM (kg)"),
            "body_fat_mass_kg": _("體脂肪量 BFM (kg)"),
            "body_fat_pct": _("體脂肪率 PBF (%)"),
            "fat_free_mass_kg": _("去脂體重 FFM (kg)"),
            "tbw_liters": _("身體總水分 TBW (L)"),
            "protein_kg": _("蛋白質 (kg)"),
            "mineral_kg": _("無機鹽 (kg)"),
            "visceral_fat_level": _("內臟脂肪等級 VFL"),
            "bmr_kcal": _("基礎代謝量 BMR (kcal)"),
            "whr": _("腰臀圍比 WHR"),
            "ecw_tbw": _("細胞外水分比 ECW/TBW"),
            "score": _("InBody 分數"),
            "muscle_leg_r": _("右下肢"),
            "muscle_leg_l": _("左下肢"),
            "fat_leg_r": _("右下肢"),
            "fat_leg_l": _("左下肢"),
        },
        "sections": {
            "whole": _("身體成分分析"),
            "segments": _("節段分析（右上肢／左上肢／軀幹／右下肢／左下肢）"),
            "seg_muscle": _("節段肌肉分析 (kg)"),
            "seg_fat": _("節段體脂肪分析 (%)"),
            "seg_quality": "",
        },
        "hidden": _TANITA_ONLY + ["bone_mass_kg", "body_water_pct", "metabolic_age"],
        "aliases": {
            "骨骼肌肉量": "muscle_mass_kg", "骨骼肌肉重": "muscle_mass_kg",
            "smm": "muscle_mass_kg", "skeletalmusclemass": "muscle_mass_kg",
            "體脂肪量": "body_fat_mass_kg", "体脂肪量": "body_fat_mass_kg",
            "脂肪量": "body_fat_mass_kg", "bfm": "body_fat_mass_kg",
            "bodyfatmass": "body_fat_mass_kg",
            "去脂體重": "fat_free_mass_kg", "去脂体重": "fat_free_mass_kg",
            "非脂肪量": "fat_free_mass_kg", "ffm": "fat_free_mass_kg",
            "fatfreemass": "fat_free_mass_kg",
            "身體總水分": "tbw_liters", "身体总水分": "tbw_liters",
            "體內總水分": "tbw_liters", "tbw": "tbw_liters",
            "totalbodywater": "tbw_liters",
            "蛋白質": "protein_kg", "蛋白质": "protein_kg", "protein": "protein_kg",
            "無機鹽": "mineral_kg", "无机盐": "mineral_kg",
            "礦物質": "mineral_kg", "矿物质": "mineral_kg", "mineral": "mineral_kg",
            "minerals": "mineral_kg",
            "腰臀圍比": "whr", "腰臀比": "whr", "whr": "whr",
            "waisthipratio": "whr",
            "細胞外水分比": "ecw_tbw", "细胞外水分比": "ecw_tbw",
            "ecw/tbw": "ecw_tbw", "ecwtbw": "ecw_tbw",
            "inbody分數": "score", "inbody分数": "score", "inbodyscore": "score",
            "身體分數": "score", "健康分數": "score", "健康分数": "score",
            "總分": "score", "分數": "score", "score": "score",
            "右下肢肌肉量": "muscle_leg_r", "左下肢肌肉量": "muscle_leg_l",
            "右下肢脂肪率": "fat_leg_r", "左下肢脂肪率": "fat_leg_l",
            "身體年齡": "metabolic_age", "身体年龄": "metabolic_age",
        },
    },
    HOWBODY: {
        "name": "HOWBODY",
        "device_placeholder": _("例：HOWBODY H30 / iBody"),
        "hint": _("欄位已換成 HOWBODY 報告紙上的叫法（骨骼肌肉量、體脂肪量、身體水分…），對著抄就行。"),
        "labels": {
            "weight_kg": _("體重 (kg) *"),
            "muscle_mass_kg": _("骨骼肌肉量 (kg)"),
            "body_fat_mass_kg": _("體脂肪量 (kg)"),
            "body_fat_pct": _("體脂肪率 (%)"),
            "fat_free_mass_kg": _("去脂體重 (kg)"),
            "tbw_liters": _("身體水分 (L)"),
            "protein_kg": _("蛋白質 (kg)"),
            "mineral_kg": _("礦物質 (kg)"),
            "visceral_fat_level": _("內臟脂肪等級"),
            "bmr_kcal": _("基礎代謝量 (kcal)"),
            "metabolic_age": _("身體年齡 (歲)"),
            "whr": _("腰臀比 WHR"),
            "score": _("健康分數"),
            "muscle_arm_r": _("右臂"), "muscle_arm_l": _("左臂"),
            "muscle_leg_r": _("右腿"), "muscle_leg_l": _("左腿"),
            "fat_arm_r": _("右臂"), "fat_arm_l": _("左臂"),
            "fat_leg_r": _("右腿"), "fat_leg_l": _("左腿"),
        },
        "sections": {
            "whole": _("身體成分分析"),
            "segments": _("節段分析（右臂／左臂／軀幹／右腿／左腿）"),
            "seg_muscle": _("節段肌肉量 (kg)"),
            "seg_fat": _("節段體脂肪率 (%)"),
            "seg_quality": "",
        },
        "hidden": _TANITA_ONLY + ["bone_mass_kg", "body_water_pct", "ecw_tbw"],
        "aliases": {
            "右臂肌肉量": "muscle_arm_r", "左臂肌肉量": "muscle_arm_l",
            "右腿肌肉量": "muscle_leg_r", "左腿肌肉量": "muscle_leg_l",
            "右臂脂肪率": "fat_arm_r", "左臂脂肪率": "fat_arm_l",
            "右腿脂肪率": "fat_leg_r", "左腿脂肪率": "fat_leg_l",
            "身體水分": "tbw_liters", "身体水分": "tbw_liters",
        },
    },
}

#: 部位在報告紙上怎麼叫（總覽頁的部位表格跟著品牌顯示）
SEGMENT_NAMES = {
    GENERIC: {
        "arm_r": _("右上肢"), "arm_l": _("左上肢"),
        "leg_r": _("右腳"), "leg_l": _("左腳"), "trunk": _("軀幹"),
    },
    INBODY: {
        "arm_r": _("右上肢"), "arm_l": _("左上肢"),
        "leg_r": _("右下肢"), "leg_l": _("左下肢"), "trunk": _("軀幹"),
    },
    HOWBODY: {
        "arm_r": _("右臂"), "arm_l": _("左臂"),
        "leg_r": _("右腿"), "leg_l": _("左腿"), "trunk": _("軀幹"),
    },
}

#: 給下拉選單用：(值, 顯示名)
BRAND_CHOICES = [(key, preset["name"]) for key, preset in BRAND_PRESETS.items()]

#: 品牌名怎麼寫都認得（機型欄打 "InBody 570" 也能自動切）
BRAND_KEYWORDS = {
    INBODY: ("inbody", "in body", "인바디"),
    HOWBODY: ("howbody", "how body", "하우바디"),
}


def brand_aliases():
    """所有品牌的項目名別名合起來（給 body_import 的 FIELD_ALIASES 用）。"""
    merged = {}
    for preset in BRAND_PRESETS.values():
        merged.update(preset["aliases"])
    return merged


def detect_brand(text):
    """從機型／品牌欄的文字認出牌子，認不出回空字串。"""
    lowered = str(text or "").strip().lower()
    if not lowered:
        return ""
    for brand, keywords in BRAND_KEYWORDS.items():
        if any(word in lowered for word in keywords):
            return brand
    return ""


def form_presets():
    """丟給前端的版本：只留表單要用的那幾塊，翻譯字串轉成 str。"""
    return {
        key: {
            "name": str(preset["name"]),
            "device_placeholder": str(preset["device_placeholder"]),
            "hint": str(preset["hint"]),
            "labels": {field: str(label) for field, label in preset["labels"].items()},
            "sections": {slot: str(title) for slot, title in preset["sections"].items()},
            "hidden": list(preset["hidden"]),
            "keywords": list(BRAND_KEYWORDS.get(key, ())),
        }
        for key, preset in BRAND_PRESETS.items()
    }

"""英文語言檔的守門測試：不准有未翻譯、fuzzy，或前後對不上的佔位符。

以後新增中文字串又忘了跑 makemessages／補翻譯，這裡就會紅燈。
"""

import io
import re

from django.conf import settings
from django.test import SimpleTestCase
from django.utils.translation import activate, deactivate, gettext

PO = settings.BASE_DIR / "locale" / "en" / "LC_MESSAGES" / "django.po"
PLACEHOLDER = re.compile(r"%\([^)]+\)s|\{[a-z_]+\}")


def _blocks():
    """把 po 拆成一段一段；只認行首關鍵字，不解跳脫字元。"""
    text = io.open(PO, encoding="utf-8").read()
    for block in text.split("\n\n"):
        msgid, msgstrs, cur = [], [], None
        for line in block.split("\n"):
            if line.startswith("msgid_plural "):
                cur = None
            elif line.startswith("msgid "):
                cur = msgid
                cur.append(line[6:])
            elif line.startswith("msgstr"):
                cur = [line[line.index('"'):]] if '"' in line else []
                msgstrs.append(cur)
            elif line.startswith('"') and cur is not None:
                cur.append(line)
        if not msgid:
            continue
        join = lambda parts: "".join(p.strip()[1:-1] for p in parts if p.strip().startswith('"'))
        yield block, join(msgid), [join(m) for m in msgstrs]


class EnglishCatalogueTests(SimpleTestCase):
    def test_every_string_is_translated(self):
        missing = [mid for _b, mid, strs in _blocks() if mid and any(s == "" for s in strs)]
        self.assertEqual(missing, [], "這些字串還沒有英文翻譯")

    def test_nothing_is_left_fuzzy(self):
        fuzzy = [
            mid
            for block, mid, _s in _blocks()
            if mid and any(line.startswith("#,") and "fuzzy" in line for line in block.split("\n"))
        ]
        self.assertEqual(fuzzy, [], "fuzzy 是機器猜的，要人看過再拿掉標記")

    def test_placeholders_survive_the_translation(self):
        bad = [
            (mid, s)
            for _b, mid, strs in _blocks()
            for s in strs
            if mid and sorted(PLACEHOLDER.findall(mid)) != sorted(PLACEHOLDER.findall(s))
        ]
        self.assertEqual(bad, [], "翻譯裡的 %(v0)s / {n} 要跟原文一模一樣")

    def test_the_compiled_catalogue_is_up_to_date(self):
        # .mo 沒重編的話，網站看到的還是舊翻譯——挑一句新的字串驗一下
        activate("en")
        try:
            self.assertEqual(gettext("設計團隊訓練計劃"), "Design a team training plan")
        finally:
            deactivate()

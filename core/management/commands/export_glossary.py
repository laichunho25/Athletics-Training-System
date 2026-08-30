"""
由 core/glossary.py 產生 docs/sprint-glossary.md。

術語只維護一份（core/glossary.py），網站與 MD 檔都由它衍生，
避免兩邊各改各的而對不上。

    python manage.py export_glossary
    python manage.py export_glossary --check   # 只檢查有沒有過期，不寫檔
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.glossary import GLOSSARY, all_terms

HEADER = """# 短跑訓練專業用詞對照表

> 本檔案由 `core/glossary.py` 自動產生，請勿直接編輯。
> 修改術語請改 `core/glossary.py`，然後執行 `python manage.py export_glossary`。

同一個概念，教練、運動員與家長常常各用各的說法。這份對照表把短跑訓練裡
反覆出現的詞固定下來——中英文並列、附上一句話解釋——讓課表上的字、
系統裡的欄位與跑道邊的口令指的是同一件事。

共 {count} 個詞條，分為 {groups} 類。

"""


def build_markdown():
    lines = [HEADER.format(count=len(all_terms()), groups=len(GLOSSARY))]

    lines.append("## 目錄\n")
    for group in GLOSSARY:
        anchor = f"{group['en'].lower().replace(' & ', '--').replace(' / ', '--').replace(' ', '-')}"
        lines.append(f"- [{group['zh']}／{group['en']}](#{anchor})（{len(group['terms'])} 條）")
    lines.append("")

    for group in GLOSSARY:
        lines.append(f"## {group['en']}")
        lines.append("")
        lines.append(f"**{group['zh']}**　{group['intro']}")
        lines.append("")
        lines.append("| English | 中文 | 說明 |")
        lines.append("| --- | --- | --- |")
        for en, zh, note in group["terms"]:
            lines.append(f"| {en} | {zh} | {note} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "訓練課表不是罐頭。這些詞是共同語言，實際的內容要由教練在持續訓練中"
        "逐步了解運動員的能力與進度後，才長得出來——ATM 負責把過程完整記錄下來並轉成分析。"
    )
    lines.append("")
    return "\n".join(lines)


class Command(BaseCommand):
    help = "由 core/glossary.py 產生 docs/sprint-glossary.md"

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="只比對檔案是否為最新，不寫入（不同步時以非零狀態結束）",
        )

    def handle(self, *args, **options):
        target = Path(settings.BASE_DIR) / "docs" / "sprint-glossary.md"
        content = build_markdown()

        if options["check"]:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            if current != content:
                raise CommandError(
                    "docs/sprint-glossary.md 與 core/glossary.py 不同步，"
                    "請執行 python manage.py export_glossary"
                )
            self.stdout.write(self.style.SUCCESS("術語表已是最新"))
            return

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.stdout.write(
            self.style.SUCCESS(
                f"已寫入 {target.relative_to(settings.BASE_DIR)}"
                f"（{len(all_terms())} 個詞條 / {len(GLOSSARY)} 類）"
            )
        )

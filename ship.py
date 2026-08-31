#!/usr/bin/env python
"""一句指令把更新送上線。

流程：系統檢查 → 跑測試 → commit → 推上 GitHub 的 main。
Render 盯著 main（見 render.yaml），收到新 commit 就自動重新部署，
所以推完就等於送到網上了。

用法（Windows 直接用 ship.bat，其他情況都可以這樣跑）：

    py ship.py                      用預設訊息 commit 並上線
    py ship.py 加了運動員列表        用自己的訊息
    py ship.py --dry-run            只演一次，不 commit 也不推
    py ship.py --skip-tests 緊急修  跳過測試（不建議，趕時間才用）
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = "https://www.hohosports.com/"
DASHBOARD = "https://dashboard.render.com/"


def say(text=""):
    print(text, flush=True)


def run(args, dry=False):
    """跑一個指令，回傳 returncode；輸出直接留在畫面上。"""
    if dry:
        say(f"      （--dry-run，只印不做）{' '.join(args)}")
        return 0
    return subprocess.call(args, cwd=ROOT)


def output(args):
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout.strip()


def die(message):
    say()
    say(f"  [X] {message}")
    sys.exit(1)


def main(argv):
    dry = "--dry-run" in argv
    skip_tests = "--skip-tests" in argv
    words = [a for a in argv if not a.startswith("--")]
    message = " ".join(words) or f"update {datetime.now():%Y-%m-%d %H:%M}"

    if not (ROOT / ".git").exists():
        die("這個資料夾不是 git repo，沒東西可以推。")

    say()
    say("  ATM 一鍵上線")
    say("  " + "-" * 40)
    if dry:
        say("  ** --dry-run：只會檢查與測試，不會 commit、不會推上線 **")

    # ---- 1. 系統檢查 ----
    say()
    say("  [1/4] 系統檢查…")
    if run([sys.executable, "manage.py", "check"]) != 0:
        die("系統檢查沒過，沒有上線。")

    # ---- 2. 測試 ----
    say()
    if skip_tests:
        say("  [2/4] 跳過測試（--skip-tests）")
    else:
        say("  [2/4] 跑測試…（約 30 秒）")
        if run([sys.executable, "manage.py", "test"]) != 0:
            die("測試沒過，沒有上線。先把上面紅字的地方修好。")

    # ---- 3. commit ----
    say()
    say("  [3/4] 記錄這次的改動…")
    if run(["git", "add", "-A"], dry) != 0:
        die("git add 失敗。")

    if dry:
        changed = [line[3:] for line in output(["git", "status", "--porcelain"]).splitlines()]
    else:
        changed = output(["git", "diff", "--cached", "--name-only"]).splitlines()

    if changed:
        for name in changed[:12]:
            say(f"      · {name}")
        if len(changed) > 12:
            say(f"      · …另外 {len(changed) - 12} 個檔案")
        if any(name.endswith("db.sqlite3") for name in changed):
            say("      ⚠ db.sqlite3 是本機的練習資料庫，也會一起被送上去；")
            say("        線上跑的是 Render 的 PostgreSQL，不受影響。")
        say(f"      commit 訊息：{message}")
        if run(["git", "commit", "-m", message], dry) != 0:
            die("commit 失敗，沒有上線。")
    else:
        say("      沒有新的改動，直接把目前的版本送上去。")

    # ---- 4. 推上 main ----
    branch = output(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "?"
    say()
    say(f"  [4/4] 推上 GitHub：{branch} → origin/main")
    if run(["git", "push", "origin", "HEAD:main"], dry) != 0:
        say()
        say("  [X] 推送失敗。常見原因：")
        say("      · 沒網路，或 GitHub 登入過期")
        say("      · 線上的 main 有你本機沒有的 commit")
        say("        → 先跑 git pull --rebase origin main，再 ship 一次")
        sys.exit(1)
    if branch != "main" and not dry:
        # 本機的 main 也跟上，免得下次看到的分支圖是舊的
        subprocess.call(
            ["git", "fetch", "origin", "main:main"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    say()
    say("  " + "-" * 40)
    if dry:
        say("  演完了，實際上什麼都沒送出去。")
        return
    say("  已送出。Render 收到 main 的新 commit 會自動重新部署，")
    say("  build 大約 3~5 分鐘，完成後開：")
    say()
    say(f"    網站      {SITE}")
    say(f"    部署進度  {DASHBOARD}")
    say()


if __name__ == "__main__":
    main(sys.argv[1:])

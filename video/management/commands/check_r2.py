"""驗 R2 設定：金鑰對不對、寫得進去嗎、CORS 放行了哪些網址。

上傳失敗時先跑這個。它完全不經過瀏覽器，所以可以把問題切成兩半：
這裡全過 = 金鑰與 bucket 沒問題，剩下的一定是瀏覽器端的 CORS；
這裡就掛了 = 環境變數或 API Token 權限有錯，跟 CORS 無關。

    python manage.py check_r2
"""

import json
from uuid import uuid4

from django.core.management.base import BaseCommand

from video import storage


class Command(BaseCommand):
    help = "檢查 Cloudflare R2 的連線、寫入權限與 CORS 設定"

    def handle(self, *args, **options):
        conf = storage.r2_settings()
        if conf is None:
            self.stdout.write(
                self.style.ERROR("R2 沒有啟用：R2_BUCKET / R2_ACCOUNT_ID / "
                                 "R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY 要四個都設齊。")
            )
            self._show_which_are_missing()
            return

        self.stdout.write(f"bucket   : {conf['bucket']}")
        self.stdout.write(f"endpoint : {conf['endpoint']}")
        self.stdout.write(f"公開網域 : {conf['public_base'] or '（未設，播放走簽發網址）'}")

        made = storage._client()
        if made is None:
            self.stdout.write(self.style.ERROR("建不出 boto3 client——是不是沒裝 boto3？"))
            return
        client, conf = made

        # 1. 連得上而且看得到這個 bucket 嗎
        try:
            client.head_bucket(Bucket=conf["bucket"])
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"[X] 連不到 bucket：{exc}"))
            self.stdout.write(
                "    常見原因：Account ID 打錯（endpoint 就會錯）、"
                "bucket 名字不符、API Token 沒有涵蓋這個 bucket。"
            )
            return
        self.stdout.write(self.style.SUCCESS("[✓] 連得上 bucket"))

        # 2. 真的寫一個小檔進去再刪掉，確認 Token 是 Read & Write 不是唯讀
        key = f"_healthcheck/{uuid4().hex}.txt"
        try:
            client.put_object(Bucket=conf["bucket"], Key=key, Body=b"atm ok")
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"[X] 寫不進去：{exc}"))
            self.stdout.write("    多半是 API Token 只給了 Object Read，要 Object Read & Write。")
            return
        self.stdout.write(self.style.SUCCESS("[✓] 寫得進去"))
        client.delete_object(Bucket=conf["bucket"], Key=key)
        self.stdout.write(self.style.SUCCESS("[✓] 刪得掉（測試檔已清掉）"))

        # 3. CORS——瀏覽器直傳成不成功全看這裡
        try:
            cors = client.get_bucket_cors(Bucket=conf["bucket"])
            rules = cors.get("CORSRules", [])
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"[!] 讀不到 CORS 設定：{exc}"))
            self.stdout.write("    R2 後台 bucket → Settings → CORS Policy 自己看一眼。")
            rules = None

        if rules is not None:
            if not rules:
                self.stdout.write(self.style.ERROR(
                    "[X] 這個 bucket 沒有 CORS 規則——瀏覽器直傳一定會失敗。"
                ))
            else:
                self.stdout.write("CORS 規則：")
                self.stdout.write(json.dumps(rules, ensure_ascii=False, indent=2))
                origins = [o for r in rules for o in r.get("AllowedOrigins", [])]
                methods = {m for r in rules for m in r.get("AllowedMethods", [])}
                self.stdout.write("")
                self.stdout.write(f"放行的網址：{'、'.join(origins) or '（無）'}")
                if "PUT" not in methods and "*" not in methods:
                    self.stdout.write(self.style.ERROR(
                        "[X] AllowedMethods 沒有 PUT——直傳用的就是 PUT。"
                    ))
                self.stdout.write(self.style.WARNING(
                    "請確認你實際開網站時、網址列上的那個網域，"
                    "一字不差地出現在上面這串裡（含 https:// 與 www）。"
                    "用 onrender.com 的網址測就要把它也加進去。"
                ))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            "伺服器這一端沒問題。還是傳不上去的話，就是瀏覽器端的 CORS，"
            "看 F12 Console 那行紅字。"
        ))

    def _show_which_are_missing(self):
        import os

        for name in ("R2_BUCKET", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
                     "R2_SECRET_ACCESS_KEY"):
            value = os.environ.get(name, "").strip()
            mark = "有" if value else "沒有"
            self.stdout.write(f"  {name}: {mark}")

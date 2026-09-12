"""找出 R2 上面沒有任何資料庫紀錄指著的物件。

直傳是兩步的：瀏覽器先把檔 PUT 上 R2，成功之後才 submit 表單讓 Django 寫紀錄。
中間斷掉——關了分頁、表單失敗、同一條片重試了幾次——物件就留在 R2 上，
沒有任何一行 TrainingVideo 指得到它。帳單照計，而且在系統裡完全看不見。

purge_videos 管的是「過期的片」，它從資料庫那一頭數起，永遠碰不到孤兒。
這個指令從 R2 那一頭數起，補上另一半。

    python manage.py find_orphans            # 只列出，不刪
    python manage.py find_orphans --apply    # 真的刪
    python manage.py find_orphans --hours 0  # 連剛上傳的也算（危險，見下）
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from video import storage
from video.models import TrainingVideo

#: 最近這幾個鐘上傳的物件一律跳過。有人可能正正就在這一刻傳到一半——
#: 檔已經在 R2 上，表單還沒 submit。那不是孤兒，那是進行中的上傳。
SAFE_HOURS = 6


class Command(BaseCommand):
    help = "列出（或刪除）R2 上沒有資料庫紀錄的孤兒物件"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours", type=int, default=SAFE_HOURS,
            help=f"只算這麼多小時之前上傳的物件，預設 {SAFE_HOURS}",
        )
        parser.add_argument(
            "--apply", action="store_true",
            help="真的刪除；不加這個參數只會列出清單",
        )

    def handle(self, *args, **options):
        made = storage._client()
        if made is None:
            raise CommandError(
                "R2 沒有設定（四個 R2_* 環境變數要齊），這個指令只對 R2 有意義。"
            )
        client, conf = made

        known = self._known_keys()
        cutoff = timezone.now() - timedelta(hours=options["hours"])

        orphans, skipped = [], 0
        for obj in self._walk(client, conf["bucket"]):
            if obj["Key"] in known:
                continue
            if obj["LastModified"] > cutoff:
                skipped += 1        # 可能正在傳，不要碰
                continue
            orphans.append(obj)

        self.stdout.write(f"R2 物件 {self._counted} 個，資料庫指得到 {len(known)} 個。")
        if skipped:
            self.stdout.write(f"（{skipped} 個是最近 {options['hours']} 小時內的，先不算。）")

        if not orphans:
            self.stdout.write(self.style.SUCCESS("沒有孤兒物件。"))
            return

        freed = sum(o["Size"] for o in orphans)
        for obj in sorted(orphans, key=lambda o: o["LastModified"]):
            self.stdout.write(
                f"  {obj['LastModified']:%Y-%m-%d %H:%M}  "
                f"{obj['Size'] / 1024 / 1024:6.2f} MB  {obj['Key']}"
            )

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"以上 {len(orphans)} 個（約 {freed / 1024 / 1024:.0f} MB）"
                    "沒有紀錄指著。確認無誤請加上 --apply。"
                )
            )
            return

        gone = sum(1 for o in orphans if storage.delete_object(o["Key"]))
        self.stdout.write(
            self.style.SUCCESS(
                f"已刪除 {gone} 個孤兒物件，釋出約 {freed / 1024 / 1024:.0f} MB。"
            )
        )
        if gone != len(orphans):
            self.stdout.write(self.style.ERROR(f"有 {len(orphans) - gone} 個刪不掉，見上面的錯誤。"))

    def _known_keys(self):
        """資料庫指得到的每一個 key：直傳的、Django 傳的、還有縮圖。

        三個欄位都要數。只比對 remote_key 的話，縮圖會整批被當成孤兒刪掉。
        """
        keys = set()
        for video in TrainingVideo.objects.all().only("remote_key", "file", "poster"):
            if video.remote_key:
                keys.add(video.remote_key)
            if video.file:
                keys.add(video.file.name)
            if video.poster:
                keys.add(video.poster.name)
        return keys

    def _walk(self, client, bucket):
        """videos/ 底下的每一個物件；超過 1000 個要翻頁，所以用 paginator。"""
        self._counted = 0
        for page in client.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix="videos/"
        ):
            for obj in page.get("Contents", []):
                self._counted += 1
                yield obj

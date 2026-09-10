"""清掉過了保留期限的影片。

保留政策同時解決兩件事：儲存費用不會無止境長，以及學生的影片不會永遠留在
系統裡。教練勾了「保留為範本」的片不受影響。

    python manage.py purge_videos              # 看看會刪掉哪些（不會真的刪）
    python manage.py purge_videos --apply      # 真的刪
    python manage.py purge_videos --days 180 --apply
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from video.models import TrainingVideo

DEFAULT_DAYS = 90


class Command(BaseCommand):
    help = "刪除超過保留期限、且未標記為範本的訓練影片"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=DEFAULT_DAYS,
            help=f"保留天數（預設 {DEFAULT_DAYS} 天）",
        )
        parser.add_argument(
            "--apply", action="store_true",
            help="真的刪除；不加這個參數只會列出清單",
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = (timezone.now() - timedelta(days=days)).date()
        stale = TrainingVideo.objects.filter(date__lt=cutoff, is_keeper=False)

        total = stale.count()
        if not total:
            self.stdout.write(f"沒有超過 {days} 天的影片可清。")
            return

        freed = sum(v.size_bytes for v in stale)
        for video in stale:
            self.stdout.write(f"  {video.date}  {video.athlete}  {video.display_title}")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"以上 {total} 條（約 {freed / 1024 / 1024:.0f} MB）會被刪除。"
                    "確認無誤請加上 --apply。"
                )
            )
            return

        for video in stale:
            video.drop_file()
            video.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"已刪除 {total} 條影片，釋出約 {freed / 1024 / 1024:.0f} MB。"
            )
        )

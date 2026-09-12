"""清掉過了保留期限的影片。

保留政策同時解決兩件事：儲存費用不會無止境長，以及學生的影片不會永遠留在
系統裡。教練勾了「保留為範本」的片不受影響。

保留天數跟著方案走（後台「影片額度設定」那一頁改）：免費預設 90 天、進階
365 天。清掉的片會同時還回上傳額度——額度算的是現在存著的片，不是累計，
所以運動員不用自己去清也會慢慢有位置。

    python manage.py purge_videos              # 看看會刪掉哪些（不會真的刪）
    python manage.py purge_videos --apply      # 真的刪
    python manage.py purge_videos --days 180 --apply   # 不理方案，一律用這個天數
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import VideoPlan
from video.models import TrainingVideo, VideoQuotaConfig


class Command(BaseCommand):
    help = "刪除超過保留期限、且未標記為範本的訓練影片"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=None,
            help="一律用這個保留天數，不理運動員的方案設定",
        )
        parser.add_argument(
            "--apply", action="store_true",
            help="真的刪除；不加這個參數只會列出清單",
        )

    def handle(self, *args, **options):
        stale = self._stale(options["days"])

        if not stale:
            self.stdout.write("沒有超過保留期限的影片可清。")
            return

        freed = sum(v.size_bytes for v in stale)
        for video in stale:
            self.stdout.write(f"  {video.date}  {video.athlete}  {video.display_title}")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"以上 {len(stale)} 條（約 {freed / 1024 / 1024:.0f} MB）會被刪除。"
                    "確認無誤請加上 --apply。"
                )
            )
            return

        for video in stale:
            video.drop_file()
            video.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"已刪除 {len(stale)} 條影片，釋出約 {freed / 1024 / 1024:.0f} MB。"
            )
        )

    def _stale(self, override_days):
        """過期的片。

        方案不同保留期就不同，所以按方案分兩批各算各的截止日，而不是一條
        SQL 掃全部——只有兩批，比起逐條片去查它主人的方案便宜得多。
        """
        today = timezone.now().date()
        config = VideoQuotaConfig.load()
        out = []
        for plan in VideoPlan.values:
            days = override_days if override_days is not None else config.limits_for(plan)[2]
            if not days:
                continue          # 0 ＝ 這個方案的片不自動清
            out.extend(
                TrainingVideo.objects.filter(
                    athlete__video_plan=plan,
                    date__lt=today - timedelta(days=days),
                    is_keeper=False,
                ).select_related("athlete__user")
            )
        return out

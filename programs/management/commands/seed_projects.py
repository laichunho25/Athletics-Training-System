"""
建立第一個報名項目：DBSAC Special Strength & Conditioning Sessions。

以 slug 為鍵 upsert，可重複執行；已存在的項目只更新內容，
不會覆蓋你在後台改過的「狀態 / 報名期限」以外的手動調整——
真的要重設請加 --force。
"""

from datetime import date, datetime, time

from django.core.management.base import BaseCommand
from django.utils import timezone

from programs.models import Project, ProjectStatus


def hk(d, t=time(23, 59)):
    """把日期轉成 Asia/Hong_Kong 的 aware datetime。"""
    return timezone.make_aware(datetime.combine(d, t))


PROJECTS = [
    {
        "slug": "dbsac-sc-2026",
        "defaults": {
            "title": "DBSAC Special Strength & Conditioning Sessions",
            "subtitle": "為 HKMAC 及之後的賽季而設的專項力量與體能課",
            "organiser": "DBSAC",
            "description": (
                "作為 HKMAC 及往後賽季備戰的一部分，我們安排了一系列專項力量與體能課程。"
                "訓練以膕繩肌、臀部與核心力量為核心，並兼顧整體力量的提升，"
                "目標是把重量室裡練到的力量，真正轉化成跑道上的表現。"
            ),
            "schedule_text": "每週一，2026 年 9 月 9 日至 11 月 9 日",
            "start_date": date(2026, 9, 9),
            "end_date": date(2026, 11, 9),
            "session_count": 10,
            "group_note": "共 10 堂，分 2 組進行，每組 5 堂",
            "capacity_per_session": 5,
            "capacity_total": 10,
            "trainer": "Lai Chun Ho",
            "recommended_for": "田徑運動員（短跑、跨欄及中距離）優先",
            "focus": (
                "發展膕繩肌、臀部與核心力量，並提升整體力量以改善運動表現。"
            ),
            "venue_name": "The Leaper Sports Lab – Hong Kong",
            "venue_address": "荔枝角利嘉街帝國中心 22A 室（Room 22A, King's Tower, King Lam Street, Lai Chi Kok）",
            "venue_note": "港鐵荔枝角站 B1 出口步行約 8 分鐘",
            "price_hkd": 320,
            "price_note": "每位參加者",
            "important_note": (
                "由於場地須提前預訂並付款，所有套裝課堂一經報名恕不退款，敬請見諒。"
            ),
            "contact_note": "WhatsApp Lai Chun Ho +852 6531 2212",
            "status": ProjectStatus.OPEN,
            "closes_at": hk(date(2026, 9, 3)),
            "display_order": 0,
        },
    }
]


class Command(BaseCommand):
    help = "建立／更新公開報名項目（以 slug 為鍵，可重複執行）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="連已存在的項目也一併覆寫（預設只建立缺少的項目）",
        )

    def handle(self, *args, **options):
        created = updated = skipped = 0
        for spec in PROJECTS:
            exists = Project.objects.filter(slug=spec["slug"]).exists()
            if exists and not options["force"]:
                skipped += 1
                continue
            _, is_new = Project.objects.update_or_create(
                slug=spec["slug"], defaults=spec["defaults"]
            )
            created += is_new
            updated += not is_new

        self.stdout.write(
            self.style.SUCCESS(
                f"報名項目：新增 {created} 個、更新 {updated} 個、略過 {skipped} 個"
                + ("（已存在的項目要覆寫請加 --force）" if skipped else "")
            )
        )

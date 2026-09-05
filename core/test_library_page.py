"""運動練習項目庫頁面：瀏覽、新增、以及等管理員確認的流程。"""
import io

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.test_factories import make_admin, make_athlete, make_coach
from training.library import library_catalog, library_groups, visible_definitions
from training.models import (
    ActivityDefinition,
    Discipline,
    LibraryStatus,
    MovementKind,
    SportType,
)

PW = "test-pw-12345"


class LibraryPageTests(TestCase):
    fixtures = ["events"]

    @classmethod
    def setUpTestData(cls):
        call_command("seed_activities", verbosity=0, stdout=io.StringIO())
        cls.coach = make_coach(username="lib-page-coach").user
        cls.athlete = make_athlete(username="lib-page-ath", coach=None)
        cls.admin = make_admin(username="lib-page-admin")
        cls.url = reverse("web:library")

    def test_the_page_opens_on_the_first_sport_with_its_disciplines(self):
        self.client.login(username="lib-page-coach", password=PW)
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["sport"].name, "田徑")
        self.assertContains(page, "短跑")
        self.assertContains(page, "運動練習項目庫")

    def test_picking_a_discipline_lists_its_movements_with_the_descriptions(self):
        """動作說明從數據分析搬過來了，要在這一頁看得到。"""
        self.client.login(username="lib-page-coach", password=PW)
        plyo = Discipline.objects.get(name="增強式與爆發力訓練")
        page = self.client.get(f"{self.url}?discipline={plyo.id}")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "單腳踝彈跳")
        self.assertContains(page, "能訓練單側穩定度")

    def test_the_movement_descriptions_left_the_analytics_page(self):
        self.client.login(username="lib-page-ath", password=PW)
        page = self.client.get(f"{reverse('web:analytics')}?athlete={self.athlete.id}")
        self.assertNotContains(page, "能訓練單側穩定度")

    def test_an_athlete_can_add_a_movement_but_it_waits_for_the_admin(self):
        self.client.login(username="lib-page-ath", password=PW)
        sprint = Discipline.objects.get(name="短跑")
        kind = MovementKind.objects.get(name="專項動作")
        self.client.post(
            self.url,
            {
                "action": "add_activity",
                "name": "沙地 30m 加速",
                "discipline": sprint.id,
                "movement_kind": kind.id,
                "default_block": "MAIN",
                "note": "在沙地做的短加速，增加推蹬阻力。",
            },
        )
        row = ActivityDefinition.objects.get(name="沙地 30m 加速")
        self.assertEqual(row.status, LibraryStatus.PENDING)
        # 分類跟著運動項目走，數據分析才知道要歸到哪個範疇
        self.assertEqual(row.category, sprint.activity_category)
        self.assertEqual(row.created_by, self.athlete.user)
        # 別人挑不到，本人挑得到
        self.assertNotIn(row, visible_definitions(self.coach))
        self.assertIn(row, visible_definitions(self.athlete.user))

    def test_an_admin_confirming_it_makes_it_permanent(self):
        sprint = Discipline.objects.get(name="短跑")
        row = ActivityDefinition.objects.create(
            name="沙地 30m 加速", discipline=sprint,
            created_by=self.athlete.user, status=LibraryStatus.PENDING,
        )
        self.client.login(username="lib-page-admin", password=PW)
        page = self.client.get(self.url)
        self.assertContains(page, "沙地 30m 加速")

        self.client.post(
            self.url, {"action": "approve", "model": "activity", "id": row.id}
        )
        row.refresh_from_db()
        self.assertEqual(row.status, LibraryStatus.APPROVED)
        self.assertIn(row, visible_definitions(self.coach))

    def test_a_coach_cannot_confirm_their_own_submission(self):
        row = SportType.objects.create(
            name="游泳", created_by=self.coach, status=LibraryStatus.PENDING
        )
        self.client.login(username="lib-page-coach", password=PW)
        self.client.post(self.url, {"action": "approve", "model": "sport", "id": row.id})
        row.refresh_from_db()
        self.assertEqual(row.status, LibraryStatus.PENDING)

    def test_an_admin_adding_something_is_confirmed_straight_away(self):
        """管理員自己加的不用再確認自己一次。"""
        self.client.login(username="lib-page-admin", password=PW)
        self.client.post(
            self.url, {"action": "add_sport", "name": "游泳", "name_en": "Swimming"}
        )
        self.assertEqual(
            SportType.objects.get(name="游泳").status, LibraryStatus.APPROVED
        )

    def test_a_new_discipline_hangs_under_the_sport_it_was_filed_in(self):
        self.client.login(username="lib-page-coach", password=PW)
        track = SportType.objects.get(name="田徑")
        self.client.post(
            self.url,
            {
                "action": "add_discipline",
                "sport": track.id,
                "name": "撐竿跳",
                "activity_category": "TRACK",
            },
        )
        row = Discipline.objects.get(name="撐竿跳")
        self.assertEqual(row.sport, track)
        self.assertEqual(row.status, LibraryStatus.PENDING)

    def test_the_pickers_are_fed_by_the_library(self):
        """數據分析「從項目庫挑」與課表的挑選清單是同一份來源。"""
        self.client.login(username="lib-page-ath", password=PW)
        page = self.client.get(f"{reverse('web:analytics')}?athlete={self.athlete.id}")
        labels = {g["label"] for g in page.context["activity_groups"]}
        self.assertIn("田徑 · 短跑", labels)
        self.assertIn("體能訓練 · 核心與穩定性訓練", labels)


class MultiSportMovementTests(TestCase):
    """同一個動作掛在好幾個運動種類底下（例：深蹲，田徑也練、體能訓練也練）。"""

    fixtures = ["events"]

    @classmethod
    def setUpTestData(cls):
        call_command("seed_activities", verbosity=0, stdout=io.StringIO())
        cls.coach = make_coach(username="multi-coach").user
        cls.url = reverse("web:library")

    def setUp(self):
        self.sprint = Discipline.objects.get(name="短跑")
        self.strength = Discipline.objects.get(name="肌力與重量訓練")
        self.squat = ActivityDefinition.objects.filter(discipline=self.strength).first()
        self.client.login(username="multi-coach", password=PW)

    def test_a_movement_can_be_added_to_another_sport(self):
        self.client.post(
            self.url,
            {
                "action": "add_to_discipline",
                "activity": self.squat.id,
                "discipline": self.sprint.id,
                "discipline_id": self.strength.id,
            },
        )
        self.assertIn(self.sprint, self.squat.extra_disciplines.all())
        # 原本的位置留著，兩邊都收得到
        homes = {d.id for d in self.squat.all_disciplines}
        self.assertEqual(homes, {self.strength.id, self.sprint.id})

    def test_the_movement_shows_up_under_both_sports(self):
        self.squat.extra_disciplines.add(self.sprint)
        page = self.client.get(f"{self.url}?discipline={self.sprint.id}")
        self.assertContains(page, self.squat.name)
        # 左邊目錄的「田徑」也把它算進去了
        track = [s for s in page.context["tree"]["sports"] if s["obj"].name == "田徑"][0]
        sprint = [d for d in track["disciplines"] if d["obj"].id == self.sprint.id][0]
        self.assertEqual(
            sprint["count"],
            visible_definitions(self.coach).filter(discipline=self.sprint).count() + 1,
        )

    def test_it_can_be_taken_off_the_extra_sport_again(self):
        self.squat.extra_disciplines.add(self.sprint)
        self.client.post(
            self.url,
            {
                "action": "remove_from_discipline",
                "activity": self.squat.id,
                "discipline": self.sprint.id,
            },
        )
        self.assertEqual(list(self.squat.extra_disciplines.all()), [])

    def test_both_pickers_list_it_under_both_sports(self):
        self.squat.extra_disciplines.add(self.sprint)
        groups = library_groups(visible_definitions(self.coach))
        for label in ("田徑 · 短跑", "體能訓練 · 肌力與重量訓練"):
            rows = [g["rows"] for g in groups if g["label"] == label][0]
            self.assertIn(self.squat.name, [d.name for d in rows])


class CascadingPickerTests(TestCase):
    """三處挑選都是「先運動種類 → 運動項目，動作才出來」。"""

    fixtures = ["events"]

    @classmethod
    def setUpTestData(cls):
        call_command("seed_activities", verbosity=0, stdout=io.StringIO())
        cls.athlete = make_athlete(username="pick-ath", coach=None)

    def test_the_catalog_goes_sport_then_discipline_then_movements(self):
        catalog = library_catalog(self.athlete.user)
        track = [s for s in catalog if s["name"] == "田徑"][0]
        self.assertEqual(track["disciplines"][0]["name"], "短跑")
        names = [a["name"] for a in track["disciplines"][0]["activities"]]
        self.assertTrue(names)
        # 別的運動種類的動作不會混進短跑
        self.assertNotIn("槓鈴深蹲", names)

    def test_the_analytics_page_ships_the_catalog(self):
        self.client.login(username="pick-ath", password=PW)
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
        )
        self.assertContains(page, 'id="libcat-json"')
        self.assertTrue(page.context["library_catalog"])

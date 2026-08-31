"""點格子即改 / 分區課表 / 即時同步的測試。

重點在兩件會出事的地方：
  1. 改不是自己寫的東西要被擋下來（而且是各角色都擋）。
  2. 一邊改完，另一邊輪詢要拿得到新內容。
"""

import json

from django.test import TestCase
from django.urls import reverse

from core.test_factories import TODAY, make_admin, make_athlete, make_coach, make_session
from planning.models import NoteKind, SessionNote, TrainingSession
from training.models import ActivityDefinition, BlockType, SessionActivity

PW = "test-pw-12345"


class LiveEditBase(TestCase):
    def setUp(self):
        self.coach = make_coach("coach_a")
        self.other_coach = make_coach("coach_b")
        self.athlete = make_athlete("ath_a", coach=self.coach)
        self.admin = make_admin("admin_a")
        self.session = make_session(self.athlete, TODAY, title="加速度課")
        self.session.assigned_by = self.coach
        self.session.created_by = self.coach.user
        self.session.save()
        self.cell_url = reverse("web:inline_edit")

    def login(self, user):
        self.client.force_login(user)

    def edit(self, target, value):
        return self.client.post(
            self.cell_url,
            data=json.dumps({"target": target, "value": value}),
            content_type="application/json",
        )


class InlineEditPermissionTests(LiveEditBase):
    def test_writer_can_edit_own_session(self):
        self.login(self.coach.user)
        res = self.edit(f"session:{self.session.id}:title", "改成加速度＋落地")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "改成加速度＋落地")

    def test_athlete_cannot_edit_coach_written_plan(self):
        self.login(self.athlete.user)
        res = self.edit(f"session:{self.session.id}:title", "偷改課表")
        self.assertEqual(res.status_code, 403)
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "加速度課")

    def test_athlete_owns_their_own_log_fields(self):
        """打卡類欄位（RPE、滿意度）本來就該由運動員自己填。"""
        self.login(self.athlete.user)
        self.assertTrue(self.edit(f"session:{self.session.id}:session_rpe", "8").json()["ok"])
        self.assertTrue(self.edit(f"session:{self.session.id}:satisfaction", "4").json()["ok"])
        self.session.refresh_from_db()
        self.assertEqual(self.session.session_rpe, 8)
        self.assertEqual(self.session.satisfaction, 4)

    def test_coach_cannot_fill_athlete_rpe(self):
        self.login(self.coach.user)
        self.assertEqual(
            self.edit(f"session:{self.session.id}:session_rpe", "9").status_code, 403
        )

    def test_admin_can_edit_anything(self):
        self.login(self.admin)
        self.assertTrue(self.edit(f"session:{self.session.id}:title", "管理員改的").json()["ok"])

    def test_unrelated_coach_cannot_see_or_edit(self):
        self.login(self.other_coach.user)
        self.assertEqual(
            self.edit(f"session:{self.session.id}:title", "別隊教練").status_code, 403
        )

    def test_invalid_value_is_rejected_with_a_message(self):
        self.login(self.athlete.user)
        res = self.edit(f"session:{self.session.id}:session_rpe", "99")
        self.assertEqual(res.status_code, 400)
        self.assertIn("10", res.json()["error"])

    def test_unknown_field_is_rejected(self):
        self.login(self.admin)
        self.assertEqual(
            self.edit(f"session:{self.session.id}:is_superuser", "1").status_code, 400
        )

    def test_anonymous_is_redirected_to_login(self):
        res = self.edit(f"session:{self.session.id}:title", "無登入")
        self.assertEqual(res.status_code, 302)


class SessionDateMoveTests(LiveEditBase):
    def test_dragging_to_another_day_changes_the_date(self):
        self.login(self.coach.user)
        new_date = TODAY.replace(day=15).isoformat()
        res = self.edit(f"session:{self.session.id}:date", new_date)
        self.assertTrue(res.json()["ok"])
        self.session.refresh_from_db()
        self.assertEqual(self.session.date.isoformat(), new_date)

    def test_bad_date_is_rejected(self):
        self.login(self.coach.user)
        self.assertEqual(
            self.edit(f"session:{self.session.id}:date", "2026/13/40").status_code, 400
        )


class ActivityBlockTests(LiveEditBase):
    def setUp(self):
        super().setUp()
        self.definition = ActivityDefinition.objects.create(
            name="Single Leg Hip Bridge",
            default_block=BlockType.WARMUP,
            default_sets="3 組",
            default_reps="左/右腳 15 次",
            default_weight="body weight",
            default_rest="30s",
        )
        self.detail_url = reverse("web:session_detail", args=[self.session.id])

    def test_adding_an_activity_from_the_library_carries_the_defaults(self):
        self.login(self.coach.user)
        self.client.post(
            self.detail_url,
            {
                "action": "add_activity",
                "block": BlockType.WARMUP,
                "definition": self.definition.id,
                "name": self.definition.name,
                "sets": self.definition.default_sets,
                "reps": self.definition.default_reps,
                "weight": self.definition.default_weight,
                "rest": self.definition.default_rest,
                "distance": "",
                "intensity": "",
            },
        )
        activity = SessionActivity.objects.get(session=self.session)
        self.assertEqual(activity.block, BlockType.WARMUP)
        self.assertEqual(activity.weight, "body weight")
        self.assertEqual(activity.created_by, self.coach.user)
        self.definition.refresh_from_db()
        self.assertEqual(self.definition.use_count, 1)

    def test_new_definition_lands_in_the_library_for_everyone(self):
        self.login(self.coach.user)
        self.client.post(
            self.detail_url,
            {
                "action": "new_definition",
                "name": "A-Skip",
                "default_block": BlockType.WARMUP,
                "distance": "30 米",
                "sets": "3 組",
                "weight": "body weight",
                "rest": "walk back",
                "also_add": "1",
            },
        )
        definition = ActivityDefinition.objects.get(name="A-Skip")
        self.assertEqual(definition.default_distance, "30 米")
        self.assertTrue(
            SessionActivity.objects.filter(session=self.session, name="A-Skip").exists()
        )

    def test_four_blocks_always_show_even_when_empty(self):
        self.login(self.coach.user)
        blocks = self.session.activities_by_block()
        self.assertEqual([b[0] for b in blocks], [b.value for b in BlockType])
        self.assertEqual(len(blocks), 4)

    def test_only_the_writer_can_edit_an_activity_cell(self):
        activity = SessionActivity.objects.create(
            session=self.session,
            block=BlockType.MAIN,
            name="100m 反複跑",
            sets="2 組",
            reps="3 次",
            distance="100 米",
            intensity="80%-90%",
            rest="每次 5 分鐘 / 每組 15 分鐘",
            created_by=self.coach.user,
        )

        self.login(self.athlete.user)
        self.assertEqual(
            self.edit(f"activity:{activity.id}:intensity", "60%").status_code, 403
        )

        self.login(self.coach.user)
        self.assertTrue(
            self.edit(f"activity:{activity.id}:intensity", "85%-95%").json()["ok"]
        )
        activity.refresh_from_db()
        self.assertEqual(activity.intensity, "85%-95%")

    def test_athlete_rates_their_own_activity_only_when_they_wrote_it(self):
        mine = SessionActivity.objects.create(
            session=self.session, block=BlockType.RECOVERY, name="慢跑收操",
            created_by=self.athlete.user,
        )
        self.login(self.athlete.user)
        self.assertTrue(self.edit(f"activity:{mine.id}:satisfaction", "5").json()["ok"])
        mine.refresh_from_db()
        self.assertEqual(mine.satisfaction, 5)

    def test_deleting_someone_elses_activity_is_refused(self):
        activity = SessionActivity.objects.create(
            session=self.session, block=BlockType.MAIN, name="60m 加速跑",
            created_by=self.coach.user,
        )
        self.login(self.athlete.user)
        self.client.post(
            self.detail_url, {"action": "delete_activity", "id": activity.id}
        )
        self.assertTrue(SessionActivity.objects.filter(pk=activity.pk).exists())


class SharedNoteTests(LiveEditBase):
    def setUp(self):
        super().setUp()
        self.detail_url = reverse("web:session_detail", args=[self.session.id])

    def test_everyone_writes_into_the_same_board(self):
        for user in (self.coach.user, self.athlete.user, self.admin):
            self.client.force_login(user)
            self.client.post(
                self.detail_url,
                {"action": "add_note", "kind": NoteKind.NOTE, "body": f"{user.username} 寫的"},
            )
        self.assertEqual(self.session.notes.count(), 3)

        # 三則都看得到
        self.client.force_login(self.athlete.user)
        page = self.client.get(self.detail_url).content.decode()
        for user in (self.coach.user, self.athlete.user, self.admin):
            self.assertIn(f"{user.username} 寫的", page)

    def test_a_note_can_only_be_edited_by_its_author(self):
        note = SessionNote.objects.create(
            session=self.session, author=self.coach.user, body="腳踝要注意"
        )
        self.login(self.athlete.user)
        self.assertEqual(self.edit(f"note:{note.id}:body", "改掉").status_code, 403)

        self.login(self.coach.user)
        self.assertTrue(self.edit(f"note:{note.id}:body", "腳踝要非常注意").json()["ok"])


class LiveSyncTests(LiveEditBase):
    def test_session_live_only_sends_html_when_something_changed(self):
        self.login(self.coach.user)
        url = reverse("web:session_live", args=[self.session.id])
        version = self.session.content_version

        unchanged = self.client.get(url, {"v": version}).json()
        self.assertFalse(unchanged["changed"])

        self.edit(f"session:{self.session.id}:title", "改過的名稱")
        changed = self.client.get(url, {"v": version}).json()
        self.assertTrue(changed["changed"])
        self.assertIn("改過的名稱", changed["html"])
        self.assertNotEqual(changed["version"], version)

    def test_a_new_activity_bumps_the_version(self):
        before = self.session.content_version
        SessionActivity.objects.create(
            session=self.session, block=BlockType.MAIN, name="200m 反複跑",
            created_by=self.coach.user,
        )
        self.assertNotEqual(TrainingSession.objects.get(pk=self.session.pk).content_version, before)

    def test_calendar_live_reflects_a_moved_session(self):
        self.login(self.coach.user)
        url = reverse("web:calendar_live")
        params = {"athlete": self.athlete.id, "year": TODAY.year, "month": TODAY.month}
        first = self.client.get(url, params).json()
        self.assertTrue(first["changed"])

        self.edit(f"session:{self.session.id}:date", TODAY.replace(day=20).isoformat())
        after = self.client.get(url, dict(params, v=first["version"])).json()
        self.assertTrue(after["changed"])
        self.assertNotEqual(after["version"], first["version"])


class PageRenderTests(LiveEditBase):
    """整頁能不能畫出來——四個區塊、拖曳屬性、活動清單都要在。"""

    def setUp(self):
        super().setUp()
        for block in BlockType:
            SessionActivity.objects.create(
                session=self.session,
                block=block,
                name=f"{BlockType(block).label}的活動",
                sets="3 組",
                reps="15 次",
                distance="30 米",
                weight="body weight",
                intensity="80%-90%",
                rest="30s",
                key_points="要點",
                note="備注",
                created_by=self.coach.user,
            )
        ActivityDefinition.objects.create(name="A-Skip", default_block=BlockType.WARMUP)

    def test_session_page_shows_all_four_blocks(self):
        self.login(self.coach.user)
        page = self.client.get(
            reverse("web:session_detail", args=[self.session.id])
        ).content.decode()
        for label in ("熱身", "正課", "補充練習", "恢復練習"):
            self.assertIn(label, page)
        for label in ("組數", "次數", "距離", "重量", "強度", "休息時間"):
            self.assertIn(label, page)
        self.assertIn("訓練要點", page)
        self.assertIn("當日備注", page)
        self.assertIn("A-Skip", page)          # 活動清單挑得到
        self.assertIn("data-edit=", page)      # 格子是可以點的

    def test_calendar_page_marks_movable_sessions(self):
        self.login(self.coach.user)
        page = self.client.get(
            reverse("web:calendar"),
            {"athlete": self.athlete.id, "year": TODAY.year, "month": TODAY.month},
        ).content.decode()
        self.assertIn('draggable="true"', page)
        self.assertIn(f'data-session="{self.session.id}"', page)

    def test_athlete_sees_locked_cells_for_coach_written_rows(self):
        self.login(self.athlete.user)
        page = self.client.get(
            reverse("web:session_detail", args=[self.session.id])
        ).content.decode()
        self.assertIn('data-can="0"', page)    # 別人寫的 → 鎖住
        self.assertIn('data-can="1"', page)    # 自己的打卡欄位 → 可改

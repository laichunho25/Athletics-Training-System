"""重用已經排好的內容：一區存成 program、日曆上把整堂課複製到別的日子。

兩件事解決的是同一個麻煩：同一組熱身、同一堂課，教練不用逐項再挑一次。
"""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from core.models import SessionStatus, SessionType
from core.test_factories import make_admin, make_athlete, make_session
from planning.models import TrainingSession
from training.models import BlockProgram, BlockType, SessionActivity

TODAY = date(2026, 6, 1)


class BlockProgramTests(TestCase):
    """課表上某一區排好之後存成 program，下一課同一區整組套用。"""

    def setUp(self):
        self.admin = make_admin()
        self.athlete = make_athlete("ath_prog")
        self.session = make_session(
            self.athlete, TODAY, session_type=SessionType.TRACK, title="加速度課"
        )
        self.next_session = make_session(
            self.athlete, date(2026, 6, 8), session_type=SessionType.TRACK, title="下一課"
        )
        self.client.force_login(self.admin)
        for i, name in enumerate(["慢跑 800m", "動態伸展", "跑姿練習"], start=1):
            SessionActivity.objects.create(
                session=self.session,
                block=BlockType.WARMUP,
                order=i,
                name=name,
                sets="2 組",
                reps="10 次",
                rest="30s",
                created_by=self.admin,
            )

    def url(self, session):
        return reverse("web:session_detail", args=[session.id])

    def save_program(self, name="短跑熱身（標準）"):
        return self.client.post(
            self.url(self.session),
            {"action": "save_program", "block": BlockType.WARMUP, "program_name": name},
        )

    def test_save_captures_every_row_in_that_block(self):
        self.save_program()
        program = BlockProgram.objects.get()
        self.assertEqual(program.block, BlockType.WARMUP)
        self.assertEqual(program.item_count, 3)
        first = program.items.first()
        self.assertEqual(first.name, "慢跑 800m")
        self.assertEqual(first.sets, "2 組")
        self.assertEqual(first.rest, "30s")

    def test_other_blocks_are_not_captured(self):
        SessionActivity.objects.create(
            session=self.session, block=BlockType.MAIN, order=1, name="6 × 200m"
        )
        self.save_program()
        names = list(BlockProgram.objects.get().items.values_list("name", flat=True))
        self.assertNotIn("6 × 200m", names)

    def test_saving_an_empty_block_is_refused(self):
        self.client.post(
            self.url(self.session),
            {"action": "save_program", "block": BlockType.RECOVERY, "program_name": "空的"},
        )
        self.assertFalse(BlockProgram.objects.exists())

    def test_same_name_overwrites_instead_of_piling_up(self):
        self.save_program()
        self.session.activities.filter(name="跑姿練習").delete()
        self.save_program()
        self.assertEqual(BlockProgram.objects.count(), 1)
        self.assertEqual(BlockProgram.objects.get().item_count, 2)

    def test_apply_writes_the_whole_block_into_another_session(self):
        self.save_program()
        program = BlockProgram.objects.get()
        self.client.post(
            self.url(self.next_session),
            {"action": "apply_program", "program": program.id},
        )
        rows = self.next_session.activities.filter(block=BlockType.WARMUP).order_by("order")
        self.assertEqual([r.name for r in rows], ["慢跑 800m", "動態伸展", "跑姿練習"])
        self.assertEqual(rows[0].sets, "2 組")
        self.assertEqual([r.order for r in rows], [1, 2, 3])
        program.refresh_from_db()
        self.assertEqual(program.use_count, 1)

    def test_apply_appends_after_what_is_already_there(self):
        SessionActivity.objects.create(
            session=self.next_session, block=BlockType.WARMUP, order=1, name="原有的一項"
        )
        self.save_program()
        self.client.post(
            self.url(self.next_session),
            {"action": "apply_program", "program": BlockProgram.objects.get().id},
        )
        rows = self.next_session.activities.filter(block=BlockType.WARMUP).order_by("order")
        self.assertEqual(rows.count(), 4)
        self.assertEqual(rows.first().name, "原有的一項")

    def test_replace_clears_the_block_first(self):
        SessionActivity.objects.create(
            session=self.next_session,
            block=BlockType.WARMUP,
            order=1,
            name="原有的一項",
            created_by=self.admin,
        )
        self.save_program()
        self.client.post(
            self.url(self.next_session),
            {
                "action": "apply_program",
                "program": BlockProgram.objects.get().id,
                "replace": "1",
            },
        )
        names = list(
            self.next_session.activities.filter(block=BlockType.WARMUP).values_list(
                "name", flat=True
            )
        )
        self.assertNotIn("原有的一項", names)
        self.assertEqual(len(names), 3)

    def test_delete_needs_to_be_the_owner(self):
        self.save_program()
        program = BlockProgram.objects.get()
        other = make_athlete("ath_other")
        self.client.force_login(other.user)
        self.client.post(
            self.url(self.session), {"action": "delete_program", "program": program.id}
        )
        self.assertTrue(BlockProgram.objects.filter(pk=program.pk).exists())

        self.client.force_login(self.admin)
        self.client.post(
            self.url(self.session), {"action": "delete_program", "program": program.id}
        )
        self.assertFalse(BlockProgram.objects.filter(pk=program.pk).exists())

    def test_the_page_lists_the_programs_of_each_block(self):
        self.save_program()
        page = self.client.get(self.url(self.next_session))
        blocks = {b["value"]: b for b in page.context["blocks"]}
        self.assertEqual(len(blocks[BlockType.WARMUP]["programs"]), 1)
        self.assertEqual(blocks[BlockType.MAIN]["programs"], [])


class CopySessionTests(TestCase):
    """日曆上把一堂已建立的課複製到其他日子。"""

    def setUp(self):
        self.admin = make_admin()
        self.athlete = make_athlete("ath_copy")
        self.session = make_session(
            self.athlete,
            TODAY,
            session_type=SessionType.TRACK,
            title="加速度課",
            status=SessionStatus.COMPLETED,
        )
        self.session.description = "起跑 30 米"
        self.session.save()
        SessionActivity.objects.create(
            session=self.session,
            block=BlockType.MAIN,
            order=1,
            name="6 × 60m",
            sets="2 組",
            created_by=self.admin,
        )
        self.client.force_login(self.admin)
        self.url = reverse("web:calendar")

    def copy(self, **extra):
        data = {
            "action": "copy_session",
            "athlete": self.athlete.id,
            "session": self.session.id,
            "date": "2026-06-08",
            "copy_activities": "1",
        }
        data.update(extra)
        return self.client.post(f"{self.url}?athlete={self.athlete.id}", data)

    def test_copy_makes_a_new_session_with_the_same_plan(self):
        self.copy()
        copy = TrainingSession.objects.get(date=date(2026, 6, 8))
        self.assertEqual(copy.title, "加速度課")
        self.assertEqual(copy.description, "起跑 30 米")
        self.assertEqual(copy.session_type, self.session.session_type)
        self.assertEqual(copy.activities.count(), 1)
        self.assertEqual(copy.activities.first().sets, "2 組")

    def test_the_original_stays_where_it_was(self):
        self.copy()
        self.session.refresh_from_db()
        self.assertEqual(self.session.date, TODAY)
        self.assertEqual(TrainingSession.objects.count(), 2)

    def test_what_was_logged_afterwards_is_not_copied(self):
        copy_target = date(2026, 6, 8)
        self.copy()
        copy = TrainingSession.objects.get(date=copy_target)
        self.assertEqual(copy.status, SessionStatus.PLANNED)
        self.assertIsNone(copy.session_rpe)
        self.assertIsNone(copy.actual_duration_min)
        self.assertEqual(copy.completion_pct, 0)
        self.assertEqual(copy.created_by, self.admin)

    def test_several_dates_at_once(self):
        self.copy(dates="2026-06-15, 2026-06-22\n2026-06-15")
        made = TrainingSession.objects.filter(title="加速度課").exclude(pk=self.session.pk)
        self.assertEqual(
            sorted(s.date for s in made),
            [date(2026, 6, 8), date(2026, 6, 15), date(2026, 6, 22)],
        )

    def test_activities_can_be_left_out(self):
        self.copy(copy_activities="")
        copy = TrainingSession.objects.get(date=date(2026, 6, 8))
        self.assertEqual(copy.activities.count(), 0)

    def test_a_date_that_makes_no_sense_is_skipped(self):
        self.copy(dates="下星期一")
        self.assertEqual(TrainingSession.objects.count(), 2)

    def test_no_date_no_copy(self):
        self.copy(date="")
        self.assertEqual(TrainingSession.objects.count(), 1)

    def test_cannot_copy_another_athletes_session(self):
        other = make_athlete("ath_stranger")
        stranger = make_session(other, TODAY, title="別人的課")
        self.copy(session=stranger.id)
        self.assertFalse(TrainingSession.objects.filter(date=date(2026, 6, 8)).exists())

    def test_the_calendar_shows_a_copy_button(self):
        page = self.client.get(f"{self.url}?athlete={self.athlete.id}&year=2026&month=6")
        self.assertContains(page, "copyev")
        self.assertContains(page, 'id="copyDlg"')

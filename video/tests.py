"""影片庫的測試：誰看得到、什麼檔擋得住、批註誰刪得掉、保留期限會不會誤刪。

檔案都寫進暫存目錄，跑完測試不會在 media/ 留東西。
"""

import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from analytics.models import MetricDomain, MetricItem, MetricRecord
from core.test_factories import TODAY, make_admin, make_athlete, make_coach
from video import services as vsvc
from video.models import TrainingVideo, VideoKind, VideoNote

MEDIA = tempfile.mkdtemp(prefix="atm-video-test-")


def fake_upload(name="clip.mp4", size=1024):
    return SimpleUploadedFile(name, b"x" * size, content_type="video/mp4")


def make_video(athlete, uploader=None, **kwargs):
    defaults = {
        "date": TODAY,
        "kind": VideoKind.STRENGTH,
        "title": "深蹲",
        "remote_key": "videos/1/abc.mp4",
        "size_bytes": 1024,
        "uploaded_by": uploader,
    }
    defaults.update(kwargs)
    return TrainingVideo.objects.create(athlete=athlete, **defaults)


@override_settings(MEDIA_ROOT=MEDIA)
class VideoTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)


class VisibilityTests(VideoTestCase):
    def setUp(self):
        self.coach = make_coach()
        self.mine = make_athlete("ath_mine", coach=self.coach)
        self.other_coach = make_coach("coach2", squad="別隊")
        self.theirs = make_athlete("ath_theirs", coach=self.other_coach)
        self.v_mine = make_video(self.mine)
        self.v_theirs = make_video(self.theirs)

    def test_athlete_sees_only_own_videos(self):
        seen = vsvc.visible_videos(self.mine.user)
        self.assertEqual(list(seen), [self.v_mine])

    def test_coach_sees_squad_videos_only(self):
        seen = vsvc.visible_videos(self.coach.user)
        self.assertEqual(list(seen), [self.v_mine])

    def test_admin_sees_everything(self):
        seen = vsvc.visible_videos(make_admin())
        self.assertCountEqual(list(seen), [self.v_mine, self.v_theirs])

    def test_get_video_refuses_someone_elses(self):
        with self.assertRaises(vsvc.VideoError):
            vsvc.get_video(self.mine.user, self.v_theirs.pk)


class UploadValidationTests(VideoTestCase):
    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)

    def test_rejects_unsupported_extension(self):
        with self.assertRaises(vsvc.VideoError):
            vsvc.check_filename("training.avi")

    def test_accepts_iphone_mov(self):
        self.assertEqual(vsvc.check_filename("IMG_0042.MOV"), "mov")

    def test_rejects_oversized_file(self):
        with self.assertRaises(vsvc.VideoError):
            vsvc.check_size(600 * 1024 * 1024)

    def test_needs_a_file_or_a_remote_key(self):
        with self.assertRaises(vsvc.VideoError):
            vsvc.save_video(self.athlete.user, self.athlete, {"date": TODAY})

    def test_save_records_browser_measured_metadata(self):
        video = vsvc.save_video(
            self.athlete.user,
            self.athlete,
            {"date": TODAY, "kind": VideoKind.SPRINT, "title": "30m 加速",
             "duration_sec": "4.83", "width": "1920", "height": "1080"},
            upload=fake_upload(),
        )
        self.assertEqual(str(video.duration_sec), "4.83")
        self.assertEqual(video.width, 1920)
        self.assertEqual(video.kind, VideoKind.SPRINT)
        self.assertTrue(video.file.name.endswith(".mp4"))

    def test_unknown_kind_falls_back_to_strength(self):
        video = vsvc.save_video(
            self.athlete.user, self.athlete, {"date": TODAY, "kind": "NONSENSE"},
            upload=fake_upload(),
        )
        self.assertEqual(video.kind, VideoKind.STRENGTH)


class OptionalLinkTests(VideoTestCase):
    """關聯是選擇性的：綁得上就綁，綁不上（別人的紀錄）就當作沒填。"""

    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete("ath_a", coach=self.coach)
        self.stranger = make_athlete("ath_b", coach=self.coach)
        self.item = MetricItem.objects.create(
            domain=MetricDomain.STRENGTH, name="背蹲舉", unit="kg", higher_is_better=True
        )
        self.mine = MetricRecord.objects.create(
            athlete=self.athlete, item=self.item, date=TODAY, weight_kg=100
        )
        self.theirs = MetricRecord.objects.create(
            athlete=self.stranger, item=self.item, date=TODAY, weight_kg=90
        )

    def test_links_own_record(self):
        video = vsvc.save_video(
            self.athlete.user, self.athlete,
            {"date": TODAY, "record": self.mine.pk}, upload=fake_upload(),
        )
        self.assertEqual(video.record, self.mine)

    def test_ignores_another_athletes_record(self):
        video = vsvc.save_video(
            self.athlete.user, self.athlete,
            {"date": TODAY, "record": self.theirs.pk}, upload=fake_upload(),
        )
        self.assertIsNone(video.record)

    def test_ignores_garbage_id(self):
        video = vsvc.save_video(
            self.athlete.user, self.athlete,
            {"date": TODAY, "record": "abc"}, upload=fake_upload(),
        )
        self.assertIsNone(video.record)

    def test_link_choices_only_lists_that_day(self):
        MetricRecord.objects.create(
            athlete=self.athlete, item=self.item, date=TODAY - timedelta(days=3),
            weight_kg=95,
        )
        choices = vsvc.link_choices(self.athlete, TODAY)
        self.assertEqual([c[0] for c in choices["records"]], [self.mine.pk])


class NoteTests(VideoTestCase):
    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        self.outsider = make_athlete("ath_out", coach=make_coach("coach9", squad="別隊"))
        self.video = make_video(self.athlete, uploader=self.athlete.user)

    def test_coach_can_pin_a_note_to_a_timestamp(self):
        note = vsvc.add_note(self.coach.user, self.video, "3.5", "起身時右膝內扣")
        self.assertEqual(str(note.at_sec), "3.50")
        self.assertEqual(note.at_display, "0:03.50")

    def test_outsider_cannot_annotate(self):
        with self.assertRaises(vsvc.VideoError):
            vsvc.add_note(self.outsider.user, self.video, "1", "亂入")

    def test_empty_note_is_refused(self):
        with self.assertRaises(vsvc.VideoError):
            vsvc.add_note(self.coach.user, self.video, "1", "   ")

    def test_negative_timestamp_clamps_to_zero(self):
        note = vsvc.add_note(self.coach.user, self.video, "-5", "開頭")
        self.assertEqual(str(note.at_sec), "0.00")

    def test_athlete_cannot_delete_the_coachs_note(self):
        note = vsvc.add_note(self.coach.user, self.video, "1", "膝蓋")
        with self.assertRaises(vsvc.VideoError):
            vsvc.delete_note(self.athlete.user, note)

    def test_coach_can_delete_any_note(self):
        note = vsvc.add_note(self.athlete.user, self.video, "1", "這裡卡住")
        vsvc.delete_note(self.coach.user, note)
        self.assertFalse(VideoNote.objects.exists())

    def test_athlete_cannot_delete_a_coach_upload(self):
        coach_clip = make_video(self.athlete, uploader=self.coach.user)
        self.assertFalse(vsvc.may_delete(self.athlete.user, coach_clip))
        self.assertTrue(vsvc.may_delete(self.coach.user, coach_clip))


class PurgeCommandTests(VideoTestCase):
    def setUp(self):
        # 保留期限是拿「真的今天」去算的，所以這裡不能用固定的 TODAY。
        today = timezone.localdate()
        self.athlete = make_athlete()
        self.old = make_video(self.athlete, date=today - timedelta(days=400), title="舊片")
        self.keeper = make_video(
            self.athlete, date=today - timedelta(days=400), title="範本", is_keeper=True
        )
        self.fresh = make_video(self.athlete, date=today, title="新片")

    def test_dry_run_deletes_nothing(self):
        call_command("purge_videos", days=90)
        self.assertEqual(TrainingVideo.objects.count(), 3)

    def test_apply_removes_only_stale_non_keepers(self):
        call_command("purge_videos", days=90, apply=True)
        self.assertCountEqual(
            list(TrainingVideo.objects.all()), [self.keeper, self.fresh]
        )


class VideoViewTests(VideoTestCase):
    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        self.client.force_login(self.coach.user)

    def test_library_page_loads(self):
        res = self.client.get(reverse("web:video_list"), {"athlete": self.athlete.id})
        self.assertEqual(res.status_code, 200)

    def test_upload_through_the_form_creates_a_video(self):
        res = self.client.post(
            reverse("web:video_list") + f"?athlete={self.athlete.id}",
            {"action": "upload", "date": TODAY.isoformat(), "kind": VideoKind.SPRINT,
             "title": "起跑", "file": fake_upload()},
        )
        self.assertEqual(res.status_code, 302)
        video = TrainingVideo.objects.get()
        self.assertEqual(video.title, "起跑")
        self.assertEqual(video.uploaded_by, self.coach.user)

    def test_bad_extension_is_reported_not_saved(self):
        self.client.post(
            reverse("web:video_list") + f"?athlete={self.athlete.id}",
            {"action": "upload", "date": TODAY.isoformat(),
             "file": SimpleUploadedFile("clip.avi", b"x", content_type="video/avi")},
        )
        self.assertFalse(TrainingVideo.objects.exists())

    def test_detail_page_loads_and_takes_a_note(self):
        video = make_video(self.athlete, uploader=self.coach.user)
        url = reverse("web:video_detail", args=[video.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {"action": "note_add", "at_sec": "2.25", "body": "手臂"})
        self.assertEqual(video.notes.get().body, "手臂")

    def test_sign_falls_back_to_plain_upload_without_r2(self):
        res = self.client.post(
            reverse("web:video_sign"),
            {"filename": "clip.mp4", "size_bytes": 1024, "content_type": "video/mp4"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["direct"])

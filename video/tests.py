"""影片庫的測試：誰看得到、什麼檔擋得住、批註誰刪得掉、保留期限會不會誤刪。

檔案都寫進暫存目錄，跑完測試不會在 media/ 留東西。
"""

import json
import shutil
import tempfile
from datetime import timedelta
from contextlib import contextmanager
from io import StringIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from analytics.models import MetricDomain, MetricItem, MetricRecord
from core.test_factories import TODAY, make_admin, make_athlete, make_coach
from video import services as vsvc
from video import storage
from core.models import VideoPlan
from video.models import (
    PlanUpgradeRequest,
    TrainingVideo,
    UpgradeStatus,
    VideoKind,
    VideoNote,
    VideoQuotaConfig,
)

MEDIA = tempfile.mkdtemp(prefix="atm-video-test-")


#: 1x1 的 png，模擬前端用 canvas 擷下來的封面
PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


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


class AnalysisToolTests(VideoTestCase):
    """分析工具存進批註的那一段：時間區間與 data 欄位。

    data 是前端送上來的，等於使用者可以隨便塞——所以這裡測的重點是
    「洗不乾淨的東西不會進資料庫」，而不是好路徑會不會過。
    """

    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        self.video = make_video(self.athlete, uploader=self.coach.user)

    def note(self, **kwargs):
        kwargs.setdefault("at_sec", "1")
        kwargs.setdefault("body", "量一下")
        return vsvc.add_note(self.coach.user, self.video, **kwargs)

    def test_timing_note_keeps_the_span(self):
        note = self.note(at_sec="2.00", end_sec="5.50",
                         data={"kind": "timing", "distance_m": 30})
        self.assertEqual(str(note.end_sec), "5.50")
        self.assertAlmostEqual(note.elapsed, 3.5)
        self.assertEqual(note.end_display, "0:05.50")
        self.assertEqual(note.tool, "timing")
        self.assertEqual(note.data["distance_m"], 30)

    def test_b_before_a_is_swapped_not_rejected(self):
        note = self.note(at_sec="9", end_sec="4")
        self.assertEqual(str(note.at_sec), "4.00")
        self.assertEqual(str(note.end_sec), "9.00")

    def test_plain_note_has_no_span_and_no_data(self):
        note = self.note()
        self.assertIsNone(note.end_sec)
        self.assertIsNone(note.elapsed)
        self.assertEqual(note.data, {})
        self.assertEqual(note.end_display, "")
        self.assertFalse(note.has_drawing)

    def test_unknown_tool_kind_is_dropped(self):
        note = self.note(data={"kind": "hack", "taps": [1, 2]})
        self.assertEqual(note.data, {})

    def test_steps_are_rounded_and_capped(self):
        note = self.note(data={"kind": "steps", "taps": [0.123456, "0.9"] + list(range(500))})
        self.assertEqual(note.data["taps"][:2], [0.123, 0.9])
        self.assertEqual(len(note.data["taps"]), vsvc.MAX_TAPS)

    def test_nonsense_taps_are_skipped_not_stored(self):
        note = self.note(data={"kind": "steps", "taps": ["abc", None, "NaN", "inf", 2]})
        self.assertEqual(note.data["taps"], [2.0])

    def test_silly_distance_is_ignored(self):
        note = self.note(data={"kind": "timing", "distance_m": 99999})
        self.assertNotIn("distance_m", note.data)

    def test_drawing_coordinates_are_clamped_to_the_frame(self):
        note = self.note(data={"kind": "draw", "shapes": [
            {"t": "line", "p": [[-2, 0.5], [3, 0.25]]},
        ]})
        self.assertTrue(note.has_drawing)
        self.assertEqual(note.data["shapes"][0]["p"], [[0.0, 0.5], [1.0, 0.25]])

    def test_bad_shapes_are_dropped(self):
        note = self.note(data={"kind": "draw", "shapes": [
            {"t": "rocket", "p": [[0, 0], [1, 1]]},     # 不認得的形狀
            {"t": "line", "p": [[0, 0, 0]]},            # 點的維度不對
            "not a shape",
            {"t": "line", "p": [[0.1, 0.2], [0.3, 0.4]]},
        ]})
        self.assertEqual(len(note.data["shapes"]), 1)
        self.assertEqual(note.data["shapes"][0]["t"], "line")

    def test_shape_count_is_capped(self):
        many = [{"t": "line", "p": [[0, 0], [1, 1]]}] * 200
        note = self.note(data={"kind": "draw", "shapes": many})
        self.assertEqual(len(note.data["shapes"]), vsvc.MAX_SHAPES)

    def test_data_is_not_a_dict(self):
        self.assertEqual(self.note(data="[]").data, {})
        self.assertEqual(self.note(data=None).data, {})


@contextmanager
def fake_r2(ok=True, deletes=True):
    """裝作 R2 接得通、刪得到。

    make_video 預設就帶 remote_key，而 purge --apply 現在會先檢查 R2——
    測試環境沒有金鑰，不頙的話每一個 purge 測試都會撞上那道閘。
    """
    note = "已連上 bucket「b」" if ok else "沒有設定"
    with mock.patch.object(storage, "check_access", return_value=(ok, note)),             mock.patch.object(storage, "delete_object", return_value=deletes):
        yield


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
        with fake_r2():
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

    def test_player_ships_the_ids_the_script_hooks_onto(self):
        """video.js 全靠這幾個 id 找元件，改模板時很容易不小心弄丟。"""
        video = make_video(self.athlete, uploader=self.coach.user)
        html = self.client.get(reverse("web:video_detail", args=[video.pk])).content.decode()
        for marker in ('id="player"', 'id="zoom1"', 'id="draw1"',
                       'id="v-zoom"', 'id="v-fps"', 'id="note-data"'):
            self.assertIn(marker, html)

    def test_direct_upload_posts_only_metadata(self):
        """R2 開著時，檔案已經在雲端了，這一筆 POST 只帶 remote_key 與封面。"""
        res = self.client.post(
            reverse("web:video_list") + f"?athlete={self.athlete.id}",
            {"action": "upload", "date": TODAY.isoformat(), "kind": VideoKind.SPRINT,
             "title": "直傳", "remote_key": f"videos/{self.athlete.id}/deadbeef.mp4",
             "size_bytes": "12345", "duration_sec": "4.83",
             "width": "1920", "height": "1080", "poster": PNG_DATA_URL},
        )
        self.assertEqual(res.status_code, 302)
        video = TrainingVideo.objects.get()
        self.assertEqual(video.remote_key, f"videos/{self.athlete.id}/deadbeef.mp4")
        self.assertFalse(video.file)
        self.assertTrue(video.poster)
        self.assertEqual(video.size_bytes, 12345)


    def test_note_add_carries_the_span_and_the_measurement(self):
        video = make_video(self.athlete, uploader=self.coach.user)
        self.client.post(
            reverse("web:video_detail", args=[video.pk]),
            {"action": "note_add", "at_sec": "2.00", "end_sec": "5.50",
             "body": "A→B 3.50s", "data": json.dumps(
                 {"kind": "timing", "distance_m": 30,
                  "shapes": [{"t": "hline", "p": [[0, 0.7], [1, 0.7]]}]})},
        )
        note = video.notes.get()
        self.assertEqual(str(note.end_sec), "5.50")
        self.assertEqual(note.data["distance_m"], 30)
        self.assertTrue(note.has_drawing)

    def test_broken_json_does_not_500_the_page(self):
        """data 是隱藏欄位，壞掉的話寧可當作沒填，也不要整頁掛掉。"""
        video = make_video(self.athlete, uploader=self.coach.user)
        res = self.client.post(
            reverse("web:video_detail", args=[video.pk]),
            {"action": "note_add", "at_sec": "1", "body": "手臂", "data": "{oops"},
        )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(video.notes.get().data, {})

    def test_detail_page_hands_saved_drawings_to_the_player(self):
        video = make_video(self.athlete, uploader=self.coach.user)
        note = vsvc.add_note(
            self.coach.user, video, "1", "膝角",
            data={"kind": "draw", "shapes": [{"t": "line", "p": [[0, 0], [1, 1]]}]},
        )
        res = self.client.get(reverse("web:video_detail", args=[video.pk]))
        self.assertEqual(res.context["note_shapes"][note.pk], note.data["shapes"])

    def test_sign_falls_back_to_plain_upload_without_r2(self):
        res = self.client.post(
            reverse("web:video_sign"),
            {"filename": "clip.mp4", "size_bytes": 1024, "content_type": "video/mp4"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["direct"])


class SearchTests(VideoTestCase):
    """搜尋與熱搜詞：找得到片，而且熱搜詞是資料自己長出來的，不是寫死的字眼。"""

    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        self.client.force_login(self.coach.user)
        self.sprint = MetricItem.objects.create(
            domain=MetricDomain.TRACK, name="100米", unit="s", higher_is_better=False
        )
        self.squat = MetricItem.objects.create(
            domain=MetricDomain.STRENGTH, name="背蹲舉", unit="kg", higher_is_better=True
        )

    def with_record(self, item, **kwargs):
        record = MetricRecord.objects.create(
            athlete=self.athlete, item=item, date=TODAY, weight_kg=100
        )
        return make_video(self.athlete, record=record, **kwargs)

    def search(self, **params):
        params.setdefault("athlete", self.athlete.id)
        res = self.client.get(reverse("web:video_list"), params)
        return [v.pk for v in res.context["videos"]]

    def test_matches_title_case_insensitively(self):
        hit = make_video(self.athlete, title="Block Start")
        make_video(self.athlete, title="深蹲")
        self.assertEqual(self.search(q="block"), [hit.pk])

    def test_matches_the_linked_item(self):
        hit = self.with_record(self.sprint, title="無題")
        self.with_record(self.squat, title="無題2")
        self.assertEqual(self.search(q="100米"), [hit.pk])

    def test_matches_a_partial_date(self):
        hit = make_video(self.athlete, date=TODAY, title="今天")
        make_video(self.athlete, date=TODAY - timedelta(days=400), title="去年")
        self.assertEqual(self.search(q=TODAY.strftime("%Y-%m")), [hit.pk])

    def test_search_and_kind_filter_stack(self):
        hit = make_video(self.athlete, title="起跑", kind=VideoKind.SPRINT)
        make_video(self.athlete, title="起跑姿勢筆記", kind=VideoKind.STRENGTH)
        self.assertEqual(self.search(q="起跑", kind=VideoKind.SPRINT), [hit.pk])

    def test_hot_terms_rank_by_how_often_they_are_filmed(self):
        for _ in range(3):
            self.with_record(self.sprint)
        self.with_record(self.squat)
        res = self.client.get(reverse("web:video_list"), {"athlete": self.athlete.id})
        self.assertEqual(res.context["hot_terms"], ["100米", "背蹲舉"])

    def test_hot_terms_ignore_the_current_filter(self):
        """篩著跑步時熱搜詞還是全部的——否則按下去就換不回別的範疇。"""
        self.with_record(self.squat)
        res = self.client.get(
            reverse("web:video_list"), {"athlete": self.athlete.id, "kind": VideoKind.SPRINT}
        )
        self.assertEqual(res.context["videos"], [])
        self.assertEqual(res.context["hot_terms"], ["背蹲舉"])

    def test_unlinked_videos_contribute_no_hot_terms(self):
        make_video(self.athlete, title="隨手拍")
        res = self.client.get(reverse("web:video_list"), {"athlete": self.athlete.id})
        self.assertEqual(res.context["hot_terms"], [])


MB = 1024 * 1024


class QuotaTests(VideoTestCase):
    """上傳額度：條數與容量兩道閘，以及後台改得動這件事。"""

    def setUp(self):
        self.athlete = make_athlete()
        self.config = VideoQuotaConfig.load()
        self.config.free_max_videos = 3
        self.config.free_max_mb = 100
        self.config.save()

    def test_defaults_come_from_the_config_row(self):
        quota = vsvc.quota_for(self.athlete)
        self.assertEqual(quota.max_videos, 3)
        self.assertEqual(quota.max_bytes, 100 * MB)
        self.assertEqual(quota.used_videos, 0)
        self.assertFalse(quota.is_full)

    def test_count_gate_blocks_the_fourth_clip(self):
        for _n in range(3):
            make_video(self.athlete, size_bytes=1 * MB)
        with self.assertRaises(vsvc.VideoError):
            vsvc.check_quota(self.athlete, 1 * MB)

    def test_size_gate_blocks_before_the_count_gate(self):
        """兩條大片就吃光 100MB——條數還剩一格也要擋下來。

        這是限條數而不限容量的漏洞：單檔上限乘以條數才是真正的佔用量。
        """
        make_video(self.athlete, size_bytes=60 * MB)
        make_video(self.athlete, size_bytes=35 * MB)
        quota = vsvc.quota_for(self.athlete)
        self.assertEqual(quota.left_videos, 1)
        with self.assertRaises(vsvc.VideoError):
            vsvc.check_quota(self.athlete, 20 * MB)

    def test_deleting_a_clip_gives_the_slot_back(self):
        videos = [make_video(self.athlete, size_bytes=1 * MB) for _n in range(3)]
        self.assertTrue(vsvc.quota_for(self.athlete).is_full)
        videos[0].delete()
        self.assertFalse(vsvc.quota_for(self.athlete).is_full)

    def test_pro_plan_gets_the_bigger_limits(self):
        self.athlete.video_plan = VideoPlan.PRO
        self.athlete.save()
        quota = vsvc.quota_for(self.athlete)
        self.assertEqual(quota.max_videos, self.config.pro_max_videos)
        self.assertTrue(quota.is_pro)

    def test_per_athlete_override_beats_the_plan(self):
        self.athlete.video_max_videos = 50
        self.athlete.save()
        self.assertEqual(vsvc.quota_for(self.athlete).max_videos, 50)

    def test_zero_means_unlimited(self):
        self.athlete.video_max_videos = 0
        self.athlete.video_max_mb = 0
        self.athlete.save()
        make_video(self.athlete, size_bytes=900 * MB)
        quota = vsvc.quota_for(self.athlete)
        self.assertTrue(quota.unlimited)
        self.assertTrue(vsvc.check_quota(self.athlete, 500 * MB).unlimited)

    def test_save_video_refuses_when_full(self):
        for _n in range(3):
            make_video(self.athlete, size_bytes=1 * MB)
        with self.assertRaises(vsvc.VideoError):
            vsvc.save_video(None, self.athlete, {}, upload=fake_upload())
        self.assertEqual(TrainingVideo.objects.count(), 3)

    def test_config_row_is_a_singleton(self):
        VideoQuotaConfig.objects.create(free_max_videos=99)
        self.assertEqual(VideoQuotaConfig.objects.count(), 1)
        self.assertEqual(VideoQuotaConfig.load().free_max_videos, 99)


class QuotaViewTests(VideoTestCase):
    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        self.client.force_login(self.coach.user)
        config = VideoQuotaConfig.load()
        config.free_max_videos = 1
        config.save()

    def test_sign_refuses_when_quota_is_full(self):
        """R2 直傳的額度要在發網址之前擋——傳完才擋會在雲端留下孤兒檔。"""
        make_video(self.athlete, size_bytes=1 * MB)
        res = self.client.post(
            reverse("web:video_sign"),
            {"athlete": self.athlete.id, "filename": "clip.mp4", "size_bytes": 1 * MB},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.json())

    def test_form_upload_refuses_when_quota_is_full(self):
        make_video(self.athlete, size_bytes=1 * MB)
        self.client.post(
            reverse("web:video_list") + f"?athlete={self.athlete.id}",
            {"action": "upload", "date": TODAY.isoformat(), "file": fake_upload()},
        )
        self.assertEqual(TrainingVideo.objects.count(), 1)

    def test_library_page_shows_the_usage_bar(self):
        res = self.client.get(reverse("web:video_list"), {"athlete": self.athlete.id})
        self.assertContains(res, "已用額度")


class PlanRetentionTests(VideoTestCase):
    """保留天數跟著方案走：進階會員的片留得久一點。"""

    def setUp(self):
        config = VideoQuotaConfig.load()
        config.free_retain_days = 90
        config.pro_retain_days = 365
        config.save()
        old = TODAY - timedelta(days=120)
        self.free = make_video(make_athlete("ath_free"), date=old)
        pro = make_athlete("ath_pro")
        pro.video_plan = VideoPlan.PRO
        pro.save()
        self.pro = make_video(pro, date=old)

    def test_only_the_free_athletes_clip_is_purged(self):
        with fake_r2():
            call_command("purge_videos", apply=True)
        self.assertCountEqual(list(TrainingVideo.objects.all()), [self.pro])

    def test_zero_days_turns_purging_off(self):
        config = VideoQuotaConfig.load()
        config.free_retain_days = 0
        config.save()
        with fake_r2():
            call_command("purge_videos", apply=True)
        self.assertEqual(TrainingVideo.objects.count(), 2)


class RetentionHintTests(VideoTestCase):
    """保留期限要講得出口：傳完即刻講一次，片的頁面也一直摂到。

    畫面上的日子要跟 purge_videos 實際篩的同一條條件走——拍攝日期，
    不是上傳時間。兩邊對不上的話，學生會看到一個永遠不會到的日期。
    """

    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        config = VideoQuotaConfig.load()
        config.free_retain_days = 90
        config.save()

    def test_purge_date_counts_from_the_shoot_date(self):
        video = make_video(self.athlete, date=TODAY - timedelta(days=10))
        self.assertEqual(video.retention_days, 90)
        self.assertEqual(video.purge_date, TODAY + timedelta(days=80))

    def test_keeper_has_no_purge_date(self):
        video = make_video(self.athlete, is_keeper=True)
        self.assertIsNone(video.retention_days)
        self.assertIsNone(video.purge_date)

    def test_zero_days_has_no_purge_date(self):
        config = VideoQuotaConfig.load()
        config.free_retain_days = 0
        config.save()
        self.assertIsNone(make_video(self.athlete).purge_date)

    def test_pro_members_get_the_longer_date(self):
        self.athlete.video_plan = VideoPlan.PRO
        self.athlete.save()
        config = VideoQuotaConfig.load()
        config.pro_retain_days = 365
        config.save()
        self.assertEqual(make_video(self.athlete).retention_days, 365)

    def test_the_page_warns_before_you_even_pick_a_file(self):
        self.client.force_login(self.athlete.user)
        res = self.client.get(reverse("web:video_list"), {"athlete": self.athlete.id})
        self.assertContains(res, "天後自動刪除")

    def test_uploading_says_when_the_clip_goes_away(self):
        self.client.force_login(self.athlete.user)
        res = self.client.post(
            reverse("web:video_list") + f"?athlete={self.athlete.id}",
            {"action": "upload", "date": TODAY.isoformat(), "file": fake_upload()},
            follow=True,
        )
        video = TrainingVideo.objects.get()
        self.assertContains(res, video.purge_date.strftime("%Y-%m-%d"))
        self.assertContains(res, "設為範本")

    def test_an_old_clip_is_told_it_is_already_past_due(self):
        """補傳一條半年前的片，下一次清理就會輪到它。"""
        self.client.force_login(self.athlete.user)
        old = (TODAY - timedelta(days=200)).isoformat()
        res = self.client.post(
            reverse("web:video_list") + f"?athlete={self.athlete.id}",
            {"action": "upload", "date": old, "file": fake_upload()},
            follow=True,
        )
        self.assertContains(res, "下次清理時會被自動刪除")

    def test_detail_page_keeps_showing_the_date(self):
        video = make_video(self.athlete)
        self.client.force_login(self.athlete.user)
        res = self.client.get(reverse("web:video_detail", args=[video.pk]))
        self.assertContains(res, video.purge_date.strftime("%Y-%m-%d"))

    def test_detail_page_says_a_keeper_is_safe(self):
        video = make_video(self.athlete, is_keeper=True)
        self.client.force_login(self.athlete.user)
        res = self.client.get(reverse("web:video_detail", args=[video.pk]))
        self.assertContains(res, "不會被保留期限清掉")


class PurgeR2GuardTests(VideoTestCase):
    """Cron 沒有 Shell 可以進去試，所以 purge 本身要講得出 R2 通不通。

    更要緊的是：連不上 R2 的時候寧可一條都不刪。以前會把資料庫那幾行
    刪掉、雲端的物件却留下來，而且 log 還寫「已刪除」——騙人騙得很彻底。
    """

    def setUp(self):
        config = VideoQuotaConfig.load()
        config.free_retain_days = 90
        config.save()
        self.athlete = make_athlete()
        self.video = make_video(
            self.athlete,
            date=TODAY - timedelta(days=200),
            remote_key="videos/1/old.mp4",
        )

    def _run(self, **options):
        out, err = StringIO(), StringIO()
        call_command("purge_videos", stdout=out, stderr=err, **options)
        return out.getvalue()

    def test_it_reports_r2_status_even_with_nothing_to_clean(self):
        """這行就是 cron 里唐一驗得到金鑰的方法，所以要無條件印。"""
        self.video.delete()
        with fake_r2():
            out = self._run()
        self.assertIn("R2：已連上 bucket", out)
        self.assertIn("沒有超過保留期限", out)

    def test_it_refuses_to_delete_when_r2_is_unreachable(self):
        with fake_r2(ok=False):
            with self.assertRaises(CommandError):
                self._run(apply=True)
        self.assertEqual(TrainingVideo.objects.count(), 1)

    def test_a_row_survives_when_its_object_cannot_be_deleted(self):
        """行刪了、檔還在，那個檔就永遠沒人指得到。寧可下星期再試。"""
        with fake_r2(deletes=False):
            with self.assertRaises(CommandError):
                self._run(apply=True)
        self.assertEqual(TrainingVideo.objects.count(), 1)

    def test_a_normal_run_still_deletes(self):
        with fake_r2():
            out = self._run(apply=True)
        self.assertIn("已刪除 1 條", out)
        self.assertEqual(TrainingVideo.objects.count(), 0)


class _FakeR2:
    """只懂 list 跟 delete 的假 bucket。

    實打 R2 的話，這幾個測試就要金鑰、要網絡，而且會真的刪東西。
    我們要驗的是「哪些 key 被當成孤兒」這個判斷，不是 boto3 會不會動。
    """

    def __init__(self, objects):
        self.objects = list(objects)
        self.deleted = []

    def get_paginator(self, _name):
        return self

    def paginate(self, **_kwargs):
        return [{"Contents": self.objects}]

    def drop(self, key):
        """頓 storage.delete_object 的，所以要像它一樣回 True。"""
        self.deleted.append(key)
        return True


def _obj(key, hours_old=48, size=1024):
    return {
        "Key": key,
        "Size": size,
        "LastModified": timezone.now() - timedelta(hours=hours_old),
    }


class FindOrphansTests(VideoTestCase):
    """直傳是兩步的，所以 R2 上會累積沒人指得到的物件。

    purge_videos 從資料庫那一頭數起，永遠碰不到孤兒；這個指令補另一半。
    """

    def setUp(self):
        self.athlete = make_athlete()
        self.video = make_video(self.athlete, remote_key="videos/1/keep.mp4")

    def _run(self, objects, **options):
        fake = _FakeR2(objects)
        out = StringIO()
        with mock.patch.object(
            storage, "_client", return_value=(fake, {"bucket": "b"})
        ), mock.patch.object(storage, "delete_object", side_effect=fake.drop):
            call_command("find_orphans", stdout=out, **options)
        return fake, out.getvalue()

    def test_a_key_with_a_row_is_left_alone(self):
        _, out = self._run([_obj("videos/1/keep.mp4")])
        self.assertIn("沒有孤兒物件", out)

    def test_a_key_with_no_row_is_reported(self):
        _, out = self._run([_obj("videos/1/keep.mp4"), _obj("videos/1/lost.mp4")])
        self.assertIn("videos/1/lost.mp4", out)
        self.assertNotIn("videos/1/keep.mp4", out)

    def test_nothing_is_deleted_without_apply(self):
        fake, _ = self._run([_obj("videos/1/lost.mp4")])
        self.assertEqual(fake.deleted, [])

    def test_apply_deletes_only_the_orphan(self):
        fake, out = self._run(
            [_obj("videos/1/keep.mp4"), _obj("videos/1/lost.mp4")], apply=True
        )
        self.assertEqual(fake.deleted, ["videos/1/lost.mp4"])
        self.assertIn("已刪除 1 個", out)

    def test_a_fresh_upload_is_not_an_orphan_yet(self):
        """剛傳完檔、表單還未 submit 的，刪下去就是刪一個進行中的上傳。"""
        fake, out = self._run([_obj("videos/1/inflight.mp4", hours_old=1)], apply=True)
        self.assertEqual(fake.deleted, [])
        self.assertIn("沒有孤兒物件", out)

    def test_posters_are_not_orphans(self):
        """縮圖在 poster 欄不在 remote_key，只比對 remote_key 會把它們整批刪掉。"""
        self.video.poster.save("p.jpg", SimpleUploadedFile("p.jpg", b"x"), save=True)
        fake, _ = self._run([_obj(self.video.poster.name)], apply=True)
        self.assertEqual(fake.deleted, [])

    def test_it_refuses_to_run_without_r2(self):
        with mock.patch.object(storage, "_client", return_value=None):
            with self.assertRaises(CommandError):
                call_command("find_orphans")


class UpgradeRequestTests(VideoTestCase):
    """升級只是排隊——不收錢、不即時開通，教練聯絡完才在後台按開通。"""

    def setUp(self):
        self.athlete = make_athlete()
        self.admin = make_admin()

    def test_request_creates_a_pending_row(self):
        req = vsvc.request_upgrade(self.athlete.user, self.athlete, note="想做整季分析")
        self.assertTrue(req.is_open)
        self.assertEqual(req.requested_by, self.athlete.user)
        # 排隊不等於開通：方案要維持原樣，直到有人收到錢
        self.athlete.refresh_from_db()
        self.assertEqual(self.athlete.video_plan, VideoPlan.FREE)

    def test_second_request_is_refused_while_one_is_open(self):
        vsvc.request_upgrade(self.athlete.user, self.athlete)
        with self.assertRaises(vsvc.VideoError):
            vsvc.request_upgrade(self.athlete.user, self.athlete)
        self.assertEqual(PlanUpgradeRequest.objects.count(), 1)

    def test_pro_members_cannot_request(self):
        self.athlete.video_plan = VideoPlan.PRO
        self.athlete.save()
        with self.assertRaises(vsvc.VideoError):
            vsvc.request_upgrade(self.athlete.user, self.athlete)

    def test_approve_flips_the_plan_and_closes_the_request(self):
        req = vsvc.request_upgrade(self.athlete.user, self.athlete)
        req.approve(self.admin)
        self.athlete.refresh_from_db()
        self.assertEqual(self.athlete.video_plan, VideoPlan.PRO)
        self.assertEqual(req.status, UpgradeStatus.APPROVED)
        self.assertEqual(req.handled_by, self.admin)
        self.assertIsNotNone(req.handled_at)

    def test_can_request_again_after_being_declined(self):
        """婉拒之後隊伍要清空，否則那個人永遠再申請不了。"""
        req = vsvc.request_upgrade(self.athlete.user, self.athlete)
        req.decline(self.admin)
        self.assertIsNone(vsvc.open_upgrade_request(self.athlete))
        vsvc.request_upgrade(self.athlete.user, self.athlete)
        self.assertEqual(PlanUpgradeRequest.objects.count(), 2)

    def test_approved_athlete_gets_the_bigger_quota(self):
        vsvc.request_upgrade(self.athlete.user, self.athlete).approve(self.admin)
        self.athlete.refresh_from_db()
        quota = vsvc.quota_for(self.athlete)
        self.assertTrue(quota.is_pro)
        self.assertEqual(quota.max_videos, VideoQuotaConfig.load().pro_max_videos)

    def test_contact_falls_back_to_the_account_phone(self):
        self.athlete.user.phone = "6531 2212"
        self.athlete.user.save()
        req = vsvc.request_upgrade(self.athlete.user, self.athlete)
        self.assertEqual(req.contact_display, "6531 2212")


class UpgradeViewTests(VideoTestCase):
    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        config = VideoQuotaConfig.load()
        config.free_max_videos = 1
        config.save()

    def test_athlete_can_file_a_request_from_the_library(self):
        self.client.force_login(self.athlete.user)
        self.client.post(
            reverse("web:video_list") + f"?athlete={self.athlete.id}",
            {"action": "upgrade", "contact": "9876 5432", "note": "起跑分析"},
        )
        req = PlanUpgradeRequest.objects.get()
        self.assertEqual(req.athlete, self.athlete)
        self.assertEqual(req.contact, "9876 5432")

    def test_coach_can_file_on_an_athletes_behalf(self):
        """「這個仔要做整季分析」——教練代按也算，申請人記的是教練。"""
        self.client.force_login(self.coach.user)
        self.client.post(
            reverse("web:video_list") + f"?athlete={self.athlete.id}",
            {"action": "upgrade"},
        )
        self.assertEqual(PlanUpgradeRequest.objects.get().requested_by, self.coach.user)

    #: 找的是送出鈕，不是標題——「申請升級進階會員」這幾個字在額度滿的
    #: 紅色提示裡也出現，拿它來比對會比對到提示、測不出表單在不在。
    FORM_MARK = "送出申請"

    def test_the_upgrade_form_only_shows_once_the_quota_is_tight(self):
        self.client.force_login(self.athlete.user)
        url = reverse("web:video_list")
        self.assertNotContains(
            self.client.get(url, {"athlete": self.athlete.id}), self.FORM_MARK
        )
        make_video(self.athlete, size_bytes=1024)
        self.assertContains(
            self.client.get(url, {"athlete": self.athlete.id}), self.FORM_MARK
        )

    def test_a_pending_request_replaces_the_form(self):
        make_video(self.athlete, size_bytes=1024)
        vsvc.request_upgrade(self.athlete.user, self.athlete)
        self.client.force_login(self.athlete.user)
        res = self.client.get(reverse("web:video_list"), {"athlete": self.athlete.id})
        self.assertContains(res, "升級申請已經收到")
        self.assertNotContains(res, self.FORM_MARK)

    def test_pro_members_never_see_the_form(self):
        self.athlete.video_plan = VideoPlan.PRO
        self.athlete.save()
        make_video(self.athlete, size_bytes=1024)
        self.client.force_login(self.athlete.user)
        res = self.client.get(reverse("web:video_list"), {"athlete": self.athlete.id})
        self.assertNotContains(res, self.FORM_MARK)

    def test_duplicate_request_is_reported_not_saved(self):
        self.client.force_login(self.athlete.user)
        url = reverse("web:video_list") + f"?athlete={self.athlete.id}"
        self.client.post(url, {"action": "upgrade"})
        self.client.post(url, {"action": "upgrade"})
        self.assertEqual(PlanUpgradeRequest.objects.count(), 1)

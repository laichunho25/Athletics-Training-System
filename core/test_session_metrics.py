"""課表頁登的數據＝數據分析那一份，而且課別限制了能登哪個範疇。"""
from datetime import date
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from analytics import services as an
from analytics.models import (
    MetricCategory,
    MetricDomain,
    MetricItem,
    MetricRecord,
    TrackMethod,
    TrainingStatus,
    ensure_builtin_items,
)
from core.models import SessionType
from planning.models import Competition
from training.models import ActivityCategory, ActivityDefinition
from core.test_factories import make_athlete, make_session

TODAY = date(2026, 6, 1)


class SessionMetricTests(TestCase):
    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a1")
        self.client.force_login(self.athlete.user)

    def url(self, session):
        return reverse("web:session_detail", args=[session.id])

    def test_strength_session_writes_the_same_records_as_analytics(self):
        s = make_session(self.athlete, TODAY, session_type=SessionType.STRENGTH)
        r = self.client.post(self.url(s), {
            "action": "add_metric",
            "domain": MetricDomain.STRENGTH,
            "item_name": "槓鈴深蹲",
            "date": TODAY.isoformat(),
            "value": ["100", "105"],
            "reps": ["5", "3"],
            "completed": ["1", "0"],
        })
        self.assertEqual(r.status_code, 302)

        item = MetricItem.objects.get(domain=MetricDomain.STRENGTH, name="槓鈴深蹲")
        recs = list(MetricRecord.objects.filter(item=item).order_by("set_no"))
        self.assertEqual(len(recs), 2)
        self.assertEqual([x.session_id for x in recs], [s.id, s.id])
        # 單位是 kg 的項目，重量自動沿用數值，噸位才算得出來
        self.assertEqual([float(x.weight_kg) for x in recs], [100.0, 105.0])

        # 同一份資料在數據分析頁看得到，不用再輸入一次
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}&item={item.id}"
        )
        self.assertContains(page, "槓鈴深蹲")

    def test_track_session_cannot_log_strength(self):
        s = make_session(self.athlete, TODAY, session_type=SessionType.TRACK)
        item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH).first()
        self.client.post(self.url(s), {
            "action": "add_metric", "domain": MetricDomain.STRENGTH,
            "item_id": item.id, "date": TODAY.isoformat(), "value": "80",
        })
        self.assertFalse(MetricRecord.objects.filter(session=s).exists())

    def test_rehab_session_offers_both_domains(self):
        s = make_session(self.athlete, TODAY, session_type=SessionType.REHAB)
        body = self.client.get(self.url(s)).content.decode()
        self.assertIn("田徑練習訓練紀錄", body)
        self.assertIn("重量訓練紀錄", body)

    def test_delete_metric_from_the_session_page(self):
        s = make_session(self.athlete, TODAY, session_type=SessionType.STRENGTH)
        item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH).first()
        self.client.post(self.url(s), {
            "action": "add_metric", "domain": MetricDomain.STRENGTH,
            "item_id": item.id, "date": TODAY.isoformat(), "value": "80",
        })
        rec = MetricRecord.objects.get(session=s)
        self.client.post(self.url(s), {"action": "delete_metric", "record_id": rec.id})
        self.assertFalse(MetricRecord.objects.filter(id=rec.id).exists())


class ComparisonTests(TestCase):
    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a2")
        self.client.force_login(self.athlete.user)
        self.item = MetricItem.objects.filter(domain=MetricDomain.STRENGTH).first()
        for on_date, value in [(date(2025, 6, 1), 90), (date(2026, 6, 1), 110)]:
            MetricRecord.objects.create(
                athlete=self.athlete, item=self.item, date=on_date,
                value=value, weight_kg=value, reps=3,
            )

    def test_year_comparison_lists_both_years(self):
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}&item={self.item.id}&compare=year"
        )
        body = page.content.decode()
        self.assertIn("2025 年", body)
        self.assertIn("2026 年", body)

    def test_phase_comparison_falls_back_to_the_unphased_bucket(self):
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}&item={self.item.id}&compare=phase"
        )
        self.assertContains(page, "未分期")

    def test_top_movements_card_is_shown(self):
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}&domain={MetricDomain.STRENGTH}"
        )
        self.assertContains(page, "最常做的動作")


class ItemListTests(TestCase):
    """項目清單：只列挑出來／登過的，並依動作分類分組。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a3")
        self.client.force_login(self.athlete.user)
        self.squat = MetricItem.objects.get(
            domain=MetricDomain.STRENGTH, name="背蹲舉 1RM"
        )
        MetricRecord.objects.create(
            athlete=self.athlete, item=self.squat, date=TODAY, value=120, weight_kg=120
        )

    def page(self):
        return self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}"
        ).content.decode()

    def test_only_items_with_records_are_listed(self):
        body = self.page()
        self.assertIn("背蹲舉 1RM", body)
        self.assertNotIn("反向跳 CMJ", body)  # 沒挑也沒登過就不佔版面

    def test_items_are_grouped_by_category(self):
        body = self.page()
        # 分類標題（不是「新增項目」表單裡那個下拉的選項）
        self.assertIn('class="itemcat">下身動作（Lower Body Movement）', body)
        self.assertNotIn('class="itemcat">核心肌群', body)  # 這一組還沒有項目

    def test_picking_from_the_activity_library_adds_an_item(self):
        definition = ActivityDefinition.objects.create(
            name="啞鈴肩推", name_en="Shoulder Press (Dumbbell)",
            category=ActivityCategory.UPPER,
        )
        r = self.client.post(reverse("web:analytics"), {
            "action": "add_item",
            "domain": MetricDomain.STRENGTH,
            "definition": definition.id,
        })
        item = MetricItem.objects.get(domain=MetricDomain.STRENGTH, name="啞鈴肩推")
        self.assertEqual(item.category, MetricCategory.UPPER)
        self.assertIn(f"item={item.id}", r["Location"])
        self.assertIn("啞鈴肩推", self.page())  # 挑出來的就算還沒紀錄也留在清單


class ActivityLibraryTests(TestCase):
    """課表加活動：可挑活動庫、可一次加多個，並自動開好數據項目。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a4")
        self.client.force_login(self.athlete.user)
        self.session = make_session(
            self.athlete, TODAY, session_type=SessionType.STRENGTH
        )
        self.squat = ActivityDefinition.objects.create(
            name="槓鈴深蹲", name_en="Squat (Barbell)",
            category=ActivityCategory.LOWER, default_sets="4 組", default_reps="5 次",
        )
        self.plank = ActivityDefinition.objects.create(
            name="平板支撐", name_en="Plank", category=ActivityCategory.CORE,
        )

    def url(self):
        return reverse("web:session_detail", args=[self.session.id])

    def test_picking_one_activity_brings_its_defaults_and_opens_a_metric_item(self):
        self.client.post(self.url(), {
            "action": "add_activity", "block": "MAIN",
            "definition": self.squat.id, "name": "槓鈴深蹲",
            "sets": "4 組", "reps": "5 次",
        })
        activity = self.session.activities.get()
        self.assertEqual(activity.definition_id, self.squat.id)
        self.assertEqual(activity.sets, "4 組")
        item = MetricItem.objects.get(domain=MetricDomain.STRENGTH, name="槓鈴深蹲")
        self.assertEqual(item.category, MetricCategory.LOWER)

    def test_many_activities_in_one_go(self):
        self.client.post(self.url(), {
            "action": "add_activity", "block": "MAIN",
            "name": "槓鈴深蹲\n平板支撐\n自己想的動作",
        })
        names = list(self.session.activities.order_by("order").values_list("name", flat=True))
        self.assertEqual(names, ["槓鈴深蹲", "平板支撐", "自己想的動作"])
        # 名字對得上活動庫的，預設值一起帶進來
        self.assertEqual(self.session.activities.get(name="槓鈴深蹲").reps, "5 次")
        self.assertEqual(
            set(MetricItem.objects.filter(
                domain=MetricDomain.STRENGTH, name__in=names
            ).values_list("name", flat=True)),
            set(names),
        )

    def test_track_session_activities_open_track_items(self):
        session = make_session(self.athlete, TODAY, session_type=SessionType.TRACK)
        self.client.post(reverse("web:session_detail", args=[session.id]), {
            "action": "add_activity", "block": "MAIN", "name": "150m 計時",
        })
        self.assertTrue(
            MetricItem.objects.filter(
                domain=MetricDomain.TRACK, name="150m 計時"
            ).exists()
        )


class CompetitionAnalysisTests(TestCase):
    """比賽數據：以每一場比賽為單位看成績，不擺動作清單那一套。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a5")
        self.client.force_login(self.athlete.user)
        self.item = MetricItem.objects.filter(
            domain=MetricDomain.COMPETITION
        ).first()
        self.spring = Competition.objects.create(
            name="春季分齡賽", date=date(2026, 3, 1)
        )
        self.summer = Competition.objects.create(
            name="夏季錦標賽", date=date(2026, 6, 1)
        )
        for meet, value in [(self.spring, 12.4), (self.summer, 12.1)]:
            MetricRecord.objects.create(
                athlete=self.athlete, item=self.item, date=meet.date,
                value=value, competition=meet,
            )

    def page(self):
        return self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.COMPETITION}"
        ).content.decode()

    def test_meets_are_listed_newest_first_with_their_marks(self):
        body = self.page()
        self.assertIn("比賽分析", body)
        self.assertIn("夏季錦標賽", body)
        self.assertIn("春季分齡賽", body)
        self.assertLess(body.index("夏季錦標賽"), body.index("春季分齡賽"))

    def test_competition_tab_drops_the_movement_cards(self):
        body = self.page()
        self.assertNotIn("最常做的動作", body)
        self.assertNotIn("從訓練活動庫挑一個動作", body)

    def test_record_can_be_pinned_to_a_meet(self):
        autumn = Competition.objects.create(name="秋季賽", date=date(2026, 9, 1))
        self.client.post(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.COMPETITION}&item={self.item.id}",
            {
                "action": "add_record",
                "item_id": self.item.id,
                "date": autumn.date.isoformat(),
                "value": ["11.9"],
                "competition": autumn.id,
            },
        )
        rec = MetricRecord.objects.get(competition=autumn)
        self.assertEqual(float(rec.value), 11.9)


class DisplayNameTests(TestCase):
    """項目名稱一律中英文對照——清單、紀錄、課表都一樣。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a6")
        self.client.force_login(self.athlete.user)
        self.item = MetricItem.objects.get(
            domain=MetricDomain.STRENGTH, name="平板支撐"
        )
        MetricRecord.objects.create(
            athlete=self.athlete, item=self.item, date=TODAY, value=60
        )

    def test_builtin_items_carry_an_english_name(self):
        self.assertEqual(self.item.name_en, "Plank")
        self.assertEqual(self.item.display_name, "平板支撐（Plank）")

    def test_analytics_list_shows_both_languages(self):
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}&item={self.item.id}"
        )
        self.assertContains(page, "平板支撐（Plank）")

    def test_session_page_shows_both_languages(self):
        s = make_session(self.athlete, TODAY, session_type=SessionType.STRENGTH)
        self.client.post(reverse("web:session_detail", args=[s.id]), {
            "action": "add_metric",
            "domain": MetricDomain.STRENGTH,
            "item_id": self.item.id,
            "date": TODAY.isoformat(),
            "value": ["55"],
            "completed": ["1"],
        })
        page = self.client.get(reverse("web:session_detail", args=[s.id]))
        self.assertContains(page, "平板支撐（Plank）")


class ItemPickerTests(TestCase):
    """加入項目的入口要一眼看得到，而且打名字也能加。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a7")
        self.client.force_login(self.athlete.user)
        self.definition = ActivityDefinition.objects.create(
            name="槓鈴深蹲", name_en="Back Squat", category=ActivityCategory.LOWER
        )

    def url(self):
        return (
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}"
        )

    def test_library_picker_is_on_the_page_with_its_options(self):
        body = self.client.get(self.url()).content.decode()
        # 挑項目的卡片放在左欄最下面：先看紀錄，要加項目才捲到底
        self.assertIn("加入要追蹤的項目", body)
        self.assertGreater(body.index("加入要追蹤的項目"), body.index("最常做的動作"))
        self.assertIn("槓鈴深蹲（Back Squat）", body)

    def test_typing_a_library_name_brings_its_english_name_and_category(self):
        self.client.post(self.url(), {
            "action": "add_item",
            "domain": MetricDomain.STRENGTH,
            "name": "槓鈴深蹲",
        })
        item = MetricItem.objects.get(
            domain=MetricDomain.STRENGTH, name="槓鈴深蹲"
        )
        self.assertEqual(item.name_en, "Back Squat")
        self.assertEqual(item.category, MetricCategory.LOWER)

    def test_session_activity_row_shows_the_english_name(self):
        s = make_session(self.athlete, TODAY, session_type=SessionType.STRENGTH)
        self.client.post(reverse("web:session_detail", args=[s.id]), {
            "action": "add_activity",
            "block": "MAIN",
            "name": "槓鈴深蹲",
        })
        page = self.client.get(reverse("web:session_detail", args=[s.id]))
        self.assertContains(page, "Back Squat")


class DeleteItemTests(TestCase):
    """自己刪項目；底下有紀錄要先提示。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a8")
        self.client.force_login(self.athlete.user)
        self.custom = MetricItem.objects.create(
            domain=MetricDomain.STRENGTH, name="單腳跳距離", name_en="Single Leg Hop",
            unit="m", higher_is_better=True, category=MetricCategory.PLYO,
        )

    def url(self):
        return (
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}"
        )

    def post_delete(self, item, **extra):
        return self.client.post(self.url(), {
            "action": "delete_item",
            "domain": MetricDomain.STRENGTH,
            "item_id": item.id,
            **extra,
        }, follow=True)

    def test_item_without_records_is_deleted(self):
        self.post_delete(self.custom, confirm="1")
        self.assertFalse(MetricItem.objects.filter(pk=self.custom.pk).exists())

    def test_item_with_records_needs_a_confirmation(self):
        MetricRecord.objects.create(
            athlete=self.athlete, item=self.custom, date=TODAY, value=3.1
        )
        page = self.post_delete(self.custom)  # 沒帶 confirm
        self.assertTrue(MetricItem.objects.filter(pk=self.custom.pk).exists())
        self.assertContains(page, "還有 1 筆紀錄")

        page = self.post_delete(self.custom, confirm="1")
        self.assertFalse(MetricItem.objects.filter(pk=self.custom.pk).exists())
        self.assertEqual(MetricRecord.objects.filter(item_id=self.custom.pk).count(), 0)

    def test_deleting_a_builtin_item_clears_only_my_records(self):
        builtin = MetricItem.objects.get(
            domain=MetricDomain.STRENGTH, name="背蹲舉 1RM"
        )
        MetricRecord.objects.create(
            athlete=self.athlete, item=builtin, date=TODAY, value=120, weight_kg=120
        )
        page = self.post_delete(builtin, confirm="1")
        self.assertTrue(MetricItem.objects.filter(pk=builtin.pk).exists())
        self.assertEqual(MetricRecord.objects.filter(item=builtin).count(), 0)
        self.assertContains(page, "系統內建項目")

    def test_the_delete_button_warns_about_the_records(self):
        MetricRecord.objects.create(
            athlete=self.athlete, item=self.custom, date=TODAY, value=3.1
        )
        page = self.client.get(f"{self.url()}&item={self.custom.id}")
        self.assertContains(page, "會一併刪掉 1 筆紀錄")


class LibrarySeedTests(TestCase):
    """活動庫是空的話自動載入預設清單——不然下拉只有點不到的分類標題。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a9")
        self.client.force_login(self.athlete.user)

    def test_empty_library_is_seeded_on_the_analytics_page(self):
        ActivityDefinition.objects.all().delete()
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}"
        )
        self.assertTrue(ActivityDefinition.objects.exists())
        self.assertGreater(len(page.context["activity_groups"]), 0)

    def test_no_empty_optgroup_is_rendered(self):
        ActivityDefinition.objects.all().delete()
        ActivityDefinition.objects.create(
            name="槓鈴深蹲", name_en="Back Squat", category=ActivityCategory.LOWER
        )
        body = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.STRENGTH}"
        ).content.decode()
        labels = [g["label"] for g in
                  self.client.get(
                      f"{reverse('web:analytics')}?athlete={self.athlete.id}"
                      f"&domain={MetricDomain.STRENGTH}"
                  ).context["activity_groups"]]
        self.assertEqual(len(labels), 1)
        self.assertEqual(body.count("<optgroup"), 1)


class TargetAndCompletedValueTests(TestCase):
    """數值（目標／完成）不是必填，只有沒挑項目才登不進去；休息時間可以用分鐘填。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a9")
        self.client.force_login(self.athlete.user)
        self.session = make_session(self.athlete, TODAY, session_type=SessionType.TRACK)

    def post(self, **extra):
        data = {
            "action": "add_metric",
            "domain": MetricDomain.TRACK,
            "item_name": "150m 課表",
            "date": TODAY.isoformat(),
        }
        data.update(extra)
        return self.client.post(
            reverse("web:session_detail", args=[self.session.id]), data
        )

    def test_item_alone_is_enough(self):
        self.assertEqual(self.post().status_code, 302)
        rec = MetricRecord.objects.get()
        self.assertIsNone(rec.value)
        self.assertIsNone(rec.target_value)
        self.assertEqual(rec.session_id, self.session.id)

    def test_no_item_no_record(self):
        self.post(item_name="", value="19.5")
        self.assertFalse(MetricRecord.objects.exists())

    def test_target_and_completed_are_kept_apart(self):
        self.post(target_value="20", value="19.5")
        rec = MetricRecord.objects.get()
        self.assertEqual((float(rec.target_value), float(rec.value)), (20.0, 19.5))

    def test_rest_can_be_given_in_minutes(self):
        self.post(value="19.5", rest_sec="3", rest_unit="min")
        self.assertEqual(MetricRecord.objects.get().rest_sec, 180)

    def test_values_can_be_fixed_in_analytics(self):
        self.post(target_value="20", value="19.5")
        rec = MetricRecord.objects.get()
        self.client.post(reverse("web:analytics"), {
            "action": "edit_record",
            "domain": MetricDomain.TRACK,
            "item_id": rec.item_id,
            f"target_value_{rec.id}": "19",
            f"value_{rec.id}": "18.8",
        })
        rec.refresh_from_db()
        self.assertEqual((float(rec.target_value), float(rec.value)), (19.0, 18.8))

    def test_analytics_page_renders_records_without_a_value(self):
        self.post(target_value="20")
        item = MetricItem.objects.get(name="150m 課表")
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.TRACK}&item={item.id}"
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "還沒填完成數值")

    def test_the_whole_record_can_be_edited_in_analytics(self):
        """紀錄明細每一格都改得動——重量、次數、休息、完成、情境都算。"""
        self.post(value="19.5", reps="2", rest_sec="60")
        rec = MetricRecord.objects.get()
        self.client.post(reverse("web:analytics"), {
            "action": "edit_record",
            "domain": MetricDomain.TRACK,
            "item_id": rec.item_id,
            f"target_value_{rec.id}": "19",
            f"value_{rec.id}": "18.8",
            f"weight_{rec.id}": "5",
            f"reps_{rec.id}": "3",
            f"rest_sec_{rec.id}": "4",
            "rest_unit": "min",
            f"completed_{rec.id}": "0",
            f"status_{rec.id}": TrainingStatus.INJURY,
            f"context_{rec.id}": "順風 1.2",
        })
        rec.refresh_from_db()
        self.assertEqual(float(rec.weight_kg), 5.0)
        self.assertEqual(rec.reps, 3)
        self.assertEqual(rec.rest_sec, 240)
        self.assertFalse(rec.completed)
        self.assertEqual(rec.status, TrainingStatus.INJURY)
        self.assertEqual(rec.context, "順風 1.2")


class SessionRecordEditTests(TestCase):
    """課表頁登完之後改得動——改的就是數據分析那一份。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a10")
        self.client.force_login(self.athlete.user)
        self.session = make_session(self.athlete, TODAY, session_type=SessionType.TRACK)
        self.client.post(reverse("web:session_detail", args=[self.session.id]), {
            "action": "add_metric",
            "domain": MetricDomain.TRACK,
            "item_name": "150m 課表",
            "date": TODAY.isoformat(),
            "value": ["19.5", "19.9"],
            "reps": ["1", "1"],
        })
        self.records = list(MetricRecord.objects.order_by("id"))
        self.assertEqual(len(self.records), 2)

    def post(self, data):
        return self.client.post(
            reverse("web:session_detail", args=[self.session.id]), data
        )

    def test_one_row_can_be_saved_on_its_own(self):
        first, second = self.records
        self.post({
            "action": "edit_metric",
            "rest_unit": "min",
            "only": first.id,
            f"value_{first.id}": "19.1",
            f"value_{second.id}": "18.0",
        })
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(float(first.value), 19.1)
        self.assertEqual(float(second.value), 19.9)   # only 沒點到的不動

    def test_all_rows_can_be_confirmed_at_once(self):
        first, second = self.records
        self.post({
            "action": "edit_metric",
            "rest_unit": "min",
            f"value_{first.id}": "19.1",
            f"value_{second.id}": "19.4",
            f"rest_sec_{first.id}": "3",
            f"status_{first.id}": TrainingStatus.RETURN,
            f"intensity_{second.id}": "95%",
        })
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((float(first.value), float(second.value)), (19.1, 19.4))
        self.assertEqual(first.rest_sec, 180)
        self.assertEqual(first.status, TrainingStatus.RETURN)
        self.assertEqual(second.intensity, "95%")

    def test_the_same_edit_shows_up_in_analytics(self):
        first = self.records[0]
        self.post({
            "action": "edit_metric",
            "rest_unit": "min",
            "only": first.id,
            f"value_{first.id}": "18.7",
            f"status_{first.id}": TrainingStatus.INJURY,
        })
        item = MetricItem.objects.get(name="150m 課表")
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.TRACK}&item={item.id}"
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "18.7")
        self.assertContains(page, "傷害治療期")

    def test_a_coach_cannot_edit_someone_elses_records(self):
        other = make_athlete("a11")
        self.client.force_login(other.user)
        first = self.records[0]
        self.post({
            "action": "edit_metric",
            "only": first.id,
            f"value_{first.id}": "1.0",
        })
        first.refresh_from_db()
        self.assertEqual(float(first.value), 19.5)


class TrackMethodItemTests(TestCase):
    """田徑練習：先挑方式、再填距離，加進要追蹤的項目清單。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a12")
        self.client.force_login(self.athlete.user)

    def add(self, **extra):
        data = {"action": "add_track_item", "domain": MetricDomain.TRACK}
        data.update(extra)
        return self.client.post(reverse("web:analytics"), data)

    def test_method_plus_distance_becomes_an_item(self):
        self.add(method=TrackMethod.REPEAT, distance_m="150")
        item = MetricItem.objects.get(name="150m 反覆跑")
        self.assertEqual(item.domain, MetricDomain.TRACK)
        self.assertEqual(item.track_method, TrackMethod.REPEAT)
        self.assertEqual(item.track_distance_m, 150)
        self.assertEqual(item.unit, "秒")
        self.assertFalse(item.higher_is_better)

    def test_same_distance_different_method_are_two_items(self):
        self.add(method=TrackMethod.REPEAT, distance_m="150")
        self.add(method=TrackMethod.TEMPO, distance_m="150")
        self.assertEqual(
            MetricItem.objects.filter(track_distance_m=150).count(), 2
        )

    def test_distance_is_optional(self):
        self.add(method=TrackMethod.START)
        self.assertTrue(MetricItem.objects.filter(name="起跑").exists())

    def test_a_method_is_required(self):
        self.add(distance_m="150")
        self.assertFalse(MetricItem.objects.filter(track_distance_m=150).exists())


class MultiItemAnalysisTests(TestCase):
    """相類似的項目可以勾起來一起分析。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a13")
        self.client.force_login(self.athlete.user)
        self.a = MetricItem.objects.create(
            domain=MetricDomain.TRACK, name="150m 反覆跑", unit="秒",
            higher_is_better=False, track_method=TrackMethod.REPEAT, track_distance_m=150,
        )
        self.b = MetricItem.objects.create(
            domain=MetricDomain.TRACK, name="150m 節奏跑", unit="秒",
            higher_is_better=False, track_method=TrackMethod.TEMPO, track_distance_m=150,
        )
        for item, value in ((self.a, "19.5"), (self.b, "21.2")):
            MetricRecord.objects.create(
                athlete=self.athlete, item=item, date=TODAY, value=value
            )

    def test_two_items_are_analysed_side_by_side(self):
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.TRACK}&items={self.a.id},{self.b.id}"
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "多項目一起分析")
        multi = page.context["multi"]
        self.assertEqual(len(multi["rows"]), 2)
        self.assertEqual(
            {row["item"].id for row in multi["rows"]}, {self.a.id, self.b.id}
        )

    def test_one_item_alone_is_not_a_comparison(self):
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.TRACK}&items={self.a.id}"
        )
        self.assertIsNone(page.context["multi"])

    def test_junk_in_the_items_parameter_is_ignored(self):
        """網址是使用者改得到的東西：亂七八糟的 items 不能讓整頁掛掉。"""
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.TRACK}&items=²,abc,,-3&items={self.a.id}"
            f"&items={self.b.id}"
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["picked_ids"], [self.a.id, self.b.id])

    def test_a_broken_analysis_does_not_take_the_page_down(self):
        """一起分析算不出來時，其餘欄位照常顯示，畫面上說一句就好。"""
        with mock.patch.object(
            an, "multi_item_analysis", side_effect=ValueError("boom")
        ):
            with self.assertLogs("core.views", level="ERROR"):
                page = self.client.get(
                    f"{reverse('web:analytics')}?athlete={self.athlete.id}"
                    f"&domain={MetricDomain.TRACK}&items={self.a.id},{self.b.id}"
                )
        self.assertEqual(page.status_code, 200)
        self.assertIsNone(page.context["multi"])
        self.assertEqual(page.context["multi_series"], "[]")
        self.assertContains(page, "一起分析時出了問題")


class StatusAwareAdviceTests(TestCase):
    """分析之前先看當天的狀態註記與其他考慮因素。"""

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a14")
        self.client.force_login(self.athlete.user)
        self.item = MetricItem.objects.create(
            domain=MetricDomain.TRACK, name="150m 反覆跑", unit="秒",
            higher_is_better=False,
        )

    def log(self, day, value, status=""):
        MetricRecord.objects.create(
            athlete=self.athlete, item=self.item,
            date=TODAY.replace(day=day), value=value, status=status,
        )

    def analysis(self):
        from analytics import services as an

        return an.metric_analysis(self.athlete, self.item)

    def test_injury_days_are_named_before_calling_it_a_decline(self):
        # 越跑越慢，但那段時間都在傷害治療期
        for i, value in enumerate(["19.5", "20.2", "21.0", "21.6"]):
            self.log(1 + i * 5, value, status=TrainingStatus.INJURY)
        result = self.analysis()
        self.assertIs(result["improving"], False)
        self.assertIn("傷害治療期", result["status_note"])
        self.assertIn("傷害治療期", result["advice"])
        self.assertNotIn("能力下降", result["advice"])

    def test_missing_status_is_pointed_out(self):
        for i, value in enumerate(["19.5", "20.2", "21.0"]):
            self.log(1 + i * 5, value)
        result = self.analysis()
        self.assertIn("沒有註記", result["status_note"])
        keys = {f["key"] for f in result["considerations"]}
        self.assertIn("status_missing", keys)
        # ACWR 與睡眠是「考慮因素」之一，不是唯一的解釋
        self.assertIn("load", keys)
        self.assertIn("sleep", keys)

    def test_statuses_are_broken_down_per_status(self):
        self.log(1, "19.5", status=TrainingStatus.PREP)
        self.log(6, "19.2", status=TrainingStatus.TAPER)
        self.log(11, "21.0", status=TrainingStatus.INJURY)
        rows = {row["value"]: row for row in self.analysis()["status_rows"]}
        self.assertEqual(set(rows), {"PREP", "TAPER", "INJURY"})
        self.assertEqual(rows["INJURY"]["days"], 1)

    def test_records_can_be_compared_by_status(self):
        self.log(1, "19.5", status=TrainingStatus.TAPER)
        self.log(6, "21.0", status=TrainingStatus.INJURY)
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.TRACK}&item={self.item.id}&compare=status"
        )
        groups = page.context["comparison"]["groups"]
        self.assertEqual({g["label"] for g in groups}, {"比賽調整期", "傷害治療期"})


class BulkSaveIsNotBlockedByTheBrowserTests(TestCase):
    """「儲存全部更改」按了要送得出去。

    休息時間換成分鐘會出現 1.67 這種值，配上 step="0.5" 就是不合法的欄位；
    那一列收在 <details> 裡沒展開時，瀏覽器沒辦法把游標移過去提示，
    整張表單就靜靜地送不出去——所以編輯欄一律 step="any"，表單也不做前端驗證。
    """

    def setUp(self):
        ensure_builtin_items()
        self.athlete = make_athlete("a15")
        self.client.force_login(self.athlete.user)
        self.item = MetricItem.objects.create(
            domain=MetricDomain.TRACK, name="150m 反覆跑", unit="秒",
            higher_is_better=False,
        )
        self.rec = MetricRecord.objects.create(
            athlete=self.athlete, item=self.item, date=TODAY,
            value="19.5", rest_sec=100,      # 100 秒 = 1.67 分
        )

    def test_analytics_edit_cells_accept_any_step(self):
        page = self.client.get(
            f"{reverse('web:analytics')}?athlete={self.athlete.id}"
            f"&domain={MetricDomain.TRACK}&item={self.item.id}"
        )
        html = page.content.decode()
        self.assertIn('id="recEdit" novalidate', html)
        self.assertIn(f'name="rest_sec_{self.rec.id}"', html)
        for name in ("value", "target_value", "rest_sec"):
            cell = html.split(f'name="{name}_{self.rec.id}"')[0]
            self.assertIn('step="any"', cell.rsplit("<input", 1)[1])

    def test_session_edit_cells_accept_any_step(self):
        session = make_session(self.athlete, TODAY, session_type=SessionType.TRACK)
        MetricRecord.objects.filter(pk=self.rec.pk).update(session=session)
        page = self.client.get(reverse("web:session_detail", args=[session.id]))
        html = page.content.decode()
        self.assertIn('id="metricEdit" novalidate', html)
        self.assertNotIn('step="0.5" form="metricEdit"', html)
        self.assertNotIn('step="0.01" form="metricEdit"', html)

    def test_an_odd_rest_value_still_saves(self):
        self.client.post(reverse("web:analytics"), {
            "action": "edit_record",
            "domain": MetricDomain.TRACK,
            "item_id": self.item.id,
            "rest_unit": "min",
            f"value_{self.rec.id}": "19.2",
            f"rest_sec_{self.rec.id}": "1.67",
        })
        self.rec.refresh_from_db()
        self.assertEqual(float(self.rec.value), 19.2)
        self.assertEqual(self.rec.rest_sec, 100)

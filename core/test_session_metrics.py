"""課表頁登的數據＝數據分析那一份，而且課別限制了能登哪個範疇。"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from analytics.models import (
    MetricCategory,
    MetricDomain,
    MetricItem,
    MetricRecord,
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
            "record_id": rec.id,
            "target_value": "19",
            "value": "18.8",
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
            "record_id": rec.id,
            "target_value": "19",
            "value": "18.8",
            "weight": "5",
            "reps": "3",
            "rest_sec": "4",
            "rest_unit": "min",
            "completed": "0",
            "context": "順風 1.2",
        })
        rec.refresh_from_db()
        self.assertEqual(float(rec.weight_kg), 5.0)
        self.assertEqual(rec.reps, 3)
        self.assertEqual(rec.rest_sec, 240)
        self.assertFalse(rec.completed)
        self.assertEqual(rec.context, "順風 1.2")

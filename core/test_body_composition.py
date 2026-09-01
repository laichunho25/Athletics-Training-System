"""狀態總覽頁的「基本指標與體組成」：解析檔案、手動輸入、歷史與圖表。"""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from accounts.body_import import parse_body_composition
from accounts.models import BodyMetricLog
from core.test_factories import make_admin, make_athlete, make_coach


class BodyImportParserTests(TestCase):
    """磅匯出的檔案要能還原成欄位。"""

    def test_reads_vertical_app_export(self):
        text = "\n".join(
            [
                "2026年06月07日,",
                "時間,09:37",
                "體重,69.20 kg",
                "體脂肪率,標準 - 16.30 %",
                "肌肉量,標準 54.90 kg",
                "BMI,標準 23.4",
                "內臟脂肪等級,標準 8.0",
                "推定骨量,標準 3.00 kg",
                "體水分率,57.7 %",
                "基礎代謝量,多 1608 kcal",
                "體內年齡,30 歲",
                "右腳肌肉量,標準 8.85 kg",
                "軀幹部位肌肉量,多 30.00 kg",
                "左上肢肌肉品質點數,高 100",
                "MBA判定,業餘",
            ]
        )
        records, unknown = parse_body_composition(text)

        self.assertEqual(len(records), 1)
        row = records[0]
        self.assertEqual(row["date"], date(2026, 6, 7))
        self.assertEqual(row["measured_at"], "09:37")
        self.assertEqual(row["weight_kg"], 69.20)
        self.assertEqual(row["body_fat_pct"], 16.30)
        self.assertEqual(row["muscle_mass_kg"], 54.90)
        self.assertEqual(row["bmi"], 23.4)
        self.assertEqual(row["visceral_fat_level"], 8.0)
        self.assertEqual(row["bone_mass_kg"], 3.00)
        self.assertEqual(row["body_water_pct"], 57.7)
        self.assertEqual(row["bmr_kcal"], 1608)
        self.assertEqual(row["metabolic_age"], 30)
        self.assertEqual(row["muscle_leg_r"], 8.85)
        self.assertEqual(row["muscle_trunk"], 30.00)
        self.assertEqual(row["mq_arm_l"], 100)
        self.assertEqual(row["mba_rating"], "業餘")
        self.assertEqual(unknown, [])

    def test_reads_table_export_with_many_rows(self):
        text = (
            "日期,體重 (kg),體脂肪率,肌肉量,心情\n"
            "2026/05/01,70.5,17.2,54.1,好\n"
            "2026/06/07,69.2,16.3,54.9,好\n"
        )
        records, unknown = parse_body_composition(text)

        self.assertEqual([r["date"] for r in records], [date(2026, 5, 1), date(2026, 6, 7)])
        self.assertEqual(records[1]["weight_kg"], 69.2)
        self.assertIn("心情", unknown)

    def test_reads_screenshot_text_with_label_and_value_on_separate_lines(self):
        """手機「實時文字」複製出來的樣子：項目名、評價字、數值各自一行。"""
        text = "\n".join(
            [
                "體組成",
                "2026年06月07日 (週日)",
                "RD-545AS",
                "時間",
                "09:37",
                "體重",
                "69.20 kg",
                "體脂肪率",
                "標準 -",
                "16.30 %",
                "肌肉量",
                "標準",
                "54.90 kg",
                "BMI",
                "標準",
                "23.4",
                "基礎代謝量",
                "多",
                "1608 kcal",
                "右腳肌肉量",
                "標準",
                "8.85 kg",
            ]
        )
        records, _ = parse_body_composition(text)

        self.assertEqual(len(records), 1)
        row = records[0]
        self.assertEqual(row["date"], date(2026, 6, 7))
        self.assertEqual(row["measured_at"], "09:37")
        self.assertEqual(row["weight_kg"], 69.20)
        self.assertEqual(row["body_fat_pct"], 16.30)
        self.assertEqual(row["muscle_mass_kg"], 54.90)
        self.assertEqual(row["bmi"], 23.4)
        self.assertEqual(row["bmr_kcal"], 1608)
        self.assertEqual(row["muscle_leg_r"], 8.85)

    def test_reads_ocr_text_with_label_and_value_on_one_line(self):
        """瀏覽器 OCR 出來的樣子：項目名與數值同一行，中間只有空白。"""
        text = "\n".join(
            [
                "體組成 2026年06月07日",
                "體重 69.20 kg",
                "體脂肪率 標準 - 16.30 %",
                "肌肉量 標準 54.90 kg",
                "BMI 23.4",
                "基礎代謝量 多 1608 kcal",
                "今日心情很好",
            ]
        )
        records, _ = parse_body_composition(text)

        self.assertEqual(len(records), 1)
        row = records[0]
        self.assertEqual(row["date"], date(2026, 6, 7))
        self.assertEqual(row["weight_kg"], 69.20)
        self.assertEqual(row["body_fat_pct"], 16.30)
        self.assertEqual(row["muscle_mass_kg"], 54.90)
        self.assertEqual(row["bmi"], 23.4)
        self.assertEqual(row["bmr_kcal"], 1608)

    def test_row_without_weight_is_dropped(self):
        records, _ = parse_body_composition("日期,體脂肪率\n2026/06/07,16.3\n")
        self.assertEqual(records, [])


class BodyMetricViewTests(TestCase):
    def setUp(self):
        self.coach = make_coach()
        self.athlete = make_athlete(coach=self.coach)
        self.url = reverse("web:athlete_body_metric", args=[self.athlete.id])
        self.dashboard = f"{reverse('web:dashboard')}?athlete={self.athlete.id}"

    def _login_coach(self):
        self.client.login(username=self.coach.user.username, password="test-pw-12345")

    def test_manual_entry_creates_then_updates_same_day(self):
        self._login_coach()
        payload = {
            "action": "save",
            "date": "2026-06-07",
            "weight_kg": "69.2",
            "body_fat_pct": "16.3",
            "muscle_mass_kg": "54.9",
            "bmr_kcal": "1608",
        }
        self.client.post(self.url, payload)
        log = BodyMetricLog.objects.get(athlete=self.athlete, date=date(2026, 6, 7))
        self.assertEqual(float(log.weight_kg), 69.2)
        self.assertEqual(log.bmr_kcal, 1608)
        self.assertEqual(log.source, BodyMetricLog.Source.MANUAL)

        # 同一天再存一次＝覆蓋，不會多一筆
        self.client.post(self.url, {**payload, "weight_kg": "68.4"})
        self.assertEqual(BodyMetricLog.objects.filter(athlete=self.athlete).count(), 1)
        log.refresh_from_db()
        self.assertEqual(float(log.weight_kg), 68.4)

    def test_weight_is_required(self):
        self._login_coach()
        self.client.post(self.url, {"action": "save", "date": "2026-06-07", "body_fat_pct": "16"})
        self.assertFalse(BodyMetricLog.objects.filter(athlete=self.athlete).exists())

    def test_file_import_updates_latest_body_state(self):
        self._login_coach()
        from django.core.files.uploadedfile import SimpleUploadedFile

        content = (
            "日期,體重,體脂肪率,肌肉量,體水分率\n"
            "2026/05/01,70.5,17.2,54.1,56.9\n"
            "2026/06/07,69.2,16.3,54.9,57.7\n"
        ).encode("utf-8")
        upload = SimpleUploadedFile("inbody.csv", content, content_type="text/csv")

        self.client.post(self.url, {"action": "import", "file": upload})

        logs = BodyMetricLog.objects.filter(athlete=self.athlete).order_by("date")
        self.assertEqual(logs.count(), 2)
        latest = self.athlete.latest_body_metric
        self.assertEqual(latest.date, date(2026, 6, 7))
        self.assertEqual(float(latest.weight_kg), 69.2)
        self.assertEqual(latest.source, BodyMetricLog.Source.IMPORT)
        self.assertEqual(latest.source_file, "inbody.csv")
        # 體重欄位一更新，總覽頁上的「目前體重」就跟著走
        self.assertEqual(float(self.athlete.current_weight_kg), 69.2)

    def test_paste_text_creates_record_on_chosen_date(self):
        self._login_coach()
        pasted = "體重\n69.20 kg\n體脂肪率\n標準\n16.30 %\n肌肉量\n54.90 kg"

        self.client.post(
            self.url, {"action": "paste", "date": "2026-06-07", "text": pasted}
        )

        log = BodyMetricLog.objects.get(athlete=self.athlete, date=date(2026, 6, 7))
        self.assertEqual(float(log.weight_kg), 69.2)
        self.assertEqual(float(log.body_fat_pct), 16.3)
        self.assertEqual(float(log.muscle_mass_kg), 54.9)
        self.assertEqual(log.source, BodyMetricLog.Source.IMPORT)

    def test_paste_without_date_uses_the_date_in_the_text(self):
        self._login_coach()
        pasted = "2026年06月07日 (週日)\n體重\n69.20 kg"

        self.client.post(self.url, {"action": "paste", "date": "", "text": pasted})

        self.assertTrue(
            BodyMetricLog.objects.filter(athlete=self.athlete, date=date(2026, 6, 7)).exists()
        )

    def test_paste_without_usable_numbers_is_rejected(self):
        self._login_coach()
        self.client.post(self.url, {"action": "paste", "text": "今日天氣不錯"})
        self.assertFalse(BodyMetricLog.objects.filter(athlete=self.athlete).exists())

    def test_other_coach_cannot_write(self):
        other = make_coach(username="coach2", squad="別隊")
        self.client.login(username=other.user.username, password="test-pw-12345")
        self.client.post(self.url, {"action": "save", "date": "2026-06-07", "weight_kg": "60"})
        self.assertFalse(BodyMetricLog.objects.filter(athlete=self.athlete).exists())

    def test_delete_removes_one_record(self):
        self._login_coach()
        log = BodyMetricLog.objects.create(
            athlete=self.athlete, date=date(2026, 6, 7), weight_kg=69.2
        )
        self.client.post(self.url, {"action": "delete", "log_id": log.id})
        self.assertFalse(BodyMetricLog.objects.filter(pk=log.id).exists())

    def test_dashboard_shows_general_info_history_and_chart(self):
        BodyMetricLog.objects.create(
            athlete=self.athlete, date=date(2026, 5, 1), weight_kg=70.5,
            body_fat_pct=17.2, muscle_mass_kg=54.1,
        )
        BodyMetricLog.objects.create(
            athlete=self.athlete, date=date(2026, 6, 7), weight_kg=69.2,
            body_fat_pct=16.3, muscle_mass_kg=54.9, body_water_pct=57.7,
            bmr_kcal=1608, metabolic_age=30, muscle_leg_r=8.85, fat_leg_r=21.5,
        )
        make_admin()
        self.client.login(username="admin1", password="test-pw-12345")

        html = self.client.get(self.dashboard).content.decode()

        self.assertIn("一般資料", html)             # 身高／體重／性別／出生年月日
        self.assertIn(str(self.athlete.birth_date), html)
        self.assertIn("體組成紀錄 (Record History)", html)
        self.assertIn("bodyChart", html)            # 時間與身體變化圖表
        self.assertIn("身體變化走勢", html)
        self.assertIn("右腳", html)                 # 部位數據表
        self.assertIn("-1.3", html)                 # 與上一次相比體重的變化

    def test_athlete_sees_own_body_section(self):
        self.client.login(username=self.athlete.user.username, password="test-pw-12345")
        html = self.client.get(reverse("web:dashboard")).content.decode()
        self.assertIn("基本指標與體組成", html)
        self.assertIn("匯入檔案", html)
        self.assertIn("貼上磅的文字", html)
        # 免費的瀏覽器端截圖辨識
        self.assertIn("辨識圖片文字", html)
        self.assertIn("body-ocr", html)

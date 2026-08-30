"""權限收斂測試——運動員只能看自己，教練只能看旗下，管理員全部。"""

from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from core.permissions import athlete_ids_visible_to, resolve_athlete
from core.test_factories import (
    TODAY,
    make_admin,
    make_athlete,
    make_coach,
    make_session,
)


class AthleteIdsVisibleToTests(TestCase):
    def setUp(self):
        self.coach_a = make_coach("coach_a", "A 隊")
        self.coach_b = make_coach("coach_b", "B 隊")
        self.a1 = make_athlete("a1", coach=self.coach_a)
        self.a2 = make_athlete("a2", coach=self.coach_a)
        self.b1 = make_athlete("b1", coach=self.coach_b)
        self.orphan = make_athlete("orphan", coach=None)
        self.admin = make_admin()

    def test_athlete_sees_only_self(self):
        self.assertEqual(set(athlete_ids_visible_to(self.a1.user)), {self.a1.id})

    def test_coach_sees_only_own_squad(self):
        visible = set(athlete_ids_visible_to(self.coach_a.user))
        self.assertEqual(visible, {self.a1.id, self.a2.id})
        self.assertNotIn(self.b1.id, visible)
        self.assertNotIn(self.orphan.id, visible)

    def test_admin_sees_everyone(self):
        visible = set(athlete_ids_visible_to(self.admin))
        self.assertEqual(
            visible, {self.a1.id, self.a2.id, self.b1.id, self.orphan.id}
        )

    def test_anonymous_sees_nobody(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(list(athlete_ids_visible_to(AnonymousUser())), [])

    def test_coach_without_athletes_sees_nobody(self):
        lonely = make_coach("coach_c", "C 隊")
        self.assertEqual(list(athlete_ids_visible_to(lonely.user)), [])


class ResolveAthleteTests(TestCase):
    def test_walks_fk_up_to_athlete_profile(self):
        athlete = make_athlete()
        session = make_session(athlete, TODAY)
        self.assertEqual(resolve_athlete(session), athlete)

    def test_athlete_profile_resolves_to_itself_via_session(self):
        athlete = make_athlete("a9")
        self.assertIsNone(resolve_athlete(object()))


class ViewAccessControlTests(TestCase):
    """HTML 前端的權限：擋匿名、擋跨運動員。"""

    def setUp(self):
        self.coach = make_coach()
        self.mine = make_athlete("mine", coach=self.coach)
        self.other_coach = make_coach("coach_x", "X 隊")
        self.theirs = make_athlete("theirs", coach=self.other_coach)
        self.pw = "test-pw-12345"

    def test_anonymous_is_redirected_to_login(self):
        for name in ("web:dashboard", "web:calendar", "web:analytics",
                     "web:nutrition", "web:injuries", "web:home"):
            with self.subTest(view=name):
                r = self.client.get(reverse(name))
                self.assertEqual(r.status_code, 302)
                self.assertIn("/accounts/login/", r["Location"])

    def test_landing_page_is_public(self):
        r = self.client.get(reverse("web:landing"))
        self.assertEqual(r.status_code, 200)

    def test_athlete_cannot_view_another_athlete_by_query_param(self):
        self.client.login(username="mine", password=self.pw)
        r = self.client.get(reverse("web:dashboard"), {"athlete": self.theirs.id})
        self.assertEqual(r.status_code, 200)
        # 參數被忽略，落回自己的資料，而不是換成別人的
        self.assertEqual(r.context["athlete"].id, self.mine.id)

    def test_coach_cannot_view_athlete_outside_squad(self):
        self.client.login(username="coach1", password=self.pw)
        r = self.client.get(reverse("web:dashboard"), {"athlete": self.theirs.id})
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.context["athlete"].id, self.theirs.id)

    def test_session_detail_404_for_other_athletes_session(self):
        session = make_session(self.theirs, TODAY)
        self.client.login(username="mine", password=self.pw)
        r = self.client.get(reverse("web:session_detail", args=[session.id]))
        self.assertEqual(r.status_code, 404)

    def test_session_detail_ok_for_own_session(self):
        session = make_session(self.mine, TODAY)
        self.client.login(username="mine", password=self.pw)
        r = self.client.get(reverse("web:session_detail", args=[session.id]))
        self.assertEqual(r.status_code, 200)

    def test_coach_can_open_own_squad_athlete_session(self):
        session = make_session(self.mine, TODAY)
        self.client.login(username="coach1", password=self.pw)
        r = self.client.get(reverse("web:session_detail", args=[session.id]))
        self.assertEqual(r.status_code, 200)

    def test_athlete_cannot_post_check_in_to_other_athletes_session(self):
        session = make_session(self.theirs, TODAY, rpe=None, minutes=None)
        self.client.login(username="mine", password=self.pw)
        r = self.client.post(
            reverse("web:session_detail", args=[session.id]),
            {"action": "complete", "session_rpe": 9, "actual_duration_min": 120},
        )
        self.assertEqual(r.status_code, 404)
        session.refresh_from_db()
        self.assertIsNone(session.session_rpe)

    def test_home_dispatches_by_role(self):
        self.client.login(username="mine", password=self.pw)
        self.assertRedirects(
            self.client.get(reverse("web:home")), reverse("web:dashboard")
        )
        self.client.logout()
        self.client.login(username="coach1", password=self.pw)
        self.assertRedirects(
            self.client.get(reverse("web:home")), reverse("web:coach_dashboard")
        )


class LoginPageTests(TestCase):
    def test_demo_credentials_hidden_when_debug_off(self):
        with self.settings(DEBUG=False):
            body = self.client.get("/accounts/login/").content.decode()
        for secret in ("atm12345", "admin12345", "coach_chan"):
            self.assertNotIn(secret, body)

    def test_demo_credentials_shown_in_debug(self):
        with self.settings(DEBUG=True):
            body = self.client.get("/accounts/login/").content.decode()
        self.assertIn("atm12345", body)


class SprintGlossaryTests(TestCase):
    """短跑術語表：資料完整性，以及 MD 檔與原始資料同步。"""

    def test_groups_and_terms_are_well_formed(self):
        from core.glossary import GLOSSARY

        self.assertGreaterEqual(len(GLOSSARY), 5)
        for group in GLOSSARY:
            for key in ("id", "en", "zh", "intro", "terms"):
                self.assertTrue(group.get(key), f"{group.get('id')} 缺少 {key}")
            self.assertTrue(group["terms"], f"{group['id']} 沒有詞條")
            for entry in group["terms"]:
                self.assertEqual(len(entry), 3, f"{entry} 應為 (英文, 中文, 解釋)")
                en, zh, note = entry
                self.assertTrue(en.strip() and zh.strip())
                self.assertGreaterEqual(len(note), 15, f"{en} 的解釋太短")

    def test_group_ids_and_english_terms_are_unique(self):
        from core.glossary import GLOSSARY, all_terms

        ids = [g["id"] for g in GLOSSARY]
        self.assertEqual(len(ids), len(set(ids)))
        names = [t[0] for t in all_terms()]
        self.assertEqual(len(names), len(set(names)), "有重複的英文詞條")

    def test_as_groups_matches_source(self):
        from core.glossary import GLOSSARY, all_terms, as_groups

        groups = as_groups()
        self.assertEqual(len(groups), len(GLOSSARY))
        self.assertEqual(
            sum(len(g["terms"]) for g in groups), len(all_terms())
        )
        first = groups[0]["terms"][0]
        self.assertEqual(
            (first["en"], first["zh"], first["note"]), GLOSSARY[0]["terms"][0]
        )

    def test_markdown_file_is_in_sync(self):
        """docs/sprint-glossary.md 由 export_glossary 產生，不可手改後忘了重跑。"""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("export_glossary", "--check", stdout=out)
        self.assertIn("最新", out.getvalue())

    def test_export_writes_every_term(self):
        from django.conf import settings

        from core.glossary import all_terms
        from core.management.commands.export_glossary import build_markdown

        md = build_markdown()
        for en, zh, _note in all_terms():
            self.assertIn(en, md)
            self.assertIn(zh, md)
        self.assertTrue(
            (Path(settings.BASE_DIR) / "docs" / "sprint-glossary.md").exists()
        )


class LandingContentTests(TestCase):
    """首頁：跑道動畫掛得上、術語表有渲染出來、罐頭課表內容已移除。"""

    def setUp(self):
        self.html = self.client.get(reverse("web:landing")).content.decode()

    def test_track_hero_canvas_and_script_present(self):
        self.assertIn('id="track-hero"', self.html)
        self.assertIn("js/track-hero", self.html)
        for slot in (
            "time", "dist", "speed", "phase", "go", "demo",
            "splits", "call", "tapfill", "tapnum",
        ):
            self.assertIn(f'data-hero="{slot}"', self.html)

    def test_hundred_metre_challenge_is_explained(self):
        self.assertIn("接受挑戰", self.html)
        self.assertIn("0 / 200 下", self.html)
        self.assertIn("On your marks", self.html)
        self.assertIn("搶跑", self.html)

    def test_glossary_is_filterable_not_a_wall_of_text(self):
        from core.glossary import GLOSSARY, all_terms

        self.assertIn("js/glossary", self.html)
        for slot in ("chips", "grid", "q", "count", "empty"):
            self.assertIn(f'data-gloss="{slot}"', self.html)
        # 每一類一個篩選鈕，外加「全部」
        self.assertEqual(self.html.count('class="chip"'), len(GLOSSARY) + 1)
        for group in GLOSSARY:
            self.assertIn(f'data-cat="{group["id"]}"', self.html)
        # 每個詞條都帶著分類與搜尋用的文字
        self.assertEqual(self.html.count('class="term"'), len(all_terms()))
        self.assertEqual(self.html.count("data-text="), len(all_terms()))

    def test_track_red_and_white_palette(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "landing.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("--track:#c0392b", css)
        self.assertIn("--line:#ffffff", css)
        self.assertNotIn("#8a5a24", css)  # 舊的銅色已全部換掉

    def test_glossary_rendered_from_context(self):
        from django.utils.html import escape

        from core.glossary import GLOSSARY, all_terms

        for group in GLOSSARY:
            self.assertIn(escape(group["zh"]), self.html)
            self.assertIn(escape(group["en"]), self.html)
        for en, zh, _note in all_terms():
            self.assertIn(escape(en), self.html)
            self.assertIn(escape(zh), self.html)

    def test_canned_prescription_content_removed(self):
        for gone in (
            "決定名次的很少是單一堂課練得多重",
            "六個主流方向",
            "十六週備賽",
            "一週長什麼樣",
            "深蹲 5×3 @ 88%",
        ):
            self.assertNotIn(gone, self.html)

    def test_intro_frames_atm_as_record_and_analysis(self):
        self.assertIn("課表不是罐頭", self.html)
        self.assertIn("不派發現成的訓練課表", self.html)

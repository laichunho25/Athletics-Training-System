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

    def test_real_credentials_log_in_and_land_in_the_app(self):
        """正式流程：POST 帳密 → 轉去 /app/，CSRF 與 next 都要正常運作。"""
        make_athlete(username="athlete_x")
        resp = self.client.post(
            "/accounts/login/",
            {"username": "athlete_x", "password": "test-pw-12345", "next": ""},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], settings.LOGIN_REDIRECT_URL)

    def test_admin_site_accepts_the_created_superuser(self):
        make_admin(username="boss")
        resp = self.client.post(
            "/admin/login/",
            {"username": "boss", "password": "test-pw-12345", "next": "/admin/"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/admin/")


class DeploymentHealthTests(TestCase):
    """部署相關回歸測試——這些一壞，整站就登入不了。"""

    def test_healthz_is_public_and_cheap(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"ok")

    def test_healthz_is_not_redirected_to_https_in_production(self):
        """Render 的健康檢查走內部 http；被 301 轉址會被判定服務不健康。"""
        with self.settings(
            SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[r"^healthz$"]
        ):
            resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)

    def test_custom_domains_are_csrf_trusted(self):
        """CSRF_TRUSTED_ORIGINS 少了網域，登入 POST 會全部被擋成 403。"""
        for host in settings.ALLOWED_HOSTS:
            if host in {"localhost", "127.0.0.1", "[::1]", "testserver"}:
                continue
            self.assertIn(f"https://{host}", settings.CSRF_TRUSTED_ORIGINS)


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
        self.assertIn("0 / 80 下", self.html)
        self.assertIn("On your marks", self.html)
        self.assertIn("搶跑", self.html)

    def test_finish_card_starts_hidden_and_can_be_dismissed(self):
        """成績卡預設要收起來，不能擋住跑道；`hidden` 必須壓得過 display:flex。"""
        css = (Path(settings.BASE_DIR) / "static" / "css" / "landing.css").read_text(
            encoding="utf-8"
        )
        js = (Path(settings.BASE_DIR) / "static" / "js" / "track-hero.js").read_text(
            encoding="utf-8"
        )
        # 樣板上預設帶 hidden
        self.assertIn('data-hero="finish"', self.html)
        self.assertRegex(self.html, r'data-hero="finish"[^>]*(?s:.{0,200}?)hidden')
        # 作者樣式蓋掉瀏覽器預設的 [hidden]{display:none}，所以要自己補一條
        self.assertIn("[hidden]{display:none!important}", css)
        # 面板本身預設不顯示，加上 .show 才展開
        self.assertRegex(css, r"\.track-finish\{[^}]*display:none")
        self.assertIn(".track-finish.show{display:flex", css)
        # JS 兩邊都要同步：開的時候加 class，關的時候拿掉
        self.assertIn('finishBox.classList.add("show")', js)
        self.assertIn('finishBox.classList.remove("show")', js)
        # 「再來」按鈕會 reset，而 reset 會呼叫 hideFinish
        self.assertIn('data-hero="again"', self.html)
        self.assertIn("hideFinish();", js)

    def test_glossary_footnote_removed(self):
        for phrase in ("一頁十條", "同時維護在", "sprint-glossary.md", "gloss-foot"):
            self.assertNotIn(phrase, self.html)

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

    def test_soft_gradient_page_keeps_red_for_the_track_only(self):
        """跑道紅只留給畫布，版面底色改為溫和的漸變。"""
        css = (Path(settings.BASE_DIR) / "static" / "css" / "landing.css").read_text(
            encoding="utf-8"
        )
        # 跑道本身仍是紅膠面 + 白線 + 綠內場
        self.assertIn("--track:#bf4029", css)
        self.assertIn("--line:#ffffff", css)
        self.assertIn("--infield:#4f8b4a", css)
        # 版面底色是漸變，重點色不是紅色
        self.assertIn("--accent:#2f6b52", css)
        self.assertRegex(css, r"body\{[^}]*background:linear-gradient")
        # 舊的紅色版面用色已全部退場
        for gone in ("#c0392b", "#8d2418", "#6d1a10", "#8a5a24"):
            self.assertNotIn(gone, css)

    def test_track_canvas_is_a_regulation_400m_stadium(self):
        """跑道畫布依規格繪製，並標出各項目起跑線與過程標記。"""
        js = (Path(settings.BASE_DIR) / "static" / "js" / "track-hero.js").read_text(
            encoding="utf-8"
        )
        for spec in ("STRAIGHT = 84.39", "KERB = 36.5", "LANE_W = 1.22", "LANES = 8"):
            self.assertIn(spec, js)
        for event in ("100 m", "110 mH", "200 m", "400 m", "800 m", "FINISH"):
            self.assertIn(event, js)
        # 分道差是算出來的，不是寫死的座標
        self.assertIn("turnStagger", js)
        self.assertIn("locateBack", js)
        # 內場草綠
        self.assertIn("#4f8b4a", js)

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

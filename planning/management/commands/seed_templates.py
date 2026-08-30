"""
建立短跑專項的課表模板（SessionTemplate）。

SessionTemplate.coach 是必填外鍵，所以不能用 loaddata 灌 fixture——
沒有教練帳號時 pk 對不上。這支指令改成「掛到現有教練身上」，
以 (coach, name) 為鍵做 upsert，可以重複執行。

用法：
    python manage.py seed_templates                 # 掛給所有教練
    python manage.py seed_templates --coach coach_chan
    python manage.py seed_templates --skip-if-empty # 沒有教練時安靜跳過（給 build.sh 用）
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import CoachProfile
from core.models import SessionType
from planning.models import SessionTemplate


def strength(code, sets, reps, pct=None, tempo="", rest=180, rir=None, note=""):
    """把「一個動作 × N 組」展開成 clone_to_session 看得懂的逐組項目。"""
    rows = []
    for n in range(1, sets + 1):
        row = {
            "exercise_code": code,
            "set_number": n,
            "reps": reps,
            "rest_sec": rest,
        }
        if pct is not None:
            row["target_1rm_pct"] = pct
        if tempo:
            row["tempo"] = tempo
        if rir is not None:
            row["rir"] = rir
        if note:
            row["note"] = note
        rows.append(row)
    return rows


def flat(*groups):
    return [row for group in groups for row in group]


TEMPLATES = [
    {
        "name": "加速期 — 蹲踞起跑 20/30/40m",
        "session_type": SessionType.TRACK,
        "planned_duration_min": 90,
        "description": (
            "起跑與前段加速。重點在第一步的推蹬角度與逐步抬起的身體角度，"
            "每趟都要完全恢復（趟間 4–5 分鐘），品質掉了就收。"
        ),
        "payload": {
            "track_sets": [
                {
                    "description": "起跑架反應起跑 4 × 20m",
                    "distance_m": 20,
                    "reps": 4,
                    "sets": 1,
                    "rest_between_reps_sec": 240,
                    "intensity_pct": 100.0,
                    "technical_focus": "推蹬角度約 45°、前三步不抬頭",
                    "surface": "TRACK",
                    "spikes_used": True,
                },
                {
                    "description": "蹲踞起跑 3 × 30m",
                    "distance_m": 30,
                    "reps": 3,
                    "sets": 1,
                    "rest_between_reps_sec": 300,
                    "intensity_pct": 100.0,
                    "technical_focus": "步幅逐步加大，身體角度線性抬起",
                    "surface": "TRACK",
                    "spikes_used": True,
                },
                {
                    "description": "蹲踞起跑 2 × 40m",
                    "distance_m": 40,
                    "reps": 2,
                    "sets": 1,
                    "rest_between_reps_sec": 360,
                    "intensity_pct": 100.0,
                    "technical_focus": "40m 前不進入直立跑姿",
                    "surface": "TRACK",
                    "spikes_used": True,
                },
            ],
            "strength_sets": strength("MED_BALL_SLAM", 3, 5, rest=120, note="賽前爆發啟動"),
        },
    },
    {
        "name": "最大速度 — 飛行跑 20/30m",
        "session_type": SessionType.TRACK,
        "planned_duration_min": 90,
        "description": (
            "95–100% 的飛行段速度。助跑 30m 進入計時區，重點是接地時間與髖的還原，"
            "總計時距離控制在 150m 以內，趟間休息 6–8 分鐘。"
        ),
        "payload": {
            "track_sets": [
                {
                    "description": "助跑 30m + 飛行 20m × 3",
                    "distance_m": 20,
                    "reps": 3,
                    "sets": 1,
                    "rest_between_reps_sec": 420,
                    "intensity_pct": 97.0,
                    "technical_focus": "接地短促、腳掌落在重心正下方",
                    "surface": "TRACK",
                    "spikes_used": True,
                },
                {
                    "description": "助跑 30m + 飛行 30m × 3",
                    "distance_m": 30,
                    "reps": 3,
                    "sets": 1,
                    "rest_between_reps_sec": 480,
                    "intensity_pct": 100.0,
                    "technical_focus": "維持高髖、不主動下踩",
                    "surface": "TRACK",
                    "spikes_used": True,
                },
            ],
            "strength_sets": flat(
                strength("POGO", 3, 10, rest=120, note="彈性剛度，接觸地面越短越好"),
                strength("BOUNDING", 3, 8, rest=180, note="單邊 8 步"),
            ),
        },
    },
    {
        "name": "速度耐力 — 150m × 4",
        "session_type": SessionType.TRACK,
        "planned_duration_min": 100,
        "description": (
            "85–95% 強度的速度耐力，練的是後段掉速。趟間 8–10 分鐘完全恢復，"
            "若第 3 趟比第 1 趟慢超過 5%，當天就停在第 3 趟。"
        ),
        "payload": {
            "track_sets": [
                {
                    "description": "150m × 4（趟間 10 分鐘）",
                    "distance_m": 150,
                    "reps": 4,
                    "sets": 1,
                    "rest_between_reps_sec": 600,
                    "intensity_pct": 92.0,
                    "technical_focus": "80m 後刻意放鬆肩頸，維持步頻",
                    "surface": "TRACK",
                    "spikes_used": True,
                }
            ],
            "strength_sets": [],
        },
    },
    {
        "name": "特殊耐力 — 300/250/200 遞減",
        "session_type": SessionType.TRACK,
        "planned_duration_min": 100,
        "description": (
            "賽季前的耐乳酸課，距離遞減、強度遞增。這是一週裡最重的一堂，"
            "前後各留 48 小時，課後 sRPE 通常會落在 800–1000 AU。"
        ),
        "payload": {
            "track_sets": [
                {
                    "description": "300m × 1",
                    "distance_m": 300,
                    "reps": 1,
                    "sets": 1,
                    "rest_between_reps_sec": 900,
                    "intensity_pct": 88.0,
                    "technical_focus": "前 200m 節奏穩定，不搶速度",
                    "surface": "TRACK",
                    "spikes_used": True,
                },
                {
                    "description": "250m × 1",
                    "distance_m": 250,
                    "reps": 1,
                    "sets": 1,
                    "rest_between_reps_sec": 900,
                    "intensity_pct": 91.0,
                    "technical_focus": "彎道出來後維持步幅",
                    "surface": "TRACK",
                    "spikes_used": True,
                },
                {
                    "description": "200m × 1",
                    "distance_m": 200,
                    "reps": 1,
                    "sets": 1,
                    "rest_between_reps_sec": 0,
                    "intensity_pct": 95.0,
                    "technical_focus": "最後一趟全力，記錄掉速幅度",
                    "surface": "TRACK",
                    "spikes_used": True,
                },
            ],
            "strength_sets": [],
        },
    },
    {
        "name": "節奏跑 — 有氧基礎 100m × 10",
        "session_type": SessionType.TRACK,
        "planned_duration_min": 60,
        "description": (
            "一般準備期的低強度量。70–75% 的節奏跑，走回起點當休息，"
            "目的是恢復與有氧底子，不是練速度——跑太快就失去意義。"
        ),
        "payload": {
            "track_sets": [
                {
                    "description": "100m × 10（走回 100m 當休息）",
                    "distance_m": 100,
                    "reps": 10,
                    "sets": 1,
                    "rest_between_reps_sec": 90,
                    "intensity_pct": 72.0,
                    "technical_focus": "肩頸放鬆、動作幅度完整",
                    "surface": "GRASS",
                    "spikes_used": False,
                }
            ],
            "strength_sets": [],
        },
    },
    {
        "name": "最大力量 — 下肢 85–95% 1RM",
        "session_type": SessionType.STRENGTH,
        "planned_duration_min": 90,
        "description": (
            "一般準備期的下肢重量日。低次數高強度、組間充分休息，"
            "目標是神經徵召而不是疲勞累積，RIR 保留 2 下。"
        ),
        "payload": {
            "track_sets": [],
            "strength_sets": flat(
                strength("BACK_SQUAT", 4, 3, pct=88.0, tempo="3-1-X-0", rest=240, rir=2),
                strength("TRAP_BAR_DL", 3, 3, pct=85.0, rest=240, rir=2),
                strength("BSS", 3, 6, rest=150, note="單邊 6 下"),
                strength("NORDIC", 3, 5, tempo="4-0-1-0", rest=120, note="離心為主，撐不住再用手"),
                strength("PALLOF", 3, 10, rest=60, note="單邊 10 下"),
            ),
        },
    },
    {
        "name": "爆發力 — 奧林匹克舉 + 增強式",
        "session_type": SessionType.STRENGTH,
        "planned_duration_min": 80,
        "description": (
            "速度導向的重量日。槓速掉超過 10% 就停止該動作，"
            "增強式接在爆發動作後面，總落地次數控制在 60 次以內。"
        ),
        "payload": {
            "track_sets": [],
            "strength_sets": flat(
                strength("POWER_CLEAN", 5, 2, pct=75.0, rest=180, note="槓速 ≥ 1.2 m/s"),
                strength("PUSH_JERK", 3, 3, pct=70.0, rest=150),
                strength("BOX_JUMP", 4, 4, rest=120, note="落地無聲、站穩再下一下"),
                strength("BROAD_JUMP", 3, 4, rest=150, note="記錄距離作為爆發力指標"),
                strength("HIP_THRUST", 3, 6, pct=70.0, rest=150),
            ),
        },
    },
    {
        "name": "上肢與軀幹穩定",
        "session_type": SessionType.STRENGTH,
        "planned_duration_min": 60,
        "description": (
            "輔助日。短跑的上肢負責擺臂節奏與軀幹剛度，練的是控制不是圍度，"
            "可以排在專項課的同一天下午。"
        ),
        "payload": {
            "track_sets": [],
            "strength_sets": flat(
                strength("BENCH_PRESS", 4, 6, pct=75.0, rest=150, rir=2),
                strength("PULL_UP", 4, 6, rest=150, note="不足次數用彈力帶輔助"),
                strength("OHP", 3, 8, pct=65.0, rest=120),
                strength("FACE_PULL", 3, 15, rest=60, note="肩後側健康"),
                strength("SIDE_PLANK", 3, 30, rest=45, note="單邊 30 秒"),
                strength("DEAD_BUG", 3, 10, rest=45),
            ),
        },
    },
    {
        "name": "技術日 — 起跑架與加速力學",
        "session_type": SessionType.TECHNIQUE,
        "planned_duration_min": 60,
        "description": (
            "低量技術課。以錄影回放為主，每一趟都要看得到修正點，"
            "強度控制在 90% 以下，不追求成績。"
        ),
        "payload": {
            "track_sets": [
                {
                    "description": "牆壁推蹬 3 × 10 步（單邊）",
                    "distance_m": 10,
                    "reps": 3,
                    "sets": 1,
                    "rest_between_reps_sec": 90,
                    "intensity_pct": 60.0,
                    "technical_focus": "髖前推、腳掌不拖地",
                    "surface": "TRACK",
                    "spikes_used": False,
                },
                {
                    "description": "起跑架出發 6 × 10m（錄影）",
                    "distance_m": 10,
                    "reps": 6,
                    "sets": 1,
                    "rest_between_reps_sec": 150,
                    "intensity_pct": 88.0,
                    "technical_focus": "前腳踏板壓力、第一步落點",
                    "surface": "TRACK",
                    "spikes_used": True,
                },
                {
                    "description": "推雪橇加速 4 × 20m",
                    "distance_m": 20,
                    "reps": 4,
                    "sets": 1,
                    "rest_between_reps_sec": 180,
                    "intensity_pct": 85.0,
                    "technical_focus": "阻力以掉速 10% 以內為準",
                    "surface": "TRACK",
                    "spikes_used": False,
                },
            ],
            "strength_sets": [],
        },
    },
    {
        "name": "恢復日 — 低衝擊循環",
        "session_type": SessionType.RECOVERY,
        "planned_duration_min": 45,
        "description": (
            "重課隔天的主動恢復。心率控制在 130 以下，全程零衝擊，"
            "痠痛或疼痛超過 5 分時，這也是傷患期的預設替代課。"
        ),
        "payload": {
            "track_sets": [],
            "strength_sets": flat(
                strength("ELLIPTICAL", 1, 20, rest=0, note="20 分鐘、心率 < 130"),
                strength("GLUTE_BRIDGE", 2, 15, rest=60),
                strength("FOOT_DOMING", 2, 15, rest=45),
                strength("BALANCE_BOARD", 2, 45, rest=45, note="單邊 45 秒"),
            ),
        },
    },
    {
        "name": "賽前激活 — 比賽前一日",
        "session_type": SessionType.TECHNIQUE,
        "planned_duration_min": 40,
        "description": (
            "比賽前一天的神經喚醒。量極低、強度接近比賽，"
            "跑完應該覺得「還想再跑」，而不是累。"
        ),
        "payload": {
            "track_sets": [
                {
                    "description": "加速跑 3 × 30m（漸進到 95%）",
                    "distance_m": 30,
                    "reps": 3,
                    "sets": 1,
                    "rest_between_reps_sec": 240,
                    "intensity_pct": 95.0,
                    "technical_focus": "找節奏，不看碼錶",
                    "surface": "TRACK",
                    "spikes_used": True,
                },
                {
                    "description": "起跑架出發 2 × 20m",
                    "distance_m": 20,
                    "reps": 2,
                    "sets": 1,
                    "rest_between_reps_sec": 300,
                    "intensity_pct": 95.0,
                    "technical_focus": "確認起跑架設定與反應",
                    "surface": "TRACK",
                    "spikes_used": True,
                },
            ],
            "strength_sets": strength("CMJ", 2, 3, rest=120, note="記錄高度，比平時低 5% 以上代表未恢復"),
        },
    },
]


class Command(BaseCommand):
    help = "建立／更新短跑專項的課表模板（以教練 + 模板名稱為鍵，可重複執行）"

    def add_arguments(self, parser):
        parser.add_argument("--coach", help="只掛給這個教練的使用者帳號")
        parser.add_argument(
            "--skip-if-empty",
            action="store_true",
            help="系統裡沒有教練時安靜跳過（給 build.sh 用，避免部署失敗）",
        )

    def handle(self, *args, **options):
        coaches = CoachProfile.objects.all()
        if options["coach"]:
            coaches = coaches.filter(user__username=options["coach"])
            if not coaches.exists():
                raise CommandError(f"找不到教練帳號：{options['coach']}")

        if not coaches.exists():
            if options["skip_if_empty"]:
                return
            raise CommandError("系統裡還沒有教練，先建立教練帳號再執行。")

        created = updated = 0
        for coach in coaches:
            for spec in TEMPLATES:
                _, is_new = SessionTemplate.objects.update_or_create(
                    coach=coach,
                    name=spec["name"],
                    defaults={
                        "session_type": spec["session_type"],
                        "planned_duration_min": spec["planned_duration_min"],
                        "description": spec["description"],
                        "payload": spec["payload"],
                    },
                )
                if is_new:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"課表模板完成：新增 {created} 筆、更新 {updated} 筆"
                f"（{coaches.count()} 位教練 × {len(TEMPLATES)} 個模板）"
            )
        )

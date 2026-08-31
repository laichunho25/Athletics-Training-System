"""建立訓練活動名稱庫的起始清單。

跑過一次之後，排課表時就有東西可以挑，不用第一次用的人自己從零打。
重覆執行不會蓋掉別人改過的預設值（只補沒有的）。

    python manage.py seed_activities
"""

from django.core.management.base import BaseCommand

from training.models import ActivityDefinition, BlockType

W, M, S, R = (
    BlockType.WARMUP,
    BlockType.MAIN,
    BlockType.SUPPLEMENT,
    BlockType.RECOVERY,
)

# (名稱, 區塊, 組數, 次數, 距離, 重量, 強度, 休息時間, 訓練要點)
ACTIVITIES = [
    # ---- 熱身 ----
    ("Single Leg Hip Bridge", W, "3 組", "左/右腳 15 次", "", "body weight", "", "30s",
     "骨盆保持水平，臀部發力，不要用腰代償"),
    ("A-Skip", W, "3 組", "", "30 米", "body weight", "", "walk back",
     "膝蓋上提到大腿與地面平行，腳掌前腳掌著地"),
    ("B-Skip", W, "3 組", "", "30 米", "body weight", "", "walk back",
     "上提後主動下扒，落點在身體正下方"),
    ("High Knees", W, "2 組", "", "20 米", "body weight", "", "walk back", "頻率優先，軀幹不後仰"),
    ("動態伸展組合", W, "1 組", "每個動作 8 次", "", "body weight", "", "不休",
     "髖、膝、踝、肩依序打開"),
    ("Leg Swing 前後擺腿", W, "2 組", "左/右腳 12 次", "", "body weight", "", "30s", "扶穩，幅度漸進加大"),
    ("Glute Bridge", W, "3 組", "15 次", "", "body weight", "", "30s", "頂點停 1 秒夾臀"),
    ("Ankling", W, "3 組", "", "20 米", "body weight", "", "walk back", "腳踝彈性，接觸地面時間短"),

    # ---- 正課 ----
    ("100m 反複跑", M, "2 組", "3 次", "100 米", "", "80%-90%", "每次：5 分鐘 / 每組：15 分鐘",
     "起跑加速段保持前傾，最高速段放鬆"),
    ("60m 加速跑", M, "3 組", "4 次", "60 米", "", "90%-95%", "每次：3 分鐘 / 每組：8 分鐘",
     "前 20 米推蹬，逐步抬起軀幹"),
    ("30m 起跑", M, "2 組", "5 次", "30 米", "", "95%-100%", "每次：3 分鐘 / 每組：10 分鐘",
     "起跑器角度固定，第一步不要拉太遠"),
    ("150m 節奏跑", M, "2 組", "3 次", "150 米", "", "75%-85%", "每次：4 分鐘 / 每組：10 分鐘",
     "維持步幅，最後 30 米不掉速"),
    ("200m 反複跑", M, "2 組", "3 次", "200 米", "", "85%-90%", "每次：6 分鐘 / 每組：12 分鐘",
     "彎道放鬆，直道加速"),
    ("400m 間歇", M, "1 組", "4 次", "400 米", "", "80%-85%", "每次：4 分鐘", "配速平均，前後 200 米差距 <2 秒"),
    ("背蹲舉 Back Squat", M, "4 組", "3 次", "", "依 1RM 換算", "85% 1RM", "3 分鐘", "下蹲到大腿平行，背部中立"),
    ("硬舉 Deadlift", M, "4 組", "3 次", "", "依 1RM 換算", "85% 1RM", "3 分鐘", "槓貼小腿，臀腿同時發力"),
    ("抓舉 Snatch", M, "5 組", "2 次", "", "依 1RM 換算", "75% 1RM", "3 分鐘", "速度優先，重量次要"),
    ("臥推 Bench Press", M, "4 組", "5 次", "", "依 1RM 換算", "80% 1RM", "2 分鐘", "肩胛收緊，槓下到胸線"),
    ("跨欄架跳 Hurdle Jump", M, "4 組", "5 次", "", "body weight", "最大努力", "2 分鐘", "落地即彈，接觸時間越短越好"),

    # ---- 補充練習 ----
    ("保加利亞分腿蹲", S, "3 組", "左/右腳 8 次", "", "20kg 啞鈴", "", "90s", "重心壓在前腳，膝蓋不內夾"),
    ("北歐腿彎舉 Nordic Curl", S, "3 組", "6 次", "", "body weight", "", "90s", "離心放慢到 4 秒"),
    ("羅馬尼亞硬舉 RDL", S, "3 組", "8 次", "", "60kg", "70% 1RM", "2 分鐘", "感覺膕繩肌被拉開再回來"),
    ("提踵 Calf Raise", S, "3 組", "15 次", "", "body weight", "", "60s", "頂點停 1 秒"),
    ("Copenhagen Plank", S, "3 組", "左/右邊 30 秒", "", "body weight", "", "45s", "內收肌撐住，骨盆不掉"),
    ("Dead Bug 死蟲", S, "3 組", "左/右邊 10 次", "", "body weight", "", "45s", "腰貼地，呼吸不中斷"),
    ("側平板 Side Plank", S, "3 組", "左/右邊 40 秒", "", "body weight", "", "45s", "身體成一直線"),
    ("藥球側拋", S, "3 組", "左/右邊 8 次", "", "4kg 藥球", "最大努力", "60s", "轉髖帶動，不是純手臂"),
    ("阻力帶側走", S, "3 組", "左/右邊 15 步", "", "彈力帶", "", "45s", "膝蓋不內扣"),

    # ---- 恢復練習 ----
    ("慢跑收操", R, "1 組", "", "800 米", "body weight", "50%", "不休", "呼吸回到平穩為止"),
    ("靜態伸展組合", R, "1 組", "每個動作 30 秒", "", "body weight", "", "不休", "拉到緊但不痛的位置"),
    ("泡沫軸放鬆", R, "1 組", "每個部位 60 秒", "", "泡沫軸", "", "不休", "痛點停留深呼吸 3 次"),
    ("冰浴", R, "1 組", "10 分鐘", "", "", "10-12°C", "不休", "高強度課後 30 分鐘內"),
    ("呼吸放鬆 4-7-8", R, "1 組", "8 個循環", "", "", "", "不休", "吸 4 秒、停 7 秒、吐 8 秒"),
    ("步行放鬆", R, "1 組", "10 分鐘", "", "body weight", "", "不休", "心率降到 100 以下"),
]


class Command(BaseCommand):
    help = "建立訓練活動名稱庫的起始清單（可重覆執行）"

    def handle(self, *args, **options):
        created = 0
        for (
            name, block, sets, reps, distance, weight, intensity, rest, key_points
        ) in ACTIVITIES:
            _obj, was_created = ActivityDefinition.objects.get_or_create(
                name=name,
                defaults={
                    "default_block": block,
                    "default_sets": sets,
                    "default_reps": reps,
                    "default_distance": distance,
                    "default_weight": weight,
                    "default_intensity": intensity,
                    "default_rest": rest,
                    "default_key_points": key_points,
                    "is_builtin": True,
                },
            )
            created += int(was_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"活動清單：新增 {created} 項，"
                f"目前共 {ActivityDefinition.objects.count()} 項。"
            )
        )

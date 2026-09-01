"""建立訓練活動名稱庫的起始清單。

跑過一次之後，排課表時就有東西可以挑，不用第一次用的人自己從零打。
重覆執行不會蓋掉別人改過的預設值（只補沒有的）；系統內建的那幾項會
順手把分類與英文名補上，因為健身房的器材與課表大多寫英文。

    python manage.py seed_activities
"""

from django.core.management.base import BaseCommand

from training.models import ActivityCategory, ActivityDefinition, BlockType

W, M, S, R = (
    BlockType.WARMUP,
    BlockType.MAIN,
    BlockType.SUPPLEMENT,
    BlockType.RECOVERY,
)

C_WARM = ActivityCategory.WARMUP
C_TRACK = ActivityCategory.TRACK
C_UP = ActivityCategory.UPPER
C_LOW = ActivityCategory.LOWER
C_CORE = ActivityCategory.CORE
C_PLYO = ActivityCategory.PLYO
C_ACC = ActivityCategory.ACCESSORY
C_REC = ActivityCategory.RECOVERY

# (中文名, 英文名, 分類, 預設區塊, 組數, 次數, 距離, 重量, 強度, 休息, 訓練要點)
ACTIVITIES = [
    # ------------------------------------------------------------ 熱身
    ("有氧熱身", "Aerobics", C_WARM, W, "1 組", "", "800-1200 米", "body weight",
     "心率 120-140", "不休", "慢跑到微微出汗，呼吸還講得出話"),
    ("伸展（動態）", "Stretching", C_WARM, W, "1 組", "每個動作 8-10 次", "", "body weight",
     "", "不休", "熱身用動態、收操用靜態；動態不要停在末端"),
    ("跳繩", "Jump Rope", C_WARM, W, "3 組", "60 秒", "", "body weight", "",
     "45s", "前腳掌著地、腳踝彈性，膝蓋不要塌"),
    ("Single Leg Hip Bridge", "Single Leg Hip Bridge", C_WARM, W, "3 組",
     "左/右腳 15 次", "", "body weight", "", "30s", "骨盆保持水平，臀部發力，不要用腰代償"),
    ("A-Skip", "A-Skip", C_WARM, W, "3 組", "", "30 米", "body weight", "", "walk back",
     "膝蓋上提到大腿與地面平行，腳掌前腳掌著地"),
    ("B-Skip", "B-Skip", C_WARM, W, "3 組", "", "30 米", "body weight", "", "walk back",
     "上提後主動下扒，落點在身體正下方"),
    ("High Knees", "High Knees", C_WARM, W, "2 組", "", "20 米", "body weight", "",
     "walk back", "頻率優先，軀幹不後仰"),
    ("動態伸展組合", "Dynamic Stretching Circuit", C_WARM, W, "1 組", "每個動作 8 次", "",
     "body weight", "", "不休", "髖、膝、踝、肩依序打開"),
    ("Leg Swing 前後擺腿", "Leg Swing", C_WARM, W, "2 組", "左/右腳 12 次", "",
     "body weight", "", "30s", "扶穩，幅度漸進加大"),
    ("Glute Bridge", "Glute Bridge", C_WARM, W, "3 組", "15 次", "", "body weight", "",
     "30s", "頂點停 1 秒夾臀"),
    ("Ankling", "Ankling", C_WARM, W, "3 組", "", "20 米", "body weight", "", "walk back",
     "腳踝彈性，接觸地面時間短"),
    ("臀肌喚醒（彈力帶）", "Glute Activation (Band)", C_WARM, W, "2 組",
     "每個動作 12 次", "", "彈力帶", "", "30s", "蚌式、側走、後踢三個動作一輪"),
    ("髖關節活動度組合", "Hip Mobility Circuit", C_WARM, W, "1 組", "每個動作 8 次", "",
     "body weight", "", "不休", "90/90、世界最偉大伸展、蜘蛛人弓步"),

    # -------------------------------------------------------- 田徑專項
    ("100m 反複跑", "100m Repetition", C_TRACK, M, "2 組", "3 次", "100 米", "",
     "80%-90%", "每次：5 分鐘 / 每組：15 分鐘", "起跑加速段保持前傾，最高速段放鬆"),
    ("60m 加速跑", "60m Acceleration", C_TRACK, M, "3 組", "4 次", "60 米", "",
     "90%-95%", "每次：3 分鐘 / 每組：8 分鐘", "前 20 米推蹬，逐步抬起軀幹"),
    ("30m 起跑", "30m Block Start", C_TRACK, M, "2 組", "5 次", "30 米", "",
     "95%-100%", "每次：3 分鐘 / 每組：10 分鐘", "起跑器角度固定，第一步不要拉太遠"),
    ("150m 節奏跑", "150m Tempo Run", C_TRACK, M, "2 組", "3 次", "150 米", "",
     "75%-85%", "每次：4 分鐘 / 每組：10 分鐘", "維持步幅，最後 30 米不掉速"),
    ("200m 反複跑", "200m Repetition", C_TRACK, M, "2 組", "3 次", "200 米", "",
     "85%-90%", "每次：6 分鐘 / 每組：12 分鐘", "彎道放鬆，直道加速"),
    ("400m 間歇", "400m Interval", C_TRACK, M, "1 組", "4 次", "400 米", "", "80%-85%",
     "每次：4 分鐘", "配速平均，前後 200 米差距 <2 秒"),
    ("飛行加速跑", "Flying Sprint", C_TRACK, M, "3 組", "3 次", "30 米加速 + 30 米計時",
     "", "95%-100%", "每次：4 分鐘", "進入計時段前已達最高速，肩頸放鬆"),
    ("上坡跑", "Hill Sprint", C_TRACK, M, "3 組", "5 次", "40 米", "", "最大努力",
     "走回坡底 / 每組 5 分鐘", "身體前傾成一直線，手臂大幅擺動"),
    ("雪橇加速拖行", "Sled Sprint", C_TRACK, M, "3 組", "4 次", "20 米",
     "體重 10%-20%", "最大努力", "每次：3 分鐘", "重量不要大到破壞跑姿"),
    ("接力交棒練習", "Relay Baton Exchange", C_TRACK, M, "3 組", "4 次", "接力區 30 米",
     "", "80%-90%", "每次：3 分鐘", "起跑點固定，交接不回頭看"),

    # -------------------------------------------------------- 上肢力量
    ("啞鈴三頭伸展", "Triceps Extension (Dumbbell)", C_UP, M, "3 組", "12 次", "",
     "啞鈴", "60%-70% 1RM", "60-90s", "手肘固定不外開，只有前臂在動"),
    ("機械坐姿划船", "Seated Row (Machine)", C_UP, M, "4 組", "10 次", "", "機械",
     "70%-80% 1RM", "90s", "先收肩胛再拉手，胸口挺住不駝背"),
    ("槓片式肩推", "Shoulder Press (Plate Loaded)", C_UP, M, "4 組", "8 次", "", "槓片機",
     "75%-85% 1RM", "2 分鐘", "核心收緊不挺腰，推到手肘接近打直"),
    ("槓鈴二頭彎舉", "Bicep Curl (Barbell)", C_UP, S, "3 組", "10 次", "", "槓鈴",
     "65%-75% 1RM", "60-90s", "手肘貼身，不用身體晃動帶起來"),
    ("機械胸推", "Chest Press (Machine)", C_UP, M, "4 組", "8 次", "", "機械",
     "75%-85% 1RM", "2 分鐘", "肩胛後收下沉，握把在胸線高度"),
    ("機械滑輪下拉", "Lat Pulldown (Machine)", C_UP, M, "4 組", "10 次", "", "機械",
     "70%-80% 1RM", "90s", "拉到鎖骨附近，不要靠後仰"),
    ("啞鈴單臂俯身划船", "Bent Over One Arm Row (Dumbbell)", C_UP, S, "3 組",
     "左/右手 10 次", "", "啞鈴", "70%-80% 1RM", "90s", "背部平直，軀幹不隨手臂轉動"),
    ("臥推", "Bench Press (Barbell)", C_UP, M, "4 組", "5 次", "", "依 1RM 換算",
     "80% 1RM", "2 分鐘", "肩胛收緊，槓下到胸線"),
    ("引體向上", "Pull Up", C_UP, M, "4 組", "6-8 次", "", "body weight（可加重）", "",
     "2 分鐘", "全幅度，下放到手臂接近打直"),
    ("伏地挺身", "Push Up", C_UP, S, "3 組", "15 次", "", "body weight", "", "60s",
     "身體成一直線，肘關節約 45 度"),
    ("農夫走路", "Farmer's Carry", C_UP, S, "3 組", "", "30 米", "重啞鈴／壺鈴", "",
     "90s", "肩胛下沉、軀幹不側傾"),

    # -------------------------------------------------------- 下肢力量
    ("槓鈴深蹲", "Squat (Barbell)", C_LOW, M, "4 組", "3-5 次", "", "依 1RM 換算",
     "85% 1RM", "3 分鐘", "下蹲到大腿平行，背部中立，膝蓋對齊腳尖"),
    ("槓鈴過頭深蹲", "Overhead Squat (Barbell)", C_LOW, M, "3 組", "5 次", "", "空槓起步",
     "40%-60% 1RM", "2 分鐘", "槓在耳後、手肘鎖死，胸口打開"),
    ("槓鈴前蹲", "Front Squat (Barbell)", C_LOW, M, "4 組", "4 次", "", "依 1RM 換算",
     "80% 1RM", "2-3 分鐘", "手肘抬高、軀幹直立，槓別滑到手上"),
    ("臀推（自體重量）", "Hip Thrust (Bodyweight)", C_LOW, S, "3 組", "15 次", "",
     "body weight", "", "60s", "肋骨收好，靠夾臀頂起來而不是拱腰"),
    ("槓鈴臀推", "Barbell Hip Thrust", C_LOW, M, "4 組", "8 次", "", "槓鈴",
     "70%-80% 1RM", "2 分鐘", "頂點停 1 秒，下巴微收"),
    ("反向硬舉", "Reverse Deadlift", C_LOW, M, "3 組", "6 次", "", "槓鈴",
     "70% 1RM", "2 分鐘", "由上而下先離心放，再從底部拉起"),
    ("硬舉", "Deadlift (Barbell)", C_LOW, M, "4 組", "3 次", "", "依 1RM 換算",
     "85% 1RM", "3 分鐘", "槓貼小腿，臀腿同時發力"),
    ("六角槓硬舉", "Trap Bar Deadlift", C_LOW, M, "4 組", "5 次", "", "六角槓",
     "80% 1RM", "2-3 分鐘", "起始像蹲，背不要先起來"),
    ("機械腿伸展", "Leg Extension (Machine)", C_LOW, S, "3 組", "12 次", "", "機械",
     "60%-70% 1RM", "60-90s", "頂點停 1 秒，離心放慢"),
    ("機械髖外展", "Hip Abductor (Machine)", C_LOW, S, "3 組", "15 次", "", "機械",
     "", "60s", "軀幹不後仰，靠臀中肌出力"),
    ("槓片式坐姿提踵", "Seated Calf Raise (Plate Loaded)", C_LOW, S, "4 組", "12 次", "",
     "槓片機", "", "60s", "全幅度，底部拉開比甲肌"),
    ("機械俯臥腿彎舉", "Lying Leg Curl (Machine)", C_LOW, S, "3 組", "10 次", "", "機械",
     "70% 1RM", "90s", "臀部不要離開墊子，離心放慢 3 秒"),
    ("保加利亞分腿蹲", "Bulgarian Split Squat", C_LOW, S, "3 組", "左/右腳 8 次", "",
     "20kg 啞鈴", "", "90s", "重心壓在前腳，膝蓋不內夾"),
    ("單腿羅馬尼亞硬舉", "Single Leg RDL", C_LOW, S, "3 組", "左/右腳 8 次", "",
     "啞鈴／壺鈴", "", "90s", "髖鉸鏈，骨盆保持水平不外翻"),
    ("羅馬尼亞硬舉 RDL", "Romanian Deadlift (RDL)", C_LOW, M, "4 組", "8 次", "",
     "槓鈴", "70% 1RM", "2 分鐘", "感覺膕繩肌被拉開再回來，背不圓"),
    ("行走弓步", "Walking Lunge", C_LOW, S, "3 組", "左/右腳 10 步", "20 米", "啞鈴", "",
     "90s", "後膝輕觸地，軀幹直立"),
    ("登階", "Step Up", C_LOW, S, "3 組", "左/右腳 10 次", "", "啞鈴", "", "90s",
     "全腳掌踩箱，不用後腳蹬地借力"),
    ("北歐腿彎舉", "Nordic Hamstring Curl", C_LOW, S, "3 組", "6 次", "", "body weight",
     "", "90s", "離心放慢到 4 秒"),
    ("提踵", "Calf Raise", C_LOW, S, "3 組", "15 次", "", "body weight", "", "60s",
     "頂點停 1 秒"),
    ("高翻", "Power Clean", C_LOW, M, "5 組", "3 次", "", "依 1RM 換算", "75%-85% 1RM",
     "3 分鐘", "速度優先，接槓時手肘快速轉到前方"),
    ("懸垂高翻", "Hang Clean", C_LOW, M, "5 組", "2 次", "", "依 1RM 換算", "70%-80% 1RM",
     "2-3 分鐘", "由膝上啟動，三關節同時伸展"),
    ("抓舉", "Snatch", C_LOW, M, "5 組", "2 次", "", "依 1RM 換算", "75% 1RM", "3 分鐘",
     "速度優先，重量次要"),
    ("借力推", "Push Press", C_LOW, M, "4 組", "4 次", "", "槓鈴", "75%-85% 1RM",
     "2 分鐘", "下沉不深，靠腿推起再鎖定"),

    # ------------------------------------------------------------ 核心
    ("平板支撐", "Plank", C_CORE, S, "3 組", "45 秒", "", "body weight", "", "45s",
     "頭到腳跟一直線，臀不翹不塌"),
    ("側平板支撐", "Side Plank", C_CORE, S, "3 組", "左/右邊 40 秒", "", "body weight",
     "", "45s", "身體成一直線，髖不下沉"),
    ("單腿 T 字平衡", "Single Leg T Balance", C_CORE, S, "3 組", "左/右腳 30 秒", "",
     "body weight", "", "45s", "支撐腳微屈，骨盆與肩保持水平"),
    ("啞鈴側屈", "Side Bend (Dumbbell)", C_CORE, S, "3 組", "左/右邊 12 次", "", "啞鈴",
     "", "60s", "只在冠狀面移動，不要前後晃"),
    ("背伸展", "Back Extension", C_CORE, S, "3 組", "12 次", "", "body weight", "",
     "60s", "靠臀腿收縮抬起，不要過度後仰"),
    ("V 字支撐", "V Sit", C_CORE, S, "3 組", "30 秒", "", "body weight", "", "45s",
     "腰不離地拱起，呼吸不中斷"),
    ("Copenhagen Plank", "Copenhagen Plank", C_CORE, S, "3 組", "左/右邊 30 秒", "",
     "body weight", "", "45s", "內收肌撐住，骨盆不掉"),
    ("Dead Bug 死蟲", "Dead Bug", C_CORE, S, "3 組", "左/右邊 10 次", "", "body weight",
     "", "45s", "腰貼地，呼吸不中斷"),
    ("鳥狗式", "Bird Dog", C_CORE, S, "3 組", "左/右邊 10 次", "", "body weight", "",
     "45s", "手腳伸展時軀幹不轉動"),
    ("Pallof Press 抗旋轉", "Pallof Press", C_CORE, S, "3 組", "左/右邊 12 次", "",
     "彈力帶／滑輪", "", "60s", "推出去時身體不被拉轉"),
    ("懸垂舉腿", "Hanging Leg Raise", C_CORE, S, "3 組", "10 次", "", "body weight", "",
     "60s", "骨盆後傾捲起，不靠擺盪"),
    ("腹輪推出", "Ab Wheel Rollout", C_CORE, S, "3 組", "8 次", "", "腹輪", "", "60s",
     "推出時腰不掉下去，能控制多遠推多遠"),
    ("俄羅斯轉體", "Russian Twist", C_CORE, S, "3 組", "左/右邊 15 次", "", "藥球", "",
     "45s", "轉的是胸椎，不是只有手在甩"),

    # -------------------------------------------------- 增強式／爆發力
    ("跨欄架跳", "Hurdle Jump", C_PLYO, M, "4 組", "5 次", "", "body weight", "最大努力",
     "2 分鐘", "落地即彈，接觸時間越短越好"),
    ("跳箱", "Box Jump", C_PLYO, M, "4 組", "5 次", "", "body weight", "最大努力",
     "2 分鐘", "跳上去、走下來，不要跳下來砸膝蓋"),
    ("立定跳遠", "Standing Broad Jump", C_PLYO, M, "4 組", "3 次", "", "body weight",
     "最大努力", "2 分鐘", "手臂帶動，落地屈膝緩衝"),
    ("跨步跳", "Bounding", C_PLYO, M, "3 組", "", "30 米", "body weight", "最大努力",
     "3 分鐘", "追求每一步的距離而不是速度"),
    ("深跳", "Depth Jump", C_PLYO, M, "3 組", "5 次", "", "30-45cm 跳箱", "最大努力",
     "3 分鐘", "接觸地面越短越好，力量期才安排"),
    ("藥球過頂前拋", "Medicine Ball Overhead Throw", C_PLYO, S, "3 組", "6 次", "",
     "4kg 藥球", "最大努力", "90s", "由髖帶動全身，不是只有手"),
    ("藥球側拋", "Medicine Ball Rotational Throw", C_PLYO, S, "3 組", "左/右邊 8 次", "",
     "4kg 藥球", "最大努力", "60s", "轉髖帶動，不是純手臂"),
    ("單腳跳", "Single Leg Hop", C_PLYO, S, "3 組", "左/右腳 6 次", "20 米",
     "body weight", "最大努力", "90s", "落地穩住 1 秒再跳下一下"),

    # ------------------------------------------------ 輔助／預防傷害
    ("阻力帶側走", "Lateral Band Walk", C_ACC, S, "3 組", "左/右邊 15 步", "", "彈力帶",
     "", "45s", "膝蓋不內扣"),
    ("腳踝離心提踵", "Eccentric Calf Raise", C_ACC, S, "3 組", "15 次", "",
     "body weight", "", "60s", "上快下慢，離心 4 秒"),
    ("脛前肌訓練", "Tibialis Raise", C_ACC, S, "3 組", "20 次", "", "body weight", "",
     "45s", "預防脛骨內側疼痛，全幅度勾腳"),
    ("肩袖外旋", "External Rotation (Band)", C_ACC, S, "3 組", "左/右邊 15 次", "",
     "彈力帶", "", "45s", "手肘貼身，動作慢"),
    ("足底放鬆", "Plantar Fascia Release", C_ACC, R, "1 組", "每邊 60 秒", "", "按摩球",
     "", "不休", "痛點停留深呼吸"),

    # -------------------------------------------------------- 恢復／放鬆
    ("慢跑收操", "Cool Down Jog", C_REC, R, "1 組", "", "800 米", "body weight", "50%",
     "不休", "呼吸回到平穩為止"),
    ("靜態伸展組合", "Static Stretching Circuit", C_REC, R, "1 組", "每個動作 30 秒", "",
     "body weight", "", "不休", "拉到緊但不痛的位置"),
    ("泡沫軸放鬆", "Foam Rolling", C_REC, R, "1 組", "每個部位 60 秒", "", "泡沫軸", "",
     "不休", "痛點停留深呼吸 3 次"),
    ("冰浴", "Ice Bath", C_REC, R, "1 組", "10 分鐘", "", "", "10-12°C", "不休",
     "高強度課後 30 分鐘內"),
    ("呼吸放鬆 4-7-8", "4-7-8 Breathing", C_REC, R, "1 組", "8 個循環", "", "", "",
     "不休", "吸 4 秒、停 7 秒、吐 8 秒"),
    ("步行放鬆", "Recovery Walk", C_REC, R, "1 組", "10 分鐘", "", "body weight", "",
     "不休", "心率降到 100 以下"),
    ("水中恢復", "Pool Recovery", C_REC, R, "1 組", "20 分鐘", "", "", "低強度", "不休",
     "過渡期的積極性恢復，非專項低強度運動"),
]


#: 舊版清單裡中英混在一起的名字 → 現在中英分兩欄之後的名字。
#: 只改系統內建的那幾筆，而且目標名稱已經存在時就跳過，不會撞名。
RENAMES = {
    "背蹲舉 Back Squat": "槓鈴深蹲",
    "硬舉 Deadlift": "硬舉",
    "抓舉 Snatch": "抓舉",
    "臥推 Bench Press": "臥推",
    "跨欄架跳 Hurdle Jump": "跨欄架跳",
    "北歐腿彎舉 Nordic Curl": "北歐腿彎舉",
    "提踵 Calf Raise": "提踵",
    "側平板 Side Plank": "側平板支撐",
}


class Command(BaseCommand):
    help = "建立訓練活動名稱庫的起始清單（可重覆執行）"

    def handle(self, *args, **options):
        renamed = 0
        for old_name, new_name in RENAMES.items():
            row = ActivityDefinition.objects.filter(name=old_name, is_builtin=True).first()
            if row is None or ActivityDefinition.objects.filter(name=new_name).exists():
                continue
            row.name = new_name
            row.save(update_fields=["name", "updated_at"])
            renamed += 1

        created = updated = 0
        for (
            name, name_en, category, block, sets, reps, distance, weight,
            intensity, rest, key_points,
        ) in ACTIVITIES:
            obj, was_created = ActivityDefinition.objects.get_or_create(
                name=name,
                defaults={
                    "name_en": name_en,
                    "category": category,
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
            # 舊資料是在還沒有「分類／英文名」這兩欄之前建的，這裡補上；
            # 教練自己新增的活動（is_builtin=False）一律不動。
            if not was_created and obj.is_builtin:
                changed = []
                if not obj.name_en:
                    obj.name_en = name_en
                    changed.append("name_en")
                if obj.category != category:
                    obj.category = category
                    changed.append("category")
                if changed:
                    obj.save(update_fields=changed + ["updated_at"])
                    updated += 1

        synced = self._sync_metric_categories()

        self.stdout.write(
            self.style.SUCCESS(
                f"活動清單：新增 {created} 項、補齊 {updated} 項、"
                f"更名 {renamed} 項，"
                f"目前共 {ActivityDefinition.objects.count()} 項；"
                f"另對齊 {synced} 個數據項目的分類／英文名。"
            )
        )

    def _sync_metric_categories(self):
        """數據項目的分類與英文名跟著活動庫走。

        課表上加過的活動會在數據分析開同名項目，兩邊的分類要一致，
        重量訓練紀錄的項目清單才分得出上身／下身／核心；
        英文名同步過去，畫面上才每個項目都有中英文對照。
        """
        from analytics.models import (
            MetricCategory,
            MetricItem,
            metric_category_for_activity,
        )

        by_name = {
            row["name"]: row
            for row in ActivityDefinition.objects.values("name", "name_en", "category")
        }
        synced = 0
        for item in MetricItem.objects.all():
            row = by_name.get(item.name)
            if row is None:
                continue
            changes = {}
            if item.category == MetricCategory.OTHER:
                category = metric_category_for_activity(row["category"])
                if category != item.category:
                    changes["category"] = category
            if not item.name_en and row["name_en"]:
                changes["name_en"] = row["name_en"]
            if changes:
                MetricItem.objects.filter(pk=item.pk).update(**changes)
                synced += 1
        return synced

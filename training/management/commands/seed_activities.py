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
C_PLY1 = ActivityCategory.PLYO_BASIC
C_PLY2 = ActivityCategory.PLYO_TRACK
C_PLY3 = ActivityCategory.PLYO_UPPER
C_PLY4 = ActivityCategory.PLYO_POGO
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

    # ------------------------------ 增強式（一）基礎與進階跳躍訓練
    ("抱膝跳", "Tuck Jump", C_PLY1, M, "3 組", "6-8 次", "", "body weight", "最大努力",
     "2 分鐘", "原地連續跳，膝蓋收到胸口，落地即彈不要蹲住"),
    ("深蹲跳", "Squat Jump", C_PLY1, M, "4 組", "5 次", "", "body weight", "最大努力",
     "2 分鐘", "蹲到底停一下再跳，練的是純向心的爆發力"),
    ("下蹲跳", "Countermovement Jump (CMJ)", C_PLY1, M, "4 組", "5 次", "",
     "body weight", "最大努力", "2 分鐘", "下蹲不要停，借反彈力量往上，手臂配合擺動"),
    ("分腿跳", "Split Jump", C_PLY1, M, "3 組", "左/右腳各 8 次", "", "body weight",
     "最大努力", "90s", "空中換腿，落地前腳膝蓋對準腳尖"),
    ("跳箱", "Box Jump", C_PLY1, M, "4 組", "5 次", "", "body weight", "最大努力",
     "2 分鐘", "跳上去、走下來，不要跳下來砸膝蓋"),
    ("立定跳遠", "Broad Jump / Standing Long Jump", C_PLY1, M, "4 組", "3 次", "",
     "body weight", "最大努力", "2 分鐘", "手臂帶動，落地屈膝緩衝"),
    ("深跳", "Depth Jump / Drop Jump", C_PLY1, M, "3 組", "5 次", "", "30-45cm 跳箱",
     "最大努力", "3 分鐘", "接觸地面越短越好，力量期才安排"),
    ("單腳跳", "Single Leg Hop", C_PLY1, S, "3 組", "左/右腳 6 次", "20 米",
     "body weight", "最大努力", "90s", "落地穩住 1 秒再跳下一下"),

    # ------------------------------ 增強式（二）田徑專項增強式訓練
    ("跨欄架跳", "Hurdle Jump / Hurdle Hop", C_PLY2, M, "4 組", "5 次", "",
     "body weight", "最大努力", "2 分鐘", "落地即彈，接觸時間越短越好"),
    ("跨步跳", "Bounding", C_PLY2, M, "3 組", "", "30 米", "body weight", "最大努力",
     "3 分鐘", "追求每一步的距離而不是速度"),
    ("單腳跨步跳", "Single-Leg Bounding", C_PLY2, M, "3 組", "左/右腳各 1 趟", "20 米",
     "body weight", "最大努力", "3 分鐘", "同一腳連續推進，骨盆不要掉，量力而為"),
    ("側向欄架跳", "Lateral Hurdle Hop", C_PLY2, M, "3 組", "來回 6 次", "",
     "低欄架 / 標誌桶", "最大努力", "2 分鐘", "落地膝蓋不內扣，往側邊推而不是往上跳"),
    ("落下跳接欄架跳", "Depth Jump to Hurdle Hop", C_PLY2, M, "3 組", "3-4 次", "",
     "30cm 跳箱 + 欄架", "最大努力", "3 分鐘", "落地那一下就要轉成往前，中間不停頓"),
    ("高遠衝力跳躍步", "Galloping / Skipping for Height & Distance", C_PLY2, M, "3 組",
     "", "30 米", "body weight", "最大努力", "2 分鐘",
     "一趟追高度、一趟追距離，擺臂與提膝要對得上"),

    # ---------------------- 增強式（三）上肢與全身旋轉爆發力訓練
    ("藥球胸前推球", "Medicine Ball Chest Pass", C_PLY3, S, "3 組", "8 次", "",
     "3-5kg 藥球", "最大努力", "60s", "站姿或半跪，推出去的是全身不是只有手"),
    ("藥球過頭砸球", "Medicine Ball Overhead Slam", C_PLY3, S, "3 組", "8 次", "",
     "4-6kg 藥球", "最大努力", "60s", "全程收好核心，砸下去不要用腰甩"),
    ("增強式俯臥撐", "Plyometric Push-Up / Clapping Push-Up", C_PLY3, S, "3 組", "5-8 次",
     "", "body weight", "最大努力", "90s", "推離地面後手先落地緩衝，撐不住就改跪姿"),
    ("藥球過頂前拋", "Medicine Ball Overhead Throw", C_PLY3, S, "3 組", "6 次", "",
     "4kg 藥球", "最大努力", "90s", "由髖帶動全身，不是只有手"),
    ("藥球側拋", "Medicine Ball Rotational Throw", C_PLY3, S, "3 組", "左/右邊 8 次", "",
     "4kg 藥球", "最大努力", "60s", "轉髖帶動，不是純手臂"),

    # ------------------------ 增強式（四）Pogo Jump（踝彈跳）的變體
    ("雙腳踝彈跳", "Double-Leg Pogo Jump", C_PLY4, W, "3 組", "15-20 次", "",
     "body weight", "快速反彈", "60s", "膝蓋幾乎打直，全靠腳踝彈，觸地越短越好"),
    ("單腳踝彈跳", "Single-Leg Pogo Jump", C_PLY4, S, "3 組", "左/右腳 10-12 次", "",
     "body weight", "快速反彈", "60s", "骨盆保持水平，落點在身體正下方"),
    ("原地踝彈跳", "In-Place Pogo Jump", C_PLY4, W, "3 組", "20 次", "", "body weight",
     "快速反彈", "45s", "垂直上下，不要往前跑掉"),
    ("直線前進踝彈跳", "Traveling Pogo Jump / Linear Pogo", C_PLY4, S, "3 組", "",
     "20 米", "body weight", "快速反彈", "60s", "邊彈邊往前，保持節奏不要越彈越低"),
    ("側向踝彈跳", "Lateral Pogo Jump", C_PLY4, S, "3 組", "左/右各 12 次", "",
     "body weight", "快速反彈", "60s", "腳踝剛性不變，用髖控制方向"),
    ("旋轉踝彈跳", "Rotational Pogo Jump", C_PLY4, S, "3 組", "左/右各 6 次", "",
     "body weight", "快速反彈", "60s", "轉體靠核心，落地方向要對正"),
    ("低振幅踝彈跳", "Low Pogo Jump", C_PLY4, W, "3 組", "20-30 次", "", "body weight",
     "快速反彈", "45s", "跳得低、彈得快，觸地時間是重點"),
    ("高振幅踝彈跳", "High Pogo Jump", C_PLY4, M, "3 組", "8-10 次", "", "body weight",
     "最大努力", "90s", "腳踝不能鬆掉，在剛性不變的前提下跳到最高"),

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


#: 動作說明——「這個動作到底在做什麼」，一句話講完。
#: 跟「訓練要點」分開：要點是做的時候要注意什麼，說明是它是哪一種動作、練到什麼。
#: 只補空白的欄位，教練自己改過的說明不會被蓋掉。
NOTES = {
    # 基礎與進階跳躍訓練 Basic & Advanced Jumping
    "抱膝跳": "原地垂直跳起後把雙膝主動收向胸口，落地立刻再跳；訓練下肢反應力量與空中收腿的協調。",
    "深跳": "從跳箱上落下，著地瞬間立刻爆發向上跳起；典型的反應式增強訓練，強調極短的觸地時間。",
    "深蹲跳": "從蹲低的位置停一下再直接往上跳，去掉反彈的助力，練的是純粹的向心爆發力。",
    "下蹲跳": "先快速下蹲再立刻往上跳，利用伸展—收縮循環；是評估與訓練彈跳力最常用的動作。",
    "分腿跳": "以弓箭步起跳、在空中換腿落地；訓練單側爆發力與落地時的控制能力。",
    "立定跳遠": "原地雙腳起跳向前跳最遠；訓練水平方向的爆發力，與起跑加速直接相關。",
    "跳箱": "雙腳起跳上箱、走下來；用較低的落地衝擊練起跳的爆發力，適合入門與大量期。",
    "單腳跳": "單腳連續向前跳，每一下都要穩住再跳下一下；訓練單側力量與落地穩定度。",

    # 田徑專項增強式訓練 Track & Field Specific Plyometrics
    "跨欄架跳": "連續越過一排欄架，每一次落地都要立刻彈起；訓練連續反應力量與跳躍節奏。",
    "跨步跳": "以誇張的大步向前跳躍、左右腳交替；強化推蹬距離與髖伸展，是跑步專項的核心增強動作。",
    "單腳跨步跳": "同一隻腳連續向前跳躍；訓練單側推進力與穩定度，負荷高，要循序漸進。",
    "側向欄架跳": "向左、右兩側連續越過低欄；提升變向能力與膝、踝的側向穩定。",
    "落下跳接欄架跳": "從跳箱落下後立刻接一連串欄架跳；把單次的反應力量轉成連續往前的推進。",
    "高遠衝力跳躍步": "以誇張的跳躍步向前推進，一趟追高度、一趟追距離；銜接跑步技術與彈性力量。",

    # 上肢與全身旋轉爆發力訓練 Upper Body & Rotational Plyometrics
    "藥球胸前推球": "雙手持藥球從胸前爆發推出；訓練上肢「推」的速度力量，也練得到下肢傳到手的發力順序。",
    "藥球過頭砸球": "舉球過頭後全力砸向地面；訓練核心與上肢的下拉爆發力，節奏要快不要停。",
    "增強式俯臥撐": "俯臥撐推起時讓雙手離地（進階可加拍手）；訓練上肢的反應力量與落地緩衝。",
    "藥球過頂前拋": "由後往前把藥球過頂拋出；用髖帶動全身，練全身的伸展鏈爆發力。",
    "藥球側拋": "側身把藥球往牆或同伴拋出；訓練軀幹旋轉的爆發力，投擲與彎道跑都用得到。",

    # Pogo Jump（踝彈跳）的主要變體與項目
    "雙腳踝彈跳": "最基礎的雙腳連續快速彈跳，著重於腳踝剛性與減少觸地時間。",
    "單腳踝彈跳": "單腳執行的踝彈跳，能訓練單側穩定度，更符合跑步與單腳起跳的特性。",
    "原地踝彈跳": "雙腳或單腳固定於原地進行縱向垂直彈跳。",
    "直線前進踝彈跳": "結合向前移動的踝彈跳，強化水平推進與下肢彈性轉換。",
    "側向踝彈跳": "向左、右兩側連續彈跳，提升側向移動與變向能力。",
    "旋轉踝彈跳": "在彈跳過程中進行 90 度或 180 度的空中轉體，挑戰核心與關節控制。",
    "低振幅踝彈跳": "極短觸地時間的快速小幅彈跳，專注於阿基里斯腱的彈性反應。",
    "高振幅踝彈跳": "在保持腳踝剛性的前提下盡可能提高跳躍高度。",
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
                    "note": NOTES.get(name, ""),
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
                if not obj.note and NOTES.get(name):
                    obj.note = NOTES[name]
                    changed.append("note")
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

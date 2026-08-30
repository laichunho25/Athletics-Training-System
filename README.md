# ATM — Athlete Training Management System

田徑個人化訓練與管理系統（Django 6 + DRF）。
規格書見 [ATM_SPEC.md](ATM_SPEC.md)，部署見 [DEPLOY.md](DEPLOY.md)。

---

## 快速開始

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py loaddata events exercises recovery_methods exercise_modifications
python manage.py seed_demo --weeks 8      # 建立示範資料
python manage.py seed_templates           # 建立短跑課表模板（需先有教練帳號）
python manage.py seed_projects            # 建立公開報名項目
python manage.py createsuperuser
python manage.py runserver          # 固定跑在 8200 埠（避開其他專案）
```

> **多專案並存**：本機已有其他 Django 專案佔用 8000 / 8001，
> 所以 ATM 在 `manage.py` 內把預設埠改成 **8200**。
> Windows 可直接雙擊 `run_atm.bat` 啟動並自動開瀏覽器。

| 位置 | 網址 |
|---|---|
| **公開首頁** | http://127.0.0.1:8200/ |
| **項目報名** | http://127.0.0.1:8200/programs/ |
| **登入** | http://127.0.0.1:8200/accounts/login/ |
| 儀表板（運動員） | http://127.0.0.1:8200/dashboard/ |
| 團隊儀表板（教練） | http://127.0.0.1:8200/team/ |
| 訓練日曆 | http://127.0.0.1:8200/calendar/ |
| 數據分析 | http://127.0.0.1:8200/analytics/ |
| 營養與恢復 | http://127.0.0.1:8200/nutrition/ |
| 傷患管理 | http://127.0.0.1:8200/injuries/ |
| Admin 後台 | http://127.0.0.1:8200/admin/ |
| API 瀏覽介面 | http://127.0.0.1:8200/api/ |

示範帳號：

| 帳號 | 密碼 | 角色 |
|---|---|---|
| `admin` | `admin12345` | 管理員（可進 /admin/） |
| `coach_chan` | `atm12345` | 教練 |
| `athlete_lai` | `atm12345` | 運動員 |

> 若無法登入 `/admin/`，代表帳號沒有 `is_staff`。`seed_demo` 已自動建立 `admin` 超級使用者，
> 或執行 `python manage.py createsuperuser`。

---

## HTML 前端

| 頁面 | 內容 |
|---|---|
| 公開首頁 `/` | 短跑訓練方向、16 週週期與一週結構，含報名與 ATM 登入入口（免登入可看） |
| 項目報名 `/programs/` | 公開招生的訓練項目列表、詳情與報名表（免登入可看，見下方章節） |
| 儀表板 | 賽事倒數、目前分期、ACWR 燈號、準備度、今日/本週課表、近 8 週負荷圖、PB 表 |
| 團隊儀表板 | 全隊 ACWR/準備度/傷患一覽，高風險與傷患警示條 |
| 訓練日曆 | 月曆（週一起）、分期色條、依狀態著色的課表，點入可打卡 |
| 課表詳情 | 專項組數與力量組數明細、RPE/時長打卡表單、教練評語、傷患調整按鈕 |
| 數據分析 | 週負荷＋ACWR＋Monotony 複合圖、專項成績趨勢（時間項目 Y 軸反轉）、1RM 趨勢、訓練量分佈圓環 |
| 營養與恢復 | TDEE 與三大營養素、熱量分配圓環、晨間問卷、近 14 天睡眠/痠痛圖、本週達成率、補充劑表 |
| 傷患管理 | 疼痛趨勢圖、今日疼痛記錄（≥6 自動調整課表）、替代動作表、RTP 檢核表、新增/結案 |

- 系統內頁樣板在 `templates/`，樣式 `static/css/atm.css`（深色主題）
- 公開首頁 `templates/site/landing.html` + `static/css/landing.css`（暖色調，獨立不繼承 base.html）
- 公開報名 `templates/programs/` + `static/css/programs.css`（沿用 landing.css 的樣式變數）
- 登入後入口為 `/app/`（依角色分流到 `/dashboard/` 或 `/team/`）
- Chart.js 4.4.7 已 vendored 於 `static/js/chart.min.js`，**完全離線可用**
- 教練檢視他人資料用 `?athlete=<id>`，權限一律經 `athlete_ids_visible_to()` 收斂

---

## 專案結構

```
config/       settings / urls
core/         共用 abstract model、enums、權限、fixtures、管理指令
accounts/     模組1 Profile & 目標（User / Coach / Athlete / Event / PB / 體測）
planning/     模組2 日程與計劃（Competition / Macrocycle / Phase / Microcycle / TrainingSession）
training/     模組3 專項與力量（TrackSet / StrengthSet / Exercise / 1RM / 神經肌肉測試）
analytics/    模組4 分析（DailyLoad / WeeklySummary + services.py 全部計算）
nutrition/    模組5 營養與恢復（TDEE / 三大營養素 / 恢復日誌）
injury/       模組6 傷患（Injury / PainLog / 復健方案 / 替代動作引擎）
```

**核心設計**：`TrainingSession` 是唯一的訓練入口表，`TrackSet` 與 `StrengthSet` 都掛在它下面，
因此負荷計算、營養推斷、傷患調整都只需要看一張表。
所有計算集中在各 app 的 `services.py`；model 只放 property，view 只做編排。

---

## 關鍵計算

| 指標 | 公式 | 位置 |
|---|---|---|
| Session Load | `RPE × 實際時長`（Foster sRPE，單位 AU） | `TrainingSession.session_load` |
| 急性負荷 | 最近 7 天總和 | `analytics.services.acute_load` |
| 慢性負荷 | 最近 28 天總和 ÷ 4 | `analytics.services.chronic_load` |
| ACWR | 急性 ÷ 慢性（另有 EWMA 版） | `calculate_acwr` / `calculate_ewma_acwr` |
| Monotony | 週平均日負荷 ÷ 標準差 | `calculate_monotony` |
| Strain | 週總負荷 × Monotony | `calculate_strain` |
| 1RM | Epley `w×(1+r/30)` / Brzycki `w×36/(37−r)` | `training.models` |
| BMR | Mifflin-St Jeor | `nutrition.services.mifflin_st_jeor` |
| 準備度 | 睡眠30 + 痠痛25 + 壓力15 + 疼痛20 + 神經肌肉10 | `readiness_score` |

### ACWR 燈號

| 區間 | 判定 | 動作 |
|---|---|---|
| < 0.80 | 🔵 訓練不足 | 可增量 5–10% |
| 0.80–1.30 | 🟢 甜蜜點 | 維持 |
| 1.30–1.50 | 🟡 偏高 | 注意恢復 |
| > 1.50 | 🔴 高受傷風險 | 減量 20–30% |

> ACWR 需滿 28 天資料才計算，否則回傳 `null`（前端顯示「資料累積中」）。

---

## 主要 API

```
GET  /api/athletes/<id>/dashboard/              運動員儀表板（倒數＋分期＋今日課表＋ACWR＋準備度）
GET  /api/coaches/<id>/dashboard/               教練團隊儀表板（全隊燈號）
GET  /api/competitions/target/                  主目標賽事與倒數
POST /api/macrocycles/<id>/generate/            一鍵產生 16 週分期＋週計劃
GET  /api/sessions/calendar/?athlete=1&year=&month=   月曆
POST /api/sessions/<id>/complete/               打卡完成（回傳新負荷與 ACWR）
POST /api/sessions/<id>/apply_injury_modifications/  依傷患自動調整課表
POST /api/session-templates/<id>/assign/        批次派發模板給多名運動員
POST /api/exercises/estimate_1rm/               1RM 推估
GET  /api/exercises/<id>/percentage_table/?athlete=1  %1RM 配重表
GET  /api/analytics/acwr/<athlete_id>/          ACWR 報告
GET  /api/analytics/load-progression/<id>/?weeks=12   週負荷柱狀圖＋ACWR 折線
GET  /api/analytics/trend/<id>/?event=400M      專項成績趨勢（含回歸斜率）
GET  /api/analytics/strength-trend/<id>/?exercise=BACK_SQUAT
GET  /api/analytics/volume-distribution/<id>/   訓練量分佈（圓餅圖）
GET  /api/analytics/readiness/<id>/             準備度分數
POST /api/nutrition/targets/calculate/          計算當日 TDEE 與三大營養素
GET  /api/nutrition/compliance/<id>/            一週營養達成率
GET  /api/injuries/<id>/alternatives/           替代動作建議
GET  /api/injuries/<id>/rtp_checklist/          Return-to-Play 檢核表
GET  /api/exercise-modifications/by_body_part/?body_part=HAMSTRING
```

**權限**：運動員只能存取自己的資料；教練可存取 `coach.athletes` 旗下運動員；管理員不限。
由 `core/permissions.py` 的 `athlete_ids_visible_to()` 統一收斂。

---

## 傷患自動調整

1. 運動員記錄 `PainLog`，活動時疼痛 ≥ 6 → 觸發 `apply_modifications()`
2. 高強度課（TRACK / STRENGTH / COMPETITION）自動降級為 RECOVERY，時長上限 45 分鐘
3. 個別力量動作依 `ExerciseModification` 對照表替換（如 硬舉 → 反向雪橇拖）
4. 疼痛超過所有替代方案的 `max_pain_level` → 標記為建議暫停
5. `sync_athlete_status()` 依傷患狀態更新運動員燈號

---

## 排程

```bash
python manage.py rebuild_analytics --days 90     # 重算全部運動員負荷，列出高風險
python manage.py rebuild_analytics --athlete 1
```

建議每日 00:30 執行（Celery beat / Windows 工作排程器）。
`TrainingSession` 的 post_save/post_delete signal 已即時重算當日與當週彙總，
此指令用於部署後回填或修正歷史資料。

---

## 基礎資料與課表模板

`core/fixtures/` 的四份 fixture 由 `loaddata` 載入，pk 固定，可重複執行：

| Fixture | 內容 |
| --- | --- |
| `events.json` | 田徑項目 |
| `exercises.json` | 動作字典（64 個動作，以 `code` 供模板引用） |
| `recovery_methods.json` | 恢復手段 |
| `exercise_modifications.json` | 替代動作對照表（55 筆，13 個身體部位全覆蓋） |

替代動作表是傷患期自動降階的依據：某部位疼痛時，教練依 `contraindicated_body_parts`
與 `max_pain_level` 查出可執行的替代動作。

**課表模板**（`SessionTemplate`）的 `coach` 是必填外鍵，沒辦法用 fixture 灌，
改由管理指令掛到現有教練身上，以「教練 + 模板名稱」為鍵做 upsert：

```bash
python manage.py seed_templates                  # 掛給所有教練
python manage.py seed_templates --coach coach_chan
python manage.py seed_templates --skip-if-empty  # 沒有教練時安靜跳過（build.sh 用）
```

內建 11 個短跑專項模板：加速期起跑、最大速度飛行跑、速度耐力 150m、
特殊耐力 300/250/200、節奏跑、最大力量、爆發力、上肢與軀幹穩定、
技術日、恢復日、賽前激活。`SessionTemplate.clone_to_session()`
會把模板展開成一堂實際課，含 `TrackSet` 與 `StrengthSet`。

---

## 公開報名（programs）

不需登入的招生流程，與 ATM 內部系統共用同一個資料庫。

| 網址 | 內容 |
| --- | --- |
| `/programs/` | 所有公開項目的列表，顯示日期、費用、餘額與報名狀態 |
| `/programs/<slug>/` | 項目詳情（日期、堂數、場地、費用、重要事項） |
| `/programs/<slug>/apply/` | 報名表：個人資料 / 運動背景 / KYC 健康申報 |
| `/programs/<slug>/done/` | 送出後的確認頁 |

**後台控制**（`/admin/programs/`）

- `Project` — 建立項目、設定內容，用「狀態」＋「報名開始／截止」控制開放與否。
  只有狀態為「開放報名」且在時間範圍內，公開頁才會出現報名按鈕。
- `capacity_total` 額滿後，新報名仍可送出，但自動標記為**候補**，不佔正取名額。
- `Application` — 每份報名的完整資料，列表會標示需留意的紅旗
  （現有傷患 / 長期病患 / 未取得醫生許可 / 未成年但無家長聯絡）。

**報名 → ATM**

在報名列表選取後執行「匯入 ATM，建立運動員檔案」，會建立 `User`＋`AthleteProfile`：
出生日期、性別、身高體重、每週訓練日、重訓年資、學校會所直接對應；
個人最佳、緊急聯絡、傷患與病歷寫進 `notes`；主項由報名時的項目分類推導。
密碼設為隨機值（對方須由後台重設），重複執行不會產生第二個帳號。
另有「匯出 CSV」動作，供保險或場地登記使用。

**第一個項目** 由 `seed_projects` 建立（DBSAC Special Strength & Conditioning
Sessions），已存在時不會被覆寫，要重設內容請加 `--force`。

---

## 公開首頁與短跑術語表

首頁 `/` 的主視覺是一個 canvas 動畫：旋轉的四百公尺跑道（wheel effect），
下方是一條一百公尺直道，按「跑一趟 100 公尺」會依
`v(t) = vmax · (1 − e^(−t/τ))` 即時演算並顯示時間、距離、速度、
所處階段與每 10 公尺分段。純 vanilla JS（`static/js/track-hero.js`），
沒有外部相依，並遵守 `prefers-reduced-motion`。

短跑訓練的專業用詞（中英對照 + 解釋）只維護一份：

```
core/glossary.py                     ← 唯一資料來源
  ├─ 首頁 #terms 區塊（core.views.landing 帶入 context）
  └─ docs/sprint-glossary.md（由管理指令產生）
```

```bash
python manage.py export_glossary          # 重新產生 docs/sprint-glossary.md
python manage.py export_glossary --check  # 只檢查是否同步（測試會跑這一項）
```

要新增或修改詞條，改 `core/glossary.py` 後執行 `export_glossary`，
網站與 MD 檔會同時更新，不會各改各的而對不上。

---

## 測試

```bash
python manage.py test          # 134 項，約 10 秒
```

涵蓋 sRPE 負荷、ACWR（含 0.80 / 1.30 / 1.50 邊界與除零保護）、單調度與壓力、
成績趨勢斜率、週負荷遞增、營養計算與準備度、疼痛封鎖與課表降階、
權限收斂（運動員／教練／管理員／匿名）、公開報名流程（開放控制、名額與候補、
表單驗證、匯入 ATM 的冪等性）、短跑術語表與 MD 檔的同步，以及 fixture 與模板的資料完整性。
跑測試時 `settings.py` 會自動切換成 MD5 雜湊，避免 PBKDF2 拖慢建帳號。

---

## 尚未實作（下一步）

- [x] HTML 前端頁面與 Chart.js 圖表
- [x] 單元測試（services 計算邏輯 + 權限）
- [ ] Notification model 與 Celery 排程
- [x] 擴充 fixtures（更多替代動作 / 課表模板）
- [x] PostgreSQL 與 Render 部署設定（見 [DEPLOY.md](DEPLOY.md)）
- [ ] 報告匯出（CSV / PDF）

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
python manage.py createsuperuser
python manage.py runserver          # 固定跑在 8200 埠（避開其他專案）
```

> **多專案並存**：本機已有其他 Django 專案佔用 8000 / 8001，
> 所以 ATM 在 `manage.py` 內把預設埠改成 **8200**。
> Windows 可直接雙擊 `run_atm.bat` 啟動並自動開瀏覽器。

| 位置 | 網址 |
|---|---|
| **公開首頁** | http://127.0.0.1:8200/ |
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
| 公開首頁 `/` | 田徑訓練六大方向、三種週期化模式介紹，暖色調，含 ATM 登入入口（免登入可看） |
| 儀表板 | 賽事倒數、目前分期、ACWR 燈號、準備度、今日/本週課表、近 8 週負荷圖、PB 表 |
| 團隊儀表板 | 全隊 ACWR/準備度/傷患一覽，高風險與傷患警示條 |
| 訓練日曆 | 月曆（週一起）、分期色條、依狀態著色的課表，點入可打卡 |
| 課表詳情 | 專項組數與力量組數明細、RPE/時長打卡表單、教練評語、傷患調整按鈕 |
| 數據分析 | 週負荷＋ACWR＋Monotony 複合圖、專項成績趨勢（時間項目 Y 軸反轉）、1RM 趨勢、訓練量分佈圓環 |
| 營養與恢復 | TDEE 與三大營養素、熱量分配圓環、晨間問卷、近 14 天睡眠/痠痛圖、本週達成率、補充劑表 |
| 傷患管理 | 疼痛趨勢圖、今日疼痛記錄（≥6 自動調整課表）、替代動作表、RTP 檢核表、新增/結案 |

- 系統內頁樣板在 `templates/`，樣式 `static/css/atm.css`（深色主題）
- 公開首頁 `templates/site/landing.html` + `static/css/landing.css`（暖色調，獨立不繼承 base.html）
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

## 尚未實作（下一步）

- [x] HTML 前端頁面與 Chart.js 圖表
- [ ] 單元測試（services 計算邏輯 + 權限）
- [ ] Notification model 與 Celery 排程
- [ ] 擴充 fixtures（更多替代動作 / 課表模板）
- [x] PostgreSQL 與 Render 部署設定（見 [DEPLOY.md](DEPLOY.md)）
- [ ] 報告匯出（CSV / PDF）

# ATM — Athlete Training Management System
## Django 開發規格書 / 建置清單

> 目標賽事基準：**全港田徑公開賽 2026-11-29**（T-16 週，系統啟動日 2026-08-09）
> 技術棧建議：Django 5.x + Django REST Framework + PostgreSQL + HTMX/Bootstrap（或 React 前端）

---

## 0. 專案骨架 (Project Skeleton)

- [ ] `django-admin startproject config .`
- [ ] 建立 apps（每個模組一個 app）

```
atm/
├── config/                 # settings, urls, wsgi
├── accounts/               # 使用者、角色、Coach/Athlete Profile   → 模組 1
├── planning/               # 賽事、週期分期、日程、訓練計劃        → 模組 2
├── training/               # 田徑專項 + 力量訓練紀錄               → 模組 3
├── analytics/              # 負荷監控、ACWR、趨勢分析              → 模組 4
├── nutrition/              # TDEE、營養素、睡眠、恢復              → 模組 5
├── injury/                 # 傷患日誌、替代動作                    → 模組 6
├── core/                   # 共用 abstract models, mixins, enums
├── templates/
└── static/
```

- [ ] `core/models.py` 建立 `TimeStampedModel`（`created_at`, `updated_at`）供全專案繼承
- [ ] `core/permissions.py` 建立 `IsCoachOfAthlete`, `IsOwnerAthlete` 權限類別
- [ ] settings：`AUTH_USER_MODEL = "accounts.User"`（**專案第一天就要設定，之後無法輕易更改**）

---

## 1. 模組 1 — 個人 Profile & 目標設定

### App: `accounts`

#### `User(AbstractUser)`
| 欄位 | 型別 | 說明 |
|---|---|---|
| `role` | `CharField(choices=Role)` | `COACH` / `ATHLETE` / `ADMIN` |
| `phone` | `CharField(blank=True)` | |
| `avatar` | `ImageField(null=True)` | |

- [ ] `Role` 用 `models.TextChoices`

#### `CoachProfile`
| 欄位 | 型別 |
|---|---|
| `user` | `OneToOneField(User, on_delete=CASCADE)` |
| `squad_name` | `CharField` — 如「短跑組」 |
| `specialties` | `CharField` — 短跑/跳部/中長跑/投擲 |
| `certification` | `CharField(blank=True)` |

#### `AthleteProfile`
| 欄位 | 型別 | 備註 |
|---|---|---|
| `user` | `OneToOneField(User)` | |
| `coach` | `FK(CoachProfile, null=True, related_name="athletes")` | 教練↔運動員 1:N |
| `birth_date` | `DateField` | 由此推算年齡（用 property，不存 age） |
| `sex` | `CharField(choices=Sex)` | 影響 TDEE 公式 |
| `height_cm` | `DecimalField(5,1)` | |
| `weight_kg` | `DecimalField(5,1)` | 建議另建 `BodyMetricLog` 存歷史 |
| `primary_event` | `FK(Event)` | 主項 |
| `secondary_events` | `M2M(Event, related_name="+")` | 副項 |
| `training_days_per_week` | `PositiveSmallIntegerField` | |
| `strength_experience_years` | `DecimalField(3,1)` | |
| `status` | `CharField(choices=AthleteStatus)` | `HEALTHY`/`NIGGLE`/`INJURED` |

#### `Event`（項目字典表）
- `code`（`400M`, `LJ`, `SP`）、`name_zh`、`name_en`、`category`（SPRINT/MID/DISTANCE/JUMP/THROW/COMBINED）、`unit`（TIME/DISTANCE/POINTS）

#### `PersonalBest`
- `athlete` FK、`event` FK、`mark`（`DecimalField`，秒或公尺）、`wind`、`date`、`competition_name`、`is_current`（BooleanField）
- [ ] `unique_together = ("athlete", "event", "date")`
- [ ] `@property mark_display` → 依 `event.unit` 格式化為 `51.20` / `1:52.34` / `6.42m`

#### `BodyMetricLog`
- `athlete`、`date`、`weight_kg`、`body_fat_pct`、`resting_hr`、`hrv`（可選）

### 待辦
- [ ] Admin 註冊全部 model，`AthleteProfile` 加 `list_filter = ("coach", "status")`
- [ ] View：`athlete_dashboard`（運動員視角）、`coach_dashboard`（教練視角，列出所有 `coach.athletes`）
- [ ] 權限：運動員只能讀寫自己的資料；教練可讀寫旗下運動員

---

## 2. 模組 2 — 日程與訓練計劃（週期化）

### App: `planning`

#### `Competition`（目標賽事）
| 欄位 | 型別 |
|---|---|
| `name` | `CharField` — 全港田徑公開賽 |
| `date` | `DateField` |
| `venue` | `CharField(blank=True)` |
| `level` | `CharField(choices=)` — `SCHOOL`/`REGIONAL`/`NATIONAL`/`INTL` |
| `is_target` | `BooleanField` — 是否為主目標賽 |
| `athletes` | `M2M(AthleteProfile, through="CompetitionEntry")` |

- [ ] `@property days_remaining` → `(self.date - date.today()).days`
- [ ] `@property weeks_remaining` → `days_remaining // 7`

#### `Macrocycle`（備戰大週期）
- `athlete` FK、`target_competition` FK、`start_date`、`end_date`、`total_weeks`
- [ ] `generate_phases()` — 依 16 週預設比例自動建立 4 個 `Phase`

#### `Phase`（分期）
| 欄位 | 值 |
|---|---|
| `phase_type` | `GENERAL_PREP` / `SPECIFIC_PREP` / `PRE_COMP` / `TAPER_COMP` / `TRANSITION` |
| `week_start` / `week_end` | 整數週次 |
| `start_date` / `end_date` | `DateField` |
| `focus` | `TextField` — 訓練重心描述 |
| `target_weekly_load` | `PositiveIntegerField` — 目標週負荷 (AU) |

**預設 16 週分期表（種子資料 fixture）**

| 期別 | 週次 | 日期 | 重心 |
|---|---|---|---|
| 準備期 General Prep | W1–W5 | 08/10 – 09/13 | 有氧基礎、一般力量、技術重建 |
| 專項期 Specific Prep | W6–W11 | 09/14 – 10/25 | 專項速度/耐力、最大力量→爆發力 |
| 賽前期 Pre-Comp | W12–W14 | 10/26 – 11/15 | 強度↑量↓、模擬賽 |
| 比賽期 Taper & Comp | W15–W16 | 11/16 – 11/29 | 減量、神經激活 |
| 恢復期 Transition | W17+ | 11/30 起 | 主動恢復、體檢 |

#### `Microcycle`（週計劃）
- `macrocycle` FK、`phase` FK、`week_number`、`start_date`、`planned_load`、`actual_load`（由 signal 回填）、`notes`

#### `TrainingSession`（單次訓練課 — **系統核心表**）
| 欄位 | 型別 | 說明 |
|---|---|---|
| `athlete` | FK | |
| `microcycle` | FK(null=True) | |
| `date` | `DateField` | |
| `time_slot` | `CharField` — AM/PM | |
| `session_type` | `choices` — `TRACK`/`STRENGTH`/`TECHNIQUE`/`RECOVERY`/`CROSS_TRAINING`/`COMPETITION`/`REST` |
| `title` | `CharField` | 「400m 專項耐力」 |
| `assigned_by` | `FK(CoachProfile, null=True)` | null = 運動員自訂 |
| `planned_duration_min` | `PositiveSmallIntegerField` | |
| `actual_duration_min` | `PositiveSmallIntegerField(null=True)` | |
| `status` | `choices` — `PLANNED`/`COMPLETED`/`PARTIAL`/`SKIPPED` |
| `completion_pct` | `PositiveSmallIntegerField(0-100)` | |
| `session_rpe` | `PositiveSmallIntegerField(1-10)` | 課後整體 RPE |
| `athlete_feedback` | `TextField(blank=True)` | |
| `coach_comment` | `TextField(blank=True)` | |

- [ ] `@property session_load` → `session_rpe * actual_duration_min`（Foster sRPE，單位 AU）
- [ ] `class Meta: ordering = ["-date", "time_slot"]`；`indexes` 加 `("athlete", "date")`
- [ ] `post_save` signal → 重算所屬 `Microcycle.actual_load`

#### `SessionTemplate`（教練可重用的課表模板）
- `coach` FK、`name`、`session_type`、`payload`（`JSONField` 存 drills/sets 結構）
- [ ] `clone_to_session(athlete, date)` method

### 待辦
- [ ] 日曆 View：日/週/月（`FullCalendar.js` 或自寫 HTMX 月曆）
- [ ] 教練批次派發：一次指派同一 template 給多名運動員（`bulk_create`）
- [ ] 運動員「打卡完成」表單（更新 status / completion_pct / session_rpe）

---

## 3. 模組 3 — 田徑專項 & 力量訓練

### App: `training`

### 3A. 田徑專項

#### `TrackSet`（一組跑段，屬於某 session）
| 欄位 | 說明 |
|---|---|
| `session` | FK(TrainingSession, related_name="track_sets") |
| `order` | 排序 |
| `description` | 「6 × 200m」 |
| `distance_m` | `PositiveIntegerField` |
| `reps` | 趟數 |
| `sets` | 組數（預設 1） |
| `target_time_sec` / `actual_time_sec` | `DecimalField(6,2)` |
| `rest_between_reps_sec` / `rest_between_sets_sec` | |
| `intensity_pct` | 相對 PB 的 % |
| `avg_hr` / `max_hr` | `PositiveSmallIntegerField(null=True)` |
| `rpe` | 1–10 |
| `technical_focus` | `TextField` — 起跑角度、擺臂、觸地時間 |
| `surface` | `TRACK`/`GRASS`/`HILL`/`TREADMILL` |
| `spikes_used` | `BooleanField` |

- [ ] `@property total_volume_m` → `distance_m * reps * sets`
- [ ] `@property pace_per_100m`
- [ ] 驗證：`actual_time_sec > 0`

#### `RepSplit`（可選，逐趟分段）
- `track_set` FK、`rep_number`、`time_sec`、`note`

### 3B. 力量訓練

#### `Exercise`（動作字典表）
- `name_zh` / `name_en`、`category`（`SQUAT`/`HINGE`/`PUSH`/`PULL`/`OLYMPIC`/`PLYO`/`CORE`/`UNILATERAL`）、`is_measured_by_1rm`（Bool）、`primary_muscles`、`video_url`、`is_plyometric`

#### `OneRepMax`
- `athlete`、`exercise`、`value_kg`、`test_date`、`is_estimated`（Bool）、`estimation_formula`（`EPLEY`/`BRZYCKI`）
- [ ] Epley：`1RM = w × (1 + reps/30)`
- [ ] Brzycki：`1RM = w × 36 / (37 − reps)`
- [ ] `classmethod latest_for(athlete, exercise)`

#### `StrengthSet`
| 欄位 | 說明 |
|---|---|
| `session` | FK(TrainingSession, related_name="strength_sets") |
| `exercise` | FK(Exercise) |
| `order` / `set_number` | |
| `reps` | |
| `weight_kg` | `DecimalField(6,2)` |
| `target_1rm_pct` | 教練指定強度 % |
| `actual_1rm_pct` | 由當前 1RM 自動計算（`save()` 內填） |
| `tempo` | `CharField` — `3-1-X-0` |
| `rest_sec` | |
| `rir` | Reps In Reserve（0–5） |
| `rpe` | 1–10 |
| `bar_velocity_ms` | `DecimalField(null=True)` — 有測速器才填 |
| `is_failure` | `BooleanField` |

- [ ] `@property tonnage` → `reps * weight_kg`
- [ ] `@property estimated_1rm` → Epley
- [ ] Session 層 `@property total_tonnage` → `sum(tonnage)`

#### `NeuromuscularTest`（神經肌肉疲勞監控）
- `athlete`、`date`、`test_type`（`CMJ`/`SJ`/`BROAD_JUMP`/`GRIP`）、`value`、`unit`
- [ ] 與 7 日基線比較，跌幅 >10% → 疲勞警示

### 待辦
- [ ] Inline formset：一個 session 頁面可同時新增多個 TrackSet / StrengthSet
- [ ] `Exercise` 與 `Event` 用 fixture 種子資料（`python manage.py loaddata`）
- [ ] 快速輸入 UI：常用動作置頂、上次重量自動帶入

---

## 4. 模組 4 — 數據分析與評估

### App: `analytics`

#### `DailyLoad`（每日彙總快取表，避免每次查詢即時計算）
- `athlete`、`date`、`total_load_au`、`track_volume_m`、`strength_tonnage_kg`、`session_count`、`avg_rpe`
- [ ] `unique_together = ("athlete", "date")`
- [ ] 由 `TrainingSession` 的 signal 或每晚 Celery/管理指令重算

#### `WeeklySummary`
- `athlete`、`week_start`、`total_load`、`monotony`、`strain`、`acwr`、`risk_flag`

### 核心計算（放在 `analytics/services.py`，**不要寫在 view 裡**）

```python
# 1. Session Load (Foster sRPE)
session_load = session_rpe * duration_min                    # 單位 AU

# 2. Acute Load  = 最近 7 天 load 總和
# 3. Chronic Load = 最近 28 天 load 總和 / 4
# 4. ACWR = acute / chronic
```

| ACWR 區間 | 判定 | 系統動作 |
|---|---|---|
| < 0.80 | 訓練不足 (Undertraining) | 🔵 提示可增量 |
| 0.80 – 1.30 | **甜蜜點 Sweet Spot** | 🟢 維持 |
| 1.30 – 1.50 | 負荷偏高 | 🟡 注意 |
| > 1.50 | **高受傷風險** | 🔴 強制警示 + 建議減量 |

```python
# 5. Monotony = 週平均日負荷 / 該週日負荷標準差      （>2.0 為警訊）
# 6. Strain   = 週總負荷 × Monotony
# 7. 週增幅   = (本週 − 上週) / 上週                （建議 ≤ 10%）
```

- [ ] `calculate_acwr(athlete, on_date)` — 建議用 EWMA 版本更準確
- [ ] `weekly_load_progression(athlete, weeks=12)`
- [ ] `performance_trend(athlete, event)` — 專項成績趨勢（含線性回歸斜率）
- [ ] `strength_trend(athlete, exercise)` — 1RM / tonnage 成長曲線
- [ ] `readiness_score(athlete, date)` — 綜合睡眠 + RPE + 疼痛 + CMJ，輸出 0–100

### 待辦
- [ ] 圖表：Chart.js（AJAX 回傳 JSON）
  - [ ] 週負荷柱狀圖 + ACWR 折線（雙 Y 軸）
  - [ ] 專項成績散點 + 趨勢線
  - [ ] 1RM 成長曲線
  - [ ] 訓練量分佈圓餅（Track / Strength / Recovery）
- [ ] 教練團隊儀表板：所有運動員 ACWR 一覽（紅黃綠燈）
- [ ] 匯出 CSV / PDF 報告

---

## 5. 模組 5 — 運動營養與恢復

### App: `nutrition`

#### `NutritionTarget`（每日目標，隨訓練日類型變動）
| 欄位 | 說明 |
|---|---|
| `athlete` | FK |
| `date` | |
| `day_type` | `HARD`/`MODERATE`/`EASY`/`REST`/`COMPETITION` |
| `bmr_kcal` / `tdee_kcal` | 計算結果 |
| `target_kcal` | 依增重/維持/減脂調整 |
| `carb_g` / `protein_g` / `fat_g` | |
| `water_ml` | |

**計算公式（放 `nutrition/services.py`）**

```python
# Mifflin-St Jeor BMR
男: BMR = 10*kg + 6.25*cm − 5*age + 5
女: BMR = 10*kg + 6.25*cm − 5*age − 161

TDEE = BMR × 活動係數 + 訓練消耗
```

| 訓練日類型 | 活動係數 | 碳水 (g/kg) | 蛋白 (g/kg) | 脂肪 |
|---|---|---|---|---|
| 休息日 REST | 1.2 | 3–4 | 1.6–1.8 | 25–30% kcal |
| 輕度 EASY | 1.375 | 4–5 | 1.6–2.0 | 25–30% |
| 中度 MODERATE | 1.55 | 5–7 | 1.8–2.0 | 20–25% |
| 高強度 HARD | 1.725 | 7–10 | 1.8–2.2 | 20–25% |
| 比賽日 COMPETITION | 1.725 | 8–10 | 1.8–2.0 | 20% |

- 水份：`35ml × kg + 訓練每小時 500–1000ml`

#### `MealLog`
- `athlete`、`date`、`meal_type`（`BREAKFAST`/`LUNCH`/`DINNER`/`PRE_TRAINING`/`POST_TRAINING`/`SNACK`）、`description`、`kcal`、`carb_g`、`protein_g`、`fat_g`、`photo`

#### `SupplementLog`
- `athlete`、`date`、`name`、`dose`、`timing`、`purpose`
- 常見：Creatine 5g、Caffeine 3–6mg/kg、Whey、Vit D、Iron、Beta-alanine

#### `RecoveryLog`
| 欄位 | 說明 |
|---|---|
| `athlete` / `date` | |
| `sleep_hours` | `DecimalField(3,1)` |
| `sleep_quality` | 1–5 |
| `bedtime` / `wake_time` | `TimeField` |
| `water_intake_ml` | |
| `soreness_level` | 1–10 全身肌肉痠痛 |
| `stress_level` | 1–5 |
| `mood` | 1–5 |
| `resting_hr` | 晨脈 |
| `methods` | `M2M(RecoveryMethod)` |

#### `RecoveryMethod`
- `name`（冰浴 / 泡沫軸放鬆 / 動態伸展 / 按摩槍 / 桑拿 / 壓縮褲 / 主動恢復慢跑）、`duration_min`、`category`

### 待辦
- [ ] 每日 `NutritionTarget` 自動生成（依當日 `TrainingSession.session_type` 推斷 `day_type`）
- [ ] 晨間問卷表單（睡眠 + 痠痛 + 心情 + 晨脈）→ 餵給 `readiness_score`
- [ ] 每週營養達成率報告（實際 vs 目標）

---

## 6. 模組 6 — 傷患與防護管理

### App: `injury`

#### `Injury`
| 欄位 | 說明 |
|---|---|
| `athlete` | FK |
| `body_part` | `choices` — 膕繩肌/股四頭/小腿/阿基里斯腱/足底/膝/踝/髖/下背/肩 |
| `side` | `LEFT`/`RIGHT`/`BILATERAL`/`NA` |
| `injury_type` | 拉傷/扭傷/肌腱炎/骨膜炎/應力性骨折/挫傷 |
| `mechanism` | `TextField` — 受傷機制（加速中 / 落地 / 過度使用） |
| `onset_date` | |
| `severity` | 1–4（依缺席天數分級） |
| `status` | `ACUTE`/`REHAB`/`RETURN_TO_RUN`/`RESOLVED` |
| `expected_return_date` | |
| `diagnosis` | `TextField` |
| `practitioner` | 物理治療師/醫生 |

#### `PainLog`（每日追蹤）
- `injury` FK、`date`、`pain_at_rest`（1–10）、`pain_during_activity`（1–10）、`swelling`（Bool）、`rom_limited`（Bool）、`note`

#### `RehabProtocol` / `RehabExercise`
- `injury` FK、`phase`（`PROTECTION`/`LOADING`/`STRENGTH`/`RTP`）、`exercise_name`、`sets`、`reps`、`frequency_per_week`、`progression_criteria`

#### `ExerciseModification`（替代動作對照表 — **教練核心工具**）
| 欄位 | 說明 |
|---|---|
| `original_exercise` | FK(Exercise) |
| `substitute_exercise` | FK(Exercise) |
| `contraindicated_body_parts` | `M2M` 或 `JSONField` |
| `max_pain_level` | 疼痛 ≤ N 時可執行 |
| `rationale` | `TextField` |

**替代方案範例（fixture 種子資料）**

| 傷患部位 | 原動作 | 替代動作 | 原因 |
|---|---|---|---|
| 膕繩肌拉傷 | 硬舉 / 衝刺 | 反向雪橇推、單車衝刺、等長橋式 | 避免離心高張力 |
| 阿基里斯腱 | 跳箱 / 彈跳 | 坐姿提踵（等長）、水中跑 | 降低跟腱負荷 |
| 下背痛 | 背蹲舉 | 高腳杯蹲、腿推、後腳抬高蹲 | 降低脊柱軸向壓力 |
| 踝扭傷 | 跑步 | 上肢循環、划船機、平衡板訓練 | 卸除承重 |
| 足底筋膜炎 | 場地跑 | 水中跑、橢圓機、足底離心訓練 | 減少衝擊 |
| 膝髕腱炎 | 深蹲 / 落地 | 等長靠牆蹲、Spanish Squat | 等長止痛 + 建腱 |

### 邏輯規則
- [ ] 若 `PainLog.pain_during_activity >= 6` → 系統自動 **封鎖** 該日高強度 session，改派替代課表
- [ ] 若 `AthleteProfile.status == INJURED` → 教練派發計劃時自動套用 `ExerciseModification` 過濾
- [ ] 傷患期間仍計算負荷，但標記 `is_modified = True`
- [ ] Return-to-Play 檢核表：無痛全速跑 + 患側/健側力量差 <10% + CMJ 恢復基線 90%

---

## 7. 跨模組功能與待辦

### 通知與自動化
- [ ] Celery + Redis（或 `django-q`）排程任務
  - [ ] 每日 00:30 重算 `DailyLoad` / `WeeklySummary` / ACWR
  - [ ] 每早 07:00 推送晨間問卷提醒
  - [ ] ACWR > 1.5 時 email/推播通知教練
- [ ] `Notification` model：`user`、`type`、`message`、`is_read`、`link`

### API（DRF）
| Endpoint | 方法 | 說明 |
|---|---|---|
| `/api/athletes/` | GET/POST | 教練限定 |
| `/api/athletes/<id>/dashboard/` | GET | 綜合儀表板 |
| `/api/sessions/` | GET/POST | `?date_from=&date_to=&status=` |
| `/api/sessions/<id>/complete/` | POST | 打卡完成 |
| `/api/analytics/acwr/<athlete_id>/` | GET | |
| `/api/analytics/trend/` | GET | `?event=400M` |
| `/api/nutrition/targets/<date>/` | GET | 自動計算回傳 |
| `/api/injuries/<id>/alternatives/` | GET | 回傳替代動作清單 |

### 權限矩陣
| 角色 | 自己資料 | 旗下運動員 | 其他運動員 | 派發計劃 | 分析報告 |
|---|---|---|---|---|---|
| Athlete | RW | — | — | 自訂只限自己 | 只看自己 |
| Coach | RW | RW | R（同隊，可設定） | ✅ | 全隊 |
| Admin | RW | RW | RW | ✅ | 全系統 |

### UI 頁面清單
- [ ] 登入 / 註冊 / 角色選擇引導頁（onboarding wizard）
- [ ] 運動員儀表板：今日課表 + 倒數 + ACWR 燈號 + 快速打卡
- [ ] 教練儀表板：運動員卡片牆（狀態燈號）+ 今日全隊課表
- [ ] 訓練日曆（月/週切換）
- [ ] Session 詳情 / 記錄頁（Track + Strength 分頁）
- [ ] 分析報告頁（4 張圖表）
- [ ] 營養與恢復頁（晨間問卷 + 每日目標）
- [ ] 傷患管理頁（傷患卡 + 疼痛趨勢 + 替代動作建議）
- [ ] Profile / PB 管理頁

---

## 8. 建置順序（建議 Sprint）

| Sprint | 內容 | 產出 |
|---|---|---|
| **S1** | 專案骨架 + `accounts`（User/Profile/Event/PB）+ Admin | 可登入、可建檔 |
| **S2** | `planning`（Competition/Macrocycle/Phase/TrainingSession）+ 日曆 | 可派發與查看課表 |
| **S3** | `training`（TrackSet/StrengthSet/Exercise/1RM）+ 記錄表單 | 可完整記錄訓練 |
| **S4** | `analytics`（services + DailyLoad + 圖表） | ACWR 與趨勢圖 |
| **S5** | `nutrition`（TDEE + 恢復日誌 + 晨間問卷） | 營養建議自動生成 |
| **S6** | `injury`（傷患日誌 + 替代動作引擎） | 傷患自動調整課表 |
| **S7** | DRF API + 權限 + 通知 + 部署 | 上線 |

---

## 9. 種子資料 (Fixtures) 清單

- [ ] `events.json` — 田徑項目（100m…10000m、跨欄、跳部、投擲、全能）
- [ ] `exercises.json` — 力量動作 60+（含分類、是否測 1RM）
- [ ] `recovery_methods.json` — 恢復手段
- [ ] `exercise_modifications.json` — 替代動作對照
- [ ] `phase_template_16w.json` — 16 週分期模板

---

## 10. 關鍵技術提醒

- ⚠️ `AUTH_USER_MODEL` 必須在第一次 `migrate` 前設定
- ⚠️ 所有計算邏輯放 `services.py`，model 只放 property，view 只做編排
- ⚠️ 時間欄位一律用秒 (`DecimalField(6,2)`) 儲存，顯示層才格式化為 `1:52.34`
- ⚠️ `TrainingSession` 加複合索引 `("athlete", "date")`，分析查詢極頻繁
- ⚠️ ACWR 需至少 28 天資料才有意義 → 資料不足時回傳 `None` 並顯示「資料累積中」
- ⚠️ 體重會變 → 存 `BodyMetricLog` 歷史，TDEE 用當日最近一筆

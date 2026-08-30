# 部署到 Render（www.hohosports.com）

> ⚠️ **這會取代現有的單車零件 OEM 網站。**
> 網域一旦指向新服務，舊 OEM 網站在這個網址就不再對外提供。
> 動手前請先做兩件事：
> 1. 到 Render 舊服務把 OEM 網站的程式碼與資料備份下來（或確認 git repo 還在）。
> 2. 舊服務**先不要刪除**，只把自訂網域移除即可，萬一要回滾隨時可以掛回去。
>
> 如果只是想先試跑，可以改用子網域 `atm.hohosports.com`，OEM 站完全不受影響，
> 確認滿意後再把 `www` 換過來。

---

## 步驟 1／推上 GitHub

專案已完成 git 初始化與第一次 commit，只差一個遠端。

```bash
cd "C:\Users\boyce\Desktop\Lai Chun Ho\DBS\Athletics Managment System"

# 到 https://github.com/new 建一個 private repo，例如 atm-athletics（不要勾 README）
git remote add origin https://github.com/<你的帳號>/atm-athletics.git
git push -u origin main
```

---

## 步驟 2／在 Render 建立服務

Render Dashboard → **New** → **Blueprint** → 選剛才的 repo。

`render.yaml` 會自動建立：

| 資源 | 名稱 | 說明 |
|---|---|---|
| Web Service | `atm-athletics` | gunicorn 跑 Django |
| PostgreSQL | `atm-db` | `DATABASE_URL` 自動注入 |

環境變數 `DJANGO_SECRET_KEY` 由 Render 自動產生，`DJANGO_DEBUG=0`、
`DJANGO_ALLOWED_HOSTS=www.hohosports.com,hohosports.com` 已寫在藍圖裡。

> **方案選擇**：`render.yaml` 寫的是 `starter`。Free 方案 15 分鐘無流量就會休眠
> （下次開啟要等 30~60 秒），資料庫 free 方案 30 天後過期會**刪除資料**。
> 正式掛自訂網域請至少用 starter。

---

## 步驟 3／建立你自己的登入帳號（**必做**）

migrate 與 loaddata 只會載入項目、動作庫這類基礎資料，**不會建立任何使用者**。
沒有這一步，登入頁會正常顯示但任何帳密都登不進去（回「帳號或密碼錯誤」）。

### 方法 A：設環境變數後重新部署（推薦）

Render → 服務 → **Environment** → Add Environment Variable：

| Key | Value |
|---|---|
| `ADMIN_USERNAME` | `boyce` |
| `ADMIN_EMAIL` | `laichunho25@gmail.com` |
| `ADMIN_PASSWORD` | 至少 12 字元的強密碼 |

存檔會自動觸發重新部署，`build.sh` 最後一行會執行：

```bash
python manage.py create_admin --skip-if-unset
```

指令是冪等的（帳號存在就更新密碼），沒設變數則安靜跳過、不會弄壞部署。
建好之後可以把 `ADMIN_PASSWORD` 從 Environment 刪掉。

### 方法 B：Render Shell 手動執行

服務頁 → **Shell** → `python manage.py create_admin`（同樣要先有上面三個變數）。

### 建好之後

用這個帳號登入 `https://www.hohosports.com/accounts/login/`，
再到 `/admin/` 幫教練和運動員開帳號（Users → Add，記得設好 Role）。

> 🔒 **正式站絕對不要跑 `seed_demo`**——它會建立 `atm12345` 這種弱密碼的示範帳號。
> 若不小心跑了，用 `python manage.py purge_demo` 清掉
>（此指令會擋住「刪光所有管理員」的情況）。
> 登入頁的示範帳密提示只在 `DEBUG=1` 顯示，正式站不會外洩。

---

## 步驟 4／切換網域（實測現況版）

目前 `hohosports.com` 的實際狀態（2026-08-30 實測）：

| 項目 | 現況 |
|---|---|
| DNS 供應商 | GoDaddy（`ns29/ns30.domaincontrol.com`） |
| `www.hohosports.com` | CNAME → `hoho-sports-trading-company.onrender.com`（舊 OEM 服務） |
| `hohosports.com`（根網域） | A → `216.24.57.1`（Render 的共用 IP） |
| 舊站行為 | `www` → 301 → `https://hohosports.com/zh-hant/` |
| 新 ATM 服務 | `https://atm-athletics.onrender.com/` 已上線（登入頁 HTTP 200） |
| 兩者區域 | 同為 Render GCP `us-west1` |

**關鍵**：網域本來就已經指向 Render，所以根網域的 A 記錄 `216.24.57.1`
**完全不用改**，只要在 Render 後台把自訂網域從舊服務搬到新服務，
再把 GoDaddy 的 `www` CNAME 改成新服務主機名即可。

### 順序（照做，可隨時回滾）

1. **先確認新站可用**：開 `https://atm-athletics.onrender.com/accounts/login/`，
   能登入、圖表正常再往下做。
2. **舊服務移除網域**：Render → `hoho-sports-trading-company` → Settings →
   Custom Domains → 移除 `www.hohosports.com` 與 `hohosports.com`。
   （同一網域不能同時掛在兩個服務上；**不要刪除舊服務本身**，保留以便回滾。）
3. **新服務加入網域**：Render → `atm-athletics` → Settings → Custom Domains →
   Add `www.hohosports.com`，再 Add `hohosports.com`。
4. **改 GoDaddy DNS**（My Products → DNS → Manage Zones → hohosports.com）：

   | 類型 | 名稱 | 舊值 | 新值 |
   |---|---|---|---|
   | CNAME | `www` | `hoho-sports-trading-company.onrender.com` | `atm-athletics.onrender.com` |
   | A | `@` | `216.24.57.1` | **不用改** |

   若 Render 顯示不同的目標主機名，以 Render 畫面上的為準。
5. **等憑證**：Render 會自動簽發 Let's Encrypt（通常數分鐘，DNS TTL 長則久一點），
   狀態變成 Certificate Issued 才算完成。
6. **確認環境變數**：新服務 Environment 內
   `DJANGO_ALLOWED_HOSTS=www.hohosports.com,hohosports.com`、`DJANGO_DEBUG=0`。
   缺了會回 400 Bad Request。

### 驗證

```bash
nslookup www.hohosports.com                            # 應指向 atm-athletics
curl -I https://www.hohosports.com/accounts/login/     # 應回 200
curl -I http://www.hohosports.com/                     # 應回 301 → https
```

### 回滾

把步驟 2、3、4 反過來做即可：新服務移除網域 → 舊服務加回 → `www` CNAME 改回
`hoho-sports-trading-company.onrender.com`。舊服務只要沒刪除，資料與內容都還在。

> **注意 HSTS**：本站正式環境開了 `SECURE_HSTS_SECONDS = 30 天` 且含 `includeSubDomains`。
> 瀏覽器造訪過 `www.hohosports.com` 之後，30 天內都會強制走 https。
> 這在正式上線是好事，但代表切換後若要暫時退回 http 測試會被瀏覽器擋下。

---

## 已完成的正式環境設定

| 項目 | 做法 |
|---|---|
| `SECRET_KEY` | 由 `DJANGO_SECRET_KEY` 環境變數提供，Render 自動產生 |
| `DEBUG` | `DJANGO_DEBUG=0`，錯誤頁不外洩程式碼 |
| `ALLOWED_HOSTS` | 環境變數 + Render 內部網址；未授權 host 回 400 |
| `CSRF_TRUSTED_ORIGINS` | 由網域自動推導成 `https://...` |
| 資料庫 | `dj-database-url` 讀 `DATABASE_URL`，本機 SQLite ↔ 線上 PostgreSQL 自動切換 |
| 靜態檔 | WhiteNoise 壓縮 + 檔名雜湊，`collectstatic` 在 build 階段完成 |
| HTTPS | `SECURE_SSL_REDIRECT` + `SECURE_PROXY_SSL_HEADER`（Render 前端做 TLS 終結） |
| HSTS | 30 天，含子網域（確認穩定後可調長） |
| Cookie | Session 與 CSRF cookie 皆 `Secure` |
| 點擊劫持 | `X_FRAME_OPTIONS = DENY` |

`python manage.py check --deploy` 除了本機的預設金鑰警告外沒有其他問題。

---

## 已知限制

- **上傳檔案（頭像 / 餐點照片）**：Render 的磁碟是暫時性的，重新部署會清空。
  要保留請加 Persistent Disk 掛在 `/var/data`，並設 `DJANGO_MEDIA_ROOT=/var/data/media`；
  或改用 S3 / Cloudflare R2。目前系統沒有這兩個功能的頁面，暫時不影響。
- **每日負荷重算**：目前靠 signal 即時更新。要排程請加 Render Cron Job：
  `python manage.py rebuild_analytics --days 90`（建議每日 00:30）。
- **時區**：已設 `Asia/Hong_Kong`。

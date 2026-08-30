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

## 步驟 3／建立你自己的管理員帳號

部署完成後，Render 服務頁 → **Shell**：

```bash
python manage.py create_admin
```

需要先在 **Environment** 加這三個變數（建完可以刪掉 `ADMIN_PASSWORD`）：

```
ADMIN_USERNAME=boyce
ADMIN_EMAIL=laichunho25@gmail.com
ADMIN_PASSWORD=<至少 12 字元的強密碼>
```

> 🔒 **正式站絕對不要跑 `seed_demo`**——它會建立 `atm12345` 這種弱密碼的示範帳號。
> 若不小心跑了，用 `python manage.py purge_demo` 清掉
>（此指令會擋住「刪光所有管理員」的情況）。

---

## 步驟 4／切換網域

1. 舊 OEM 服務 → Settings → Custom Domains → **移除** `www.hohosports.com`
   （先移除，同一個網域不能同時掛在兩個服務上）
2. 新服務 `atm-athletics` → Settings → Custom Domains → **Add** `www.hohosports.com`
3. Render 會顯示要設定的 DNS 記錄，到你的網域註冊商設定：

   | 類型 | 名稱 | 值 |
   |---|---|---|
   | CNAME | `www` | `atm-athletics.onrender.com` |
   | A（根網域，選用） | `@` | Render 提供的 IP |

4. 等 DNS 生效（幾分鐘到數小時），Render 會自動簽發 Let's Encrypt 憑證

驗證：

```bash
nslookup www.hohosports.com
curl -I https://www.hohosports.com/accounts/login/    # 應回 200
```

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

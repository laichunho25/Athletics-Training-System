#!/usr/bin/env bash
# Render build script — 每次部署時執行
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

# 收集靜態檔（atm.css / chart.min.js / admin）
python manage.py collectstatic --no-input

# 套用資料庫遷移
python manage.py migrate --no-input

# 載入基礎資料（項目 / 動作庫 / 恢復手段 / 替代動作對照表）
# loaddata 是冪等的：相同 pk 會被覆寫，不會重複新增
python manage.py loaddata events exercises recovery_methods exercise_modifications

# 有設定 ADMIN_USERNAME / ADMIN_PASSWORD 時自動建立管理員（可重複執行）
python manage.py create_admin --skip-if-unset

# 部署後健檢：資料庫一個帳號都沒有 = 沒人登入得了，要在 build log 大聲提醒
python manage.py check_accounts

# 有教練帳號時建立短跑課表模板（可重複執行；沒有教練就安靜跳過）
python manage.py seed_templates --skip-if-empty

# 建立公開報名項目（已存在的項目不會被覆寫，教練在後台改過的內容會保留）
python manage.py seed_projects

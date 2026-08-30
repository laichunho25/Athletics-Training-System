@echo off
REM ===== ATM 田徑訓練管理系統 啟動器 =====
REM 固定使用 8200 埠，避免與其他 Django 專案（8000 / 8001）衝突。
cd /d "%~dp0"

echo.
echo  ATM - Athlete Training Management System
echo  ----------------------------------------
echo  網址：http://127.0.0.1:8200/
echo  登入：http://127.0.0.1:8200/accounts/login/
echo.
echo  示範帳號： admin/admin12345 ^| coach_chan/atm12345 ^| athlete_lai/atm12345
echo  按 Ctrl+C 可停止伺服器
echo.

start "" http://127.0.0.1:8200/accounts/login/
python manage.py runserver 127.0.0.1:8200
pause

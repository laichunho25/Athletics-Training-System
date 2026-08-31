@echo off
REM ===== ATM one-command deploy =====
REM   ship                     -> commit with a default message and go live
REM   ship added athlete list  -> use your own commit message
REM   ship --dry-run           -> rehearse only, nothing is committed or pushed
REM All the real work (and the Chinese output) lives in ship.py.
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM Find a Python that actually has Django installed (PATH may point elsewhere).
set "PY="
for %%C in ("py -3.13" "py" "python") do (
  if not defined PY (
    %%~C -c "import django" >nul 2>&1 && set "PY=%%~C"
  )
)
if not defined PY (
  echo [X] No Python with Django found. Run: pip install -r requirements.txt
  exit /b 1
)

!PY! ship.py %*
set "CODE=!errorlevel!"
if not "!CODE!"=="0" pause
exit /b !CODE!

@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Hay chay CAI_DAT_WINDOWS.bat truoc.
  pause
  exit /b 1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765 " ^| findstr "LISTENING"') do (
  taskkill /F /T /PID %%a >nul 2>&1
)
".venv\Scripts\python.exe" app.py
pause

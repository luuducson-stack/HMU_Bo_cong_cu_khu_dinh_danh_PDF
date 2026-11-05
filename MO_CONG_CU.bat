@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing_venv
".venv\Scripts\python.exe" -c "import pathlib, sys; bad=[p.name for p in sorted(pathlib.Path('.').glob('*.py')) if b'\x00' in p.read_bytes() or p.read_bytes().startswith(b'\xff')]; sys.exit(print('[HMU LOI] Phat hien file ma nguon bi hong (0xFF/null bytes) do loi sao chep USB:', ', '.join(bad)) or 1 if bad else 0)"
if errorlevel 1 goto app_fail
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto app_fail
goto end
:missing_venv
echo [HMU LOI] Chua co moi truong ao .venv. Hay chay CAI_DAT_WINDOWS.bat truoc.
if not exist "HMU_JOBS" mkdir "HMU_JOBS"
powershell -NoProfile -Command "$now=[DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'); $err=@{session_started_at=$now;total_errors=1;errors=@(@{id='err_missing_venv';timestamp=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();iso_time=$now;category='FILE_ERROR';stage='STARTUP';error_type='EnvironmentError';message='Chua co moi truong ao .venv. Hay chay CAI_DAT_WINDOWS.bat truoc.'})}; $err | ConvertTo-Json -Depth 5 | Out-File -FilePath 'HMU_JOBS\error_report.json' -Encoding utf8" 2>nul
echo [HMU BAO LOI] Chi tiet loi ghi tai: "%~dp0HMU_JOBS\error_report.json"
pause
exit /b 1
:app_fail
echo.
echo [HMU LOI] Ung dung dung voi ma loi %errorlevel%.
if exist "HMU_JOBS\error_report.json" echo [HMU BAO LOI] Kiem tra chi tiet loi tai: "%~dp0HMU_JOBS\error_report.json"
pause
exit /b 1
:end
pause
exit /b 0

@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [HMU LỖI] Chưa có môi trường ảo .venv. Hãy chạy CAI_DAT_WINDOWS.bat trước.
  if not exist "HMU_JOBS" mkdir "HMU_JOBS"
  powershell -NoProfile -Command "$now=[DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'); $err=@{session_started_at=$now;total_errors=1;errors=@(@{id='err_missing_venv';timestamp=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();iso_time=$now;category='FILE_ERROR';stage='STARTUP';error_type='EnvironmentError';message='Chưa có môi trường ảo .venv. Hãy chạy CAI_DAT_WINDOWS.bat trước.'})}; $err | ConvertTo-Json -Depth 5 | Out-File -FilePath 'HMU_JOBS\error_report.json' -Encoding utf8" 2>nul
  echo [HMU BÁO LỖI] Chi tiết lỗi ghi tại: %~dp0HMU_JOBS\error_report.json
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 (
  echo.
  echo [HMU LỖI] Ứng dụng thoát với mã lỗi %errorlevel%.
  if exist "HMU_JOBS\error_report.json" (
    echo [HMU BÁO LỖI] Kiểm tra chi tiết lỗi tại: %~dp0HMU_JOBS\error_report.json
  )
)
pause

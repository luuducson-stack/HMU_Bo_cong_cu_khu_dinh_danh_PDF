@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -c "import pathlib, sys; bad=[p.name for p in sorted(pathlib.Path('.').glob('*.py')) if b'\x00' in p.read_bytes() or p.read_bytes().startswith(b'\xff')]; sys.exit(print('[HMU LOI] Phat hien file ma nguon bi hong (0xFF/null bytes) do loi sao chep USB:', ', '.join(bad)) or 1 if bad else 0)"
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -c "import app, engine, hmu_recognizers, ocr_helper, output_qc, batch, batch_runtime, batch_worker, delivery, error_pipeline, updater"
if errorlevel 1 goto fail
echo Cai dat va kiem thu hoan tat. Chay MO_CONG_CU.bat
pause
exit /b 0
:fail
echo Chua hoan tat. Xem thong bao loi o tren.
pause
exit /b 1

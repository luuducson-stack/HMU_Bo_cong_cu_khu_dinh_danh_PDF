@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" test_hmu_recognizers.py
if errorlevel 1 goto fail
".venv\Scripts\python.exe" test_workflow.py
if errorlevel 1 goto fail
echo Cai dat va kiem thu hoan tat. Chay MO_CONG_CU.bat
pause
exit /b 0
:fail
echo Chua hoan tat. Xem thong bao loi o tren.
pause
exit /b 1

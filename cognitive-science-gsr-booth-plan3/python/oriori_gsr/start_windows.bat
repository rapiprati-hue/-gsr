@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
where py >nul 2>nul
if %errorlevel% equ 0 (set "PY=py -3") else (set "PY=python")
%PY% -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11 or later is required'"
if errorlevel 1 goto python_error
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
if errorlevel 1 goto setup_error
if exist ".venv\.oriori_ready" goto run_app
echo [oriori_gsr] Installing dependencies. Internet is needed on first launch.
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto setup_error
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto setup_error
echo 1.0>.venv\.oriori_ready
:run_app
echo [oriori_gsr] Starting your booth. Keep this window open.
.venv\Scripts\python.exe app.py
pause
exit /b
:python_error
echo Install Python 3.11 or newer from python.org and select Add Python to PATH.
echo Close this window and run start_windows.bat again.
pause
exit /b 1
:setup_error
echo Setup failed. Check your internet connection and read README.md.
echo No error was hidden. Please keep the message above for troubleshooting.
pause
exit /b 1

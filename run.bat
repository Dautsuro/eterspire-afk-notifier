@echo off
rem Starts Eterspire AFK Notifier. The first start installs what it needs into a .venv folder.
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" goto run

echo First start: setting things up, this only happens once and needs internet...
py -3 -m venv .venv 2>nul || python -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Python 3.10 or newer is required: https://www.python.org/downloads/
    echo Tick "Add python.exe to PATH" during the installation, then run this file again.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo Installing the requirements failed, see the messages above.
    rmdir /s /q .venv
    pause
    exit /b 1
)

:run
start "" ".venv\Scripts\pythonw.exe" run.py

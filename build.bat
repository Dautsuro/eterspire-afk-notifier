@echo off
rem Builds dist\EterspireNotifier.exe, a single file players can run without installing Python.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (py -3 -m venv .venv 2>nul || python -m venv .venv)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller || exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name EterspireNotifier ^
    --add-data "eterspire_notifier\templates;eterspire_notifier\templates" ^
    --add-data "eterspire_notifier\sounds;eterspire_notifier\sounds" ^
    --add-data "eterspire_notifier\assets;eterspire_notifier\assets" ^
    --icon eterspire_notifier\assets\icon.ico --hidden-import pystray._win32 ^
    run.py || exit /b 1
echo.
echo Done: dist\EterspireNotifier.exe

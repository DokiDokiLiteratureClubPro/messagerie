@echo off
REM Crée Messagerie.exe (Windows) dans le dossier "dist"
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --onefile --windowed --name Messagerie app.py
echo.
echo Termine ! L'executable est dans : %~dp0dist\Messagerie.exe
pause

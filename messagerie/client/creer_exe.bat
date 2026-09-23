@echo off
REM Construit Messagerie.exe localement (normalement GitHub le fait tout seul)
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --onefile --windowed --name Messagerie --collect-all customtkinter app.py
pause

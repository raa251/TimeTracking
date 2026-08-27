@echo off
REM Baut dist\TimeTracker.exe  (Parameter --onedir fuer die Ordner-Variante)
setlocal
cd /d "%~dp0"
python -m pip install --quiet --upgrade pyinstaller
python build.py %*
echo.
pause

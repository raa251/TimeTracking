@echo off
REM Startet den TimeTracker-Tray-Client ohne Konsolenfenster.
setlocal
set HERE=%~dp0
start "" pythonw "%HERE%run.pyw"
endlocal

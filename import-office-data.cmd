@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0import-office-data.ps1" %*
if errorlevel 1 (
    echo Import failed. Read the error above.
    pause
    exit /b 1
)
pause

@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-local.ps1"
if errorlevel 1 (
    echo Shutdown needs attention. Read the error above.
    pause
    exit /b 1
)
pause

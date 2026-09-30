@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local.ps1" -OpenBrowser
if errorlevel 1 (
    echo Startup failed. Read the error above.
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local.ps1" -Lan
if errorlevel 1 (
    echo Phone service startup failed. Read the error above.
    pause
    exit /b 1
)
echo Computer and phone services are running. You can close this window.
pause

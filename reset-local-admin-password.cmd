@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0reset-local-admin-password.ps1"
if errorlevel 1 (
    echo Password reset failed. Read the error above.
    pause
    exit /b 1
)
pause

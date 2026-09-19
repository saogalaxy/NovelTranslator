@echo off
setlocal
cd /d "%~dp0"
title Novel Translator — Easy Installer
echo.
echo Novel Translator Easy Installer
echo Checking Python, files, and packages...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\easy_install.ps1"
if errorlevel 1 (
    echo.
    echo Setup did not finish. Fix the message above, then double-click this file again.
    pause
    exit /b 1
)

if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo pythonw.exe is missing after setup.
    pause
    exit /b 1
)

echo READY TO GO: YES
echo Starting Novel Translator...
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"
endlocal
exit /b 0

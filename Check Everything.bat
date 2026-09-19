@echo off
setlocal
cd /d "%~dp0"
title Novel Translator — Ready Check
echo.
echo Checking that everything is ready to go...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\easy_install.ps1"
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

echo.
echo Everything is ready. You can close this window or start the app with
echo Start Novel Translator.bat
echo.
pause
endlocal

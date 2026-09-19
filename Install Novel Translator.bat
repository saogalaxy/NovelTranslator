@echo off
setlocal
cd /d "%~dp0"
title Novel Translator - Easy Install
echo.
echo Novel Translator Easy Installer
echo Checks files, builds the exe, installs, then auto-launches.
echo.
echo STORAGE (read this):
echo   Installs to your Windows user profile drive (usually C:), not a drive picker.
echo   Location: %%LocalAppData%%\NovelTranslator\
echo   Typical size: ~120-200 MB app on PC.
echo   Books stay in Documents\NovelTranslator (kept on uninstall).
echo   Uninstall: Settings - Apps - Novel Translator
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\desktop_install.ps1"
if errorlevel 1 (
    echo.
    echo Setup did not finish. Fix the message above, then double-click this file again.
    pause
    exit /b 1
)

echo.
echo READY TO GO: YES
pause
endlocal
exit /b 0

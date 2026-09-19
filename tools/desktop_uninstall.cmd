@echo off
setlocal
title Uninstall Novel Translator
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
endlocal
exit /b %ERRORLEVEL%

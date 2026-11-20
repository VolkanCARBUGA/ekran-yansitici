@echo off
rem Ekran Yansitici - Windows otomatik baslatma kurulumu (kaldirmak icin: OTOMATIK_BASLATMA_KUR.bat --kaldir)
set "ARGS="
if /i "%~1"=="--kaldir" set "ARGS=-Kaldir"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\windows_install.ps1" %ARGS%
pause

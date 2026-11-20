@echo off
rem Ekran Yansitici - Manuel baslatici (Windows, USB + Wi-Fi)
setlocal
cd /d "%~dp0app"
if exist venv\Scripts\python.exe goto :run
echo Sanal ortam olusturuluyor...
where py >nul 2>&1 && (py -3 -m venv venv) || (python -m venv venv)
if not exist venv\Scripts\python.exe (
    echo HATA: Python 3.10+ bulunamadi. https://www.python.org/downloads/ adresinden kurun.
    pause
    exit /b 1
)
:run
venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt
venv\Scripts\python.exe server.py %*
pause

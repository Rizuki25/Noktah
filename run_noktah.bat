@echo off
setlocal
rem ------------------------------------------------------------------
rem  Jalankan noktah.py dengan Python yang punya PySide6 + winsdk.
rem  Klik dua kali file ini, atau dari terminal: run_noktah.bat
rem ------------------------------------------------------------------

cd /d "%~dp0"

rem Cek dulu dependensinya ada di Python 3.10
py -3.10 -c "import PySide6, winsdk" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   PySide6 / winsdk belum terpasang di Python 3.10.
    echo   Jalankan dulu:  py -3.10 -m pip install PySide6 winsdk
    echo.
    pause
    exit /b 1
)

rem pythonw = tanpa jendela terminal hitam
set "PYW=%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"
if exist "%PYW%" (
    start "" "%PYW%" "%~dp0noktah.py"
) else (
    start "" pyw -3.10 "%~dp0noktah.py"
)
exit /b 0

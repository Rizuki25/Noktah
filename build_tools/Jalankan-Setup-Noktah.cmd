@echo off
setlocal
chcp 65001 >nul
title Noktah - Setup

cd /d "%~dp0"

set "SETUP=%~dp0Noktah-Setup-1.0.0.exe"
if not exist "%SETUP%" (
    echo.
    echo   Noktah-Setup-1.0.0.exe tidak ditemukan di folder ini.
    echo.
    pause
    exit /b 1
)

rem Inno Setup butuh membongkar dirinya ke folder temp sebelum mulai.
rem Kalau %TEMP% Windows diblokir (Error 5: Access is denied), arahkan
rem ke folder lokal di sebelah file ini.
set "TMP=%~dp0_setup_tmp"
set "TEMP=%~dp0_setup_tmp"
if not exist "%TMP%" mkdir "%TMP%" 2>nul

echo.
echo   Menjalankan installer Noktah...
echo   (folder temp dipakai: %TMP%)
echo.

"%SETUP%"
set "RC=%ERRORLEVEL%"

if exist "%TMP%" rd /s /q "%TMP%" 2>nul

echo.
if "%RC%"=="0" (
    echo   Selesai.
) else (
    echo   Installer berhenti dengan kode %RC%.
    echo   Kalau masih "Access is denied", pakai cara ZIP + Install-Noktah.cmd.
)
echo.
pause

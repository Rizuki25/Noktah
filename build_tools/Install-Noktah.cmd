@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Noktah - Pemasangan

cd /d "%~dp0"

set "SRC=%~dp0Noktah"
set "DEST=%~1"
if "%DEST%"=="" set "DEST=%LOCALAPPDATA%\Programs\Noktah"

if not exist "%SRC%\Noktah.exe" (
    echo.
    echo   File Noktah.exe tidak ditemukan di folder "Noktah".
    echo   Pastikan zip diekstrak utuh, lalu jalankan lagi file ini.
    echo.
    pause
    exit /b 1
)

echo.
echo   Memasang Noktah ke:
echo   %DEST%
echo.

taskkill /IM Noktah.exe /F >nul 2>&1
if not exist "%DEST%" mkdir "%DEST%"
xcopy "%SRC%\*" "%DEST%\" /E /I /Y /Q >nul
if errorlevel 1 (
    echo   Gagal menyalin file. Coba jalankan file ini sebagai Administrator,
    echo   atau pilih folder lain.
    pause
    exit /b 1
)

rem --- shortcut Start Menu + Desktop ---
set "LNK_START=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Noktah.lnk"
set "LNK_DESK=%USERPROFILE%\Desktop\Noktah.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "foreach ($p in @('%LNK_START%','%LNK_DESK%')) {" ^
  "  $s = $w.CreateShortcut($p);" ^
  "  $s.TargetPath = '%DEST%\Noktah.exe';" ^
  "  $s.WorkingDirectory = '%DEST%';" ^
  "  $s.IconLocation = '%DEST%\Noktah.exe,0';" ^
  "  $s.Description = 'Noktah - notch pemutar musik';" ^
  "  $s.Save() }"  >nul 2>&1

rem --- penguninstall sederhana ---
> "%DEST%\Hapus Noktah.cmd" echo @echo off
>>"%DEST%\Hapus Noktah.cmd" echo taskkill /IM Noktah.exe /F ^>nul 2^>^&1
>>"%DEST%\Hapus Noktah.cmd" echo del "%LNK_START%" ^>nul 2^>^&1
>>"%DEST%\Hapus Noktah.cmd" echo del "%LNK_DESK%" ^>nul 2^>^&1
>>"%DEST%\Hapus Noktah.cmd" echo del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Noktah.lnk" ^>nul 2^>^&1
>>"%DEST%\Hapus Noktah.cmd" echo start "" cmd /c "timeout /t 2 ^>nul ^& rmdir /s /q "%%~dp0""

echo   Selesai dipasang.
echo.

if "%~1"=="" (
    set /p AUTO="  Jalankan otomatis saat login Windows? (y/N): "
    if /i "!AUTO!"=="y" (
        copy /y "%LNK_START%" "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Noktah.lnk" >nul
        echo   Autostart diaktifkan.
    )
)

echo.
echo   Noktah sekarang ada di Start Menu dan Desktop.
echo   (Untuk menghapus: jalankan "Hapus Noktah.cmd" di folder pemasangan.)
echo.
if "%~1"=="" (
    start "" "%DEST%\Noktah.exe"
    echo   Noktah dijalankan.
)
echo.
pause

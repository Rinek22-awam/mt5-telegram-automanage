@echo off
rem Klik dua kali file ini untuk menyalakan bot. Tutup jendelanya (atau Ctrl+C) untuk mematikan.
title Bot Eksekutor MT5
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   BOT EKSEKUTOR MT5
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python belum terpasang atau tidak ditemukan.
    goto selesai
)

if not exist ".env" (
    echo [X] File .env belum ada. Salin .env.example jadi .env lalu isi tokennya.
    goto selesai
)

python -c "import MetaTrader5, dotenv, yaml" >nul 2>nul
if errorlevel 1 (
    echo Memasang paket yang dibutuhkan, tunggu sebentar...
    python -m pip install -q -r requirements.txt
)

echo Pastikan MT5 sudah terbuka, login akun demo, dan tombol Algo Trading hijau.
echo Bot jalan selama jendela ini terbuka. Tutup jendela ini untuk mematikan bot.
echo.
python -m copier.main

:selesai
echo.
echo ============================================
echo   Bot berhenti. Tekan tombol apa saja untuk menutup jendela ini.
echo ============================================
pause >nul

@echo off
rem Klik dua kali file ini. Tutup jendelanya untuk berhenti.
title Coba Baca Gambar
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   COBA BACA GAMBAR
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python belum terpasang atau tidak ditemukan.
    goto selesai
)

if not exist ".env" (
    echo [X] File .env belum ada. Salin .env.example jadi .env lalu isi.
    goto selesai
)

python -c "import MetaTrader5, dotenv, yaml, telethon, google.genai" >nul 2>nul
if errorlevel 1 (
    echo Memasang paket yang dibutuhkan, tunggu sebentar...
    python -m pip install -q -r requirements.txt
)

if "%~1"=="" (
    echo Cara pakai: seret file gambar sinyal ke atas file .bat ini.
    goto selesai
)
echo Membaca %~nx1 dengan Gemini...
echo.
python -m reader.main --coba-gambar "%~1"

:selesai
echo.
echo ============================================
echo   Selesai. Tekan tombol apa saja untuk menutup jendela ini.
echo ============================================
pause >nul

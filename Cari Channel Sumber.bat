@echo off
rem Klik dua kali file ini. Tutup jendelanya untuk berhenti.
title Cari Channel Sumber
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   CARI CHANNEL SUMBER
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

python -c "import MetaTrader5, dotenv, yaml, telethon" >nul 2>nul
if errorlevel 1 (
    echo Memasang paket yang dibutuhkan, tunggu sebentar...
    python -m pip install -q -r requirements.txt
)

echo Menampilkan channel yang kamu ikuti. Ketik ID channel yang mau dicek,
echo lalu pilih topiknya. Pilihanmu bisa langsung disimpan ke config.yaml.
echo Pertama kali: masukkan nomor HP Telegram (format +62...) dan kode login dari Telegram.
echo.
python -m reader.main --cari-channel

:selesai
echo.
echo ============================================
echo   Selesai. Tekan tombol apa saja untuk menutup jendela ini.
echo ============================================
pause >nul

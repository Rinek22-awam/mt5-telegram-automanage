@echo off
rem Satu-satunya file yang perlu diklik: menu bot, pembaca, utilitas, dan pengaturan SOP.
title Menu Bot Eksekutor
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python belum terpasang atau tidak ditemukan.
    pause
    exit /b
)

if not exist ".env" (
    echo [X] File .env belum ada. Salin .env.example jadi .env lalu isi.
    pause
    exit /b
)

python -c "import MetaTrader5, dotenv, yaml, telethon, pytest" >nul 2>nul
if errorlevel 1 (
    echo Memasang paket yang dibutuhkan, tunggu sebentar...
    python -m pip install -q -r requirements.txt
)

python -m panel.main
if errorlevel 1 pause

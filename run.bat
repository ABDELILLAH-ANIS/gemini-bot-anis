@echo off
chcp 65001 > nul
title بوت متجر اشتراكات Gemini Pro
echo ========================================================
echo        تشغيل بوت متجر اشتراكات Gemini Pro
echo ========================================================
echo.

if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe main.py
) else (
    python main.py
)

pause

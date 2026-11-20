@echo off
chcp 65001 >nul
title OxAlpha Free API Proxy

echo ============================================================
echo   OxAlpha Free API Proxy - Starting...
echo ============================================================

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

pip show fastapi >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Installing dependencies...
    pip install -r requirements.txt
)

echo [*] Starting proxy on http://localhost:8080
python server.py
pause

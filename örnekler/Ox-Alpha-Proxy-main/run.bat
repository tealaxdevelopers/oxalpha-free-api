@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Ox Alpha Proxy
color 0A

REM -- auto-install if deps missing --
if not exist node_modules (
  echo [Ox Alpha] node_modules not found - installing deps...
  call npm install
  if errorlevel 1 (
    echo [Ox Alpha] npm install failed - check Node.js 18+ is installed.
    pause
    exit /b 1
  )
  echo [Ox Alpha] deps installed.
  timeout /t 1 >nul
)
if not exist node_modules\playwright (
  echo [Ox Alpha] playwright missing - installing chromium...
  call npx playwright install chromium
)

:menu
cls
echo ==========================================
echo   Ox Alpha Proxy - Stealth Reasoning 1M
echo   https://github.com/gc1dk/ox-alpha-proxy
echo ==========================================
echo.
if exist web.env (
  echo Current web.env:
  type web.env
  echo ------------------------------------------
) else (
  echo No web.env - defaults will be used.
  echo.
)
echo [1] Start server
echo [2] Start with visible browser (HEADED=1) - use once to solve captcha
echo [3] Edit settings (web.env)
echo [4] Reset session (clear profile + state)
echo [5] Re-install deps
echo [0] Exit
echo.
set /p "choice=Choose [1-5,0]: "
if "%choice%"=="1" goto askhost
if "%choice%"=="2" goto askhost_headed
if "%choice%"=="3" goto edit
if "%choice%"=="4" goto reset
if "%choice%"=="5" goto install
if "%choice%"=="0" exit /b
goto menu

:askhost
echo.
echo -- Network --
echo [1] Localhost only  (127.0.0.1) - private, default
echo [2] LAN + localhost (0.0.0.0) - other devices on your network can open http://YOUR-IP:3000
echo.
set /p "hostchoice=Run on LAN? [1=localhost, 2=LAN]: "
if "%hostchoice%"=="2" (set HOST=0.0.0.0) else (set HOST=127.0.0.1)
goto start

:askhost_headed
echo.
echo -- Network --
echo [1] Localhost only  (127.0.0.1)
echo [2] LAN + localhost (0.0.0.0)
echo.
set /p "hostchoice=Run on LAN? [1=localhost, 2=LAN]: "
if "%hostchoice%"=="2" (set HOST=0.0.0.0) else (set HOST=127.0.0.1)
set HEADED=1
goto start

:start
echo.
echo [Ox Alpha] Starting on %HOST%:%PORT% HEADED=%HEADED%...
if exist web.env (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in ("web.env") do (
    set "key=%%a"
    set "val=%%b"
    if defined key if defined val if not "!key!"=="" if not "!key:~0,1!"==" " set "!key!=!val!"
  )
)
if defined hostchoice (
  if "%hostchoice%"=="2" set HOST=0.0.0.0
  if "%hostchoice%"=="1" set HOST=127.0.0.1
)
if not exist sandbox mkdir sandbox >nul 2>nul
call npm start
echo.
echo [Ox Alpha] Server stopped.
pause
goto menu

:edit
if not exist web.env copy example.env web.env >nul
echo Opening web.env in notepad - save and close to return.
notepad web.env
goto menu

:reset
echo Clearing profile and session...
rmdir /s /q profile 2>nul
del /q state.json 2>nul
del /q selectors.json 2>nul
echo Done - next start will be a fresh browser profile.
pause
goto menu

:install
call npm install
call npx playwright install chromium
pause
goto menu

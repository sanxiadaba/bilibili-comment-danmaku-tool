@echo off
setlocal
cd /d "%~dp0"
title Bilibili comment/danmaku tool

where python >nul 2>nul
if errorlevel 1 (
  echo [error] python not found. Install Python 3.10+ and tick "Add Python to PATH".
  pause
  exit /b 1
)

if not exist "dist\index.html" (
  echo First run: building the frontend, this takes a few minutes...
  where pnpm >nul 2>nul
  if errorlevel 1 (
    echo [error] pnpm not found. Install Node.js 18+ then run: npm install -g pnpm
    pause
    exit /b 1
  )
  call pnpm install
  if errorlevel 1 goto fail
  call pnpm build:dist
  if errorlevel 1 goto fail
)

echo.
echo Starting the local server; the browser will open at http://127.0.0.1:8001/
echo Close this window to stop the server. Logs: logs\app.jsonl
echo.
python backend\desktop_entry.py
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo [error] Start failed. See the messages above, or the tail of logs\app.jsonl
pause
exit /b 1
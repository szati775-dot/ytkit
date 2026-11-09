@echo off
title ytkit - connect YouTube (one-time setup)
cd /d "%~dp0"
rem Guided one-time setup: opens each Google page in your browser, finds the
rem downloaded key in Downloads, signs in, and copies the line for Claude.
call "%~dp0ytkit.bat" setup %*
echo.
pause

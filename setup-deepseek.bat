@echo off
title DeepSeek setup (runs on this PC, free and offline)
setlocal EnableExtensions
rem Installs Ollama (free local AI runner) if needed, downloads a DeepSeek-R1
rem model, and opens a chat with it. Run it again any time to chat.
rem   setup-deepseek.bat          asks which size to use
rem   setup-deepseek.bat 14b      uses deepseek-r1:14b without asking
rem Sizes (download / memory needed, roughly):
rem   1.5b  1.1 GB / 4 GB RAM     any PC, weakest answers
rem   7b    4.7 GB / 8 GB RAM     good
rem   8b    4.9 GB / 8 GB RAM     good (default)
rem   14b   9 GB   / 16 GB RAM    better, slow without a graphics card
rem   32b   20 GB  / 32 GB RAM    best on a single gaming GPU (24 GB VRAM)

set "SIZE=%~1"
if not defined SIZE (
  echo Which DeepSeek-R1 size?  1.5b, 7b, 8b, 14b, 32b
  echo   8 GB RAM: 8b    16 GB RAM: 14b    weak or old PC: 1.5b
  set /p "SIZE=Size [8b]: "
)
if not defined SIZE set "SIZE=8b"
set "MODEL=deepseek-r1:%SIZE%"

rem 1. Find Ollama, install it if missing.
call :find_ollama && goto have_ollama
echo.
echo Ollama is not installed. Installing it (free, from ollama.com)...
where winget >nul 2>&1 && (
  winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
)
call :find_ollama && goto have_ollama
echo winget did not work; downloading the installer instead...
set "SETUP=%TEMP%\OllamaSetup.exe"
curl -L --fail -o "%SETUP%" https://ollama.com/download/OllamaSetup.exe || goto fail_install
echo Running the Ollama installer. Click through it, then come back here.
start "" /wait "%SETUP%"
call :find_ollama && goto have_ollama
:fail_install
echo.
echo Could not install Ollama. Install it by hand from https://ollama.com/download
echo then run this file again.
start "" https://ollama.com/download
pause
exit /b 1

:have_ollama
echo Using Ollama: %OLLAMA%

rem 2. Make sure the Ollama background service is running.
"%OLLAMA%" list >nul 2>&1 || (
  echo Starting the Ollama service...
  start "Ollama" /min "%OLLAMA%" serve
  timeout /t 5 /nobreak >nul
)

rem 3. Download the model (skipped if already downloaded; resumes if interrupted).
echo.
echo Downloading %MODEL% ... this can take a while the first time.
"%OLLAMA%" pull %MODEL% || (
  echo.
  echo Download failed. Check the size name ^(1.5b, 7b, 8b, 14b, 32b^) and your internet, then try again.
  pause
  exit /b 1
)

rem 4. Chat.
echo.
echo ============================================================
echo  DeepSeek is ready: %MODEL%
echo  It runs on this PC only - free, private, works offline.
echo  Type a message and press Enter.  Type /bye to quit.
echo  Other programs can use it at http://localhost:11434
echo ============================================================
echo.
"%OLLAMA%" run %MODEL%
exit /b 0

:find_ollama
set "OLLAMA="
for %%P in (ollama.exe) do if not "%%~$PATH:P"=="" set "OLLAMA=%%~$PATH:P"
if not defined OLLAMA if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA=%ProgramFiles%\Ollama\ollama.exe"
if defined OLLAMA exit /b 0
exit /b 1

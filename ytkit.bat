@echo off
rem Runs ytkit with the first Python 3 that really works. Example:  ytkit channel
setlocal
call :try "C:\Program Files\Python310\python.exe" && goto run
call :try py && goto run
call :try python && goto run
call :try python3 && goto run
echo Python 3 was not found. Install it from python.org, tick "Add Python to PATH", then try again.
exit /b 1

:try
set "PY=%~1"
"%PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
exit /b %errorlevel%

:run
"%PY%" -I "%~dp0ytkit.py" %*

@echo off
setlocal
title Stream-Tools - Install

echo ==========================================
echo        Stream-Tools dependency setup
echo ==========================================
echo.

where python >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PY_CMD=py -3"
    ) else (
        echo [ERROR] Python was not found.
        echo Install Python 3.10+ and reopen this script.
        pause
        exit /b 1
    )
)

echo Using Python command: %PY_CMD%
for /f "delims=" %%i in ('%PY_CMD% -c "import sys; print(sys.executable)"') do set "PY_EXE=%%i"
echo Python executable: %PY_EXE%
echo.
echo Installing required packages...
call %PY_CMD% -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Could not upgrade pip.
    pause
    exit /b 1
)

call %PY_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)

REM Extra safety: explicitly install required runtime modules
call %PY_CMD% -m pip install python-dotenv requests
if errorlevel 1 (
    echo [ERROR] Failed to install python-dotenv/requests.
    pause
    exit /b 1
)

REM Verify imports with the same Python executable
call %PY_CMD% -c "import requests; import dotenv; print('Import check OK')"
if errorlevel 1 (
    echo [ERROR] Import check failed for requests/dotenv.
    echo Try running with the same interpreter:
    echo   %PY_CMD% monitor.py
    pause
    exit /b 1
)

echo.
echo [OK] Dependencies installed successfully.
echo Next step: run create_env.bat then start with:
echo   %PY_CMD% monitor.py
echo.
pause
exit /b 0

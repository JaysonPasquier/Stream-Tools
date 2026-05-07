@echo off
setlocal
title Stream-Tools - Install

echo ==========================================
echo        Stream-Tools dependency setup
echo ==========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PY_CMD=python"
    ) else (
        echo [ERROR] Python was not found.
        echo Install Python 3.10+ and reopen this script.
        pause
        exit /b 1
    )
)

echo Using Python command: %PY_CMD%
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

echo.
echo [OK] Dependencies installed successfully.
echo Next step: run create_env.bat
echo.
pause
exit /b 0

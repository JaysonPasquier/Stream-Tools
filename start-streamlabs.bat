@echo off
setlocal EnableExtensions

REM ============================================================
REM  Streamlabs launcher — edit the path below to your .exe
REM ============================================================
set "STREAMLABS_EXE=C:\Program Files\Streamlabs OBS\Streamlabs OBS.exe"

REM monitor.py is started from this .bat folder (repo root)
cd /d "%~dp0"

if not exist "%STREAMLABS_EXE%" (
    echo [ERROR] Streamlabs not found at:
    echo   %STREAMLABS_EXE%
    echo.
    echo Edit STREAMLABS_EXE at the top of start-streamlabs.bat
    echo and set the full path to your Streamlabs Desktop .exe
    pause
    exit /b 1
)

if not exist "monitor.py" (
    echo [ERROR] monitor.py not found in: %CD%
    pause
    exit /b 1
)

where python >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PY_CMD=py -3"
    ) else (
        echo [ERROR] Python not found. Run install.bat first.
        pause
        exit /b 1
    )
)

echo Starting Streamlabs Desktop...
start "" "%STREAMLABS_EXE%"

echo Starting Stream-Tools monitor...
start "Stream-Tools monitor" /D "%CD%" cmd /k %PY_CMD% monitor.py

echo.
echo [OK] Streamlabs and monitor.py should be running.
echo Close the "Stream-Tools monitor" window to stop the script.
echo.
pause
exit /b 0

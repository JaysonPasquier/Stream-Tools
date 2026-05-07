@echo off
setlocal EnableDelayedExpansion
title Stream-Tools - Interactive .env creator

echo =================================================
echo      Stream-Tools interactive .env creator
echo =================================================
echo.
echo This script will ask every value needed for .env.
echo For each item:
echo - press Y if you already have it (you will paste it)
echo - press N if not (script explains how to get it)
echo.

call :askValue VAL_PUUID "Valorant PUUID" "Find your Valorant PUUID from Henrik account lookup endpoint using your Riot ID (name and tag)."
call :askValue HENRIK_API_KEY "Henrik API key" "Open https://docs.henrikdev.xyz and create/get your API key."
call :askValue VAL_REGION "Valorant region" "Use eu, na, ap, kr, latam, br depending on your account shard. Default usually eu."
call :askValue VAL_PLATFORM "Valorant platform" "Usually pc."

call :askValue LOL_PUUID "League of Legends PUUID" "Use Riot account API (account-v1 by Riot ID) or Riot tools to get your LoL account PUUID."
call :askValue LOL_REGION "LoL regional route" "Use europe, americas, asia, or sea. Example for EUW: europe."
call :askValue LOL_PLATFORM "LoL platform" "Use server platform like euw1, na1, kr, etc."
call :askValue RIOT_API_KEY "Riot API key" "Open https://developer.riotgames.com and create an app. Use your Riot API key."

call :askValue TWITCH_CHANNEL "Twitch channel login" "This is your channel username/login (lowercase), not full URL."
call :askValue TWITCH_CLIENT_ID "Twitch Client ID" "Create an app in Twitch Developer Console and copy Client ID."
call :askValue TWITCH_ACCESS_TOKEN "Twitch Access Token" "Generate a user OAuth token with scopes allowing stream metadata reads."

echo.
echo Cloudflare worker endpoint configuration:
echo 1) Single URL for both rank and streak
echo 2) Separate URL for rank and streak
choice /c 12 /n /m "Choose [1/2]: "
if errorlevel 2 goto separateUrls
if errorlevel 1 goto singleUrl

:singleUrl
call :askValue CF_WORKER_UPDATE_URL "Cloudflare update URL (single endpoint)" "Example: https://your-worker.workers.dev/update"
set "CF_RANK_UPDATE_URL="
set "CF_SESSION_UPDATE_URL="
goto afterUrls

:separateUrls
set "CF_WORKER_UPDATE_URL="
call :askValue CF_RANK_UPDATE_URL "Cloudflare rank update URL" "Endpoint used by !rank payload updates."
call :askValue CF_SESSION_UPDATE_URL "Cloudflare session update URL" "Endpoint used by !streak payload updates."
goto afterUrls

:afterUrls
call :askValue CF_UPDATE_TOKEN "Cloudflare update token" "Set same secret in Worker env and use it here."

call :askDefault POLL_INTERVAL_SECONDS "Poll interval in seconds" "20"
call :askDefault TEST_MODE "Test mode (true/false)" "false"

echo.
echo Writing .env file...
(
echo VAL_PUUID=!VAL_PUUID!
echo HENRIK_API_KEY=!HENRIK_API_KEY!
echo VAL_REGION=!VAL_REGION!
echo VAL_PLATFORM=!VAL_PLATFORM!
echo.
echo LOL_PUUID=!LOL_PUUID!
echo LOL_REGION=!LOL_REGION!
echo LOL_PLATFORM=!LOL_PLATFORM!
echo RIOT_API_KEY=!RIOT_API_KEY!
echo.
echo TWITCH_CHANNEL=!TWITCH_CHANNEL!
echo TWITCH_CLIENT_ID=!TWITCH_CLIENT_ID!
echo TWITCH_ACCESS_TOKEN=!TWITCH_ACCESS_TOKEN!
echo.
echo CF_WORKER_UPDATE_URL=!CF_WORKER_UPDATE_URL!
echo CF_RANK_UPDATE_URL=!CF_RANK_UPDATE_URL!
echo CF_SESSION_UPDATE_URL=!CF_SESSION_UPDATE_URL!
echo CF_UPDATE_TOKEN=!CF_UPDATE_TOKEN!
echo.
echo POLL_INTERVAL_SECONDS=!POLL_INTERVAL_SECONDS!
echo TEST_MODE=!TEST_MODE!
) > ".env"

echo.
echo [OK] .env created successfully at project root.
echo You can now run:
echo   python monitor.py
echo.
pause
exit /b 0

:askValue
set "VAR_NAME=%~1"
set "DISPLAY_NAME=%~2"
set "HELP_TEXT=%~3"
:askValueLoop
echo.
echo -----------------------------------------
echo %DISPLAY_NAME%
choice /c YN /n /m "Do you already have it? [Y/N]: "
if errorlevel 2 (
    echo [How to get it]
    echo %HELP_TEXT%
    echo.
    choice /c CR /n /m "Press [C] to continue and paste value, or [R] to re-read explanation: "
    if errorlevel 2 goto askValueLoop
)
set /p "TMP_VALUE=Paste %DISPLAY_NAME%: "
if "!TMP_VALUE!"=="" (
    echo Value cannot be empty.
    goto askValueLoop
)
set "%VAR_NAME%=!TMP_VALUE!"
exit /b 0

:askDefault
set "VAR_NAME=%~1"
set "DISPLAY_NAME=%~2"
set "DEFAULT_VALUE=%~3"
echo.
set /p "TMP_VALUE=%DISPLAY_NAME% (default: %DEFAULT_VALUE%): "
if "!TMP_VALUE!"=="" set "TMP_VALUE=%DEFAULT_VALUE%"
set "%VAR_NAME%=!TMP_VALUE!"
exit /b 0

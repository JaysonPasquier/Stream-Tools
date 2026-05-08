@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Stream-Tools - Interactive .env creator

echo =================================================
echo      Stream-Tools interactive .env creator
echo =================================================
echo.
echo Order:
echo 1) API keys
echo 2) Game setup (Valorant / LoL, each optional)
echo 3) Twitch
echo 4) Cloudflare
echo 5) Runtime options
echo.

set "VAL_PUUID="
set "VAL_REGION=eu"
set "VAL_PLATFORM=pc"
set "LOL_PUUID="
set "LOL_REGION=europe"
set "LOL_PLATFORM=euw1"
set "CF_WORKER_BASE_URL="
set "CF_RANK_UPDATE_URL="
set "CF_SESSION_UPDATE_URL="

echo -------------------- API KEYS --------------------
call :askRequired HENRIK_API_KEY "Henrik API key (Valorant)"
call :askRequired RIOT_API_KEY "Riot API key (LoL)"

echo.
echo -------------------- GAME SETUP --------------------
call :askYN "Setup Valorant variables? [Y/N]: " SETUP_VALO
call :askYN "Setup League of Legends variables? [Y/N]: " SETUP_LOL
if /i "!SETUP_VALO!"=="N" if /i "!SETUP_LOL!"=="N" (
    echo At least one game must be enabled.
    pause
    exit /b 1
)
if /i "!SETUP_VALO!"=="Y" call :setupValorant
if /i "!SETUP_LOL!"=="Y" call :setupLol

echo.
echo -------------------- TWITCH --------------------
call :askRequired TWITCH_CHANNEL "Twitch channel login (lowercase)"
call :askRequired TWITCH_CLIENT_ID "Twitch Client ID"
call :askRequired TWITCH_ACCESS_TOKEN "Twitch Access Token"

echo.
echo -------------------- CLOUDFLARE --------------------
echo Using one base URL for both rank and streak.
echo Example: https://your-worker.your-subdomain.workers.dev
call :askRequired CF_WORKER_BASE_URL "Cloudflare worker base URL"
set "CF_RANK_UPDATE_URL="
set "CF_SESSION_UPDATE_URL="
call :askRequired CF_UPDATE_TOKEN "Cloudflare update token"

echo.
echo -------------------- RUNTIME --------------------
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
echo CF_WORKER_BASE_URL=!CF_WORKER_BASE_URL!
echo CF_WORKER_UPDATE_URL=
echo CF_RANK_UPDATE_URL=!CF_RANK_UPDATE_URL!
echo CF_SESSION_UPDATE_URL=!CF_SESSION_UPDATE_URL!
echo CF_UPDATE_TOKEN=!CF_UPDATE_TOKEN!
echo.
echo POLL_INTERVAL_SECONDS=!POLL_INTERVAL_SECONDS!
echo TEST_MODE=!TEST_MODE!
) > ".env"

echo.
echo [OK] .env created successfully.
echo You can now run: python monitor.py
echo.
pause
exit /b 0

:setupValorant
echo.
echo ---------- Valorant ----------
call :askRequired VAL_NAME "Valorant Riot game name"
call :askRequired VAL_TAG "Valorant Riot tag"
echo Lookup URL (Henrik):
echo https://api.henrikdev.xyz/valorant/v2/account/!VAL_NAME!/!VAL_TAG!?api_key=!HENRIK_API_KEY!
call :askYN "Auto-fetch VAL_PUUID now? [Y/N]: " VAL_FETCH
if /i "!VAL_FETCH!"=="Y" call :fetchValPuuid
if "!VAL_PUUID!"=="" call :askRequired VAL_PUUID "Valorant PUUID (manual paste)"
call :askDefault VAL_REGION "Valorant region" "eu"
call :askDefault VAL_PLATFORM "Valorant platform" "pc"
goto :eof

:setupLol
echo.
echo ---------- League of Legends ----------
call :askRequired LOL_NAME "LoL Riot game name"
call :askRequired LOL_TAG "LoL Riot tag"
call :askDefault LOL_REGION "LoL regional route (account/match-v5)" "europe"
call :askDefault LOL_PLATFORM "LoL platform (league-v4)" "euw1"
echo Lookup URL (Riot account-v1):
echo https://!LOL_REGION!.api.riotgames.com/riot/account/v1/accounts/by-riot-id/!LOL_NAME!/!LOL_TAG!?api_key=!RIOT_API_KEY!
call :askYN "Auto-fetch LOL_PUUID now? [Y/N]: " LOL_FETCH
if /i "!LOL_FETCH!"=="Y" call :fetchLolPuuid
if "!LOL_PUUID!"=="" call :askRequired LOL_PUUID "LoL PUUID (manual paste)"
goto :eof

:fetchValPuuid
set "VAL_PUUID="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $u='https://api.henrikdev.xyz/valorant/v2/account/!VAL_NAME!/!VAL_TAG!?api_key=!HENRIK_API_KEY!'; try { $r=Invoke-RestMethod -Uri $u -Method Get; if($r -and $r.data -and $r.data.puuid){ $r.data.puuid } } catch { '' }"`) do set "VAL_PUUID=%%i"
if not "!VAL_PUUID!"=="" (
    echo [OK] VAL_PUUID fetched.
) else (
    echo [WARN] Auto-fetch failed for VAL_PUUID.
)
goto :eof

:fetchLolPuuid
set "LOL_PUUID="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $u='https://!LOL_REGION!.api.riotgames.com/riot/account/v1/accounts/by-riot-id/!LOL_NAME!/!LOL_TAG!?api_key=!RIOT_API_KEY!'; try { $r=Invoke-RestMethod -Uri $u -Method Get -Headers @{ 'X-Riot-Token'='!RIOT_API_KEY!' }; if($r -and $r.puuid){ $r.puuid } } catch { '' }"`) do set "LOL_PUUID=%%i"
if not "!LOL_PUUID!"=="" (
    echo [OK] LOL_PUUID fetched.
) else (
    echo [WARN] Auto-fetch failed for LOL_PUUID.
)
goto :eof

:askRequired
set "VAR_NAME=%~1"
set "DISPLAY_NAME=%~2"
:askRequiredLoop
set "TMP_VALUE="
set /p "TMP_VALUE=%DISPLAY_NAME%: "
if "!TMP_VALUE!"=="" (
    echo Value cannot be empty.
    goto askRequiredLoop
)
set "%VAR_NAME%=!TMP_VALUE!"
goto :eof

:askDefault
set "VAR_NAME=%~1"
set "DISPLAY_NAME=%~2"
set "DEFAULT_VALUE=%~3"
set "TMP_VALUE="
set /p "TMP_VALUE=%DISPLAY_NAME% (default: %DEFAULT_VALUE%): "
if "!TMP_VALUE!"=="" set "TMP_VALUE=%DEFAULT_VALUE%"
set "%VAR_NAME%=!TMP_VALUE!"
goto :eof

:askYN
set "PROMPT=%~1"
set "OUTVAR=%~2"
:askYNLoop
set "TMP_YN="
set /p "TMP_YN=%PROMPT%"
if /i "!TMP_YN!"=="Y" (
    set "%OUTVAR%=Y"
    goto :eof
)
if /i "!TMP_YN!"=="N" (
    set "%OUTVAR%=N"
    goto :eof
)
echo Please type Y or N.
goto askYNLoop

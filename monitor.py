#!/usr/bin/env python3
"""
Unified Twitch session monitor for Valorant + League of Legends.

This single process computes and pushes:
- Rank text (for !rank)
- Session streak text (for !streak)

It shares polling logic to reduce duplicate API requests versus running
separate rank and streak scripts.
"""

import os
import time
import threading
import posixpath
import http.server
import socketserver
from datetime import datetime, timezone
from typing import List, Optional, Set, Tuple
from urllib.parse import quote

import requests
try:
    import obspython as obs  # type: ignore
except ImportError:
    obs = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_CANDIDATES = [
    os.path.join(SCRIPT_DIR, ".env"),
    os.path.join(os.getcwd(), ".env"),
]


def _fallback_load_dotenv(path: str = ".env") -> None:
    """
    Minimal .env loader for environments where python-dotenv is unavailable
    (e.g. OBS embedded Python). Existing environment variables are not
    overwritten.
    """
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


if load_dotenv:
    loaded = False
    for env_path in ENV_CANDIDATES:
        if os.path.exists(env_path):
            load_dotenv(env_path)
            loaded = True
            break
    if not loaded:
        load_dotenv()
else:
    loaded = False
    for env_path in ENV_CANDIDATES:
        if os.path.exists(env_path):
            _fallback_load_dotenv(env_path)
            loaded = True
            break
    if not loaded:
        _fallback_load_dotenv()


def log_info(message: str) -> None:
    if obs is not None:
        try:
            obs.script_log(obs.LOG_INFO, message)
            return
        except Exception:
            pass
    print(message)


def log_error(message: str) -> None:
    if obs is not None:
        try:
            obs.script_log(obs.LOG_ERROR, message)
            return
        except Exception:
            pass
    print(message)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VAL_PUUID = os.environ.get("VAL_PUUID", "").strip()
HENRIK_API_KEY = os.environ.get("HENRIK_API_KEY", "").strip()
VAL_REGION = os.environ.get("VAL_REGION", "eu").strip()
VAL_PLATFORM = os.environ.get("VAL_PLATFORM", "pc").strip()

LOL_PUUID = os.environ.get("LOL_PUUID", "").strip()
LOL_REGION = os.environ.get("LOL_REGION", "europe").strip()  # match-v5
LOL_PLATFORM = os.environ.get("LOL_PLATFORM", "euw1").strip()  # league-v4
RIOT_API_KEY = os.environ.get("RIOT_API_KEY", "").strip()

TWITCH_CHANNEL = os.environ.get("TWITCH_CHANNEL", "").strip()
TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "").strip()
TWITCH_ACCESS_TOKEN = os.environ.get("TWITCH_ACCESS_TOKEN", "").strip()

# Cloudflare URL modes:
# 1) Base URL mode (recommended):
#    - CF_WORKER_BASE_URL=https://xxx.workers.dev
#    - monitor will use:
#        POST <base>/update
#        GET  <base>/rank
#        GET  <base>/streak
# 2) Legacy direct update URLs:
#    - CF_RANK_UPDATE_URL / CF_SESSION_UPDATE_URL, or CF_WORKER_UPDATE_URL for both.
CF_WORKER_BASE_URL = os.environ.get("CF_WORKER_BASE_URL", "").strip().rstrip("/")
CF_WORKER_UPDATE_URL = os.environ.get("CF_WORKER_UPDATE_URL", "").strip()
CF_RANK_UPDATE_URL = os.environ.get("CF_RANK_UPDATE_URL", "").strip()
CF_SESSION_UPDATE_URL = os.environ.get("CF_SESSION_UPDATE_URL", "").strip()
CF_UPDATE_TOKEN = os.environ.get("CF_UPDATE_TOKEN", "").strip()

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "20"))
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
OVERLAY_SERVER_ENABLED = os.environ.get("OVERLAY_SERVER_ENABLED", "true").lower() == "true"
OVERLAY_SERVER_HOST = os.environ.get("OVERLAY_SERVER_HOST", "127.0.0.1").strip()
OVERLAY_SERVER_PORT = int(os.environ.get("OVERLAY_SERVER_PORT", "8787"))


LOL_TIER_ORDER = [
    "IRON",
    "BRONZE",
    "SILVER",
    "GOLD",
    "PLATINUM",
    "EMERALD",
    "DIAMOND",
    "MASTER",
    "GRANDMASTER",
    "CHALLENGER",
]
LOL_DIVISION_OFFSET = {"IV": 0, "III": 100, "II": 200, "I": 300}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class ValorantSession:
    def __init__(self) -> None:
        self.wins = 0
        self.losses = 0
        self.draws = 0
        self.rr_delta = 0
        self.last_seen_match_ids = set()  # type: Set[str]
        self.last_map = ""
        self.last_rr_change = 0


class LolSession:
    def __init__(self) -> None:
        self.wins = 0
        self.losses = 0
        self.lp_delta = 0
        self.last_seen_match_ids = set()  # type: Set[str]
        self.last_champion = ""
        self.last_lp_change = 0
        self.last_known_score = None  # type: Optional[int]


class RuntimeState:
    def __init__(self) -> None:
        self.stream_live = False
        self.stream_start = None  # type: Optional[datetime]
        self.current_game = None  # type: Optional[str]
        self.last_rank_pushed = None  # type: Optional[str]
        self.last_session_pushed = None  # type: Optional[str]
        self.val = ValorantSession()
        self.lol = LolSession()


STATE = RuntimeState()
STOP_EVENT = threading.Event()
MONITOR_THREAD = None  # type: Optional[threading.Thread]
HTTP_SERVER = None  # type: Optional[socketserver.TCPServer]
HTTP_THREAD = None  # type: Optional[threading.Thread]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def signed(n: int) -> str:
    return f"+{n}" if n > 0 else str(n)


def detect_game(game_name: str) -> Optional[str]:
    g = (game_name or "").upper()
    if "VALORANT" in g:
        return "VALORANT"
    if "LEAGUE OF LEGENDS" in g or g == "LOL":
        return "LOL"
    return None


def parse_iso_datetime(value: str) -> datetime:
    """
    Python 3.6-safe ISO datetime parser for values like:
    - 2026-05-08T08:54:12Z
    - 2026-05-08T08:54:12.345Z
    - 2026-05-08T08:54:12+00:00
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Empty datetime string")

    normalized = raw.replace("Z", "+00:00")
    # Python 3.7+ fast path
    if hasattr(datetime, "fromisoformat"):
        return datetime.fromisoformat(normalized)

    # Python 3.6 fallback
    if normalized.endswith("+00:00"):
        base = normalized[:-6]
        if "." in base:
            return datetime.strptime(base, "%Y-%m-%dT%H:%M:%S.%f").replace(
                tzinfo=timezone.utc
            )
        return datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    if "." in normalized:
        return datetime.strptime(normalized, "%Y-%m-%dT%H:%M:%S.%f")
    return datetime.strptime(normalized, "%Y-%m-%dT%H:%M:%S")


class OverlayHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Serve static files rooted at SCRIPT_DIR (OBS-safe, Python 3.6 compatible)."""

    def log_message(self, fmt, *args):
        log_info("[HTTP] " + (fmt % args))

    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        path = posixpath.normpath(path)
        parts = [p for p in path.split("/") if p and p not in (".", "..")]
        full = SCRIPT_DIR
        for p in parts:
            full = os.path.join(full, p)
        return full


def build_overlay_url() -> str:
    base = "http://{host}:{port}/rank/overlay.html".format(
        host=OVERLAY_SERVER_HOST, port=OVERLAY_SERVER_PORT
    )
    params = []
    if TWITCH_CHANNEL:
        params.append("channel=" + quote(TWITCH_CHANNEL))
    if VAL_PUUID:
        params.append("puuid=" + quote(VAL_PUUID))
    if LOL_PUUID:
        params.append("lol_puuid=" + quote(LOL_PUUID))
    if HENRIK_API_KEY:
        params.append("api_key=" + quote(HENRIK_API_KEY))
    if RIOT_API_KEY:
        params.append("riot_api_key=" + quote(RIOT_API_KEY))
    return base + ("?" + "&".join(params) if params else "")


def start_overlay_http_server() -> None:
    global HTTP_SERVER, HTTP_THREAD
    if not OVERLAY_SERVER_ENABLED:
        return
    if HTTP_THREAD and HTTP_THREAD.is_alive():
        return
    try:
        HTTP_SERVER = socketserver.ThreadingTCPServer(
            (OVERLAY_SERVER_HOST, OVERLAY_SERVER_PORT), OverlayHTTPRequestHandler
        )
        HTTP_SERVER.daemon_threads = True
        HTTP_THREAD = threading.Thread(
            target=HTTP_SERVER.serve_forever, name="OverlayHTTPServer", daemon=True
        )
        HTTP_THREAD.start()
        log_info(
            "[HTTP] Overlay server started: http://{host}:{port}".format(
                host=OVERLAY_SERVER_HOST, port=OVERLAY_SERVER_PORT
            )
        )
        log_info("[HTTP] OBS Browser Source URL: " + build_overlay_url())
    except Exception as exc:
        log_error("[HTTP] Failed to start overlay server: {0}".format(exc))
        HTTP_SERVER = None
        HTTP_THREAD = None


def stop_overlay_http_server() -> None:
    global HTTP_SERVER, HTTP_THREAD
    if HTTP_SERVER is not None:
        try:
            HTTP_SERVER.shutdown()
            HTTP_SERVER.server_close()
            log_info("[HTTP] Overlay server stopped.")
        except Exception as exc:
            log_error("[HTTP] Error stopping overlay server: {0}".format(exc))
    HTTP_SERVER = None
    HTTP_THREAD = None


def lol_rank_score(entry: dict) -> int:
    tier = entry["tier"].upper()
    rank = entry.get("rank", "").upper()
    lp = int(entry["leaguePoints"])

    if tier not in LOL_TIER_ORDER:
        raise RuntimeError(f"Unknown LoL tier: {tier}")

    tier_idx = LOL_TIER_ORDER.index(tier)
    if tier in {"MASTER", "GRANDMASTER", "CHALLENGER"}:
        division = 0
    else:
        division = LOL_DIVISION_OFFSET.get(rank)
        if division is None:
            raise RuntimeError(f"Unknown LoL division: {rank}")
    return tier_idx * 400 + division + lp


def require_env() -> None:
    required = {
        "TWITCH_CHANNEL": TWITCH_CHANNEL,
        "TWITCH_CLIENT_ID": TWITCH_CLIENT_ID,
        "TWITCH_ACCESS_TOKEN": TWITCH_ACCESS_TOKEN,
        "CF_UPDATE_TOKEN": CF_UPDATE_TOKEN,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    if not (
        CF_WORKER_BASE_URL
        or CF_WORKER_UPDATE_URL
        or CF_RANK_UPDATE_URL
        or CF_SESSION_UPDATE_URL
    ):
        raise RuntimeError(
            "Missing Cloudflare URL config. Set CF_WORKER_BASE_URL or legacy update URLs."
        )


def rank_update_url() -> str:
    return CF_RANK_UPDATE_URL or CF_WORKER_UPDATE_URL


def session_update_url() -> str:
    return CF_SESSION_UPDATE_URL or CF_WORKER_UPDATE_URL


def base_update_url() -> str:
    return f"{CF_WORKER_BASE_URL}/update" if CF_WORKER_BASE_URL else ""


def base_rank_url() -> str:
    return f"{CF_WORKER_BASE_URL}/rank" if CF_WORKER_BASE_URL else ""


def base_streak_url() -> str:
    return f"{CF_WORKER_BASE_URL}/streak" if CF_WORKER_BASE_URL else ""


def push_text(url: str, text: str, label: str) -> None:
    if TEST_MODE:
        log_info(f"[TEST:{label}] {text}")
        return
    if not url:
        raise RuntimeError(f"Missing {label} worker update URL")
    resp = requests.post(
        url,
        data=text.encode("utf-8"),
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "x-auth-token": CF_UPDATE_TOKEN,
        },
        timeout=12,
    )
    resp.raise_for_status()


def push_combined_update(rank_text: str, streak_text: str) -> None:
    url = base_update_url()
    if TEST_MODE:
        log_info(f"[TEST:UPDATE] {url} rank='{rank_text}' streak='{streak_text}'")
        return
    if not url:
        raise RuntimeError("Missing CF_WORKER_BASE_URL for combined update mode")
    resp = requests.post(
        url,
        json={"rank": rank_text, "streak": streak_text},
        headers={"x-auth-token": CF_UPDATE_TOKEN},
        timeout=12,
    )
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------
def fetch_twitch_stream() -> Tuple[bool, Optional[datetime], str]:
    resp = requests.get(
        "https://api.twitch.tv/helix/streams",
        params={"user_login": TWITCH_CHANNEL},
        headers={
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {TWITCH_ACCESS_TOKEN}",
        },
        timeout=12,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        return False, None, ""
    row = data[0]
    started_at = parse_iso_datetime(row["started_at"])
    return True, started_at, row.get("game_name", "")


def fetch_twitch_channel_game_name() -> str:
    """
    Read current channel category even if stream is offline.
    Uses users -> channels Helix flow.
    """
    users_resp = requests.get(
        "https://api.twitch.tv/helix/users",
        params={"login": TWITCH_CHANNEL},
        headers={
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {TWITCH_ACCESS_TOKEN}",
        },
        timeout=12,
    )
    users_resp.raise_for_status()
    users_data = users_resp.json().get("data", [])
    if not users_data:
        return ""
    broadcaster_id = users_data[0].get("id")
    if not broadcaster_id:
        return ""

    channels_resp = requests.get(
        "https://api.twitch.tv/helix/channels",
        params={"broadcaster_id": broadcaster_id},
        headers={
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {TWITCH_ACCESS_TOKEN}",
        },
        timeout=12,
    )
    channels_resp.raise_for_status()
    channels_data = channels_resp.json().get("data", [])
    if not channels_data:
        return ""
    return channels_data[0].get("game_name", "") or ""


def fetch_val_rank() -> Tuple[str, int, int]:
    if not (VAL_PUUID and HENRIK_API_KEY):
        raise RuntimeError("Missing Valorant env vars")
    url = (
        f"https://api.henrikdev.xyz/valorant/v3/by-puuid/mmr/"
        f"{VAL_REGION}/{VAL_PLATFORM}/{VAL_PUUID}"
    )
    resp = requests.get(url, params={"api_key": HENRIK_API_KEY}, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != 200:
        raise RuntimeError(f"Henrik rank API payload error: {payload}")
    cur = payload["data"]["current"]
    tier_name = cur["tier"]["name"]
    rr = int(cur["rr"])
    last_change = int(cur.get("last_change", 0))
    text = f"{tier_name} : {rr} RR [{signed(last_change)}]"
    return text, rr, last_change


def fetch_val_mmr_history() -> List[dict]:
    url = (
        f"https://api.henrikdev.xyz/valorant/v2/by-puuid/mmr-history/"
        f"{VAL_REGION}/{VAL_PLATFORM}/{VAL_PUUID}"
    )
    resp = requests.get(url, params={"api_key": HENRIK_API_KEY}, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != 200:
        raise RuntimeError(f"Henrik history API payload error: {payload}")
    return payload["data"]["history"]


def fetch_lol_solo_entry() -> dict:
    if not (LOL_PUUID and RIOT_API_KEY):
        raise RuntimeError("Missing LoL env vars")
    url = f"https://{LOL_PLATFORM}.api.riotgames.com/lol/league/v4/entries/by-puuid/{LOL_PUUID}"
    resp = requests.get(url, params={"api_key": RIOT_API_KEY}, timeout=15)
    resp.raise_for_status()
    entries = resp.json()
    for entry in entries:
        if entry.get("queueType") == "RANKED_SOLO_5x5":
            return entry
    raise RuntimeError("No RANKED_SOLO_5x5 entry found")


def fetch_lol_match_ids(start_epoch: int) -> List[str]:
    url = f"https://{LOL_REGION}.api.riotgames.com/lol/match/v5/matches/by-puuid/{LOL_PUUID}/ids"
    resp = requests.get(
        url,
        params={
            "startTime": start_epoch,
            "queue": 420,
            "count": 20,
            "api_key": RIOT_API_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_lol_match(match_id: str) -> dict:
    url = f"https://{LOL_REGION}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    resp = requests.get(url, params={"api_key": RIOT_API_KEY}, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def build_val_session_text() -> str:
    s = STATE.val
    total = s.wins + s.losses
    if total == 0:
        return "0W / 0L +0 RR"
    base = f"{s.wins}W / {s.losses}L {signed(s.rr_delta)} RR"
    if s.last_map:
        base += f" | Last game : {s.last_map} {signed(s.last_rr_change)} RR"
    return base


def build_lol_session_text() -> str:
    s = STATE.lol
    total = s.wins + s.losses
    if total == 0:
        return "0W / 0L +0 LP"
    base = f"{s.wins}W / {s.losses}L {signed(s.lp_delta)} LP"
    if s.last_champion:
        base += f" | Last game : {s.last_champion} {signed(s.last_lp_change)} LP"
    return base


def build_lol_rank_text(entry: dict, last_lp_change: int) -> str:
    tier_div = f"{entry['tier']} {entry['rank']}"
    lp = int(entry["leaguePoints"])
    return f"{tier_div} : {lp} LP [{signed(last_lp_change)}]"


def reset_session(game: Optional[str]) -> None:
    STATE.val = ValorantSession()
    STATE.lol = LolSession()
    STATE.last_rank_pushed = None
    STATE.last_session_pushed = None
    STATE.current_game = game


# ---------------------------------------------------------------------------
# Per-game processing
# ---------------------------------------------------------------------------
def process_valorant() -> Tuple[str, str]:
    rank_text, _, _ = fetch_val_rank()
    history = fetch_val_mmr_history()

    if not STATE.stream_start:
        return rank_text, build_val_session_text()

    new_rows: List[Tuple[datetime, dict]] = []
    for match in history:
        dt = parse_iso_datetime(match["date"])
        if dt < STATE.stream_start:
            continue
        mid = match.get("match_id", "")
        if mid and mid not in STATE.val.last_seen_match_ids:
            new_rows.append((dt, match))

    new_rows.sort(key=lambda x: x[0])
    for _, m in new_rows:
        change = int(m.get("last_change", 0))
        if change > 0:
            STATE.val.wins += 1
        elif change < 0:
            STATE.val.losses += 1
        else:
            STATE.val.draws += 1
        STATE.val.rr_delta += change
        mid = m.get("match_id", "")
        if mid:
            STATE.val.last_seen_match_ids.add(mid)
        STATE.val.last_map = (m.get("map") or {}).get("name", "Unknown")
        STATE.val.last_rr_change = change

    return rank_text, build_val_session_text()


def process_lol() -> Tuple[str, str]:
    entry = fetch_lol_solo_entry()
    score = lol_rank_score(entry)

    # Rank line ("last game change") for !rank style display.
    rank_delta = 0
    if STATE.lol.last_known_score is not None:
        rank_delta = score - STATE.lol.last_known_score

    # Session LP tracking baseline.
    old_score = STATE.lol.last_known_score
    STATE.lol.last_known_score = score
    if old_score is not None and score != old_score:
        STATE.lol.lp_delta += score - old_score
        # If we already have at least one detected game this session, attribute
        # the score delta to the latest game.
        if STATE.lol.last_champion:
            STATE.lol.last_lp_change += score - old_score

    if STATE.stream_start:
        start_epoch = int(STATE.stream_start.timestamp())
        ids = fetch_lol_match_ids(start_epoch)
        unseen = [m for m in ids if m not in STATE.lol.last_seen_match_ids]
        for match_id in reversed(unseen):
            data = fetch_lol_match(match_id)
            info = data.get("info", {})
            game_end_ms = info.get("gameEndTimestamp")
            if game_end_ms:
                game_end = datetime.fromtimestamp(game_end_ms / 1000, tz=timezone.utc)
                if game_end < STATE.stream_start:
                    continue
            me = next((p for p in info.get("participants", []) if p.get("puuid") == LOL_PUUID), None)
            if not me:
                continue
            if me.get("win"):
                STATE.lol.wins += 1
            else:
                STATE.lol.losses += 1
            STATE.lol.last_seen_match_ids.add(match_id)
            STATE.lol.last_champion = me.get("championName", "Unknown")
            STATE.lol.last_lp_change = 0

    return build_lol_rank_text(entry, rank_delta), build_lol_session_text()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main_loop(stop_event: Optional[threading.Event] = None) -> None:
    require_env()
    start_overlay_http_server()

    log_info("[Main] Unified monitor started.")
    log_info(f"[Main] Poll interval: {POLL_INTERVAL_SECONDS}s")
    if CF_WORKER_BASE_URL:
        log_info(f"[Cloudflare] update={base_update_url()}")
        log_info(f"[Cloudflare] rank={base_rank_url()}")
        log_info(f"[Cloudflare] streak={base_streak_url()}")
    while not (stop_event and stop_event.is_set()):
        try:
            is_live, started_at, game_name = fetch_twitch_stream()

            # TEST_MODE override:
            # - still query real Twitch live status
            # - if offline, simulate live and use channel category for game logic
            if TEST_MODE and not is_live:
                channel_game = fetch_twitch_channel_game_name()
                if channel_game:
                    game_name = channel_game
                is_live = True
                if started_at is None:
                    started_at = datetime.now(timezone.utc)
                log_info(
                    f"[TEST] Stream offline -> simulated live (category: {game_name or 'unknown'})"
                )

            game = detect_game(game_name)

            if not is_live:
                if STATE.stream_live:
                    log_info("[Twitch] Stream offline, resetting live state.")
                STATE.stream_live = False
                STATE.stream_start = None
                STATE.current_game = None
                STATE.last_rank_pushed = None
                STATE.last_session_pushed = None
                if stop_event and stop_event.wait(POLL_INTERVAL_SECONDS):
                    break
                continue

            # Stream start
            if not STATE.stream_live:
                log_info(f"[Twitch] Live detected: {game_name}")
                STATE.stream_live = True
                STATE.stream_start = started_at
                reset_session(game)

            # Category switch while live
            if game and game != STATE.current_game:
                log_info(f"[Twitch] Category switch: {STATE.current_game} -> {game}")
                reset_session(game)

            if game == "VALORANT":
                rank_text, session_text = process_valorant()
            elif game == "LOL":
                rank_text, session_text = process_lol()
            else:
                log_info(f"[Twitch] Unsupported category '{game_name}', skipping update.")
                if stop_event and stop_event.wait(POLL_INTERVAL_SECONDS):
                    break
                continue

            rank_changed = rank_text != STATE.last_rank_pushed
            session_changed = session_text != STATE.last_session_pushed

            if CF_WORKER_BASE_URL and (rank_changed or session_changed):
                push_combined_update(rank_text, session_text)
                if rank_changed:
                    log_info(f"[Push:rank] {rank_text}")
                    STATE.last_rank_pushed = rank_text
                if session_changed:
                    log_info(f"[Push:streak] {session_text}")
                    STATE.last_session_pushed = session_text
            else:
                if rank_changed:
                    push_text(rank_update_url(), rank_text, "RANK")
                    STATE.last_rank_pushed = rank_text
                    log_info(f"[Push:rank] {rank_text}")

                if session_changed:
                    push_text(session_update_url(), session_text, "SESSION")
                    STATE.last_session_pushed = session_text
                    log_info(f"[Push:streak] {session_text}")

        except Exception as exc:
            log_error(f"[Error] {exc}")

        if stop_event and stop_event.wait(POLL_INTERVAL_SECONDS):
            break

    log_info("[Main] Monitor loop stopped.")
    stop_overlay_http_server()


def main() -> None:
    main_loop()


def _start_obs_monitor_thread() -> None:
    global MONITOR_THREAD
    # OBS can call load/reload hooks multiple times; always stop old thread first.
    if MONITOR_THREAD and MONITOR_THREAD.is_alive():
        _stop_obs_monitor_thread()
    STOP_EVENT.clear()
    MONITOR_THREAD = threading.Thread(
        target=main_loop, args=(STOP_EVENT,), name="StreamToolsMonitor", daemon=True
    )
    MONITOR_THREAD.start()
    log_info("[OBS] Monitor thread started.")


def _stop_obs_monitor_thread() -> None:
    global MONITOR_THREAD
    STOP_EVENT.set()
    if MONITOR_THREAD and MONITOR_THREAD.is_alive():
        MONITOR_THREAD.join(timeout=2.0)
    MONITOR_THREAD = None
    log_info("[OBS] Monitor thread stopped.")


def script_description():
    return "Stream-Tools monitor (Valorant + LoL rank/streak)."


def script_load(settings):
    # Called by OBS when script is loaded.
    _start_obs_monitor_thread()


def script_unload():
    # Called by OBS when script is unloaded / OBS closes.
    _stop_obs_monitor_thread()


if __name__ == "__main__":
    main()

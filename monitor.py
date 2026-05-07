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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()


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

# You can use one worker or two workers:
# - If CF_RANK_UPDATE_URL / CF_SESSION_UPDATE_URL are set, they are used.
# - Otherwise, CF_WORKER_UPDATE_URL is used for both.
CF_WORKER_UPDATE_URL = os.environ.get("CF_WORKER_UPDATE_URL", "").strip()
CF_RANK_UPDATE_URL = os.environ.get("CF_RANK_UPDATE_URL", "").strip()
CF_SESSION_UPDATE_URL = os.environ.get("CF_SESSION_UPDATE_URL", "").strip()
CF_UPDATE_TOKEN = os.environ.get("CF_UPDATE_TOKEN", "").strip()

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "20"))
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"


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
@dataclass
class ValorantSession:
    wins: int = 0
    losses: int = 0
    draws: int = 0
    rr_delta: int = 0
    last_seen_match_ids: Set[str] = field(default_factory=set)
    last_map: str = ""
    last_rr_change: int = 0


@dataclass
class LolSession:
    wins: int = 0
    losses: int = 0
    lp_delta: int = 0
    last_seen_match_ids: Set[str] = field(default_factory=set)
    last_champion: str = ""
    last_lp_change: int = 0
    last_known_score: Optional[int] = None


@dataclass
class RuntimeState:
    stream_live: bool = False
    stream_start: Optional[datetime] = None
    current_game: Optional[str] = None  # "VALORANT" | "LOL" | None
    last_rank_pushed: Optional[str] = None
    last_session_pushed: Optional[str] = None
    val: ValorantSession = field(default_factory=ValorantSession)
    lol: LolSession = field(default_factory=LolSession)


STATE = RuntimeState()


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


def rank_update_url() -> str:
    return CF_RANK_UPDATE_URL or CF_WORKER_UPDATE_URL


def session_update_url() -> str:
    return CF_SESSION_UPDATE_URL or CF_WORKER_UPDATE_URL


def push_text(url: str, text: str, label: str) -> None:
    if TEST_MODE:
        print(f"[TEST:{label}] {text}")
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
    started_at = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
    return True, started_at, row.get("game_name", "")


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
        dt = datetime.fromisoformat(match["date"].replace("Z", "+00:00"))
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
def main() -> None:
    require_env()

    print("[Main] Unified monitor started.")
    print(f"[Main] Poll interval: {POLL_INTERVAL_SECONDS}s")
    while True:
        try:
            is_live, started_at, game_name = fetch_twitch_stream()
            game = detect_game(game_name)

            if not is_live:
                if STATE.stream_live:
                    print("[Twitch] Stream offline, resetting live state.")
                STATE.stream_live = False
                STATE.stream_start = None
                STATE.current_game = None
                STATE.last_rank_pushed = None
                STATE.last_session_pushed = None
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Stream start
            if not STATE.stream_live:
                print(f"[Twitch] Live detected: {game_name}")
                STATE.stream_live = True
                STATE.stream_start = started_at
                reset_session(game)

            # Category switch while live
            if game and game != STATE.current_game:
                print(f"[Twitch] Category switch: {STATE.current_game} -> {game}")
                reset_session(game)

            if game == "VALORANT":
                rank_text, session_text = process_valorant()
            elif game == "LOL":
                rank_text, session_text = process_lol()
            else:
                print(f"[Twitch] Unsupported category '{game_name}', skipping update.")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            if rank_text != STATE.last_rank_pushed:
                push_text(rank_update_url(), rank_text, "RANK")
                STATE.last_rank_pushed = rank_text
                print(f"[Push:rank] {rank_text}")

            if session_text != STATE.last_session_pushed:
                push_text(session_update_url(), session_text, "SESSION")
                STATE.last_session_pushed = session_text
                print(f"[Push:session] {session_text}")

        except Exception as exc:
            print(f"[Error] {exc}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

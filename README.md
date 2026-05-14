# Stream-Tools

Stream-Tools is a local script for Twitch streamers.
It auto-detects your live game category (Valorant / LoL) and updates:

- `!rank`
- `!streak`

You can run it in terminal, or add `monitor.py` inside OBS Scripts.

## Output examples

`!rank`
- Valorant: `Ascendant 3 : 0 RR [-18]`
- LoL: `DIAMOND III : 16 LP [+42]`

`!streak`
- Valorant: `3W / 1L +28 RR | Last game : Split -20 RR`
- LoL: `7W / 2L +5 LP | Last game : Riven -58 LP`

Overlay examples:

![Valorant overlay](images/val.png)
![LoL overlay](images/lol.png)

## Installation (step by step)

### 1) Download and install dependencies

On Windows, run:

```bat
install.bat
```

### 2) Prepare Cloudflare Worker

Follow this full tutorial (with screenshots):

- [Cloudflare setup tutorial](./Cloudflare.md)

### 3) Create `.env`

Run:

```bat
create_env.bat
```

The script asks everything and creates `.env` for you.

### 4) Start monitor

```bat
python monitor.py
```

or inside OBS:

1. Open OBS
2. Click **Outils** -> **Scripts**
3. Click **+**
4. Select `monitor.py`

## What is needed in `.env`

`create_env.bat` fills all of this:

- `VAL_PUUID`
- `HENRIK_API_KEY`
- `VAL_REGION`
- `VAL_PLATFORM`
- `LOL_PUUID`
- `RIOT_API_KEY`
- `LOL_REGION`
- `LOL_PLATFORM`
- `TWITCH_CHANNEL`
- `TWITCH_CLIENT_ID`
- `TWITCH_ACCESS_TOKEN`
- `CF_WORKER_BASE_URL`
- `CF_UPDATE_TOKEN`
- `POLL_INTERVAL_SECONDS`
- `TEST_MODE`

## How to get each key/value

- Henrik API key (Valorant): [[https://docs.henrikdev.xyz](https://api.henrikdev.xyz/dashboard/)]
- Riot personal key type info: [https://developer.riotgames.com/app-type](https://developer.riotgames.com/app-type)
- Twitch access token + client id helper: [https://twitchtokengenerator.com](https://twitchtokengenerator.com)
- Cloudflare worker + KV setup: [Cloudflare.md](./Cloudflare.md)

## OBS overlay note

- Do not use `file://.../rank/overlay.html`
- Use the local HTTP URL printed in script log (Browser Source URL)

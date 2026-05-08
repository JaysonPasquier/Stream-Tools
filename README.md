# Stream-Tools

You can use Stream-Tools in two ways:
- outside OBS (run it manually with Python), or
- inside OBS (OBS launches the script when OBS starts, and stops it when OBS closes).

Stream-Tools is a local script for Twitch streamers.

It auto-detects if you are live on Valorant or League of Legends, then updates:

- `!rank` : `auto track your rank (valorant and/or league of legends)`
- `!streak` : `track your match history for valorant and/or league of legends of the stream only (reset on stream lunch)`

for your bot.

## What each command displays

`!rank`

- Valorant: `Ascendant 3 : 0 RR [-18]`
- LoL: `DIAMOND III : 16 LP [+42]`

`!streak`

- Valorant: `3W / 1L +28 RR | Last game : Split -20 RR`
- LoL: `7W / 2L +5 LP | Last game : Riven -58 LP`

## How it works

- `monitor.py` is the main script.
- One process handles both rank and streak.
- It uses Twitch category to switch automatically between Valorant and LoL.
- It pushes text to Cloudflare Worker endpoints.

## Quick start (Windows)

1. Install dependencies:

```bat
install.bat
```

2. Create your `.env` interactively:

```bat
create_env.bat
```

3. Start the monitor (or add it to obs script so it start on obs startup):

```bat
python monitor.py
```

## API keys you need

- Henrik API key (Valorant): [https://docs.henrikdev.xyz](https://docs.henrikdev.xyz)
- Riot API key (LoL): [https://developer.riotgames.com](https://developer.riotgames.com)

Riot note:

- Personal key: best choice for personal use or small private community projects.
- Get it here: [https://developer.riotgames.com/app-type](https://developer.riotgames.com/app-type)

## Twitch setup (Client ID + Access Token)

You need these in `.env`:

- `TWITCH_CHANNEL` (your channel login in lowercase)
- `TWITCH_CLIENT_ID`
- `TWITCH_ACCESS_TOKEN`

Get `TWITCH_ACCESS_TOKEN`:

1. Generate a user OAuth token
2. Quick option: [https://twitchtokengenerator.com](https://twitchtokengenerator.com)
3. Copy token to `TWITCH_ACCESS_TOKEN`

Official docs:

- [https://dev.twitch.tv/docs/authentication/getting-tokens-oauth](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth)

## Cloudflare setup guide

For a full step-by-step tutorial with screenshots, read:

- [Cloudflare setup tutorial](./Cloudflare.md)

## Add monitor.py to OBS

You can run the monitor directly inside OBS:

1. Open OBS
2. Click **Outils** -> **Scripts**
3. Click **+**
4. Select `monitor.py`

When loaded, the script starts automatically.
When OBS closes or you remove the script, it stops automatically.

Overlay note:

- Use OBS **Browser Source** with the local HTTP URL printed in the script log
- Do not use `file://.../overlay.html`

## Files

- `monitor.py`: main unified monitor
- `.env.example`: env template (placeholders only)
- `install.bat`: installs Python packages
- `create_env.bat`: interactive `.env` creator
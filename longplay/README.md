# VCMI Longplay fork

This repo is a fork of https://github.com/vcmi/vcmi

The aim of this experimental project is to introduce a long living campaign with multiple players without needing every player to be online at the same time.

Note!: This project is VERY experimental. Most of it has been vibed with locally hosted qwen3.6:35b, so please tone down you expectations.

<img width="543" height="382" alt="image" src="https://github.com/user-attachments/assets/092511c2-9e49-41fc-8b5c-617cce95980a" />
<img width="743" height="503" alt="image" src="https://github.com/user-attachments/assets/5b29a5d9-d7ad-47d9-b784-b1a692a83d2f" />
<img width="530" height="378" alt="image" src="https://github.com/user-attachments/assets/096a25ff-4cf8-4881-97d5-e3ccf86f51b8" />



Plan is the following:
- Remote host machine runs the client and allows web based desktop access
- Only the player with their turn can access the host (username/password auth) (admin account for maintenance)
- Rinse & repeat until game is over

All of the longplay code should exist under /longplay -directory, except when/if we need to modify the source for hooks etc.

Currently only works for coop scenarios, combat turns in a PVP scenario has not been implemented yet

## Building the source

Most of the VCMI source is unmodified, but there probably needs to be a couple of hooks for the host OS to allow correct users to log in to the system, hence why this is a fork.

All commands run from the root of this repo.

### Build the builder image

```
docker build -f longplay/builder/Dockerfile -t vcmi-builder ..
```

### Compile source within the container

```
docker run --rm -it -v "${PWD}:/src" vcmi-builder

cd src/longplay/builder/build

cmake -S ../../../ -DENABLE_CCACHE=OFF -DENABLE_TEST=OFF -DENABLE_MMAI=OFF -DENABLE_LAUNCHER=OFF -DENABLE_DISCORD=OFF -DCMAKE_BUILD_TYPE=Release -DENABLE_STATIC=ON

cmake --build . -j8

exit
```

Or just run ```build.bat```

Compiled binaries can be found in ```longplay/builder/build/bin/```

## vcmiclient modifications

Most of the source code modifications contain a comment // \_\_longplay\_\_ <- search for this in order to find longplay -related modifications

Listed some changes to vcmiclient

### Saving game on turn START

Default saving happens right before turn ends, therefor there is a modification to the autosave logic to happen right when next player's turn starts.
The reason being, that if player A ends his turn -> save happens here -> player B turn -> quit -> load -> it will still be player A turn

### Automatically skipping all dialogues

When player's turn starts, he is prompted with a dialogue of something like: "Player red's turn" with an accept button (sometimes some random events). 
We cannot have that, because in order to save the game right at next player's start -> we need to skip all these dialogues -> and perform a save.


## Docker compose and starting a game

To start a game, first one needs to configure the session, then just run docker compose.

### Environment variables, the game config

This happens by tweaking the ```env.conf``` file under /longplay.
Most of the env vars are quite self-explanatory. For map, just make sure to use the partial path like "Maps/Caught in the middle"
and not the full path (this is how vcmiclient reads the maps from $XDG_CONFIG_DIR (or something)).

Note!: It is recommended not to change these variables if you've already started a game, the whole system is heavily vibe-coded and is pretty fragile. So make sure to configure everything correctly,
before starting a game.

Note!: Note that only COOP scenarios are supported currently, so make sure to select a map where all the players are on the same side.

### Copy game data

Buy a copy of Heroes 3. Install it, and copy /Data, /Maps, and /Mp3 -directories to /longplay/host/gamedata/*

The folder structure should look like this:

- /longplay/host/gamedata
    - /Data
    - /Maps
    - /Mp3
    - /Mods (if any, like HOTA etc...)

### Starting a game

You've built vcmiclient and copied your Heroes 3 copy's game data to /longplay/host/gamedata, now it's time for you to start a game.
Just run:

```docker compose -f longplay/docker-compose.yml up --build```

Then just head to:

```http://localhost:8080/``` 

and login with a user configured in the previously mentioned env.conf

### Clearing saves / starting a new game

Saves dir is currently a named volume, so in order to get rid of the saves, you'll have to delete the previously created mount volume

```
docker compose down

docker volume ls

docker volume rm your_project_name_host-data
```

After that, you can reconfigure the env.conf and build/run docker compose again


## NGINX proxy

In docker-compose.yml you can find an nginx server.
This proxies all https traffic to http, since the remote desktop over the internet requires https.
For that one has to configure HTTPS/TLS certs, using for example, certbot.

If http will suffice, you can just comment out the whole nginx part, uncomment portal's ports and use those instead.


## Telegram bot

There are a couple env vars to configure a bot that sends messages to a channel, informing who's turn it is.

To set it up:
- Search for @BotFather on telegram
- send /newbot
- follow the instructions
- save the token it sends you
- create a channel
- add your previously created bot to the channel
- set the channel ID and bot token to env.conf

# Architecture overview

The whole system is constructed around 3 different services (see longplay/docker-compose.yml)

                    [ Internet / Client Browser ]
                                │
                                ▼ (HTTPS)
                        ┌───────────────┐
                        │  NGINX Proxy  │  (SSL Termination)
                        └───────┬───────┘
                                │
                                ▼ (HTTP / WebSockets)
                        ┌───────────────┐
                        │    Portal     │  (Auth, Turn Management, & Proxy)
                        └───────┬───────┘
                                │
                                ▼ (Local VNC/WebRTC)
                        ┌───────────────┐
                        │     Host      │  (Ubuntu KDE + VCMI Client)
                        └───────────────┘

## Host

Base Image: Built on lscr.io/linuxserver/webtop:ubuntu-kde, providing a lightweight, dockerized Ubuntu desktop environment running the KDE Plasma interface.

Remote Desktop Delivery: It exposes a built-in, WebSocket-based remote desktop interface (via Kasm/selkies), allowing full desktop interaction directly inside a web browser without external plugins.

Application Lifecycle: The host natively runs the vcmiclient. A supervisor script or daemon monitors the VCMI process, ensuring it automatically restarts and maintains its exact state if it ever closes or crashes.

## Portal

Authentication & Queue Management: Players log into this interface. The Portal tracks player turns, manages the queue, and grants desktop access only to the active player.

Traffic Reverse-Proxying: To prevent exposing the Host directly, all remote desktop traffic (WebSockets/HTTP) is reverse-proxied through the Portal.

Session Enforcement: The Portal actively monitors turns. The moment a player's turn ends, the Portal forcefully terminates their remote desktop WebSocket connection and transfers access rights to the next player in line (This happens by Host posting gamestate updates to Portal).

## NGINX (optional, but required for over-the-internet)

The NGINX service is an optional but highly recommended edge proxy, essential for over-the-internet deployment.

Host's desktop access requires https over the internet, so outside of LAN this seems to be required.

## Desktop volume control (`volume-hook.js`)

The portal page renders a small volume + mute widget for the Kasm/Selkies
remote desktop. Because Selkies plays audio through its own `AudioContext`
(not through a `<video>` element that inherits the surrounding page's
`volume` property), the standard `element.volume = ...` route reaches only
the raw stream's default level — Chromium/Edge plays it at 100 % on the
first ~100 ms after boot regardless of the level we wanted. On Firefox the
situation is easier, but on Chromium we need to *intercept* the client's own
audio graph. That is the job of `volume-hook.js`.

### Why it exists

- Selkies' audio path is a Web Audio `GainNode` (the "master" gain of the
  `AudioContext`'s output), not a `<video>` — setting the volume on a
  `<video>` has no effect on it.
- Selkies itself *resets* that master gain to 1.0 whenever the AudioContext
  reaches `"running"`, so any level we set before that transition is wiped.
- The user's preference lives in the parent portal's `localStorage`
  (`lp_volume` / `lp_muted`). Without a hook, the iframe audio starts at
  full volume (or a race-dependent level) for the first few hundred ms — an
  audible burst every time the desktop loads.

### How it works

1. **Gain-node capture.** The hook patches
   `AudioContext.prototype.createGain` (and the `webkitAudioContext`
   equivalent) to record every `GainNode` the client creates into a shared
   list. The patch is read-only: we never override `AudioParam.value` or
   `AudioParam.prototype.setValueAtTime`. Those native round-trip through
   each other internally on Chromium/Edge, and overriding either of them
   produces `RangeError: Maximum call stack size exceeded`. Keeping the
   native setters intact sidesteps that recursion on every engine.

2. **Seeding from `localStorage`.** The desktop iframe is served same-origin
   under `/desktop/` (reverse-proxied by the portal), so it shares
   `lp_volume` / `lp_muted` with the portal page. At IIFE evaluation time
   the hook reads those keys and seeds its internal target, so the *first*
   clamp it applies is already at the user's saved level — not 1.0.
   Visitors with no stored value stay muted, preserving "silent until the
   parent drives it" for new users.

3. **Synchronous clamp on node capture.** When a `GainNode` is captured the
   hook assigns `node.gain.value = <target>` *immediately* (not via
   `setValueAtTime`). `setValueAtTime` schedules against the context's
   clock, which on Firefox adds a frame of delay; the direct assignment
   applies the same tick. `setValueAtTime` is only used as a fallback in
   case an engine rejects the direct assignment while the context is not
   yet running. In addition to clamping every captured `GainNode`, the same
   pass also sets `volume` / `muted` on any `<video>` / `<audio>` element
   in the document — a belt-and-braces path for Kasm variants that expose
   their audio through HTML5 media rather than Web Audio. A re-entrancy
   guard makes the whole apply path idempotent if engine-internal code ever
   re-enters us.

4. **Bounded re-assert window.** `startReassert()` installs a `setInterval`
   that calls `applyToAll()` every 50 ms for ~40 ticks (≈2 s), then clears
   itself. It is idempotent: if one is already running, subsequent calls
   are no-ops. The window is armed from three places —

   - inside the `createGain` patch, right after a node is captured (this is
     the decisive one for the 50/50 race below),
   - inside a `statechange` listener on the AudioContext (covers the
     "context transitions to running *after* we captured" case), and
   - inside the `setVolume` control-surface entry point (covers live slider
     drives and the parent's first post-load drive).

   The window is intentionally short: long enough to out-race Selkies'
   post-running master-gain reset, short enough that we never pin the live
   param once the client is healthy.

5. **Control surface.** `window.__lpSetVolume(v, muted)` and a
   `postMessage('lp-set-volume', …)` listener let the parent drive the
   level at runtime. `index.html` polls every 50 → 150 → 500 ms up to 64
   attempts and calls either path; the hook's re-assert window then holds
   the level for the ~2 s in which Selkies' own audio graph settles.

### The 50/50 race (root cause of the "sometimes loads at 100 %" bug)

Before the `createGain`-side arm, only the `statechange` listener could
start the re-assert window. `statechange` fires **only on transitions**:

| Context state when `createGain` runs | `statechange` will fire? | Re-assert armed? | Outcome |
|---|---|---|---|
| Context still `suspended` / `idle` | Yes, later | ✅ | Clamp wins → correct level |
| Context already `running` | No (it already fired before the hook existed) | ❌ | Selkies' `master.gain = 1.0` reset sticks |

That second row is the 50/50: it depends on *when* the `AudioContext`
reaches `"running"` relative to when our patched `createGain` first
captures a node, which varies with network / CPU / Edge's tab-startup
scheduling. On the losing path, nothing else arms the re-assert window, so
the audible full-volume state persists until the user touches the slider —
which *does* arm it (because `setVolume` is one of the three armed-from
places). Arming from `createGain` closes the losing branch: the moment
Selkies creates any gain node we re-assert for ~2 s, so our clamp wins
regardless of when the context reaches running.

### Files involved

| File | Role |
|---|---|
| `portal/templates/volume-hook.js` | Hook injected into the iframe; owns gain capture, sync clamp, re-assert window, and the control surface. |
| `portal/templates/index.html` | Portal page: owns the slider UI, `localStorage` persistence, and drives the hook via `frame.contentWindow.__lpSetVolume` (with a `postMessage` fallback). |
| `portal/server.py` | Injects the hook as the *first* child of `<head>` in text/html responses reverse-proxied from the Selkies client, so it executes before the client's own scripts. |

### Debugging tips

- The hook runs inside the iframe. Open the iframe's DevTools (right-click
  the iframe → "Inspect element", or use the target's DevTools) to see its
  console.
- Stored values live in the parent origin's `localStorage` under
  `lp_volume` and `lp_muted`. Clearing them returns you to "start muted,
  first drive wins" baseline behaviour.
- If you ever see 100 % on load again with no slider interaction, first
  confirm the hook is actually in the served HTML (it must be the first
  `<script>` inside `<head>`). The server-side injection is gated on
  `VOLUME_HOOK_JS` being non-empty AND the proxied response being
  `text/html`. A change to either gate will silently disable the hook.

# HOTA (Horn of the abyss)

To activate HOTA, download the mod, place it under /longplay/host/gamedata/Mods,
and edit /longplay/host/modSettings.json to include it, or delete "hota" if not needed.

note: remember to pull/download appropriate HOTA version, since we are running "develop" (currently 1.8 in development) we have to make sure the mod is supported by core, for this you can pull from the HOTA repository a specific commit, and just zip the content-directory (this is how the mod is actually packaged)
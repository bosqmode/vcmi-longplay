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
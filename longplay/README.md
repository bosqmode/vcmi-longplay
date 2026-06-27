# VCMI Longplay fork

This repo is a fork of https://github.com/vcmi/vcmi

The aim of this project is to introduce a long living campaign with multiple players without needing every player to be online at the same time.

Plan is the following:
- Remote host machine runs the client and allows web based desktop access
- Only the player with their turn can access the host (username/password auth) (admin account for maintenance)
- Rinse & repeat until game is over

Things to consider:
- Copying savefiles from the host for backup
- Host shutdown/boot for cost optimization (imagine we host this on AWS and the server just keeps running for a week without anybody playing their turn?)
- WebUI for login & RDP, display who's turn it is, maybe a Telegram -bot?

All of the longplay code should exist under /longplay -directory, except when/if we need to modify the source for hooks etc.

## Building the source

Most of the VCMI source is unmodified, but there probably needs to be a couple of hooks for the host OS to allow correct users to log in to the system, hence why this is a fork.

All commands run from the root of this repo.

### Build the builder image

docker build -f longplay/builder/Dockerfile -t vcmi-builder ..

### Compile source within the container

docker run --rm -it -v "${PWD}:/src" vcmi-builder

cd src/longplay/builder/build

cmake -S ../../../ -DENABLE_CCACHE=OFF -DENABLE_TEST=OFF -DENABLE_MMAI=OFF -DENABLE_LAUNCHER=OFF -DCMAKE_BUILD_TYPE=Release -DENABLE_STATIC=ON

cmake --build . -j8

exit

Compiled binaries can be found in longplay/builder/build/bin/

## Building the host container

### Copy gamedata to /longplay/host/gamedata

Copy the installed game data (config/, Data/, Maps/ and Mp3/) to /longplay/host/gamedata/

Like this:
- /longplay/host/gamedata
    - /config
    - /Data
    - /Maps
    - /Mp3

### Build the host container

docker build -f longplay/host/Dockerfile -t vcmi-host .

### Start host container

docker run --rm --name vcmi_host -p 3000:3000 -p 3001:3001 vcmi-host

### Connecting

https://localhost:3000/
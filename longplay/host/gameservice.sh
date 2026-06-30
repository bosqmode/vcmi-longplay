#!/bin/bash
set -e

VCMI_BIN="/home/abc/VCMI/vcmiclient"
CHECK_INTERVAL=5

echo "Starting game service monitor..."

DISPLAY=":1"
export DISPLAY

echo "Using display: $DISPLAY"

# Wait for KDE desktop to be ready
sleep 5

export HOME=/home/abc
export XDG_DATA_HOME=/home/abc/.local/share
export LD_LIBRARY_PATH=/home/abc/VCMI:${LD_LIBRARY_PATH:-}
export XDG_RUNTIME_DIR=/config/.XDG
export PULSE_RUNTIME_PATH=/defaults

# Read custom environment variables set by docker-compose.yml
S6_ENV_DIR="/run/s6/container_environment/"
if [ -d "$S6_ENV_DIR" ]; then
    for env_file in "$S6_ENV_DIR"/*; do
        if [ -f "$env_file" ]; then
            varname=$(basename "$env_file")
            varvalue=$(cat "$env_file")
            export "${varname}=${varvalue}"
        fi
    done
fi

echo $MAP

# Main monitoring loop
while true; do
    if pgrep -f "$VCMI_BIN" > /dev/null 2>&1; then
        echo "vcmiclient is running (PID: $(pgrep -f "$VCMI_BIN" | head -1))"
    else
        echo "vcmiclient not found. Launching..."
        runuser abc -c "/home/abc/VCMI/vcmiclient --longplay-map \"$MAP\" --longplay-players \"$PLAYERS\" --longplay-factions \"$FACTIONS\" --longplay-difficulty \"$DIFFICULTY\"" 2>&1 &
        sleep 5
        xdotool search --name "vcmi" windowfocus >/dev/null 2>&1 || true
    fi
    sleep $CHECK_INTERVAL
done
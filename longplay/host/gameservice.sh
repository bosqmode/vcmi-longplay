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

get_latest_autosave_relative_path() {
    local save_base="/home/abc/.local/share/vcmi/Saves/Autosave"
    
    # ls -t sorts by modification time, most recent first
    local latest_file
    latest_file=$(find "$save_base" -type f -name "*.vsgm1" -size +0c -print0 2>/dev/null \
        | xargs -0 ls -t 2>/dev/null | head -n 1)
    
    if [ -n "$latest_file" ]; then
        local relative_path="${latest_file#$save_base}"
        echo "Saves/Autosave${relative_path%/}"
    fi
}

# Main monitoring loop
while true; do
    if pgrep -f "$VCMI_BIN" > /dev/null 2>&1; then
        echo "vcmiclient is running (PID: $(pgrep -f "$VCMI_BIN" | head -1))"
    else
        echo "vcmiclient not found. Launching..."

        echo "Checking for saves..."
        AUTOSAVE_RELATIVE_PATH=$(get_latest_autosave_relative_path)
        echo "Save file is: $AUTOSAVE_RELATIVE_PATH"

        if [ -n "$AUTOSAVE_RELATIVE_PATH" ]; then
            echo "Loading from save"
            runuser abc -c "/home/abc/VCMI/vcmiclient --longplay-players \"$PLAYERS\" --longplay-load-save \"$AUTOSAVE_RELATIVE_PATH\"" 2>&1 &
        else
            echo "No autosave found. starting new game..."
            runuser abc -c "/home/abc/VCMI/vcmiclient --longplay-map \"$MAP\" --longplay-players \"$PLAYERS\" --longplay-factions \"$FACTIONS\" --longplay-difficulty \"$DIFFICULTY\"" 2>&1 &
        fi
        sleep 5
        xdotool search --name "vcmi" windowfocus >/dev/null 2>&1 || true
    fi
    sleep $CHECK_INTERVAL
done
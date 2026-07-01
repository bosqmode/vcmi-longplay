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
    
    # Use -maxdepth to only find files directly in Autosave, not nested dirs
    # Also verify it's a regular file (not a directory)
    local latest_file=""
    local latest_mtime=0
    
    while IFS= read -r -d '' file; do
        if [ -f "$file" ] && [ "$file" != "$save_base" ]; then
            local mtime
            mtime=$(stat -c %Y "$file" 2>/dev/null || echo 0)
            if [ "$mtime" -gt "$latest_mtime" ]; then
                latest_mtime=$mtime
                latest_file="$file"
            fi
        fi
    done < <(find "$save_base" -type f -name "*.vsgm1" -size +0c -print0 2>/dev/null)
    
    if [ -n "$latest_file" ] && [ -f "$latest_file" ]; then
        # Extract the relative path from Autosave directory
        local rel_dir
        rel_dir=$(realpath --relative-to="$save_base" "$(dirname "$latest_file")")
        local rel_file
        rel_file=$(basename "$latest_file")
        echo "Saves/Autosave/${rel_dir}/${rel_file}"
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
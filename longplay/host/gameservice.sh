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

# Ensure X11 authorization is available for abc user
if [ -f /home/abc/.Xauthority ]; then
    export XAUTHORITY=/home/abc/.Xauthority
elif [ -f /root/.Xauthority ]; then
    export XAUTHORITY=/root/.Xauthority
fi

echo "XAUTHORITY=$XAUTHORITY"

# Main monitoring loop
while true; do
    if pgrep -f "$VCMI_BIN" > /dev/null 2>&1; then
        echo "vcmiclient is running (PID: $(pgrep -f "$VCMI_BIN" | head -1))"
    else
        echo "vcmiclient not found. Launching..."
        runuser -u abc -- "/home/abc/VCMI/vcmiclient" 2>&1 &
        sleep 5
        xdotool search --name "vcmi" windowfocus >/dev/null 2>&1 || true
    fi
    sleep $CHECK_INTERVAL
done
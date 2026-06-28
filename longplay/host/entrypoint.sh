#!/bin/bash
set -e

USERNAME="${USERNAME:-abc}"
SOCKET_PATH="/tmp/longplay-autosave.sock"
SAVE_SERVICE="/home/${USERNAME}/saveservice.py"

# Clean up stale socket from previous runs
if [ -f "$SOCKET_PATH" ]; then
    rm -f "$SOCKET_PATH"
fi

chmod 1777 /tmp

# DROP PRIVILEGES HERE: 
# This tells the system: "Switch to user 'abc', then run my Python script"
#exec s6-setuidgid ${USERNAME} python3 -u "$SAVE_SERVICE" 2>&1

python3 -u "$SAVE_SERVICE" 2>&1
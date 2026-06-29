#!/bin/bash
set -e

chmod 1777 /tmp

echo "starting gamestateservice.py -service..."
python3 -u "/gamestateservice.py" 2>&1



# DROP PRIVILEGES HERE: 
# This tells the system: "Switch to user 'abc', then run my Python script"
#exec s6-setuidgid ${USERNAME} python3 -u "$GAMESTATE_SERVICE" 2>&1
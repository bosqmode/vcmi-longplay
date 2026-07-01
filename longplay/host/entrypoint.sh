#!/bin/bash
set -e

chmod 1777 /tmp

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

echo "starting gamestateservice.py -service..."
python3 -u "/gamestateservice.py" 2>&1



# DROP PRIVILEGES HERE: 
# This tells the system: "Switch to user 'abc', then run my Python script"
#exec s6-setuidgid ${USERNAME} python3 -u "$GAMESTATE_SERVICE" 2>&1
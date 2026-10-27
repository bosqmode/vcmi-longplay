import os
import socket
import select
import asyncio
import glob
import subprocess
import aiohttp
import json

print("Starting gamestateservice.py")

# Load the portal API key from environment to authenticate with the portal service
PORTAL_APIKEY = os.environ.get("PORTAL_APIKEY", "")

# Socket paths mapped to their purpose
SOCKET_ROUTES = {
    "/tmp/longplay-autosave.sock": "autosave",
    "/tmp/longplay-gamestate.sock": "gamestate",
    "/tmp/longplay-start.sock": "start"
}

# Portal endpoints
POST_SAVE_URL = "http://portal:8000/saves"
POST_GAMESTATE_UPDATE = "http://portal:8000/gamestate"
POST_START = "http://portal:8000/start"
POST_REPLAY_URL = "http://portal:8000/replays/upload"

# Replay ring buffer (written by replayservice; see /custom-services.d/replayservice)
RING_DIR = os.environ.get("REPLAY_RING_DIR", "/home/abc/replay/ring")
_replay_inflight = False   # safety net (single-threaded loop)
_previous_player = None

# Create all sockets
sockets = []
for path, route_type in SOCKET_ROUTES.items():
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    if os.path.exists(path):
        os.remove(path)
    server.bind(path)
    os.chmod(path, 0o666)
    server.listen(5)
    sockets.append((path, route_type, server))
    print(f"Listening on {path} for {route_type}")


async def upload_save_post(filepath: str):
    """Upload a save file to the portal."""
    filepath = filepath.strip()
    if not filepath:
        print("No file path received for autosave")
        return
    
    print(f"upload_save_post: uploading {filepath}")
    
    try:
        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            if os.path.exists(filepath):
                data.add_field('file', open(filepath, 'rb'))
            else:
                print(f"Warning: save file not found at {filepath}")
            
            async with session.post(POST_SAVE_URL, data=data) as response:
                if response.status == 200:
                    print(f"Successfully uploaded save to endpoint {POST_SAVE_URL}")
                else:
                    print(f"Failed uploading save: {response.status} - {await response.text()}")
    except Exception as e:
        print(f"Error uploading save: {e}")

def _build_ring_snapshot():
    """Concatenate ALL ring segments and re-encode: 640w, 10 fps, CRF 30. Returns path or None."""
    global _replay_inflight
    if _replay_inflight:
        return None
    _replay_inflight = True
    try:
        # rec_<YYYYMMDDHHMMSS>.mp4  ->  name sort == chronological order
        segs = sorted(glob.glob(os.path.join(RING_DIR, "rec_*.mp4")))
        if not segs:
            return None  # ring not warmed up yet
        out_path = "/tmp/replay_latest.mp4"
        list_path = "/tmp/replay_concat_list.txt"
        with open(list_path, "w") as f:
            for p in segs:
                f.write("file '%s'\n" % p)
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", list_path,   # all segments, one input
            "-vf", "scale=640:-2",                            # 640px wide, AR preserved, even height
            "-r", "10",                                       # cap framerate to 10
            "-c:v", "libx264", "-crf", "30", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-an",                                            # no audio track
            "-movflags", "+faststart", out_path,
        ], check=True, timeout=60)
        return out_path
    except Exception as e:
        print(f"[replay] snapshot build failed: {e}")
        return None
    finally:
        _replay_inflight = False


async def upload_replay(path):
    files = open(path, "rb")
    try:
        data = aiohttp.FormData()
        data.add_field("file", files)
        headers = {"X-Portal-Apikey": PORTAL_APIKEY} if PORTAL_APIKEY else {}
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(POST_REPLAY_URL, data=data, headers=headers) as r:
                print(f"[replay] upload {r.status}: {(await r.text())[:200]}")
    finally:
        files.close()


def build_ring_and_upload_replay():
    """Capture + upload the last 30s."""
    print("upload replay called")
    snap = _build_ring_snapshot()
    if snap:
        try:
            asyncio.run(upload_replay(snap))     # matches existing asyncio.run pattern
        except Exception as e:
            print(f"[replay] upload failed: {e}")
    else:
        print("[replay] no snapshot (ring not warmed up or busy)")

async def post_gamestate(data: str):
    try:
        headers = {}
        if PORTAL_APIKEY:
            headers["X-Portal-Apikey"] = PORTAL_APIKEY
        
        async with aiohttp.ClientSession() as session:
            async with session.post(POST_GAMESTATE_UPDATE, json=data, headers=headers):
                pass  # Context manager sends the request, body is ignored
    except Exception as e:
        print(f"Error posting gamestate: {e}")


def handle_gamestate(data: str):
    gamestate = data.strip()
    player, day, color = gamestate.split(':')
    data = {"player": player, "day": int(day), "playerColor": color}
    asyncio.run(post_gamestate(data))

    global _previous_player
    if _previous_player != player:
        if _previous_player is not None:
            build_ring_and_upload_replay()
        _previous_player = player

async def post_start(msg: str):
    try:
        headers = {}
        if PORTAL_APIKEY:
            headers["X-Portal-Apikey"] = PORTAL_APIKEY
        
        async with aiohttp.ClientSession() as session:
            async with session.post(POST_START, data=msg, headers=headers):
                pass  # Context manager sends the request, body is ignored
    except Exception as e:
        print(f"Error posting gamestate: {e}")

def handle_start(msg: str):
    message = msg.strip()
    asyncio.run(post_start(msg))

SOCKET_HANDLERS = {
    "gamestate": handle_gamestate,
    "start": handle_start
}

while True:
    # Extract just the server socket objects for select()
    server_sockets = [s[2] for s in sockets]
    readable, _, _ = select.select(server_sockets, [], [])
    for server in readable:
        # Find which route this server corresponds to
        route_type = None
        for path, rt, srv in sockets:
            if srv == server:
                route_type = rt
                break
        try:
            connection, _ = server.accept()
            with connection:
                data = connection.recv(4096).decode('utf-8')
                handler = SOCKET_HANDLERS.get(route_type)
                if handler:
                    handler(data)
                else:
                    print(f"Unknown route type: {route_type}")
        except Exception as e:
            print(f"Error handling socket message: {e}")
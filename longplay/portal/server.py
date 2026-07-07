import os
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, WebSocket, Request, HTTPException, Header, Depends
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import httpx
import websockets
import requests

app = FastAPI(title="VCMI Portal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEBTOP_HTTP_URL = "http://host:3000"
WEBTOP_WS_URL = "ws://host:3000"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_CHANNEL_ID = os.environ.get("TELEGRAM_BOT_CHANNEL_ID", "")

active_sessions: dict[str, WebSocket] = {}
current_gamestate = {}

def send_telegram_message(message):
    if TELEGRAM_BOT_CHANNEL_ID == "" or TELEGRAM_BOT_TOKEN == "":
        return
    
    TOKEN = TELEGRAM_BOT_TOKEN
    CHAT_ID = TELEGRAM_BOT_CHANNEL_ID
    
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")


send_telegram_message("Turnbot initialized!")

# ── Credential loading from os.environ (loaded by docker-compose) ─────

def _load_credentials_from_env() -> tuple[dict[str, str], dict[str, str]]:
    """Load PLAYERS/PLAYER_PASSWORDS and ADMIN/ADMIN_PASSWORD from environment variables."""
    players_str = os.environ.get("PLAYERS", "")
    passwords_str = os.environ.get("PLAYER_PASSWORDS", "")
    admin_user = os.environ.get("ADMIN", "")
    admin_pass = os.environ.get("ADMIN_PASSWORD", "")

    player_creds: dict[str, str] = {}
    admin_creds: dict[str, str] = {}

    players_list = [p.strip() for p in players_str.split(",") if p.strip()]
    passwords_list = [p.strip() for p in passwords_str.split(",") if p.strip()]

    # Pair players with passwords positionally
    for i, player in enumerate(players_list):
        if i < len(passwords_list):
            player_creds[player] = passwords_list[i]

    if admin_user and admin_pass:
        admin_creds[admin_user] = admin_pass

    return player_creds, admin_creds


PLAYER_CREDENTIALS, ADMIN_CREDENTIALS = _load_credentials_from_env()

# ── Portal API key for internal service authentication ─────────────────

PORTAL_APIKEY = os.environ.get("PORTAL_APIKEY", "")


async def validate_portal_apikey(x_portal_apikey: str | None = Header(default=None)) -> None:
    """Validate requests using the PORTAL_APIKEY environment variable.
    
    If PORTAL_APIKEY is not set, validation is skipped (useful for local development).
    """
    if not PORTAL_APIKEY:
        return  # Skip validation if API key not configured
    
    if x_portal_apikey != PORTAL_APIKEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


# ── Rate limiting for /auth/login ─────────────────────────────────────

class RateLimiter:
    """Simple in-memory sliding-window rate limiter per IP."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = {}

    def is_allowed(self, ip: str) -> bool:
        now = asyncio.get_event_loop().time() if not hasattr(asyncio.get_event_loop(), "new_event_loop") else __import__("time").time()
        window_start = now - self.window_seconds
        # Clean old entries
        self._attempts.setdefault(ip, [])
        self._attempts[ip] = [t for t in self._attempts[ip] if t > window_start]
        if len(self._attempts[ip]) >= self.max_attempts:
            return False
        self._attempts[ip].append(now)
        return True


_login_limiter = RateLimiter(max_attempts=5, window_seconds=60)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Authentication helpers ────────────────────────────────────────────

def _parse_token(token: str | None) -> tuple[str, str] | None:
    """Split token on last ':' to get (username, password). Returns None if invalid."""
    if not token or ":" not in token:
        return None
    username, password = token.rsplit(":", 1)
    if not username or not password:
        return None
    return (username, password)


def _validate_credentials(username: str, password: str) -> bool:
    return (PLAYER_CREDENTIALS.get(username) == password) or (ADMIN_CREDENTIALS.get(username) == password)


async def verify_token_gamestate(request: Request | None = None, authorization: str | None = Header(default=None)) -> str | None:
    """checks access to fetch gamestate. Uses 'lp-token' cookie/query param to avoid conflicts with webtop's own token system."""
    resolved_token = request.cookies.get("lp-token")
    if not resolved_token and authorization and authorization.startswith("Bearer "):
        resolved_token = authorization[7:] # strips "Bearer "
    if not resolved_token and request.query_params.get("lp-token"):
        resolved_token = request.query_params.get("lp-token")

    creds = _parse_token(resolved_token)
    if not creds or not _validate_credentials(creds[0], creds[1]):
        raise HTTPException(status_code=403, detail="Invalid credentials")

    return creds[0]

async def verify_token_desktop(request: Request | None = None, authorization: str | None = Header(default=None)) -> str | None:
    """checks access to fetch desktop. Uses 'lp-token' cookie/query param (same as other API endpoints) to avoid conflicts with webtop's own token system."""
    # Extract token using same logic as gamestate endpoint: lp-token cookie, then Bearer header, then lp-token query param
    resolved_token = request.cookies.get("lp-token") if request else None
    if not resolved_token and authorization and authorization.startswith("Bearer "):
        resolved_token = authorization[7:]
    if not resolved_token and request and request.query_params.get("lp-token"):
        resolved_token = request.query_params.get("lp-token")

    creds = _parse_token(resolved_token)
    if not creds or not _validate_credentials(creds[0], creds[1]):
        raise HTTPException(status_code=403, detail="Invalid credentials")
    
    user = creds[0]
    
    # Also check turn-based access for players (admins bypass turn check)
    current_player = current_gamestate.get("player", None)
    if current_player is not None:
        if user not in ADMIN_CREDENTIALS and user != current_player:
            raise HTTPException(status_code=403, detail="Not your turn")

    return user

@app.post("/auth/login")
async def auth_login(request: Request):
    """Authenticate username+password and return a token string."""
    data = await request.json()
    username = (data.get("username", "") or "").strip()
    password = (data.get("password", "") or "").strip()

    if not username or not password:
        raise HTTPException(status_code=400, detail="Missing username or password")

    ip = _get_client_ip(request)
    if not _login_limiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too many login attempts, try again later")

    if not _validate_credentials(username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = f"{username}:{password}"
    is_admin = username in ADMIN_CREDENTIALS
    return {"status": "ok", "username": username, "token": token, "isAdmin": is_admin}

@app.get("/")
async def serve_index():
    return FileResponse("templates/index.html")


@app.api_route("/desktop/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_http(path: str, request: Request, authorization: str | None = Header(default=None)):
    try:
        await verify_token_desktop(authorization=authorization, request=request)

        headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "accept-encoding"]}
        headers["accept-encoding"] = "identity"
        # Strip ALL token-like query params before forwarding to webtop to avoid conflicts with webtop's own token system
        filtered_params = {k: v for k, v in request.query_params.items() if k not in ("token", "lp-token")}

        async with httpx.AsyncClient() as client:
                url = f"{WEBTOP_HTTP_URL}/{path}"
                proxied_res = await client.request(
                    method=request.method,
                    url=url,
                    headers=headers,
                    params=filtered_params if filtered_params else None
                )
                
                exclude_headers = ["content-length", "connection"]
                response_headers = {k: v for k, v in proxied_res.headers.items() if k.lower() not in exclude_headers}
                
                return StreamingResponse(
                    proxied_res.aiter_bytes(),
                    status_code=proxied_res.status_code,
                    headers=response_headers
                )
    except HTTPException:
        return StreamingResponse(iter([b'<html><body>Access denied. Not your turn.</body></html>']), status_code=403, headers={"content-type": "text/html"})

@app.websocket("/desktop/websockets")
async def proxy_websocket(websocket: WebSocket):
    # Overriding standard check by manually accepting the connection 
    # to bypass FastAPI's automatic 403 origin guard
    await websocket.accept()
    
    # Extract longplay API token from cookie or query param (use 'lp-token' to avoid conflicts with webtop's own token system)
    cookie_header = websocket.headers.get("cookie", "")
    lp_token = None
    if cookie_header:
        for cookie in cookie_header.split(";"):
            name, value = cookie.strip().split("=", 1)
            if name == "lp-token":
                lp_token = value
    if not lp_token:
        lp_token = websocket.query_params.get("lp-token")

    # Also check Authorization header
    auth_header = websocket.headers.get("authorization", "")
    if not lp_token and auth_header.startswith("Bearer "):
        lp_token = auth_header[7:]

    # Validate credentials using our API token
    creds = _parse_token(lp_token)
    if not creds or not _validate_credentials(creds[0], creds[1]):
        await websocket.close(code=4001, reason="Invalid credentials")
        return

    # Turn-based check (admins bypass)
    current_player = current_gamestate.get("player", None)
    if current_player is not None and creds[0] not in ADMIN_CREDENTIALS:
        # Compare USERNAME from token, not the full token string
        if creds[0] != current_player:
            await websocket.close(code=4001, reason="Not your turn")
            return

    active_sessions[lp_token] = websocket

    # Forward to Webtop's exact internal websocket endpoint
    async with websockets.connect(f"{WEBTOP_WS_URL}/websockets") as target_ws:
        async def client_to_webtop():
            try:
                while True:
                    # Capture text or bytes dynamically
                    message = await websocket.receive()
                    if "bytes" in message:
                        await target_ws.send(message["bytes"])
                    elif "text" in message:
                        await target_ws.send(message["text"])
            except Exception:
                pass

        async def webtop_to_client():
            try:
                while True:
                    data = await target_ws.recv()
                    if isinstance(data, bytes):
                        await websocket.send_bytes(data)
                    else:
                        await websocket.send_text(data)
            except Exception:
                pass

        await asyncio.gather(client_to_webtop(), webtop_to_client())

async def turn_monitor():
    """Background task that checks turn changes and kicks disconnected players"""
    global CURRENT_PLAYER_INDEX
    while True:
        await asyncio.sleep(2)  # Check every 2 seconds
        
        current_player = current_gamestate.get("player", None)
        
        if current_player is None:
            continue

        print(f"ws active sessions: {len(active_sessions.items())}")

        # Close sessions for players who no longer have their turn (admins are never kicked)
        for player_id, ws in list(active_sessions.items()):
            # Extract username from token (format: username:password)
            session_username = player_id.split(":")[0] if ":" in player_id else player_id
            if session_username != current_player and session_username not in ADMIN_CREDENTIALS:
                try:
                    await ws.close(code=4001, reason="Your turn has ended")
                    del active_sessions[player_id]
                    print(f"Kicked {session_username}, it's now {current_player}'s turn")
                except Exception as e:
                    print(f"Error closing session for {player_id}: {e}")
        
        # Clean up any already-closed sessions
        dead_sessions = [pid for pid, ws in active_sessions.items() if ws.client_state.name == 'DISCONNECTED']
        for pid in dead_sessions:
            del active_sessions[pid]

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(turn_monitor())

@app.post("/gamestate", dependencies=[Depends(validate_portal_apikey)])
async def update_gamestate(request: Request):
    data = await request.json()
    previous_player = current_gamestate.get("player", None)
    current_gamestate.update({
        "player": data.get("player", None),
        "day": data.get("day", 0),
        "playerColor": data.get("playerColor", None),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    new_player = current_gamestate.get("player", None)

    if previous_player != new_player:
        send_telegram_message(f"*Turn Update* {new_player}'s turn!") # should be converted to async

    print(f"Gamestate update: {current_gamestate['player']}, {current_gamestate['playerColor']}, {current_gamestate['day']}, {current_gamestate['timestamp']}")
    return {"status": "ok"}

@app.get("/gamestate")
async def get_gamestate(request: Request, authorization: str | None = Header(default=None)):
    await verify_token_gamestate(authorization=authorization, request=request)
    return current_gamestate

@app.post("/start", dependencies=[Depends(validate_portal_apikey)])
async def start_post(request: Request):
    body_bytes = await request.body()
    data = body_bytes.decode("utf-8")
    print(f"received start post: {data}")
    send_telegram_message(f"gameservice.sh: {data}")
    return {"status": "ok"}

# old save stuff, maybe one day...
class SaveInfo(BaseModel):
    name: str
    size: int
    uploaded_at: str

@app.post("/saves", dependencies=[Depends(validate_portal_apikey)])
async def upload_save(file: UploadFile = File(...)):
    print(f"saveserver.py::saves() unimplemented")
    return {"status": "ok"}

@app.get("/saves", dependencies=[Depends(validate_portal_apikey)])
async def list_saves() -> list[SaveInfo]:
    print(f"saveserver.py::list_saves() unimplemented")
    return {"status": "ok"}

@app.get("/saves/{filename}", dependencies=[Depends(validate_portal_apikey)])
async def download_save(filename: str):
    print(f"saveserver.py::download_save() unimplemented")
    return {"status": "ok"}

@app.delete("/saves/{filename}", dependencies=[Depends(validate_portal_apikey)])
async def delete_save(filename: str):
    print(f"saveserver.py::delete_save() unimplemented")
    return {"status": "ok"}

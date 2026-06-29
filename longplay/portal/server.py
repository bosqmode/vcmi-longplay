import os
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
from fastapi import FastAPI, WebSocket, Request, HTTPException
from fastapi.responses import StreamingResponse
import httpx
import websockets

app = FastAPI(title="VCMI Save Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TEST_PLAYERS = ["P1", "P2", "P3"]
CURRENT_PLAYER_INDEX = 0

WEBTOP_HTTP_URL = "http://host:3000"
WEBTOP_WS_URL = "ws://host:3000"

SAVES_DIR = Path(os.environ.get("SAVES_DIR", "/saves"))
SAVES_DIR.mkdir(parents=True, exist_ok=True)
active_sessions: dict[str, WebSocket] = {}

class SaveInfo(BaseModel):
    name: str
    size: int
    uploaded_at: str

def verify_token(token: str = None, request: Request = None):
    if not token and request:
        token = request.cookies.get("desktop_token")
    
    if token != TEST_PLAYERS[CURRENT_PLAYER_INDEX]:
        raise HTTPException(status_code=403, detail="Not your turn")

@app.post("/saves")
async def upload_save(file: UploadFile = File(...)):
    print(f"saveserver.py::upload_save()")
    save_path = SAVES_DIR / file.filename
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)
    return {"filename": file.filename, "status": "uploaded"}


@app.get("/saves")
async def list_saves() -> list[SaveInfo]:
    print(f"saveserver.py::list_saves()")
    saves = []
    for save_file in SAVES_DIR.iterdir():
        if save_file.is_file():
            stat = save_file.stat()
            saves.append(
                SaveInfo(
                    name=save_file.name,
                    size=stat.st_size,
                    uploaded_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                )
            )
    return sorted(saves, key=lambda s: s.name)


@app.get("/saves/{filename}")
async def download_save(filename: str):
    print(f"saveserver.py::download_save()")
    save_path = SAVES_DIR / filename
    if not save_path.exists():
        return {"error": "Save not found"}
    return FileResponse(save_path, media_type="application/octet-stream", filename=filename)


@app.delete("/saves/{filename}")
async def delete_save(filename: str):
    print(f"saveserver.py::delete_save()")
    save_path = SAVES_DIR / filename
    if save_path.exists():
        save_path.unlink()
        return {"status": "deleted"}
    return {"error": "Save not found"}

@app.get("/")
async def serve_index():
    return FileResponse("templates/index.html")


@app.api_route("/desktop/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_http(path: str, request: Request, token: str = None):
    try:
        if not token:
            token = request.cookies.get("desktop_token")

        verify_token(token)

        headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "accept-encoding"]}
        headers["accept-encoding"] = "identity"

        async with httpx.AsyncClient() as client:
                url = f"{WEBTOP_HTTP_URL}/{path}"
                proxied_res = await client.request(
                    method=request.method,
                    url=url,
                    headers=headers,
                    params=request.query_params
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
    
    cookie_header = websocket.headers.get("cookie", "")
    
    # Parse the cookie string manually
    token = None
    if cookie_header:
        for cookie in cookie_header.split(";"):
            name, value = cookie.strip().split("=", 1)
            if name == "desktop_token":
                token = value
    
    if not token:
        token = websocket.query_params.get("token")

    if not token or token != TEST_PLAYERS[CURRENT_PLAYER_INDEX]:
        await websocket.close(code=4001, reason="Not your turn")
        return

    active_sessions[token] = websocket

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


@app.get("/api/turn-status")
async def get_turn_status():
    """Returns current turn state for frontend polling"""
    return {
        "current_player": TEST_PLAYERS[CURRENT_PLAYER_INDEX],
        "players": TEST_PLAYERS,
        "turn_index": CURRENT_PLAYER_INDEX
    }

@app.post("/api/turn-status")
async def advance_turn():
    """Test endpoint to simulate turn advancement"""
    global CURRENT_PLAYER_INDEX
    CURRENT_PLAYER_INDEX = (CURRENT_PLAYER_INDEX + 1) % len(TEST_PLAYERS)
    return {"current_player": TEST_PLAYERS[CURRENT_PLAYER_INDEX]}


async def turn_monitor():
    """Background task that checks turn changes and kicks disconnected players"""
    global CURRENT_PLAYER_INDEX
    while True:
        await asyncio.sleep(2)  # Check every 2 seconds
        
        print("Checking turns...")
        print(f"{TEST_PLAYERS[CURRENT_PLAYER_INDEX]}")
        print(f"Sessions: {[x for x in active_sessions.keys()]}")

        current_player = TEST_PLAYERS[CURRENT_PLAYER_INDEX]
        
        # Close sessions for players who no longer have their turn
        for player_id, ws in list(active_sessions.items()):
            if player_id != current_player:
                try:
                    await ws.close(code=4001, reason="Your turn has ended")
                    del active_sessions[player_id]
                    print(f"Kicked {player_id}, it's now {current_player}'s turn")
                except Exception as e:
                    print(f"Error closing session for {player_id}: {e}")
        
        # Clean up any already-closed sessions
        dead_sessions = [pid for pid, ws in active_sessions.items() if ws.client_state.name == 'DISCONNECTED']
        for pid in dead_sessions:
            del active_sessions[pid]

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(turn_monitor())


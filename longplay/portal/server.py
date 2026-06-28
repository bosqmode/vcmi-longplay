import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketDisconnect as StarletteWebSocketDisconnect
import websockets as ws_lib
import ssl
import asyncio
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import StreamingResponse
import httpx
import websockets

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

app = FastAPI(title="VCMI Save Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEBTOP_HTTP_URL = "http://host:3000"
WEBTOP_WS_URL = "ws://host:3000"

SAVES_DIR = Path(os.environ.get("SAVES_DIR", "/saves"))
SAVES_DIR.mkdir(parents=True, exist_ok=True)


class SaveInfo(BaseModel):
    name: str
    size: int
    uploaded_at: str

def verify_token(token: str = None):
    # Replace this with your actual database lookup or JWT validation
    # if token != "my_secret_gatekeeper_token":
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED, 
    #         detail="Invalid or missing API token"
    #     )
    print("asd")

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

@app.websocket("/desktop/ws")
async def websocket_desktop_proxy(websocket: WebSocket):
    """Proxy WebSocket connection to host webtop streaming"""
    await websocket.accept()
    
    # Connect to host's webtop websocket endpoint
    import websockets as ws_lib
    async with ws_lib.connect(
        "wss://host:3001/websocket",
        ssl=ssl_context,
        extra_headers={"Host": "host:3001"}
    ) as host_ws:
        # Bidirectional proxy
        async def client_to_host():
            try:
                while True:
                    message = await websocket.receive_text()
                    await host_ws.send(message)
            except WebSocketDisconnect:
                pass
        
        async def host_to_client():
            try:
                while True:
                    message = await host_ws.recv()
                    await websocket.send_text(message)
            except WebSocketDisconnect:
                pass
        
        # Run both directions concurrently
        import asyncio
        await asyncio.gather(
            client_to_host(),
            host_to_client(),
            return_exceptions=True
        )

@app.get("/")
async def serve_index():
    return FileResponse("templates/index.html")


@app.api_route("/desktop/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_http(path: str, request: Request, token: str = None):
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
    
@app.websocket("/websockify")
async def proxy_websocket(websocket: WebSocket, token: str = None):
    """
    Intercepts the WebSocket handshake, checks auth, and tunnels 
    the raw remote desktop data frames to and from the Webtop container.
    """
    # # Guard check for WebSockets
    # if token != "my_secret_gatekeeper_token":
    #     await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    #     return

    await websocket.accept()

    # Establish connection to the backend Webtop container
    async with websockets.connect(f"{WEBTOP_WS_URL}/websockify") as target_ws:
        
        # Helper to pipe data from Client -> Webtop
        async def client_to_webtop():
            try:
                while True:
                    data = await websocket.receive_bytes()
                    await target_ws.send(data)
            except WebSocketDisconnect:
                pass
            except Exception:
                await target_ws.close()

        # Helper to pipe data from Webtop -> Client
        async def webtop_to_client():
            try:
                while True:
                    data = await target_ws.recv()
                    await websocket.send_bytes(data)
            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception:
                await websocket.close()

        # Run both listeners concurrently
        await asyncio.gather(client_to_webtop(), webtop_to_client())


@app.websocket("/desktop/websockets")
async def proxy_websocket(websocket: WebSocket):
    # Overriding standard check by manually accepting the connection 
    # to bypass FastAPI's automatic 403 origin guard
    await websocket.accept()
    
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
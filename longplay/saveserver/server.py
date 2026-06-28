import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="VCMI Save Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SAVES_DIR = Path(os.environ.get("SAVES_DIR", "/saves"))
SAVES_DIR.mkdir(parents=True, exist_ok=True)


class SaveInfo(BaseModel):
    name: str
    size: int
    uploaded_at: str


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
# Plan: "Last 30 seconds up to turn end" replay

Goal: when a player's turn ends (the autosave boundary), capture and serve a
~30‑second video of the host desktop right up to that moment. The portal shows
it in the Status view.

Scope: **all changes live under `longplay/`** (no vcmiclient source changes needed —
the autosave socket `CCallback::save()` → `performAutosave()` already fires on the
turn boundary).

---

## 1. How it works (architecture)

```
 +-------------------------------------------------------------+
 |  host container (vcmi)                                       |
 |                                                             |
 |  replayservice  (long-running bash, ffmpeg x11grab)         |
 |     └─ continuously records :1 into /home/abc/replay/ring/  |
 |        keeps only the newest 3 x 10s segments  (~30s ring)   |
 |                                                             |
 |  turn ends -> CCallback::save() -> autosave socket          |
 |     └─> gamestateservice.py::handle_autosave               |
 |           1. concat the 3 newest segments -> /tmp/mp4       |
 |           2. POST it to portal /replays/upload (X-Portal-…)  |
 +-----------------------------|-------------------------------+
                               | http://portal:8000
 +---------------------------- v -----------------------------+
 |  portal container                                            |
 |     └─ /replays/upload  ->  writes /replay/latest.mp4       |
 |                          + rotates /replay/history/replay_* |
 |     └─ GET /replays/latest (lp-token) -> FileResponse       |
 |                                                             |
 |  index.html  Status view: <video src="/replays/latest">      |
 +-------------------------------------------------------------+
```

Why a ring buffer instead of one big recording:
- constant small disk footprint (3 segments, ~1–2 MB), no runaway growth;
- always "warm", so the last 30 s are immediately available at turn end;
- snapshot = a single cheap `ffmpeg -f concat -c copy` (no re-encode).

---

## 2. Verified current state (file : line references) + corrections

| Fact | Where | Implication / correction to the draft |
|---|---|---|
| Autosave fires at **turn boundary (start of next turn)**, not literally "turn end" | `lib/callback/CCallback.cpp:334`, `CPlayerInterface::performAutosave()` | Good enough — it's exactly "when player X's turn ends / player Y's begins". Snapshot the last 30 s at that moment = player X's final actions. Keep. |
| `handle_autosave` exists but upload is **commented out** | `host/gamestateservice.py:63-72` (commented task at 69-70) | Add the replay logic here. Do **not** touch the commented save-upload. |
| Handlers are **synchronous** inside a blocking `select` loop; `post_gamestate` uses `asyncio.run(...)` | `host/gamestateservice.py:87-91, 115-135` | **Correction:** do NOT use `asyncio.create_task` (no running loop → would raise). Use blocking `subprocess` for the ffmpeg concat + `asyncio.run(upload_replay(...))`, matching the existing `asyncio.run` pattern. |
| No persistent event loop in the host service | same file | Concurrency guard is a plain module global (single‑threaded loop, so it's a safety net only). |
| Portal→server auth = `X-Portal-Apikey` via `validate_portal_apikey` | `portal/server.py:134-143`; sent in `post_gamestate`/`post_start` at `gamestateservice.py:76-83, 95-102` | POST replay reuses `Depends(validate_portal_apikey)` and sends the header. (Note: the existing `upload_save_post` does **not** send it — we will.) |
| Browser→server auth = `lp-token` cookie | `portal/server.py:194-229`; cookie set in `index.html:280` | GET replay reuses `verify_token_gamestate` (any authenticated user). **Correction/decision:** use `verify_token_gamestate`, not `verify_token_desktop` (which is turn‑gated), so the already‑open Status view can show the replay to any logged‑in player. See D1. |
| s6/Webtop custom services are **flat executables** in `/custom-services.d/` (not dir+`run`) | `host/Dockerfile:77-82` (`gameservice`, `gamestateservice`) | New recorder mirrors this: one flat executable `replayservice`. |
| Display for x11grab is `:1`; env set in `gameservice.sh:9-21`; recorder does **not** set it | `host/gameservice.sh` | Recorder must set `DISPLAY=:1` (and, if needed, `XAUTHORITY`). See D3. |
| Portal WORKDIR `/app`, `mkdir -p /saves` | `portal/Dockerfile:3,10` | Replay store goes to `/replay` backed by a **named volume** (survives container recreates). |
| `ffmpeg` is already installed in the host image | `host/Dockerfile:34` | No new packages needed (Ubuntu `ffmpeg` ships `libx264`). |
| Build context for portal is `./portal`; it reads templates via `__file__` | `docker-compose.yml:3-5`, `portal/server.py:31` | `/replay` mount is independent of build context — safe. |
| Home dir is world‑rwx across services (`chmod -R 777`) | `host/Dockerfile:71-72` | gamestateservice (root) can read recorder (abc) output. No extra permission work. |
| Status card Day block is the insertion point | `portal/templates/index.html:94-100` | Insert the replay card right after it. |
| Vue app is **Composition API** and exposes state via a `return {…}` object | `index.html:563-571` | New `replayUrl`/`replayMetaText`/methods must be added to that returned object. |
| Status polling cadence | `index.html:334-347` (`startGamestatePolling`, 3s) | Refresh replay on **day change** inside `fetchGameState` (lines 310-321). |

Open decisions (recommended defaults in bold):
- **D1 – GET auth: any authenticated user (`verify_token_gamestate`)** vs turn‑gated. Recommend former (status view is already open to all).
- **D2 – Ring size = 3 × 10 s = 30 s.** Make `SEG_SECONDS`/`KEEP` env‑tunable.
- **D3 – x11grab access to `:1`:** probe with a 1‑s `x11grab` capture at service start; if it fails, set `XAUTHORITY=/home/abc/.Xauthority` and/or run as `abc` via `runuser`.
- **D4 – Resolution:** scale to ~640×360 for small files & low CPU (vs full desktop).
- **D5 – Leave the disabled "saves" upload as‑is;** the replay is independent of it.

---

## 3. Implementation

### Task A — `host/replayservice` (new): continuous ring recorder

Recommended shape (timestamped filenames → trivial chronological order, no rotation bugs):

```bash
#!/bin/bash
# replayservice — record the X desktop (:1) into a 3 x 10s ring buffer.
set -u
export DISPLAY="${DISPLAY:-:1}"
[ -z "${XAUTHORITY:-}" ] && [ -f /home/abc/.Xauthority ] && export XAUTHORITY=/home/abc/.Xauthority

RING_DIR="${REPLAY_RING_DIR:-/home/abc/replay/ring}"
SEG_SECONDS="${REPLAY_SEGMENT_SECONDS:-10}"   # each segment
KEEP="${REPLAY_KEEP_SEGMENTS:-3}"             # segments to retain -> ~30s total
mkdir -p "$RING_DIR" && chmod 777 "$RING_DIR" 2>/dev/null || true

# Wait until the display is grabbable (KDE may still be booting).
until [ -n "$(DISPLAY=$DISPLAY xdpyinfo 2>/dev/null)" ]; do
  sleep 1;
done
echo "[replayservice] recording $DISPLAY -> $RING_DIR"

while true; do
  ts=$(date +%Y%m%d%H%M%S)
  # 10s of real-time capture; scale + crf30 keeps each segment small (~0.5-1MB).
  if ffmpeg -hide_banner -loglevel error -y \
       -f x11grab -framerate 10 -i "$DISPLAY:none" \
       -vf "scale=640:-2" \
       -t "$SEG_SECONDS" \
       -c:v libx264 -preset veryfast -crf 30 -pix_fmt yuv420p \
       -an -movflags +faststart \
       "$RING_DIR/rec_$ts.mp4"; then
     # Keep only the newest $KEEP segments; delete the rest.
     ls -1t "$RING_DIR"/rec_*.mp4 2>/dev/null | tail -n +"$((KEEP+1))" | xargs -r rm -f
  else
    echo "[replayservice] segment failed, will retry shortly"
    sleep 1
  fi
done
```

Properties:
- After the first ~30 s the ring always holds the newest 3 segments (≈30 s of footage).
- Disk stays ≈1–2 MB regardless of uptime.
- `-an` (no audio) — the game audio path doesn't matter here and it saves CPU/bandwidth.
- Timestamp names → `sort` = chronological → the concat is always in order.

### Task B — `host/Dockerfile`: register the service (mirrors lines 77–82)

```dockerfile
COPY ./longplay/host/replayservice /custom-services.d/replayservice
RUN chmod +x /custom-services.d/replayservice
```
Add next to the `gameservice`/`gamestateservice` lines. (Confirm the custom‑service
runner iterates the flat dir — it already runs two services there.)

### Task C — `host/gamestateservice.py`: snapshot + upload on autosave

New top‑level constants/helpers (near the existing `RING_DIR`/ports block):

```python
import subprocess, glob
RING_DIR = os.environ.get("REPLAY_RING_DIR", "/home/abc/replay/ring")
POST_REPLAY_URL = "http://portal:8000/replays/upload"
_replay_inflight = False   # safety net (single-threaded loop)

def _build_ring_snapshot():
    """Concatenate the newest 3 ring segments into one mp4. Returns path or None."""
    global _replay_inflight
    if _replay_inflight:
        return None
    _replay_inflight = True
    try:
        segs = sorted(glob.glob(os.path.join(RING_DIR, "rec_*.mp4")))  # name-sorted == time-ordered
        if len(segs) < 3:
            return None  # ring not warmed up yet
        latest = segs[-3:]
        out_path = "/tmp/replay_latest.mp4"
        list_path = "/tmp/replay_concat_list.txt"
        with open(list_path, "w") as f:
            for p in latest:
                f.write("file '%s'\n" % p)
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-list", list_path,
            "-c", "copy", "-movflags", "+faststart", out_path,
        ], check=True, timeout=30)
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

def handle_autosave(data: str):
    """Autosave fires at the turn boundary -> capture + upload the last 30s."""
    print("autosave signal:", data.strip())
    snap = _build_ring_snapshot()
    if snap:
        try:
            asyncio.run(upload_replay(snap))     # matches existing asyncio.run pattern
        except Exception as e:
            print(f"[replay] upload failed: {e}")
    else:
        print("[replay] no snapshot (ring not warmed up or busy)")
    # NOTE: leave the previously-commented save-upload lines untouched.
```

Why this shape: `_build_ring_snapshot` is blocking but short (few seconds) and safe in
the single‑threaded select loop; the upload uses `asyncio.run` exactly like
`post_gamestate`/`post_start`. The snapshot is independent of (and not blocked by) the
disabled save-upload — a save failure still yields a good replay, and vice‑versa.

### Task D — `portal/server.py`: store + endpoints

Add imports: `import shutil` (or use `os.listdir`). Constants near other config:

```python
REPLAY_DIR = os.environ.get("REPLAY_DIR", "/replay")
REPLAY_LATEST = os.path.join(REPLAY_DIR, "latest.mp4")
REPLAY_HISTORY = os.path.join(REPLAY_DIR, "history")
REPLAY_KEEP = 5

@app.post("/replays/upload", dependencies=[Depends(validate_portal_apikey)])
async def upload_replay(file: UploadFile = File(...)):
    os.makedirs(REPLAY_DIR, exist_ok=True)
    os.makedirs(REPLAY_HISTORY, exist_ok=True)
    tmp = REPLAY_LATEST + ".tmp"
    with open(tmp, "wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
    os.replace(tmp, REPLAY_LATEST)          # atomic for the browser

    hist = os.path.join(REPLAY_HISTORY,
        "replay_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".mp4")
    shutil.copy2(REPLAY_LATEST, hist)       # keep a small ring of history (optional)
    named = sorted(os.listdir(REPLAY_HISTORY))
    for old in named[:-REPLAY_KEEP]:
        try: os.remove(os.path.join(REPLAY_HISTORY, old))
        except OSError: pass
    return {"status": "ok", "size": os.path.getsize(REPLAY_LATEST)}

@app.get("/replays/latest")
async def get_replay_latest(request: Request, authorization: str | None = Header(default=None)):
    await verify_token_gamestate(request=request, authorization=authorization)
    if not os.path.exists(REPLAY_LATEST):
        raise HTTPException(status_code=404, detail="No replay yet")
    return FileResponse(REPLAY_LATEST, media_type="video/mp4",
                        filename="last-turn-replay.mp4")
```

(If `verify_token_gamestate` is ever refactored into a shared dependency, use that.)

### Task E — `portal/templates/index.html`: Status‑view video

Insert right after the Day block (after line 100 `</div>`), i.e. still inside the
`v-if="gameState.player"` status card:

```html
<!-- Turn replay: last ~30s up to the previous player's turn end -->
<div class="flex flex-col items-center mb-6">
    <div class="w-full flex items-center justify-between mb-2">
        <p class="text-gray-400 text-sm font-medium uppercase tracking-wider">Last turn replay (30s)</p>
        <button @click="reloadReplay" class="text-xs text-gray-500 hover:text-white">reload</button>
    </div>
    <video v-if="replayUrl" :src="replayUrl"
           class="w-full rounded-lg bg-black" controls loop muted playsinline></video>
    <p v-else class="text-gray-500 text-sm">No replay yet (appears after the first turn ends).</p>
    <p v-if="replayMetaText" class="text-gray-500 text-xs mt-1">{{ replayMetaText }}</p>
</div>
```

JS (Composition API — add refs alongside the other `ref(...)` declarations, and methods
near the other functions):

```js
const replayUrl = ref(null);
const replayMetaText = ref('');
async function refreshReplay() {
  replayMetaText.value = 'loading…';
  try {
    const r = await fetch('/replays/latest', { credentials: 'include' });
    if (r.ok) {
      const len = r.headers.get('content-length');
      replayUrl.value = `/replays/latest?t=${Date.now()}`;   // cache-bust
      replayMetaText.value = len ? `${(Math.round(+len/1024/1024*10)/10)} MB` : '';
    } else { replayUrl.value = null; replayMetaText.value = 'no replay yet'; }
  } catch (e) { replayUrl.value = null; replayMetaText.value = String(e); }
}
function reloadReplay(){ replayUrl.value = null; refreshReplay(); }
```

Auto‑refresh on turn change: in `fetchGameState()` (lines 310–321), track the previous
day and refresh when it changes:

```js
// near other refs:  const prevDay = ref(null);
// at the bottom of the `resp.ok` branch in fetchGameState():
if (gameState.value.day !== prevDay.value) {
    prevDay.value = gameState.value.day;
    refreshReplay();
}
```

Expose to the template by adding to the returned object (lines 563–571):

```js
replayUrl, replayMetaText, refreshReplay, reloadReplay
```

Call `refreshReplay()` once on entering the Status view (e.g. inside `login()` after
`currentView.value = 'status'`, and in `exitDesktop()`).

### Task F — `docker-compose.yml`: named replay volume

```yaml
volumes:
  host-data:
  replay-storage:        # survives container recreates
services:
  portal:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - replay-storage:/replay
```

`REPLAY_DIR`/mount both default to `/replay`, so **no env change is required** (you may
still set `REPLAY_DIR=/replay` in `env.conf` for clarity/override).

### Task G — docs (small)

- `longplay/README.md`: new "Turn replay" section — the autosave trigger, the ring
  buffer, how to change size/framerate/scale (env vars for the recorder).
- `longplay/TODO.md`: one line under "Nice to have / done" —
  "`Turn-end replay: ring-buffer recorder + POST to portal on autosave socket`".

---

## 4. Auth & security

- **POST /replays/upload** — host only, via `X-Portal-Apikey` (`validate_portal_apikey`).
- **GET /replays/latest** — any authenticated portal user via `lp-token`
  (`verify_token_gamestate`). Turn‑gating is optional (D1) but recommended *off* so the
  Status view (already open to all players) can display it.
- Upload is written to a temp file then `os.replace()` → atomic, no torn reads by the
  browser mid‑upload.

## 5. Risks / edge cases

- **First ~30 s of host uptime** → ring has <3 segments → snapshot returns `None` →
  `404` until warmed. Acceptable; document it.
- **Two autosaves within 10 s** → `_replay_inflight` drops the second; we only want
  one per turn anyway.
- **x11grab can't open `:1`** (X auth) → probe at start (D3); fix with `XAUTHORITY`
  and/or `runuser -u abc`. Validate before wiring the upload.
- **CPU/disk of x11grab+encode** is constant and tiny at the chosen scale (D4); lower
  `framerate`/scale if the host is already CPU‑bound by Selkies.
- **Order of concat** is guaranteed by timestamped filenames (no `seg0/1/2` ordering bugs).

## 6. Rollout & verification

1. `docker compose up` the full stack.
2. Log in to the portal, start a game (existing Start flow).
3. Confirm the ring warms: `docker exec vcmi-host ls -la /home/abc/replay/ring/` → 3 mp4s.
4. End a turn (or trigger any in‑game save — same socket fires). Watch host logs
   (`[replayservice]`, `handle_autosave`) and portal logs for `POST /replays/upload`.
5. Open the Status view: video plays the last ~30 s, size ~1–2 MB, size label present.
6. Restart the portal container; `GET /replays/latest` still serves the file from the
   named volume.
7. Negative path: before the first turn ends, `GET /replays/latest` returns 404 and the
   UI shows "No replay yet".

## 7. Files touched (checklist)

- [ ] `longplay/host/replayservice` (new) — ring recorder
- [ ] `longplay/host/Dockerfile` — register `replayservice`
- [ ] `longplay/host/gamestateservice.py` — snapshot + upload on autosave
- [ ] `longplay/portal/server.py` — `/replays/upload`, `/replays/latest`
- [ ] `longplay/portal/templates/index.html` — Status‑view `<video>` + JS
- [ ] `longplay/docker-compose.yml` — `replay-storage` volume
- [ ] `longplay/README.md`, `longplay/TODO.md` — docs

"""
Lote completo: percorre subpastas do Drive, enumera imagens, chama Freepik
nano-banana-pro e salva em ./out/<numero_subpasta>/<nome>_swap.<ext>.

Estado em ./state.json permite retomar se o processo cair.

Configuração:
  - FREEPIK_API_KEY: chave Freepik (mesma do projeto antigo)
  - MODEL_REF_ID:    Drive file id da foto-referência da modelo (público)
  - MODEL_REF_MIME:  mime da referência (default image/png)
  - subfolders.json: lista [["1","<drive_folder_id>"], ...] das pastas com cenas
"""
from __future__ import annotations

import concurrent.futures
import html
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).parent
OUT = HERE / "out"
STATE_PATH = HERE / "state.json"
LOG_PATH = HERE / "batch.log"
SUBFOLDERS_PATH = HERE / "subfolders.json"

FREEPIK_API_KEY = os.environ.get("FREEPIK_API_KEY", "").strip()
if not FREEPIK_API_KEY:
    print("ERROR: FREEPIK_API_KEY not set", file=sys.stderr)
    sys.exit(2)

MODEL_REF_ID = os.environ.get("MODEL_REF_ID", "").strip()
MODEL_REF_MIME = os.environ.get("MODEL_REF_MIME", "image/png")
if not MODEL_REF_ID:
    print("ERROR: MODEL_REF_ID env var not set (Drive file id of the model reference).", file=sys.stderr)
    sys.exit(2)

POST_URL = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro"
STATUS_URL = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro/{task_id}"

PROMPT = (
    "Place the exact model from @img2 into the scene from @img1. "
    "FROM @img2 (keep identical): Same model: face, hair, body proportions, and all physical features. "
    "Same outfit: exact clothing with identical color, fit and details. "
    "If the original subject in @img1 is holding a phone or any object, keep that object held in the exact same way in the new image. "
    "Same nails color. "
    "FROM @img1 (replicate exactly): Same pose and body position as the model in @img1. "
    "Same facial expression, mouth and gaze as the original subject in @img1. "
    "Same location in the frame (exact placement and scale). "
    "Same background and scenario. "
    "Same camera angle and framing. "
    "Same lighting style."
)


def load_subfolders() -> list[tuple[str, str]]:
    """Carrega lista [(name, folder_id), ...] de subfolders.json."""
    if not SUBFOLDERS_PATH.exists():
        print(f"ERROR: {SUBFOLDERS_PATH.name} not found. Crie um JSON com [[\"1\",\"<drive_folder_id>\"], ...].", file=sys.stderr)
        sys.exit(2)
    raw = json.loads(SUBFOLDERS_PATH.read_text(encoding="utf-8"))
    return [(str(name), str(fid)) for name, fid in raw]


def log(msg: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def drive_public_url(file_id: str) -> str:
    return f"https://lh3.googleusercontent.com/d/{file_id}=w2000"


def http_json(method: str, url: str, body: dict | None = None, retries: int = 3) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last_err: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("x-freepik-api-key", FREEPIK_API_KEY)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode("utf-8", errors="replace")
            last_err = RuntimeError(f"HTTP {e.code}: {body_txt}")
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt * 3)
                continue
            raise last_err
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(2 ** attempt * 3)
    assert last_err is not None
    raise last_err


ENTRY_RE = re.compile(
    r'<div class="flip-entry"\s+id="entry-([^"]+)"[^>]*>.*?'
    r'<div class="flip-entry-title">([^<]+)</div>',
    re.DOTALL,
)


def list_folder(folder_id: str) -> list[tuple[str, str]]:
    url = f"https://drive.google.com/embeddedfolderview?id={folder_id}&hl=en#list"
    with urllib.request.urlopen(url, timeout=60) as r:
        page = r.read().decode("utf-8", errors="replace")
    out: list[tuple[str, str]] = []
    for fid, name in ENTRY_RE.findall(page):
        out.append((fid, html.unescape(name)))
    return out


def mime_from_name(name: str) -> str:
    n = name.lower()
    if n.endswith(".png"):
        return "image/png"
    if n.endswith(".webp"):
        return "image/webp"
    if n.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if n.endswith((".mp4", ".mov", ".webm", ".avi", ".mkv")):
        return "video/unknown"
    return "application/octet-stream"


def submit(scene_id: str, mime: str) -> str:
    body = {
        "prompt": PROMPT,
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "reference_images": [
            {"image": drive_public_url(scene_id),     "mime_type": mime,           "text": "img1: scene"},
            {"image": drive_public_url(MODEL_REF_ID), "mime_type": MODEL_REF_MIME, "text": "img2: model"},
        ],
    }
    resp = http_json("POST", POST_URL, body)
    return resp["data"]["task_id"]


def poll(task_id: str, timeout_s: int = 600) -> list[str]:
    deadline = time.time() + timeout_s
    delay = 4.0
    while time.time() < deadline:
        time.sleep(delay)
        resp = http_json("GET", STATUS_URL.format(task_id=task_id))
        data = resp.get("data", {})
        status = data.get("status")
        if status == "COMPLETED":
            return data.get("generated", []) or []
        if status == "FAILED":
            raise RuntimeError(f"task failed: {json.dumps(resp)[:500]}")
        delay = min(delay * 1.15, 10.0)
    raise TimeoutError(f"task {task_id} timeout {timeout_s}s")


def download(url: str, dest: pathlib.Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=180) as r, open(dest, "wb") as f:
        f.write(r.read())


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"done": {}, "failed": {}}


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def process_one(subfolder_name: str, scene_id: str, scene_name: str) -> tuple[str, str, str]:
    """Returns (scene_id, status, detail). status in {done, failed}."""
    try:
        mime = mime_from_name(scene_name)
        stem = pathlib.Path(scene_name).stem
        ext = pathlib.Path(scene_name).suffix or ".png"
        out_path = OUT / subfolder_name / f"{stem}_swap{ext}"
        if out_path.exists() and out_path.stat().st_size > 0:
            return (scene_id, "done", f"already exists {out_path.name}")

        task_id = submit(scene_id, mime)
        images = poll(task_id)
        if not images:
            return (scene_id, "failed", "no images returned")
        download(images[0], out_path)
        return (scene_id, "done", str(out_path))
    except Exception as e:
        return (scene_id, "failed", f"{type(e).__name__}: {e}")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    state = load_state()
    done_ids = set(state.get("done", {}).keys())
    failed_ids = set(state.get("failed", {}).keys())

    log(f"start batch. loaded state: {len(done_ids)} done, {len(failed_ids)} failed")

    subfolders = load_subfolders()
    log(f"loaded {len(subfolders)} subfolders from {SUBFOLDERS_PATH.name}")

    # Enumerate everything first so we know total
    all_jobs: list[tuple[str, str, str]] = []  # (subfolder_name, scene_id, scene_name)
    for sub_name, sub_id in subfolders:
        try:
            entries = list_folder(sub_id)
        except Exception as e:
            log(f"[{sub_name}] ERROR listing folder: {e}")
            continue
        images = [(fid, name) for fid, name in entries if mime_from_name(name).startswith("image/")]
        log(f"[{sub_name}] {len(images)} images")
        for fid, name in images:
            all_jobs.append((sub_name, fid, name))

    pending = [j for j in all_jobs if j[1] not in done_ids]
    log(f"total jobs: {len(all_jobs)} | pending: {len(pending)} | skip (already done): {len(all_jobs) - len(pending)}")

    if not pending:
        log("nothing to do")
        return 0

    # Parallel: 3 concurrent. API tasks spend most time polling → safe to overlap.
    MAX_WORKERS = 3
    t0 = time.time()
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(process_one, sub, sid, sname): (sub, sid, sname)
            for sub, sid, sname in pending
        }
        for fut in concurrent.futures.as_completed(futures):
            sub, sid, sname = futures[fut]
            scene_id, status, detail = fut.result()
            completed += 1
            if status == "done":
                state.setdefault("done", {})[scene_id] = {"sub": sub, "name": sname, "detail": detail}
                log(f"OK  [{sub}] ({completed}/{len(pending)}) {sname}")
            else:
                state.setdefault("failed", {})[scene_id] = {"sub": sub, "name": sname, "detail": detail}
                log(f"ERR [{sub}] ({completed}/{len(pending)}) {sname} -> {detail}")
            save_state(state)

    elapsed = time.time() - t0
    done_count = sum(1 for j in pending if j[1] in state.get("done", {}))
    failed_count = len(pending) - done_count
    log(f"done in {elapsed:.0f}s. new successes: {done_count} | new failures: {failed_count}")
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

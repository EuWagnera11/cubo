"""
Freepik nano-banana-pro swap: place the reference model into a scene image.

Usage:
    python swap.py <scene_file_id> <scene_filename> [--resolution 2K]

Outputs: downloads the generated image to ./out/<original_basename>_swap.<ext>
Prints the absolute output path on the last line so the caller can pipe it.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

FREEPIK_API_KEY = os.environ.get("FREEPIK_API_KEY", "").strip()
if not FREEPIK_API_KEY:
    print("ERROR: set FREEPIK_API_KEY env var before running.", file=sys.stderr)
    sys.exit(2)

# TODO: definir Drive file ID público da nova modelo de referência
MODEL_REF_ID = os.environ.get("MODEL_REF_ID", "").strip()
MODEL_REF_MIME = os.environ.get("MODEL_REF_MIME", "image/png")
if not MODEL_REF_ID:
    print("ERROR: set MODEL_REF_ID env var (Google Drive file id of the model reference).", file=sys.stderr)
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


def drive_public_url(file_id: str) -> str:
    return f"https://lh3.googleusercontent.com/d/{file_id}=w2000"


def http_json(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-freepik-api-key", FREEPIK_API_KEY)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} {method} {url}", file=sys.stderr)
        print(raw, file=sys.stderr)
        raise
    return json.loads(raw)


def submit(scene_id: str, mime: str, resolution: str) -> str:
    body = {
        "prompt": PROMPT,
        "aspect_ratio": "9:16",
        "resolution": resolution,
        "reference_images": [
            {"image": drive_public_url(scene_id),      "mime_type": mime,             "text": "img1: scene"},
            {"image": drive_public_url(MODEL_REF_ID),  "mime_type": MODEL_REF_MIME,   "text": "img2: model"},
        ],
    }
    resp = http_json("POST", POST_URL, body)
    task_id = resp["data"]["task_id"]
    print(f"submitted task_id={task_id}", file=sys.stderr)
    return task_id


def poll(task_id: str, timeout_s: int = 600) -> list[str]:
    deadline = time.time() + timeout_s
    delay = 4.0
    while time.time() < deadline:
        time.sleep(delay)
        resp = http_json("GET", STATUS_URL.format(task_id=task_id))
        data = resp.get("data", {})
        status = data.get("status")
        print(f"  status={status}", file=sys.stderr)
        if status == "COMPLETED":
            return data.get("generated", []) or []
        if status == "FAILED":
            raise RuntimeError(f"task failed: {json.dumps(resp)}")
        delay = min(delay * 1.2, 10.0)
    raise TimeoutError(f"task {task_id} did not finish in {timeout_s}s")


def download(url: str, dest: pathlib.Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene_id")
    ap.add_argument("scene_filename")
    ap.add_argument("--resolution", default="2K", choices=["1K", "2K", "4K"])
    ap.add_argument("--mime", default="image/jpeg")
    args = ap.parse_args()

    out_dir = pathlib.Path(__file__).parent / "out"
    out_dir.mkdir(exist_ok=True)

    stem = pathlib.Path(args.scene_filename).stem
    ext = pathlib.Path(args.scene_filename).suffix or ".png"
    out_path = out_dir / f"{stem}_swap{ext}"

    task_id = submit(args.scene_id, args.mime, args.resolution)
    images = poll(task_id)
    if not images:
        print("ERROR: no images returned", file=sys.stderr)
        return 1

    download(images[0], out_path)
    print(str(out_path.resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

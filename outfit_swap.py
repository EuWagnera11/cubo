"""Outfit swap: mantém tudo da @img1 (imagem LOCAL) e muda só a roupa via prompt customizado."""
from __future__ import annotations
import argparse, base64, json, os, pathlib, sys, time
import urllib.error, urllib.request

API_KEY = os.environ.get("FREEPIK_API_KEY", "").strip()
if not API_KEY: print("ERROR: FREEPIK_API_KEY not set", file=sys.stderr); sys.exit(2)

POST_URL = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro"
STATUS_URL = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro/{task_id}"


def mime_from_name(name):
    n = name.lower()
    if n.endswith(".png"): return "image/png"
    if n.endswith(".webp"): return "image/webp"
    return "image/jpeg"


def http_json(method, url, body=None):
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-freepik-api-key", API_KEY)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")


def run(local_path, prompt):
    p = pathlib.Path(local_path)
    raw = p.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    mime = mime_from_name(p.name)
    print(f"input: {p.name} ({len(raw)/1024:.1f}KB)", file=sys.stderr)

    body = {
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "reference_images": [
            {"image": b64, "mime_type": mime, "text": "img1: source photo (keep everything, only change outfit)"},
        ],
    }
    tid = http_json("POST", POST_URL, body)["data"]["task_id"]
    print(f"task_id={tid}", file=sys.stderr)
    delay = 4.0
    for _ in range(150):
        time.sleep(delay)
        r = http_json("GET", STATUS_URL.format(task_id=tid))
        st = r.get("data", {}).get("status")
        print(f"  {st}", file=sys.stderr)
        if st == "COMPLETED": return r["data"].get("generated", []) or []
        if st == "FAILED": raise RuntimeError(f"failed: {json.dumps(r)[:300]}")
        delay = min(delay * 1.15, 10.0)
    raise TimeoutError("timeout")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_path")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    inp = pathlib.Path(args.input_path)
    out_dir = pathlib.Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / inp.name

    imgs = run(inp, args.prompt)
    if not imgs: print("ERROR: no images", file=sys.stderr); return 1
    with urllib.request.urlopen(imgs[0], timeout=180) as r, open(out_path, "wb") as f:
        f.write(r.read())
    print(str(out_path.resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

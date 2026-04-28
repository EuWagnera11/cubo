"""Troca o fundo de uma foto mantendo o sujeito intacto."""
from __future__ import annotations
import argparse, base64, json, os, pathlib, sys, time
import urllib.error, urllib.request

API_KEY = os.environ.get("FREEPIK_API_KEY", "").strip()
if not API_KEY: sys.exit(2)

POST_URL = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro"
STATUS_URL = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro/{task_id}"


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
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--aspect", default="9:16")
    args = ap.parse_args()

    p = pathlib.Path(args.input)
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    body = {
        "prompt": args.prompt,
        "aspect_ratio": args.aspect,
        "resolution": "2K",
        "reference_images": [
            {"image": b64, "mime_type": mime, "text": "img1: source — keep subject pixel-perfect, replace background only"},
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
        if st == "COMPLETED":
            imgs = r["data"].get("generated", []) or []
            if not imgs: print("ERROR: no images", file=sys.stderr); return 1
            out = pathlib.Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(imgs[0], timeout=300) as rr, open(out, "wb") as f:
                f.write(rr.read())
            print(str(out.resolve()))
            return 0
        if st == "FAILED":
            print(f"FAILED: {json.dumps(r)[:300]}", file=sys.stderr); return 1
        delay = min(delay * 1.15, 10.0)
    return 1


if __name__ == "__main__":
    sys.exit(main())

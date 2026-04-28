"""Aplica a Skin Enhancer API da Freepik numa foto local.

3 modos:
  - faithful   (padrão): aprimoramento natural, preserva textura e identidade
  - creative:           aprimoramento artístico mais agressivo
  - flexible:           direcionado, com optimized_for específico

Uso:
    python skin_enhance.py <input.png> --out <output.png> [--mode faithful] \\
        [--skin-detail 80] [--sharpen 30] [--smart-grain 25] \\
        [--optimized-for transform_to_real]
"""
from __future__ import annotations
import argparse, base64, json, os, pathlib, sys, time
import urllib.error, urllib.request

API_KEY = os.environ.get("FREEPIK_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: FREEPIK_API_KEY not set", file=sys.stderr); sys.exit(2)

POST_BASE = "https://api.freepik.com/v1/ai/skin-enhancer"
STATUS_URL = "https://api.freepik.com/v1/ai/skin-enhancer/{tid}"

OPTIMIZED_CHOICES = [
    "enhance_skin", "improve_lighting", "enhance_everything",
    "transform_to_real", "no_make_up",
]


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
        body_txt = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code}: {body_txt[:500]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="imagem local de entrada")
    ap.add_argument("--out", required=True, help="caminho de saída")
    ap.add_argument("--mode", default="faithful", choices=["faithful", "creative", "flexible"])
    ap.add_argument("--skin-detail", type=int, default=80, help="(faithful) 0-100, default 80")
    ap.add_argument("--sharpen", type=int, default=15, help="0-100, default 15")
    ap.add_argument("--smart-grain", type=int, default=0, help="0-100, default 0 (smart_grain alto deixa pixelado)")
    ap.add_argument("--optimized-for", choices=OPTIMIZED_CHOICES, default="transform_to_real",
                    help="(flexible) tipo de otimização")
    args = ap.parse_args()

    inp = pathlib.Path(args.input)
    if not inp.exists():
        print(f"ERROR: input not found: {inp}", file=sys.stderr); return 2

    img_b64 = base64.b64encode(inp.read_bytes()).decode("ascii")

    body: dict = {
        "image": img_b64,
        "sharpen": args.sharpen,
        "smart_grain": args.smart_grain,
    }
    if args.mode == "faithful":
        body["skin_detail"] = args.skin_detail
    elif args.mode == "flexible":
        body["optimized_for"] = args.optimized_for

    post_url = f"{POST_BASE}/{args.mode}"
    tid = http_json("POST", post_url, body)["data"]["task_id"]
    print(f"mode={args.mode} task_id={tid}", file=sys.stderr)

    delay = 3.0
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(delay)
        r = http_json("GET", STATUS_URL.format(tid=tid))
        st = r.get("data", {}).get("status")
        print(f"  {st}", file=sys.stderr)
        if st == "COMPLETED":
            imgs = r["data"].get("generated", []) or []
            if not imgs:
                print("ERROR: no images returned", file=sys.stderr); return 1
            out = pathlib.Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(imgs[0], timeout=300) as rr, open(out, "wb") as f:
                f.write(rr.read())
            print(str(out.resolve()))
            return 0
        if st == "FAILED":
            print(f"FAILED: {json.dumps(r)[:500]}", file=sys.stderr); return 1
        delay = min(delay * 1.15, 8.0)
    print("TIMEOUT", file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main())

"""Swap com 2 imagens LOCAIS (cena/grid + modelo).

Variante de swap.py para casos em que você não quer subir as imagens no Drive.
Envia ambas como base64 para o nano-banana-pro.

Uso:
    python swap_local.py --scene <cena.jpg> --model <modelo.png> --out <out.png> \\
                         [--prompt "..."] [--aspect 9:16] [--resolution 2K]

Se --prompt não for fornecido, usa o prompt padrão de recriação de cena.
"""
from __future__ import annotations
import argparse, base64, json, os, pathlib, sys, time
import urllib.error, urllib.request

API_KEY = os.environ.get("FREEPIK_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: FREEPIK_API_KEY not set", file=sys.stderr)
    sys.exit(2)

POST_URL = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro"
STATUS_URL = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro/{tid}"

DEFAULT_PROMPT = (
    "Place the exact woman from the SECOND reference (img2: model) into the EXACT scene shown in the FIRST reference (img1). "
    "Recreate the FIRST reference image identically — same composition, layout, framing, poses, expressions, "
    "wardrobe, accessories (rings, earrings, jewelry), background, lighting, color grading and camera angles. "
    "The ONLY change: replace the person with the woman from img2, preserving her facial features, hair color, "
    "skin tone, eye color and overall identity. "
    "Photorealistic, natural skin texture, sharp focus, professional editorial photography."
)


def mime_from_path(p: pathlib.Path) -> str:
    s = p.suffix.lower()
    if s == ".png": return "image/png"
    if s == ".webp": return "image/webp"
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
        body_txt = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code}: {body_txt[:500]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True, help="cena/grid de referência (imagem local)")
    ap.add_argument("--model", required=True, help="foto da modelo (imagem local)")
    ap.add_argument("--out",   required=True, help="caminho de saída")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--aspect", default="9:16",
                    choices=["1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2"])
    ap.add_argument("--resolution", default="2K", choices=["1K", "2K", "4K"])
    args = ap.parse_args()

    scene_p = pathlib.Path(args.scene)
    model_p = pathlib.Path(args.model)
    out_p = pathlib.Path(args.out)
    for p in (scene_p, model_p):
        if not p.exists():
            print(f"ERROR: file not found: {p}", file=sys.stderr); return 2

    scene_b64 = base64.b64encode(scene_p.read_bytes()).decode("ascii")
    model_b64 = base64.b64encode(model_p.read_bytes()).decode("ascii")

    body = {
        "prompt": args.prompt,
        "aspect_ratio": args.aspect,
        "resolution": args.resolution,
        "reference_images": [
            {"image": scene_b64, "mime_type": mime_from_path(scene_p),
             "text": "img1: scene/grid — recreate this layout, composition, poses, wardrobe, background, lighting identically"},
            {"image": model_b64, "mime_type": mime_from_path(model_p),
             "text": "img2: model — preserve face, hair color, skin tone, eye color, identity"},
        ],
    }
    tid = http_json("POST", POST_URL, body)["data"]["task_id"]
    print(f"task_id={tid}", file=sys.stderr)

    delay = 4.0
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(delay)
        r = http_json("GET", STATUS_URL.format(tid=tid))
        st = r.get("data", {}).get("status")
        print(f"  {st}", file=sys.stderr)
        if st == "COMPLETED":
            imgs = r["data"].get("generated", []) or []
            if not imgs:
                print("ERROR: no images generated", file=sys.stderr); return 1
            out_p.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(imgs[0], timeout=300) as rr, open(out_p, "wb") as f:
                f.write(rr.read())
            print(str(out_p.resolve()))
            return 0
        if st == "FAILED":
            print(f"FAILED: {json.dumps(r)[:500]}", file=sys.stderr); return 1
        delay = min(delay * 1.15, 10.0)
    print("TIMEOUT", file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main())

"""Image Upscaler Magnific (Freepik) — replica refinamento estilo SeedVR2/ULT V6.

Magnific upscale com refinamento por IA — adiciona detalhe sem alterar
identidade quando configurado pra retratos (engine=magnific_sparkle,
optimized_for=soft_portraits).

Limite: output máximo 25.3 megapixels. Use scale_factor compatível:
- input 1K (~2 MP) → 2x/4x ok
- input 2K (~8 MP) → 2x ok (=32 MP excede! USAR no máx 1.5x equivalente — não tem, então ficar em 2x se input ≤6 MP)
- input 4K (~17 MP) → não dá pra 2x (=68 MP). Reduzir input ou pular.

Defaults pra modelos IA realistas (Sophia/Pamela):
    engine=magnific_sparkle, optimized_for=soft_portraits,
    scale_factor=2x, creativity=-2, hdr=3, resemblance=6, fractality=0

Uso:
    python upscale.py <input.png> --out <output.png>
    python upscale.py <input.png> --out <output.png> --scale 2x --engine magnific_sparkle \\
        --creativity -2 --hdr 3 --resemblance 6 --prompt "..."
"""
from __future__ import annotations
import argparse, base64, json, os, pathlib, sys, time
import urllib.error, urllib.request

API_KEY = os.environ.get("FREEPIK_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: FREEPIK_API_KEY not set", file=sys.stderr); sys.exit(2)

POST_URL = "https://api.freepik.com/v1/ai/image-upscaler"
STATUS_URL = "https://api.freepik.com/v1/ai/image-upscaler/{tid}"

OPTIMIZED_CHOICES = [
    "standard", "soft_portraits", "hard_portraits",
    "art_n_illustration", "videogame_assets", "nature_n_landscapes",
    "films_n_photography", "3d_renders", "science_fiction_n_horror",
]
ENGINE_CHOICES = ["automatic", "magnific_illusio", "magnific_sharpy", "magnific_sparkle"]
SCALE_CHOICES = ["2x", "4x", "8x", "16x"]


def http_json(method, url, body=None):
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-freepik-api-key", API_KEY)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code}: {body_txt[:600]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="imagem local de entrada")
    ap.add_argument("--out", required=True)
    ap.add_argument("--scale", default="2x", choices=SCALE_CHOICES, help="scale factor (default 2x)")
    ap.add_argument("--engine", default="magnific_sparkle", choices=ENGINE_CHOICES,
                    help="engine Magnific (default magnific_sparkle, melhor pra retratos)")
    ap.add_argument("--optimized-for", default="soft_portraits", choices=OPTIMIZED_CHOICES,
                    help="categoria de otimização (default soft_portraits — preserva pele macia)")
    ap.add_argument("--creativity", type=int, default=-2, help="-10 a 10 (default -2 = fiel ao original)")
    ap.add_argument("--hdr", type=int, default=3, help="-10 a 10 (default 3 = detalhe sem caricatura)")
    ap.add_argument("--resemblance", type=int, default=6, help="-10 a 10 (default 6 = preserva identidade)")
    ap.add_argument("--fractality", type=int, default=0, help="-10 a 10 (default 0 = sem microdetail forçado)")
    ap.add_argument("--prompt", default="", help="texto guia (opcional, usar prompt original da geração ajuda)")
    args = ap.parse_args()

    inp = pathlib.Path(args.input)
    if not inp.exists():
        print(f"ERROR: input not found: {inp}", file=sys.stderr); return 2

    # Sanity check: pixel count
    try:
        import cv2
        img = cv2.imread(str(inp))
        h, w = img.shape[:2]
        in_mp = h * w / 1_000_000
        scale_int = int(args.scale.rstrip("x"))
        out_mp = in_mp * (scale_int ** 2)
        print(f"input: {w}x{h} ({in_mp:.1f} MP) | scale {args.scale} -> output ~{out_mp:.1f} MP", file=sys.stderr)
        if out_mp > 25.3:
            print(f"ERRO: output {out_mp:.1f} MP excederia limite 25.3 MP. Reduza scale_factor ou input.", file=sys.stderr)
            return 2
    except Exception:
        pass

    img_b64 = base64.b64encode(inp.read_bytes()).decode("ascii")
    body = {
        "image": img_b64,
        "scale_factor": args.scale,
        "optimized_for": args.optimized_for,
        "engine": args.engine,
        "creativity": args.creativity,
        "hdr": args.hdr,
        "resemblance": args.resemblance,
        "fractality": args.fractality,
    }
    if args.prompt:
        body["prompt"] = args.prompt

    print(f"engine={args.engine} optimized={args.optimized_for} scale={args.scale}", file=sys.stderr)
    print(f"creativity={args.creativity} hdr={args.hdr} resemblance={args.resemblance} fractality={args.fractality}", file=sys.stderr)

    tid = http_json("POST", POST_URL, body)["data"]["task_id"]
    print(f"task_id={tid}", file=sys.stderr)

    delay = 5.0
    deadline = time.time() + 1200  # upscale demora mais (até 20 min em casos extremos)
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
            with urllib.request.urlopen(imgs[0], timeout=600) as rr, open(out, "wb") as f:
                f.write(rr.read())
            print(str(out.resolve()))
            return 0
        if st == "FAILED":
            print(f"FAILED: {json.dumps(r)[:500]}", file=sys.stderr); return 1
        delay = min(delay * 1.15, 12.0)
    print("TIMEOUT", file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main())

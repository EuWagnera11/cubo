"""Gera uma foto nova da modelo numa cena descrita por prompt.

Diferente de swap_local.py (que precisa de uma imagem-cena de referência),
este script só precisa da(s) foto(s) da modelo + prompt descrevendo a cena.

Default: usa refs/modelo_grid.png como referência canônica de identidade da Sophia.
Pode-se passar múltiplas refs com --model várias vezes (ex: grid + full-body) para
travar identidade com mais força ainda.

Uso:
    python gen_scene.py --out out.png \\
                        --prompt "Same woman from the references at copacabana beach..." \\
                        [--model refs/modelo_grid.png] [--model refs/modelo_ref.png] \\
                        [--aspect 9:16] [--resolution 2K]
"""
from __future__ import annotations
import argparse, base64, json, os, pathlib, sys, time
import urllib.error, urllib.request

API_KEY = os.environ.get("FREEPIK_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: FREEPIK_API_KEY not set", file=sys.stderr); sys.exit(2)

POST_URL = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro"
STATUS_URL = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro/{tid}"

HERE = pathlib.Path(__file__).parent
DEFAULT_REF = HERE / "refs" / "modelo_grid.png"

# Boilerplate exigindo 100% de fidelidade da modelo, anexado ao prompt do usuário.
IDENTITY_LOCK = (
    " IDENTITY (absolute, non-negotiable): match the woman's face, hair color, hair texture, "
    "eye color, skin tone and body proportions EXACTLY as shown in the reference image(s). "
    "Do NOT alter her features, hair color (vibrant ginger copper red — NOT pink, NOT auburn, NOT blonde), "
    "skin tone, or facial geometry in any way. The reference is the absolute source of truth for her appearance. "
    "No tattoos anywhere on her body. No glasses. Eyes properly aligned, no strabismus, both pupils centered. "
    "Photorealistic editorial photography, natural skin texture with visible pores and subtle freckles, "
    "no plastic AI smoothing, no waxy skin."
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
    ap.add_argument("--model", action="append", default=None,
                    help="foto(s) da modelo. Pode ser passado múltiplas vezes. Default: refs/modelo_grid.png")
    ap.add_argument("--out",   required=True, help="caminho de saída")
    ap.add_argument("--prompt", required=True, help="prompt descrevendo a cena (boilerplate de identidade é anexado)")
    ap.add_argument("--no-identity-lock", action="store_true",
                    help="não anexa o boilerplate de fidelidade (use só se souber o que está fazendo)")
    ap.add_argument("--aspect", default="9:16",
                    choices=["1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2"])
    ap.add_argument("--resolution", default="2K", choices=["1K", "2K", "4K"])
    args = ap.parse_args()

    refs = args.model or [str(DEFAULT_REF)]
    ref_paths = [pathlib.Path(p) for p in refs]
    for p in ref_paths:
        if not p.exists():
            print(f"ERROR: model file not found: {p}", file=sys.stderr); return 2

    reference_images = []
    for i, p in enumerate(ref_paths, start=1):
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        reference_images.append({
            "image": b64,
            "mime_type": mime_from_path(p),
            "text": (f"Identity reference #{i} ({p.name}): preserve the woman's face, hair color, "
                     f"skin tone, eye color and proportions exactly as shown here."),
        })

    prompt = args.prompt if args.no_identity_lock else (args.prompt + IDENTITY_LOCK)

    body = {
        "prompt": prompt,
        "aspect_ratio": args.aspect,
        "resolution": args.resolution,
        "reference_images": reference_images,
    }
    print(f"refs: {len(reference_images)} ({', '.join(p.name for p in ref_paths)})", file=sys.stderr)
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
            out_p = pathlib.Path(args.out)
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

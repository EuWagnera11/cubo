"""Skin Enhancer com proteção de logos/texto/objetos — universal.

Problema: skin_enhance.py aplica o enhancer Freepik na imagem inteira, e o
modelo redesenha logos/texto (Starbucks, marcas, palavras na cena, números).

Solução: roda Skin Enhancer normal, depois compõe SÓ regiões "alteradas
suavemente" (pele, cabelo, fundo) usando enhanced. Em regiões com EDGES
FORTES e ALTERAÇÃO SIGNIFICATIVA (logos, texto, UI overlays), restaura
pixels da imagem ORIGINAL.

Lógica:
- Pele muda gradualmente (diff médio espalhado, edges suaves) → manter enhanced
- Logo/texto muda BRUSCAMENTE em regiões com edges fortes → restaurar original
- Fundo simples não muda muito → manter enhanced ou tanto faz

Universal: não depende de detector de rosto/pele. Funciona com qualquer
modelo (Sophia, Pamela, etc.), qualquer cena, qualquer iluminação.

Pipeline:
1. Roda Freepik Skin Enhancer na imagem original
2. Calcula diff(original, enhanced)
3. Detecta edges na imagem original (Canny)
4. Dilata edges → "regiões com possível texto/logo/UI"
5. Onde edges + diff > thresholds → mask_protect
6. Compose: enhanced em geral, original onde mask_protect

Uso:
    python safe_skin_enhance.py <input.png> --out <output.png> --mode faithful
"""
from __future__ import annotations
import argparse, base64, json, os, pathlib, sys, time
import urllib.error, urllib.request
import cv2
import numpy as np

API_KEY = os.environ.get("FREEPIK_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: FREEPIK_API_KEY not set", file=sys.stderr); sys.exit(2)

POST_BASE = "https://api.freepik.com/v1/ai/skin-enhancer"
STATUS_URL = "https://api.freepik.com/v1/ai/skin-enhancer/{tid}"


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


def call_skin_enhancer(input_path: pathlib.Path, mode: str, skin_detail: int,
                       optimized_for: str, sharpen: int, smart_grain: int) -> bytes:
    img_b64 = base64.b64encode(input_path.read_bytes()).decode("ascii")
    body: dict = {"image": img_b64, "sharpen": sharpen, "smart_grain": smart_grain}
    if mode == "faithful":
        body["skin_detail"] = skin_detail
    elif mode == "flexible":
        body["optimized_for"] = optimized_for

    post_url = f"{POST_BASE}/{mode}"
    tid = http_json("POST", post_url, body)["data"]["task_id"]
    print(f"  enhancer mode={mode} task_id={tid}", file=sys.stderr)

    delay = 3.0
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(delay)
        r = http_json("GET", STATUS_URL.format(tid=tid))
        st = r.get("data", {}).get("status")
        print(f"    {st}", file=sys.stderr)
        if st == "COMPLETED":
            imgs = r["data"].get("generated", []) or []
            if not imgs: raise RuntimeError("no enhanced image returned")
            with urllib.request.urlopen(imgs[0], timeout=300) as rr:
                return rr.read()
        if st == "FAILED": raise RuntimeError(f"enhancer FAILED: {json.dumps(r)[:300]}")
        delay = min(delay * 1.15, 8.0)
    raise TimeoutError("enhancer timeout")


def build_protection_mask(original: np.ndarray, enhanced: np.ndarray,
                          edge_low: int = 80, edge_high: int = 200,
                          diff_thresh: int = 25,
                          dilate_size: int = 21,
                          feather_size: int = 31) -> np.ndarray:
    """Cria máscara binária (uint8) marcando regiões a PROTEGER (manter original).

    Identifica:
    - Edges fortes na imagem original (logos, texto, UI, objetos definidos)
    - Onde o enhancer mudou significativamente
    Cruza os dois → áreas onde provavelmente o enhancer destruiu detalhe.
    """
    h, w = original.shape[:2]

    if enhanced.shape != original.shape:
        enhanced = cv2.resize(enhanced, (w, h))

    # Edges da imagem ORIGINAL (Canny)
    gray_orig = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray_orig, edge_low, edge_high)

    # Dilata edges pra cobrir vizinhança (logo inteiro, não só contornos)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_size, dilate_size))
    edges_dilated = cv2.dilate(edges, kernel)

    # Diff entre original e enhanced (onde enhancer mudou)
    diff = cv2.absdiff(original, enhanced)
    diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

    # Máscara de proteção: edges fortes E diff significativo
    protect = ((edges_dilated > 0) & (diff_gray > diff_thresh)).astype(np.uint8) * 255

    # Feather pra blend suave
    if feather_size % 2 == 0: feather_size += 1
    protect = cv2.GaussianBlur(protect, (feather_size, feather_size), 0)
    return protect


def compose_protect(original: np.ndarray, enhanced: np.ndarray, protect_mask: np.ndarray) -> np.ndarray:
    """result = original onde protect_mask alta, enhanced caso contrário."""
    if enhanced.shape != original.shape:
        enhanced = cv2.resize(enhanced, (original.shape[1], original.shape[0]))
    alpha = protect_mask.astype(np.float32) / 255.0
    alpha_3 = cv2.merge([alpha, alpha, alpha])
    result = original.astype(np.float32) * alpha_3 + enhanced.astype(np.float32) * (1.0 - alpha_3)
    return np.clip(result, 0, 255).astype(np.uint8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="imagem original")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="faithful", choices=["faithful", "creative", "flexible"])
    ap.add_argument("--skin-detail", type=int, default=20)
    ap.add_argument("--optimized-for", default="enhance_skin",
                    choices=["enhance_skin", "improve_lighting", "enhance_everything", "transform_to_real", "no_make_up"])
    ap.add_argument("--sharpen", type=int, default=15)
    ap.add_argument("--smart-grain", type=int, default=0)
    ap.add_argument("--edge-low", type=int, default=80)
    ap.add_argument("--edge-high", type=int, default=200)
    ap.add_argument("--diff-thresh", type=int, default=25,
                    help="diff mínimo pra considerar 'enhancer modificou'. Subir = menos proteção (mais aggressive enhance)")
    ap.add_argument("--dilate-size", type=int, default=21,
                    help="dilatação dos edges. Subir = proteção MAIS conservadora (logos/texto + buffer)")
    ap.add_argument("--feather-size", type=int, default=31)
    ap.add_argument("--debug-mask", action="store_true", help="salva _mask_protect.png e _enhanced_full.png")
    args = ap.parse_args()

    inp = pathlib.Path(args.input)
    if not inp.exists():
        print(f"ERROR: input not found: {inp}", file=sys.stderr); return 2

    print(f"[1/4] chamando Skin Enhancer ({args.mode})...", file=sys.stderr)
    enhanced_bytes = call_skin_enhancer(inp, args.mode, args.skin_detail,
                                         args.optimized_for, args.sharpen, args.smart_grain)

    print(f"[2/4] decodificando imagens...", file=sys.stderr)
    original = cv2.imread(str(inp))
    enhanced = cv2.imdecode(np.frombuffer(enhanced_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    print(f"  size: {original.shape[1]}x{original.shape[0]}", file=sys.stderr)

    print(f"[3/4] calculando máscara de proteção (edges + diff)...", file=sys.stderr)
    protect = build_protection_mask(original, enhanced,
                                     edge_low=args.edge_low, edge_high=args.edge_high,
                                     diff_thresh=args.diff_thresh,
                                     dilate_size=args.dilate_size,
                                     feather_size=args.feather_size)
    pct_protected = (protect > 50).sum() / protect.size * 100
    print(f"  protegido: {pct_protected:.1f}% da imagem", file=sys.stderr)

    print(f"[4/4] compondo (enhanced em geral, original em logos/edges fortes)...", file=sys.stderr)
    result = compose_protect(original, enhanced, protect)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), result, [cv2.IMWRITE_PNG_COMPRESSION, 4])

    if args.debug_mask:
        cv2.imwrite(str(out.with_name(out.stem + "_mask_protect.png")), protect)
        cv2.imwrite(str(out.with_name(out.stem + "_enhanced_full.png")), enhanced)
        print(f"  debug: saved _mask_protect.png + _enhanced_full.png", file=sys.stderr)

    print(str(out.resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

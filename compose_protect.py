"""Compõe duas imagens preservando logos/texto da REFERENCE.

Pega imagem `--input` (refined: pós-Magnific ou pós-skin_enhancer) + imagem
`--reference` (raw: original do nano-banana antes de qualquer reinterpretação).

Onde a reference tem edges fortes E o refined diverge significativamente
(provavelmente onde tinha logo/texto/objeto definido), restaura pixels da
reference. Resto da imagem (pele/cabelo/fundo) usa o refined.

Universal: não depende de detector de rosto. Funciona em qualquer cena.

Uso:
    python compose_protect.py --refined <magnific_4k.png> --reference <raw_4k.png> --out <final.png>
"""
from __future__ import annotations
import argparse, pathlib, sys
import cv2
import numpy as np


def build_protection_mask(reference: np.ndarray, refined: np.ndarray,
                          edge_low: int = 80, edge_high: int = 200,
                          diff_thresh: int = 25,
                          dilate_size: int = 21,
                          feather_size: int = 31) -> np.ndarray:
    h, w = reference.shape[:2]
    if refined.shape != reference.shape:
        refined = cv2.resize(refined, (w, h))

    # Edges da REFERENCE (Canny) — onde tem logo/texto/objeto definido
    gray_ref = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray_ref, edge_low, edge_high)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_size, dilate_size))
    edges_dilated = cv2.dilate(edges, kernel)

    # Diff entre reference e refined (onde refined mudou)
    diff = cv2.absdiff(reference, refined)
    diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

    protect = ((edges_dilated > 0) & (diff_gray > diff_thresh)).astype(np.uint8) * 255

    if feather_size % 2 == 0: feather_size += 1
    return cv2.GaussianBlur(protect, (feather_size, feather_size), 0)


def compose(reference: np.ndarray, refined: np.ndarray, protect_mask: np.ndarray) -> np.ndarray:
    """result = reference onde protect alta, refined caso contrário."""
    if refined.shape != reference.shape:
        refined = cv2.resize(refined, (reference.shape[1], reference.shape[0]))
    alpha = protect_mask.astype(np.float32) / 255.0
    alpha_3 = cv2.merge([alpha, alpha, alpha])
    result = reference.astype(np.float32) * alpha_3 + refined.astype(np.float32) * (1.0 - alpha_3)
    return np.clip(result, 0, 255).astype(np.uint8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refined", required=True, help="imagem refinada (Magnific output, ou skin-enhancer output)")
    ap.add_argument("--reference", required=True, help="imagem reference (nano-banana raw, com logos fiéis)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--edge-low", type=int, default=80)
    ap.add_argument("--edge-high", type=int, default=200)
    ap.add_argument("--diff-thresh", type=int, default=25,
                    help="diff mínimo. Subir = menos proteção (mais aggressive refined).")
    ap.add_argument("--dilate-size", type=int, default=21,
                    help="dilatação dos edges. Subir = proteção mais conservadora.")
    ap.add_argument("--feather-size", type=int, default=31)
    ap.add_argument("--debug-mask", action="store_true")
    args = ap.parse_args()

    refined_p = pathlib.Path(args.refined)
    reference_p = pathlib.Path(args.reference)
    for p in (refined_p, reference_p):
        if not p.exists():
            print(f"ERROR: not found: {p}", file=sys.stderr); return 2

    print(f"refined: {refined_p}", file=sys.stderr)
    print(f"reference: {reference_p}", file=sys.stderr)

    refined = cv2.imread(str(refined_p))
    reference = cv2.imread(str(reference_p))
    print(f"  refined: {refined.shape[1]}x{refined.shape[0]}", file=sys.stderr)
    print(f"  reference: {reference.shape[1]}x{reference.shape[0]}", file=sys.stderr)

    if refined.shape != reference.shape:
        print(f"  resizing refined to match reference...", file=sys.stderr)
        refined = cv2.resize(refined, (reference.shape[1], reference.shape[0]),
                              interpolation=cv2.INTER_LANCZOS4)

    protect = build_protection_mask(reference, refined,
                                     edge_low=args.edge_low, edge_high=args.edge_high,
                                     diff_thresh=args.diff_thresh,
                                     dilate_size=args.dilate_size,
                                     feather_size=args.feather_size)
    pct = (protect > 50).sum() / protect.size * 100
    print(f"protegido (reference): {pct:.1f}% da imagem", file=sys.stderr)

    result = compose(reference, refined, protect)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), result, [cv2.IMWRITE_PNG_COMPRESSION, 4])

    if args.debug_mask:
        cv2.imwrite(str(out.with_name(out.stem + "_protect_mask.png")), protect)

    print(str(out.resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

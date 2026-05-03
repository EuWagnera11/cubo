"""
Prompt envelopes — templates master-class por tool/op.

A IA do Lovable provou empiricamente que o prompt cru do user NÃO basta pra
preservar identidade em scene-swap/dresser. A "mágica" é envelopa o prompt
com instruções determinísticas de identity-preservation, lighting, framing.

Cada template é versionado (`name@vN`). A geração grava `envelope_version`
em DB pra a gente saber qual template gerou qual output (rollback fácil
se trocarmos um template e regredir qualidade).

Uso:
    from api.envelopes import envelope, EnvelopeOpts

    final, version = envelope(
        tool="edit", op="dresser",
        raw_prompt="biquíni vermelho",
        opts=EnvelopeOpts(aspect_ratio="9:16"),
    )
    # final  → prompt envelopado pra mandar ao Freepik
    # version → "dresser@v1" — grava em generations.envelope_version
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class EnvelopeOpts:
    aspect_ratio: str = "1:1"
    camera: str | None = None      # "medium close-up, eye-level"
    lens: str | None = None        # "50mm f/1.8"
    mood: str | None = None        # "intimate", "dramatic", "playful"
    shot_index: int | None = None  # cinema multi-shot
    shot_total: int | None = None
    persona_description: str | None = None  # ficha física da persona


# ─────────────── Templates (v1) ───────────────
# Mantém o inglês — Freepik/Gemini respondem melhor em inglês.
# Trocar de versão = bumpar o sufixo, manter v1 disponível pra A/B.

def _scene_swap_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Coloca pessoa (ref @img2) numa cena (ref @img1) preservando identidade."""
    return (
        "Place the woman from the SECOND reference @img2 into the exact scene, "
        "setting and pose shown in the FIRST reference @img1. Match the lighting, "
        "atmosphere, position, color grading, clothes of first reference, framing "
        "and composition of the first image perfectly. Preserve the woman's facial "
        "features, hair, body shape, tattoos, piercings and overall identity exactly "
        "from the second image. Photorealistic editorial portrait, natural skin "
        "texture, sharp focus, professional photography. no tatoos, no glasses"
        + (f", {raw}" if raw else "")
    )


def _dresser_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Troca a roupa de uma pessoa (ref @img1) pelo outfit (ref @img2)."""
    return (
        "Dress the person from the FIRST reference @img1 with the OUTFIT shown in "
        "the SECOND reference @img2. Preserve the person's exact face, hair, skin "
        "tone, tattoos, body shape, pose, framing, camera angle, background, scene "
        "and lighting from the FIRST image. Replace ONLY the outfit, matching the "
        "SECOND image's color, fabric, print, cut, straps and details exactly. "
        "Photorealistic, natural skin texture, sharp focus."
        + (f" {raw}" if raw else "")
    )


def _hot_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Edição livre de imagem usando 2 refs (img1=base, img2=guia visual)."""
    return (
        "Edit the FIRST reference image @img1 according to the instructions, using "
        "the SECOND reference @img2 as visual guide. Preserve the identity (face, "
        "hair, body) of the main subject. Photorealistic, natural skin texture, "
        "sharp focus."
        + (f" {raw}" if raw else "")
    )


def _cinema_shot_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Frame cinematográfico 21:9 com continuidade visual entre shots."""
    idx = opts.shot_index or 1
    total = opts.shot_total or 1
    camera = opts.camera or "medium close-up, eye-level"
    lens = opts.lens or "50mm f/1.8"
    mood = opts.mood or "intimate"
    persona = (
        f"Subject (consistent across all shots): {opts.persona_description}. "
        if opts.persona_description else ""
    )
    return (
        f"Cinematic still, frame {idx}/{total}, 21:9 anamorphic, 35mm film grain, "
        f"color graded teal/orange or as scene dictates. Coherent character and "
        f"wardrobe across all shots.\n\n"
        f"{persona}Scene: {raw}\n\n"
        f"Camera: {camera}. Lens: {lens}. Mood: {mood}."
    )


def _product_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Foto editorial de produto — studio softbox, micro-contraste."""
    return (
        "Editorial product photography. Studio softbox lighting, seamless gradient "
        "backdrop, micro-contrast on materials, "
        f"{opts.aspect_ratio} hero composition, no AI artifacts on logos/text.\n\n"
        f"Product brief: {raw}"
    )


def _ecommerce_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Hero shot pra marketplace — fundo limpo, foco frontal."""
    return (
        "E-commerce hero shot for marketplace listing. Clean white or contextual "
        "background, product centered, accurate color reproduction, sharp focus "
        "front-to-back, no extraneous props.\n\n"
        f"Brief: {raw}"
    )


def _character_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Reference sheet — full body neutro pra reuso como identity ref."""
    return (
        "Character reference sheet style. Full-body neutral pose, T-pose optional, "
        "even diffuse lighting, neutral grey backdrop, sharp on facial features, "
        "accurate proportions for downstream re-use as identity reference.\n\n"
        f"Character: {raw}"
    )


def _r3d_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Render 3D simulado via prompt — Octane/ZBrush vibe."""
    return (
        "Octane render, 3D character/asset, isometric or three-quarter view, "
        "subsurface scattering, studio HDRI lighting, ZBrush sculpt detail, "
        "sharp PBR materials, clean white or neutral grey backdrop.\n\n"
        f"Subject: {raw}"
    )


def _assets_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Asset/prop isolado — preparado pra background_remover em pós."""
    return (
        f"{raw}, isolated on pure white background, studio lighting, centered, "
        f"no shadow, sharp edges, single subject only, no text or logos."
    )


def _depth_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Cena com profundidade clara — base pra extrair depth map em pós."""
    return (
        "Photographic scene with clear depth layers (foreground, midground, "
        "background), strong parallax cues, even lighting without heavy shadows, "
        "sharp focus front-to-back.\n\n"
        f"Scene: {raw}"
    )


def _marketing_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Campanha — cópia + visual guidance."""
    return (
        f"Marketing visual aligned with brand brief. Editorial-grade photography, "
        f"{opts.aspect_ratio} composition, strong focal hierarchy, copy-friendly "
        f"negative space.\n\n"
        f"Brief: {raw}"
    )


def _image_default_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Default genérico pra tab `image` — minimal, deixa o user dirigir."""
    # Pra image livre, NÃO envelopar pesado. Só adiciona aspect_ratio se o user
    # não mencionou. Lovable confirmou: nano-banana respeita melhor prompt cru.
    if opts.aspect_ratio and "aspect ratio" not in raw.lower():
        return f"{raw}\n\nAspect ratio: {opts.aspect_ratio}."
    return raw


def _video_default_v1(raw: str, opts: EnvelopeOpts) -> str:
    """Default pra video — Lovable confirmou: prompt cru funciona melhor.
    Kling 2.5 Pro respeita identidade nativamente quando body usa `image` certo."""
    return raw


# ─────────────── Registry ───────────────
# Chave: "<tool>:<op>" ou "<tool>:" (default da tool)
# Valor: (template_fn, version_string)

EnvelopeFn = Callable[[str, EnvelopeOpts], str]

_ENVELOPES: dict[str, tuple[EnvelopeFn, str]] = {
    # Edit ops com 2 refs
    "edit:scene_swap":  (_scene_swap_v1,   "scene_swap@v1"),
    "edit:dresser":     (_dresser_v1,      "dresser@v1"),
    "edit:hot":         (_hot_v1,          "hot@v1"),

    # Tools com prompt envelope forte
    "cinema:":          (_cinema_shot_v1,  "cinema_shot@v1"),
    "product:":         (_product_v1,      "product@v1"),
    "ecommerce:":       (_ecommerce_v1,    "ecommerce@v1"),
    "character:":       (_character_v1,    "character@v1"),
    "character:create": (_character_v1,    "character@v1"),
    "r3d:":             (_r3d_v1,          "r3d@v1"),
    "assets:":          (_assets_v1,       "assets@v1"),
    "depth:":           (_depth_v1,        "depth@v1"),
    "marketing:":       (_marketing_v1,    "marketing@v1"),

    # Tools com prompt mais livre
    "image:":           (_image_default_v1, "image_default@v1"),
    "video:":           (_video_default_v1, "video_default@v1"),
}


# ─────────────── Public API ───────────────

def envelope(
    tool: str,
    raw_prompt: str,
    *,
    op: str | None = None,
    opts: EnvelopeOpts | None = None,
) -> tuple[str, str]:
    """
    Aplica o envelope correto pra (tool, op) e retorna (final_prompt, version).

    Lookup ordem:
      1. "<tool>:<op>" exato (ex: "edit:dresser")
      2. "<tool>:" default da tool (ex: "image:")
      3. fallback raw_prompt sem envelope, version="raw@v0"

    `opts` é opcional — só usado por templates que precisam (cinema, product, etc).
    """
    opts = opts or EnvelopeOpts()
    raw = (raw_prompt or "").strip()

    keys_to_try = []
    if op:
        keys_to_try.append(f"{tool}:{op}")
    keys_to_try.append(f"{tool}:")

    for key in keys_to_try:
        if key in _ENVELOPES:
            fn, version = _ENVELOPES[key]
            return fn(raw, opts), version

    # Fallback puro
    return raw, "raw@v0"


def list_envelopes() -> list[str]:
    """Lista todos os envelopes disponíveis (`<tool>:<op>` keys)."""
    return sorted(_ENVELOPES.keys())

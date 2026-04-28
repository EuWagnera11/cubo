"""
Refine — Specialized AI features.

Funções compostas que usam Freepik + Claude pra criar workflows específicos:
  - multi_view              : 4 ângulos da mesma persona (front/side/back/3/4)
  - hair_change             : muda cor/estilo do cabelo
  - outfit_change           : troca outfit completo
  - expression_change       : muda expressão facial
  - age_change              : envelhecer/rejuvenescer
  - photo_restoration       : colorize + denoise + upscale fotos antigas
  - twin_generation         : 2x da mesma persona na cena
  - headshot_pro            : LinkedIn/profile photo profissional
  - ecommerce_product       : produto em fundo branco + lifestyle
  - real_estate_enhance     : staging virtual de imóveis
  - food_photography        : food photo profissional
  - magazine_cover          : capa de revista editorial
  - youtube_thumbnail       : thumbnail YouTube otimizado
  - instagram_grid_9        : 9 posts coerentes pra grid
  - story_sequence          : sequência narrativa visual
  - brand_mockup            : produto em mockups (mug, t-shirt, etc)
  - passport_photo          : foto formato passaporte
  - wedding_album           : álbum de casamento
  - maternity_session       : ensaio gestante
  - family_portrait         : retrato família
  - pet_portrait            : retrato pet editorial
"""
from __future__ import annotations

import asyncio
from typing import Literal, Optional

from .freepik import get_freepik, FreepikError


# ────────────────────────────────────────────────────────────────
#                    PERSONA MULTI-VIEW & TRANSFORMS
# ────────────────────────────────────────────────────────────────

async def multi_view(persona_ref: str, *, num_angles: int = 4) -> list[str]:
    """
    Gera N ângulos da mesma persona (front, 3/4, side, back).
    Útil pra preparar canonical_grid pra novos personas.
    """
    angles = ["front view portrait", "three-quarter view", "side profile view", "back view"][:num_angles]
    fp = get_freepik()
    results = []
    for angle in angles:
        prompt = f"same person, {angle}, neutral expression, studio lighting, full body, identity preserved"
        tid = await fp.nano_banana_pro(prompt=prompt, reference_images=[persona_ref])
        result = await fp.poll_task(tid, kind="image")
        urls = result.get("generated") or result.get("urls") or []
        if urls:
            results.append(urls[0] if isinstance(urls, list) else urls)
    return results


async def hair_change(image_url: str, *, color: str = "", style: str = "") -> str:
    """Muda cor/estilo do cabelo preservando rosto e pose."""
    prompt_parts = ["same person, same pose, same outfit, same background"]
    if color:
        prompt_parts.append(f"hair color changed to {color}")
    if style:
        prompt_parts.append(f"hairstyle changed to {style}")
    prompt_parts.append("face identity preserved, natural realistic")
    prompt = ", ".join(prompt_parts)

    fp = get_freepik()
    tid = await fp.nano_banana_pro(prompt=prompt, reference_images=[image_url])
    return tid


async def expression_change(image_url: str, expression: str) -> str:
    """Muda expressão facial (smile, serious, laughing, surprised, etc)."""
    prompt = f"same person, change facial expression to {expression}, preserve everything else"
    fp = get_freepik()
    tid = await fp.nano_banana_pro(prompt=prompt, reference_images=[image_url])
    return tid


async def age_change(image_url: str, *, target_age: int) -> str:
    """Age progression/regression."""
    prompt = f"same person aged to {target_age} years old, preserve identity, natural progression"
    fp = get_freepik()
    tid = await fp.nano_banana_pro(prompt=prompt, reference_images=[image_url])
    return tid


async def twin_generation(persona_ref: str, scene_prompt: str) -> str:
    """Gera 2 cópias da mesma persona interagindo na mesma cena."""
    prompt = f"two of the same person interacting, {scene_prompt}, identical twins, same identity preserved"
    fp = get_freepik()
    tid = await fp.nano_banana_pro(prompt=prompt, reference_images=[persona_ref, persona_ref])
    return tid


# ────────────────────────────────────────────────────────────────
#                    PHOTO RESTORATION & ENHANCEMENT
# ────────────────────────────────────────────────────────────────

async def photo_restoration(old_photo_url: str, *, colorize: bool = True,
                             upscale: bool = True) -> dict:
    """
    Pipeline completo de restauração de foto antiga:
      1. Colorize (se P&B)
      2. Skin enhancer (denoise + sharpen)
      3. Magnific upscale 2x
    Retorna URLs intermediários e final.
    """
    fp = get_freepik()
    current = old_photo_url
    steps: dict[str, str] = {"original": old_photo_url}

    if colorize:
        tid = await fp.colorize(current, prompt="natural photographic colors, period-accurate")
        r = await fp.poll_task(tid, kind="enhance")
        out = r.get("generated") or [current]
        current = out[0] if isinstance(out, list) else out
        steps["colorized"] = current

    # Denoise / restore detail
    tid = await fp.skin_enhancer(current, mode="faithful", skin_detail=15)
    r = await fp.poll_task(tid, kind="enhance")
    out = r.get("generated") or [current]
    current = out[0] if isinstance(out, list) else out
    steps["enhanced"] = current

    if upscale:
        tid = await fp.magnific_upscaler(current, scale=2, engine="magnific_sparkle")
        r = await fp.poll_task(tid, kind="enhance")
        out = r.get("generated") or [current]
        current = out[0] if isinstance(out, list) else out
        steps["upscaled"] = current

    return {"final": current, "steps": steps}


# ────────────────────────────────────────────────────────────────
#                    PROFESSIONAL PRESETS
# ────────────────────────────────────────────────────────────────

async def headshot_pro(persona_ref: str, *, style: Literal["corporate", "creative", "casual", "editorial"] = "corporate") -> str:
    """LinkedIn/profile photo profissional."""
    style_prompts = {
        "corporate": "corporate professional headshot, studio lighting, neutral background, suit/blazer, confident smile, sharp",
        "creative":  "creative industry headshot, artistic lighting, modern background, smart casual",
        "casual":    "approachable casual headshot, natural light, relaxed expression, warm",
        "editorial": "editorial magazine cover headshot, dramatic lighting, fashion-forward, striking",
    }
    fp = get_freepik()
    return await fp.nano_banana_pro(
        prompt=style_prompts[style], reference_images=[persona_ref],
        aspect_ratio="square_1_1", size="2k",
    )


async def ecommerce_product(product_image_url: str, *,
                            mode: Literal["white_bg", "lifestyle", "luxury"] = "white_bg",
                            scene_prompt: str = "") -> str:
    """Produto em fundo branco / lifestyle / luxury."""
    if mode == "white_bg":
        prompt = "product photography on pure white seamless background, studio lighting, e-commerce ready, sharp"
    elif mode == "lifestyle":
        prompt = scene_prompt or "product in lifestyle setting, natural use, warm aesthetic, instagram-ready"
    else:
        prompt = "luxury product photography, dramatic lighting, marble surface, premium aesthetic, magazine quality"
    fp = get_freepik()
    return await fp.nano_banana_pro(prompt=prompt, reference_images=[product_image_url])


async def real_estate_enhance(property_image_url: str, *, style: str = "modern") -> str:
    """Virtual staging de imóvel."""
    prompt = f"interior real estate photography, {style} furniture staging, professional architectural, magazine-quality"
    fp = get_freepik()
    return await fp.nano_banana_pro(prompt=prompt, reference_images=[property_image_url])


async def food_photography(food_image_url: str, *, mood: str = "bright airy") -> str:
    """Food photo profissional pra cardápio / Instagram."""
    prompt = f"food photography, {mood}, restaurant magazine quality, appetizing, professional plating, overhead or 3/4 angle"
    fp = get_freepik()
    return await fp.nano_banana_pro(prompt=prompt, reference_images=[food_image_url])


async def magazine_cover(persona_ref: str, *, magazine_name: str = "VOGUE",
                         theme: str = "editorial fashion", headline: str = "") -> str:
    """Capa de revista editorial."""
    prompt = (f"{magazine_name} magazine cover, {theme}, dramatic editorial composition, "
              f"professional fashion photography, dramatic lighting, headline space top/bottom")
    if headline:
        prompt += f", suggesting headline: {headline}"
    fp = get_freepik()
    return await fp.nano_banana_pro(
        prompt=prompt, reference_images=[persona_ref],
        aspect_ratio="portrait_3_4", size="4k",
    )


async def youtube_thumbnail(persona_ref: str, *, theme: str, big_text: str = "") -> str:
    """Thumbnail YouTube otimizado (1280x720, clickbait visual)."""
    prompt = (f"YouTube thumbnail, {theme}, dramatic facial expression, vibrant high-contrast, "
              f"big bold composition, clickbait aesthetic, optimized for thumbnail")
    if big_text:
        prompt += f", text overlay '{big_text}'"
    fp = get_freepik()
    return await fp.nano_banana_pro(
        prompt=prompt, reference_images=[persona_ref],
        aspect_ratio="widescreen_16_9", size="2k",
    )


async def passport_photo(persona_ref: str) -> str:
    """Foto formato passaporte (white bg, frontal, neutra)."""
    prompt = ("passport photo, frontal view, neutral expression, plain white background, "
              "even lighting, sharp focus, official document style, head and shoulders, no shadows")
    fp = get_freepik()
    return await fp.nano_banana_pro(
        prompt=prompt, reference_images=[persona_ref],
        aspect_ratio="portrait_3_4", size="2k",
    )


# ────────────────────────────────────────────────────────────────
#                    SPECIALIZED SHOOTS
# ────────────────────────────────────────────────────────────────

async def maternity_session(persona_ref: str, *, weeks: int = 32) -> str:
    """Ensaio gestante editorial."""
    prompt = (f"maternity photoshoot, {weeks} weeks pregnant, flowing dress, golden hour outdoor, "
              f"romantic editorial, professional maternity photography")
    fp = get_freepik()
    return await fp.nano_banana_pro(prompt=prompt, reference_images=[persona_ref])


async def wedding_session(persona_ref: str, *, scene: str = "garden") -> str:
    """Ensaio casamento."""
    prompt = (f"wedding photography, bride white gown, {scene} venue, romantic golden hour, "
              f"professional wedding editorial, magazine-quality")
    fp = get_freepik()
    return await fp.nano_banana_pro(prompt=prompt, reference_images=[persona_ref])


async def boudoir_session(persona_ref: str) -> str:
    """Boudoir editorial elegante."""
    prompt = ("boudoir photography editorial, silk slip dress, soft natural light, "
              "luxurious bedroom, refined sensual elegance, magazine-quality, tasteful")
    fp = get_freepik()
    return await fp.nano_banana_pro(prompt=prompt, reference_images=[persona_ref])


async def family_portrait(persona_refs: list[str], *, scene: str = "park sunset") -> str:
    """Retrato família (múltiplas refs)."""
    prompt = f"family portrait photography, {scene}, candid moment, professional family editorial"
    fp = get_freepik()
    return await fp.nano_banana_pro(prompt=prompt, reference_images=persona_refs)

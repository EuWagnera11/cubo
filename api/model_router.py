"""
Model router — mapeia ID de modelo (com hífen, do pricing.py / payload do front)
para o nome do método Python no cliente Freepik (com underscore).

Quando o front envia `model="nano-banana-pro"` ou `video_engine="kling-v3-std"`,
o backend resolve aqui qual método chamar em `freepik.py`.
"""
from __future__ import annotations
import inspect
from typing import Any, Callable

# ── IMAGE: model id → freepik.py method name ─────────────────────────────
IMAGE_MODEL_TO_METHOD: dict[str, str] = {
    "nano-banana-pro":       "nano_banana_pro",
    "nano-banana-pro-flash": "nano_banana_pro_flash",
    "nano-banana-2":         "nano_banana_pro",  # alias até ter método dedicado
    "mystic":                "mystic",
    "flux-dev":              "flux_dev",
    "flux-pro-1-1":          "flux_pro",
    "flux-2-pro":            "flux_2_pro",
    "flux-2-turbo":          "flux_2_turbo",
    "flux-2-klein":          "flux_2_klein",
    "flux-kontext-pro":      "flux_kontext_pro",
    "hyperflux":             "hyperflux",
    "imagen-3":              "imagen3",
    "imagen-4-fast":         "imagen_4_fast",
    "imagen-4-ultra":        "imagen_4_ultra",
    "seedream-v4":           "seedream_v4",
    "seedream-v4-5":         "seedream_v4_5",
    "seedream-v5-lite":      "seedream_v5_lite",
    "z-image-turbo":         "z_image_turbo",
    "runway-t2i":            "runway_t2i",
}

# ── VIDEO: engine id → freepik.py method name ────────────────────────────
VIDEO_ENGINE_TO_METHOD: dict[str, str] = {
    # Kling V3 family
    "kling-v3-std":        "kling_v3",
    "kling-v3-pro":        "kling_v3",
    "kling-v3-motion-std": "kling_v3_motion_control",
    "kling-v3-motion-pro": "kling_v3_motion_control",
    "kling-v3-omni-std":   "kling_v3_omni",
    "kling-v3-omni-pro":   "kling_v3_omni",
    # Kling O1
    "kling-o1-std":        "kling_o1",
    "kling-o1-pro":        "kling_o1",
    # Kling V2
    "kling-v2-6-pro":      "kling_v2_6",
    "kling-pro-2-5-turbo": "kling_pro_2_5_turbo",
    "kling-pro-2-1":       "kling_v2_1",
    "kling-std-2-1":       "kling_v2_1",
    # Veo
    "veo-3-1-1080p":       "veo_3_1",
    "veo-3-1-4k":          "veo_3_1",
    "veo-3-1-fast-1080p":  "veo_3_1_fast",
    # Hailuo
    "hailuo-02-768p":        "hailuo_02",
    "hailuo-02-1080p":       "hailuo_02",
    "hailuo-2-3-768p":       "hailuo_2_3",
    "hailuo-2-3-1080p":      "hailuo_2_3",
    "hailuo-2-3-fast-768p":  "hailuo_2_3",
    "hailuo-2-3-fast-1080p": "hailuo_2_3",
    # Runway
    "runway-gen-4-5":      "runway_gen_4_5",
    "runway-gen-4-turbo":  "runway_gen_4_turbo",
    # Seedance
    "seedance-pro-720p":     "seedance_pro",
    "seedance-pro-1080p":    "seedance_pro",
    "seedance-1-5-pro-1080p": "seedance_1_5_pro",
    # Pixverse
    "pixverse-v5-720p":   "pixverse_v5",
    "pixverse-v5-1080p":  "pixverse_v5",
    # LTX
    "ltx-2-fast-1080p":   "ltx_2_fast",
    "ltx-2-pro-1080p":    "ltx_2_pro",
    "ltx-2-pro-4k":       "ltx_2_pro",
    # Wan
    "wan-2-6-720p":       "wan_2_6",
    "wan-2-6-1080p":      "wan_2_6",
    "wan-2-7":            "wan_2_7",
    # Omnihuman
    "omnihuman-1-5":      "omnihuman_1_5",
}


def resolve_image_method(model_id: str) -> str:
    """Retorna o nome do método freepik.py para o `model_id`. Default: nano_banana_pro."""
    if not model_id:
        return "nano_banana_pro"
    if model_id in IMAGE_MODEL_TO_METHOD:
        return IMAGE_MODEL_TO_METHOD[model_id]
    # Fallback: tenta com underscore (caso o caller já tenha enviado nome de método)
    candidate = model_id.replace("-", "_")
    return candidate if candidate.replace("_", "").isalnum() else "nano_banana_pro"


def resolve_video_method(engine_id: str) -> str:
    """Retorna o nome do método freepik.py para o `engine_id`. Default: kling_v3."""
    if not engine_id:
        return "kling_v3"
    if engine_id in VIDEO_ENGINE_TO_METHOD:
        return VIDEO_ENGINE_TO_METHOD[engine_id]
    candidate = engine_id.replace("-", "_")
    return candidate if candidate.replace("_", "").isalnum() else "kling_v3"


def call_with_supported_kwargs(fn: Callable, **all_kwargs: Any) -> Any:
    """
    Chama `fn` apenas com os kwargs que ele aceita (filtra pela assinatura).

    Cada método freepik.py tem assinatura diferente — uns aceitam `reference_images`,
    outros não; uns querem `size`, outros `resolution`, outros nem isso.
    Esse helper evita TypeError filtrando kwargs incompatíveis.
    """
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        # Built-ins ou C-functions sem signature: passa tudo, deixa rebentar
        return fn(**all_kwargs)
    params = sig.parameters
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if accepts_kwargs:
        return fn(**all_kwargs)
    valid = {k: v for k, v in all_kwargs.items() if k in params}
    return fn(**valid)

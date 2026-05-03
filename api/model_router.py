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
# Lista alinhada com /v1/ai/text-to-image/* da Magnific (2026-05).
IMAGE_MODEL_TO_METHOD: dict[str, str] = {
    "nano-banana-pro":       "nano_banana_pro",
    "nano-banana-pro-flash": "nano_banana_pro_flash",
    "nano-banana-2":         "nano_banana_2",  # endpoint /gemini-2-5-flash-image-preview (refs como URLs)
    "mystic":                "mystic",
    "flux-pro-1-1":          "flux_pro",
    "flux-2-klein":          "flux_2_klein",
    "flux-kontext-pro":      "flux_kontext_pro",
    "hyperflux":             "hyperflux",
    "imagen4-fast":          "imagen_4_fast",
    "imagen4-ultra":         "imagen_4_ultra",
    "seedream-v4":           "seedream_v4",
    "seedream-v4-edit":      "seedream_edit_v4",
}

# ── VIDEO: engine id → freepik.py method name ────────────────────────────
# Lista alinhada com a API atual da Magnific/Freepik (2026-05) — paths confirmados.
VIDEO_ENGINE_TO_METHOD: dict[str, str] = {
    # Kling V3 (em /v1/ai/video/)
    "kling-v3-pro":            "kling_v3_pro",
    "kling-v3-std":            "kling_v3_std",
    "kling-v3-motion-pro":     "kling_v3_motion_control",   # quality=pro
    "kling-v3-motion-std":     "kling_v3_motion_control",   # quality=std
    "kling-v3-omni-pro":       "kling_v3_omni",             # quality=pro
    "kling-v3-omni-std":       "kling_v3_omni",             # quality=std
    # Kling O1
    "kling-o1-pro":            "kling_o1",
    "kling-o1-std":            "kling_o1",
    # Kling V2
    "kling-v2-5-pro":          "kling_v2_6",                # método antigo aponta pra v2-5-pro
    "kling-v2-1-master":       "kling_v2_1",                # tier=master
    "kling-v2-1-pro":          "kling_v2_1",                # tier=pro
    "kling-v2-1-std":          "kling_v2_1",                # tier=std
    # Veo
    "veo-3-1":                 "veo_3_1",
    "veo-3-1-fast":            "veo_3_1_fast",
    # Hailuo (Minimax)
    "hailuo-02-1080p":         "hailuo_02",
    "hailuo-2-3-1080p":        "hailuo_2_3",
    # Runway
    "runway-4-5":              "runway_gen_4_5",
    "runway-act-two":          "runway_act_two",
    # Seedance
    "seedance-pro-1080p":      "seedance_pro",
    "seedance-pro-720p":       "seedance_pro",
    # Pixverse
    "pixverse-v5":             "pixverse_v5",
    "pixverse-v5-transition":  "pixverse_v5_transition",
    # LTX (text-to-video)
    "ltx-2-pro":               "ltx_2_pro",
    # Wan
    "wan-v2-6-1080p":          "wan_2_6",
    "wan-2-5-i2v-1080p":       "wan_2_5_i2v",
    "wan-2-5-t2v-1080p":       "wan_2_5_t2v",
    "wan-2-5-t2v-720p":        "wan_2_5_t2v",
    "wan-2-5-t2v-480p":        "wan_2_5_t2v",
    "wan-2-7":                 "wan_2_7",
    # Omnihuman (audio-to-video — animar foto com áudio)
    "omnihuman-1-5":           "omnihuman_1_5",
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

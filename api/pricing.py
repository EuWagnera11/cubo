"""Pricing — tabelas centrais de custo em créditos do Cubo / Refine.

Multiplicador: créditos = custo USD Freepik × 1.785 (igual à plataforma web Freepik).
Calibrado pra que Nano Banana 2 1K = 75 créditos (mesmo peso do Freepik).

Estrutura:
  - IMAGE_COSTS    : (model, resolution) -> credits
  - VIDEO_COSTS    : (model, duration_s, audio_mode) -> credits
  - ENHANCE_COSTS  : operation -> credits
  - EDIT_COSTS     : operation -> credits
  - AUDIO_COSTS    : operation -> credits
  - SWAP_COSTS     : operation -> credits
  - SPECIALIZED_COSTS : workflow -> credits
  - DAILY_CAPS     : tier -> {model: max_per_day}
  - MODEL_TIERS    : model -> visual tier (economic/balanced/premium)

Usage:
    from api.pricing import IMAGE_COSTS, get_image_cost, get_video_cost
    cost = get_image_cost("nano-banana-pro", "4k")  # → 535
"""
from __future__ import annotations

from typing import Literal, Optional


# ════════════════════════════════════════════════════════════════
#                          IMAGEM (text-to-image)
# ════════════════════════════════════════════════════════════════

IMAGE_COSTS: dict[tuple[str, str], int] = {
    # ─── 🟢 Econômicos ───
    ("flux-2-turbo",            "1k"): 18,
    ("flux-dev",                "1k"): 20,
    ("z-image-turbo",           "1k"): 35,
    ("imagen-4-fast",           "1k"): 35,
    ("seedream-v4",             "1k"): 60,
    ("flux-2-pro",              "1k"): 65,
    ("flux-kontext-pro",        "1k"): 70,
    ("seedream-v4-5",           "1k"): 75,
    ("seedream-v5-lite",        "1k"): 75,
    ("nano-banana-2",           "1k"): 75,
    ("flux-pro-1-1",            "1k"): 80,

    # ─── 🟡 Equilibrados ───
    ("imagen-3",                "1k"): 90,
    ("flux-2-klein",            "1k"): 20,
    ("flux-2-klein",            "2k"): 90,
    ("imagen-4-ultra",          "1k"): 110,
    ("mystic",                  "1k"): 125,
    ("mystic",                  "2k"): 215,
    ("runway-t2i",              "1k"): 180,

    # ─── 🔴 Premium ───
    ("nano-banana-pro-flash",   "1k"): 170,
    ("nano-banana-pro-flash",   "2k"): 255,
    ("nano-banana-pro-flash",   "4k"): 340,
    ("nano-banana-pro",         "1k"): 180,
    ("nano-banana-pro",         "2k"): 270,
    ("nano-banana-pro",         "4k"): 535,
    ("hyperflux",               "1k"): 290,
    ("mystic",                  "4k"): 680,
}


def get_image_cost(model: str, resolution: str = "1k") -> Optional[int]:
    return IMAGE_COSTS.get((model, resolution))


# ════════════════════════════════════════════════════════════════
#                              VÍDEO
# ════════════════════════════════════════════════════════════════

# Chave: (model, duration, audio_mode)
# audio_mode: "silent" ou "audio"
VIDEO_COSTS: dict[tuple[str, str, str], int] = {
    # ─── 🟢 Econômicos ───
    ("hailuo-02-768p",        "6s",  "silent"): 255,
    ("hailuo-2-3-fast-768p",  "6s",  "silent"): 340,
    ("ltx-2-fast-1080p",      "5s",  "silent"): 360,
    ("pixverse-v5-720p",      "5s",  "silent"): 430,
    ("hailuo-2-3-768p",       "6s",  "silent"): 500,
    ("ltx-2-pro-1080p",       "5s",  "silent"): 525,

    # ─── 🟡 Equilibrados ───
    ("kling-std-2-1",         "5s",  "silent"): 530,
    ("kling-std-2-1",         "10s", "silent"): 1060,
    ("hailuo-2-3-fast-1080p", "6s",  "silent"): 590,
    ("kling-v2-6-pro",        "5s",  "silent"): 625,
    ("kling-v2-6-pro",        "10s", "silent"): 1250,
    ("kling-v2-6-pro",        "5s",  "audio"):  1250,
    ("kling-v2-6-pro",        "10s", "audio"):  2500,
    ("seedance-pro-720p",     "5s",  "silent"): 625,
    ("kling-pro-2-5-turbo",   "5s",  "silent"): 670,
    ("kling-pro-2-5-turbo",   "10s", "silent"): 1340,
    ("hailuo-02-1080p",       "6s",  "silent"): 830,
    ("pixverse-v5-1080p",     "5s",  "silent"): 850,
    ("hailuo-2-3-1080p",      "6s",  "silent"): 875,
    ("kling-pro-2-1",         "5s",  "silent"): 890,
    ("kling-pro-2-1",         "10s", "silent"): 1780,
    ("wan-2-6-720p",          "5s",  "silent"): 890,
    ("veo-3-1-fast-1080p",    "5s",  "silent"): 890,
    ("veo-3-1-fast-1080p",    "5s",  "audio"):  1340,
    ("seedance-pro-1080p",    "5s",  "silent"): 1385,
    ("seedance-1-5-pro-1080p","5s",  "silent"): 1110,
    ("seedance-1-5-pro-1080p","5s",  "audio"):  2185,
    ("runway-gen-4-5",        "5s",  "silent"): 1070,
    ("wan-2-6-1080p",         "5s",  "silent"): 1340,
    ("runway-gen-4-turbo",    "5s",  "silent"): 1340,
    ("wan-2-7",               "5s",  "silent"): 890,
    ("omnihuman-1-5",         "5s",  "silent"): 1440,

    # ─── 🔴 Premium ───
    ("kling-v3-std",          "5s",  "silent"): 1500,
    ("kling-v3-std",          "10s", "silent"): 3000,
    ("kling-v3-std",          "5s",  "audio"):  2000,
    ("veo-3-1-1080p",         "5s",  "silent"): 1785,
    ("kling-v3-pro",          "5s",  "silent"): 2000,
    ("kling-v3-pro",          "10s", "silent"): 4000,
    ("kling-v3-pro",          "5s",  "audio"):  3010,
    ("ltx-2-pro-4k",          "5s",  "silent"): 2140,
    ("kling-v3-motion-pro",   "5s",  "silent"): 1785,
    ("kling-v3-motion-std",   "5s",  "silent"): 1340,
    ("kling-v3-omni-pro",     "5s",  "silent"): 2000,
    ("kling-v3-omni-std",     "5s",  "silent"): 1500,
    ("kling-o1-pro",          "5s",  "silent"): 1000,
    ("kling-o1-std",          "5s",  "silent"): 750,
    ("veo-3-1-1080p",         "5s",  "audio"):  3570,
    ("veo-3-1-4k",            "5s",  "silent"): 3570,
    ("veed-fabric-1-0",       "5s",  "silent"): 1340,

    # ─── Lipsync ───
    ("latent-sync",           "10s", "silent"): 90,
}


def get_video_cost(model: str, duration: str = "5s", audio: bool = False) -> Optional[int]:
    return VIDEO_COSTS.get((model, duration, "audio" if audio else "silent"))


# ════════════════════════════════════════════════════════════════
#                            ENHANCERS
# ════════════════════════════════════════════════════════════════

ENHANCE_COSTS: dict[str, int] = {
    "magnific_1k_to_2k":    215,
    "magnific_2k_to_4k":    425,
    # 4K → 8K vai como add-on (R$19,90), não consome créditos

    "skin_creative":        560,
    "skin_faithful":        710,
    "skin_flexible":        865,

    "bg_remove":            35,
    "image_relight":        265,
    "style_transfer":       265,

    # Video upscaler (multiplicador frame)
    "video_upscaler_1k":    14,    # por segundo (estimativa: 30fps × $0.008/frame × 1.785 / 30 = ~14)
    "video_upscaler_2k":    19,
    "video_upscaler_4k":    25,
    "video_upscaler_turbo_1k": 11,
    "video_upscaler_turbo_2k": 13,
    "video_upscaler_turbo_4k": 14,
}


# ════════════════════════════════════════════════════════════════
#                          EDIÇÃO
# ════════════════════════════════════════════════════════════════

EDIT_COSTS: dict[str, int] = {
    "reimagine_flux":             20,
    "image_to_prompt":            45,
    "improve_prompt":             45,
    "image_expand_ideogram":      55,
    "inpaint_ideogram_turbo":     55,
    "seedream_edit_v4":           60,
    "change_camera":              60,
    "seedream_edit_v4_5":         75,
    "seedream_edit_v5_lite":      75,
    "image_expand_seedream":      75,
    "inpaint_ideogram_default":   110,
    "image_expand_flux":          150,
    "inpaint_ideogram_quality":   160,
}


# ════════════════════════════════════════════════════════════════
#                            ÁUDIO
# ════════════════════════════════════════════════════════════════

AUDIO_COSTS: dict[str, int] = {
    "sound_effect":         8,
    "audio_isolation_10s":  35,
    "tts_per_100_chars":    40,
    "lipsync_10s":          90,
    "music_30s":            425,
    "music_60s":            850,
    # Voice clone vai como add-on R$39 (não consome créditos)
}


# ════════════════════════════════════════════════════════════════
#                            SWAPS
# ════════════════════════════════════════════════════════════════

SWAP_COSTS: dict[str, int] = {
    "face_swap":   535,    # NB Pro 2K + relight
    "cloth_swap":  715,    # NB Pro 2K + skin enhance
    "scene_swap":  1355,   # NB Pro 4K + skin creative + relight
}


# ════════════════════════════════════════════════════════════════
#                       FERRAMENTAS ESPECIALIZADAS
# ════════════════════════════════════════════════════════════════

SPECIALIZED_COSTS: dict[str, int] = {
    "headshot_pro":         270,
    "passport_photo":       270,
    "hair_change":          270,
    "expression_change":    270,
    "age_change":           270,
    "ecommerce_product":    270,
    "real_estate_enhance":  270,
    "food_photography":     270,
    "youtube_thumbnail":    270,
    "twin_generation":      270,
    "magazine_cover":       535,
    "maternity_session":    535,
    "wedding_session":      535,
    "boudoir_session":      535,
    "family_portrait":      535,
    "pet_portrait":         535,
    "multi_view":           720,    # 4 ângulos × NB Pro 1K
    "photo_restoration":    990,    # colorize + skin enhance + magnific 2x
    "instagram_grid_9":     2430,   # 9 imagens NB Pro 1K
    "story_sequence":       1620,   # 6 imagens NB Pro 1K
    "brand_mockup":         270,
}


# ════════════════════════════════════════════════════════════════
#                          DAILY CAPS POR PLANO
# ════════════════════════════════════════════════════════════════

# Limite diário em modelos premium pra evitar abuso de margem.
# Tier "free" e "studio" usam None (sem cap específico — studio é ilimitado).
DAILY_CAPS: dict[str, dict[str, int]] = {
    "free": {
        "kling-v3-pro": 0, "kling-v3-std": 0,
        "veo-3-1-1080p": 0, "veo-3-1-4k": 0,
        "nano-banana-pro": 1, "mystic": 1,
    },
    "starter": {
        "kling-v3-pro":     1,
        "kling-v3-std":     2,
        "veo-3-1-1080p":    1,
        "veo-3-1-4k":       0,
        "nano-banana-pro":  5,
        "mystic":           3,
    },
    "creator": {
        "kling-v3-pro":     4,
        "kling-v3-std":     8,
        "veo-3-1-1080p":    3,
        "veo-3-1-4k":       1,
        "nano-banana-pro":  20,
        "mystic":           12,
    },
    "pro": {
        "kling-v3-pro":     12,
        "kling-v3-std":     25,
        "veo-3-1-1080p":    10,
        "veo-3-1-4k":       5,
        "nano-banana-pro":  80,
        "mystic":           50,
    },
    "studio": {
        # Sem caps em studio — ilimitado dentro do saldo de créditos
    },
}


def get_daily_cap(tier: str, model: str) -> Optional[int]:
    """Retorna o cap diário do modelo no plano. None = ilimitado."""
    return DAILY_CAPS.get(tier, {}).get(model)


# ════════════════════════════════════════════════════════════════
#                       TIERS VISUAIS DOS MODELOS
# ════════════════════════════════════════════════════════════════

ModelTier = Literal["economic", "balanced", "premium", "elite"]

MODEL_TIERS: dict[str, ModelTier] = {
    # 🟢 Económicos
    "flux-dev":              "economic",
    "flux-2-turbo":          "economic",
    "flux-2-pro":            "economic",
    "flux-2-klein":          "economic",
    "flux-pro-1-1":          "economic",
    "flux-kontext-pro":      "economic",
    "z-image-turbo":         "economic",
    "imagen-4-fast":         "economic",
    "seedream-v4":           "economic",
    "seedream-v4-5":         "economic",
    "seedream-v5-lite":      "economic",
    "nano-banana-2":         "economic",
    "reimagine-flux":        "economic",
    "hailuo-02-768p":        "economic",
    "hailuo-2-3-fast-768p":  "economic",
    "ltx-2-fast-1080p":      "economic",
    "pixverse-v5-720p":      "economic",
    "hailuo-2-3-768p":       "economic",
    "ltx-2-pro-1080p":       "economic",

    # 🟡 Equilibrados
    "imagen-3":              "balanced",
    "imagen-4-ultra":        "balanced",
    "mystic":                "balanced",
    "runway-t2i":            "balanced",
    "kling-std-2-1":         "balanced",
    "kling-v2-6-pro":        "balanced",
    "seedance-pro-720p":     "balanced",
    "seedance-pro-1080p":    "balanced",
    "seedance-1-5-pro-1080p":"balanced",
    "kling-pro-2-5-turbo":   "balanced",
    "kling-pro-2-1":         "balanced",
    "hailuo-02-1080p":       "balanced",
    "pixverse-v5-1080p":     "balanced",
    "hailuo-2-3-1080p":      "balanced",
    "hailuo-2-3-fast-1080p": "balanced",
    "wan-2-6-720p":          "balanced",
    "wan-2-6-1080p":         "balanced",
    "wan-2-7":               "balanced",
    "veo-3-1-fast-1080p":    "balanced",
    "runway-gen-4-5":        "balanced",
    "runway-gen-4-turbo":    "balanced",
    "kling-o1-pro":          "balanced",
    "kling-o1-std":          "balanced",

    # 🔴 Premium
    "nano-banana-pro":       "premium",
    "nano-banana-pro-flash": "premium",
    "hyperflux":             "premium",
    "kling-v3-std":          "premium",
    "kling-v3-pro":          "premium",
    "kling-v3-motion-pro":   "premium",
    "kling-v3-motion-std":   "premium",
    "kling-v3-omni-pro":     "premium",
    "kling-v3-omni-std":     "premium",
    "veo-3-1-1080p":         "premium",
    "veo-3-1-4k":            "premium",
    "ltx-2-pro-4k":          "premium",
    "veed-fabric-1-0":       "premium",
    "omnihuman-1-5":         "premium",
}


def get_model_tier(model: str) -> ModelTier:
    return MODEL_TIERS.get(model, "balanced")


# ════════════════════════════════════════════════════════════════
#                       NOMES E DESCRIÇÕES VISÍVEIS
# ════════════════════════════════════════════════════════════════

MODEL_LABELS: dict[str, str] = {
    "flux-dev":              "Flux Dev",
    "flux-2-turbo":          "Flux 2 Turbo",
    "flux-2-pro":            "Flux 2 Pro",
    "flux-2-klein":          "Flux 2 Klein",
    "flux-pro-1-1":          "Flux Pro 1.1",
    "flux-kontext-pro":      "Flux Kontext Pro",
    "z-image-turbo":         "Z-Image Turbo",
    "imagen-4-fast":         "Imagen 4 Fast",
    "imagen-4-ultra":        "Imagen 4 Ultra",
    "imagen-3":              "Imagen 3",
    "seedream-v4":           "Seedream v4",
    "seedream-v4-5":         "Seedream v4.5",
    "seedream-v5-lite":      "Seedream v5 Lite",
    "nano-banana-2":         "Nano Banana 2",
    "nano-banana-pro":       "Nano Banana Pro",
    "nano-banana-pro-flash": "Nano Banana Pro Flash",
    "mystic":                "Mystic (Magnific)",
    "hyperflux":             "HyperFlux",
    "runway-t2i":            "Runway Text-to-Image",
    "reimagine-flux":        "Reimagine Flux",

    # Vídeo
    "hailuo-02-768p":        "Hailuo 02 768p",
    "hailuo-02-1080p":       "Hailuo 02 1080p",
    "hailuo-2-3-fast-768p":  "Hailuo 2.3 Fast 768p",
    "hailuo-2-3-fast-1080p": "Hailuo 2.3 Fast 1080p",
    "hailuo-2-3-768p":       "Hailuo 2.3 768p",
    "hailuo-2-3-1080p":      "Hailuo 2.3 1080p",
    "pixverse-v5-720p":      "Pixverse v5 720p",
    "pixverse-v5-1080p":     "Pixverse v5 1080p",
    "ltx-2-fast-1080p":      "LTX 2.0 Fast 1080p",
    "ltx-2-pro-1080p":       "LTX 2.0 Pro 1080p",
    "ltx-2-pro-4k":          "LTX 2.0 Pro 4K",
    "wan-2-6-720p":          "WAN 2.6 720p",
    "wan-2-6-1080p":         "WAN 2.6 1080p",
    "wan-2-7":               "WAN 2.7",
    "seedance-pro-720p":     "Seedance Pro 720p",
    "seedance-pro-1080p":    "Seedance Pro 1080p",
    "seedance-1-5-pro-1080p":"Seedance 1.5 Pro 1080p",
    "kling-std-2-1":         "Kling Std 2.1",
    "kling-pro-2-1":         "Kling Pro 2.1",
    "kling-pro-2-5-turbo":   "Kling Pro 2.5 Turbo",
    "kling-v2-6-pro":        "Kling V2.6 Pro",
    "kling-v3-std":          "Kling V3 Standard",
    "kling-v3-pro":          "Kling V3 Pro",
    "kling-v3-motion-pro":   "Kling V3 Motion Control Pro",
    "kling-v3-motion-std":   "Kling V3 Motion Control Std",
    "kling-v3-omni-pro":     "Kling V3 Omni Pro",
    "kling-v3-omni-std":     "Kling V3 Omni Std",
    "kling-o1-pro":          "Kling O1 Pro",
    "kling-o1-std":          "Kling O1 Std",
    "veo-3-1-fast-1080p":    "Veo 3.1 Fast 1080p",
    "veo-3-1-1080p":         "Veo 3.1 1080p",
    "veo-3-1-4k":            "Veo 3.1 4K",
    "runway-gen-4-5":        "Runway Gen 4.5",
    "runway-gen-4-turbo":    "Runway Gen4 Turbo",
    "veed-fabric-1-0":       "Veed Fabric 1.0",
    "omnihuman-1-5":         "OmniHuman 1.5",
    "latent-sync":           "Latent Sync (lipsync)",
}

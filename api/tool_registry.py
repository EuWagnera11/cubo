"""
TOOL_REGISTRY — fonte única de verdade pro mapeamento ferramenta→motor.

Cada tool tem:
  - default: motor canônico (usado quando o user não escolhe)
  - options: lista pra dropdown no front
  - auto_route(ctx): callable que decide motor por contexto runtime
                     (refs, duração, t2v vs i2v, etc) — None = mantém default

A rota POST /generations chama `resolve_model(tool, op, ctx, override=None)`
pra decidir qual motor disparar antes de chamar o Freepik.

Decisões espelham a recomendação do Lovable (ver lovable.txt §1):
  - 2+ refs → nano-banana-2 (gemini-2-5-flash-image-preview, aceita URLs string)
  - 1 ref → nano-banana-pro (aceita base64 objects)
  - 10s → kling-v3-pro (V2.5 Pro só faz 5s)
  - first+last frame → pixverse-v5-transition
  - audio-driven → omnihuman-1-5
  - t2v puro → ltx-2-pro
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ─────────────── Context types ───────────────

@dataclass
class RouteContext:
    """Contexto de runtime pra decisão de auto-routing."""
    refs: list[dict] = field(default_factory=list)      # [{url, role}]
    has_image: bool = False                              # algum ref ou image_url
    duration: int | None = None                          # video duration em s
    aspect_ratio: str = "1:1"
    is_first_last: bool = False                          # pixverse transition
    has_audio: bool = False                              # omnihuman audio-to-video
    has_motion_video: bool = False                       # kling motion control
    style: str | None = None                             # "photoreal_hero", "editorial", etc
    intent: str | None = None                            # edit op: inpaint, outpaint, relight, bg_remove
    t2v: bool = False                                    # text-to-video puro

    @property
    def num_refs(self) -> int:
        return len(self.refs or [])


@dataclass
class ToolDef:
    default: str
    options: list[str]
    auto_route: Optional[Callable[[RouteContext], Optional[str]]] = None


# ─────────────── Registry ───────────────

def _route_image(ctx: RouteContext) -> Optional[str]:
    if ctx.num_refs >= 2:
        return "nano-banana-2"           # multi-ref → gemini flash (URLs strings)
    if ctx.num_refs == 1:
        return "nano-banana-pro"         # 1 ref → base64 object
    if ctx.style == "photoreal_hero":
        return "mystic"
    return None  # mantém default


def _route_video(ctx: RouteContext) -> Optional[str]:
    if ctx.t2v or (not ctx.has_image and not ctx.refs):
        return "ltx-2-pro"               # text-to-video puro
    if ctx.has_audio:
        return "omnihuman-1-5"           # audio-driven (animar foto + voz)
    if ctx.is_first_last:
        return "pixverse-v5-transition"
    if ctx.has_motion_video:
        return "kling-v3-motion-pro"
    if (ctx.duration or 5) >= 10:
        return "kling-v3-pro"            # V2.5 Pro só faz 5s
    return None  # default kling-v2-5-pro


def _route_edit(ctx: RouteContext) -> Optional[str]:
    intent_map = {
        "inpaint":   "inpaint_ideogram",
        "outpaint":  "image_expand_seedream",
        "relight":   "relight",
        "bg_remove": "background_remover",
        "scene_swap": "nano-banana-2",   # multi-ref editorial
        "dresser":    "nano-banana-2",   # idem (img1=pessoa, img2=outfit)
        "change_camera": "change_camera",
    }
    return intent_map.get(ctx.intent or "")


def _route_upscale(ctx: RouteContext) -> Optional[str]:
    return None  # default magnific_precision_v2 cobre 95% dos casos


def _route_audio(ctx: RouteContext) -> Optional[str]:
    intent_map = {
        "tts":   "text_to_speech",
        "music": "elevenlabs_music",
        "sfx":   "elevenlabs_sound_effect",
        "clone": "voice_clone",
    }
    return intent_map.get(ctx.intent or "")


TOOL_REGISTRY: dict[str, ToolDef] = {
    # ─── Studio: image-first tools ───
    "image": ToolDef(
        default="nano-banana-pro",
        options=[
            "nano-banana-pro", "nano-banana-2", "nano-banana-pro-flash",
            "seedream-v4", "imagen4-ultra", "imagen4-fast",
            "flux-pro-1-1", "flux-kontext-pro", "flux-2-klein",
            "mystic", "hyperflux",
        ],
        auto_route=_route_image,
    ),
    "cinema": ToolDef(
        default="nano-banana-pro",
        options=["nano-banana-pro", "mystic", "seedream-v4", "imagen4-ultra"],
    ),
    "ecommerce": ToolDef(
        default="nano-banana-pro",
        options=["nano-banana-pro", "seedream-v4", "mystic", "flux-kontext-pro"],
    ),
    "product": ToolDef(
        default="nano-banana-pro",
        options=["nano-banana-pro", "seedream-v4", "mystic"],
    ),
    "marketing": ToolDef(
        default="nano-banana-pro",
        options=["nano-banana-pro", "mystic", "seedream-v4", "imagen4-ultra"],
    ),
    "character": ToolDef(
        default="nano-banana-pro",
        options=["nano-banana-pro", "nano-banana-2"],
        auto_route=_route_image,  # multi-ref também aplica aqui
    ),

    # ─── Hipóteses (não tem motor nativo) ───
    "r3d": ToolDef(
        default="seedream-v4",       # bom pra "Octane render" via prompt
        options=["seedream-v4", "nano-banana-pro", "mystic"],
    ),
    "assets": ToolDef(
        default="seedream-v4",       # combina bem com background_remover
        options=["seedream-v4", "flux-pro-1-1", "nano-banana-pro"],
    ),
    "depth": ToolDef(
        default="nano-banana-pro",   # placeholder até MiDaS local
        options=["nano-banana-pro"],
    ),

    # ─── Edit & upscale ───
    "edit": ToolDef(
        default="nano-banana-pro",
        options=[
            "nano-banana-pro", "seedream-v4-edit", "flux-kontext-pro",
            "seedream_edit_v4_5", "seedream_edit_v5_lite",
            "inpaint_ideogram", "image_expand_seedream", "image_expand_flux",
            "background_remover", "relight", "change_camera", "reimagine_flux",
        ],
        auto_route=_route_edit,
    ),
    "upscale": ToolDef(
        default="magnific_precision_v2",
        options=[
            "magnific_upscaler",
            "magnific_precision_v1",
            "magnific_precision_v2",
        ],
        auto_route=_route_upscale,
    ),

    # ─── Video ───
    "video": ToolDef(
        default="kling-v2-5-pro",
        options=[
            # Kling V2/V3 (todos i2v)
            "kling-v2-5-pro", "kling-v3-pro", "kling-v3-std",
            "kling-v3-motion-pro", "kling-v3-motion-std",
            "kling-v3-omni-pro", "kling-v3-omni-std",
            "kling-o1-pro", "kling-o1-std",
            "kling-v2-1-master", "kling-v2-1-pro", "kling-v2-1-std",
            # Outros providers
            "veo-3-1", "veo-3-1-fast",
            "hailuo-02-1080p", "hailuo-2-3-1080p",
            "runway-4-5",
            "seedance-pro-1080p", "seedance-pro-720p",
            "pixverse-v5", "pixverse-v5-transition",
            "wan-2-7", "wan-v2-6-1080p",
            "wan-2-5-i2v-1080p", "wan-2-5-t2v-1080p", "wan-2-5-t2v-720p",
            # Especialistas
            "omnihuman-1-5",     # audio-to-video
            "ltx-2-pro",         # t2v
            "runway-act-two",    # video+prompt (performance)
        ],
        auto_route=_route_video,
    ),

    # ─── Audio (sub-tabs via op) ───
    "audio": ToolDef(
        default="elevenlabs_music",
        options=[
            "text_to_speech",
            "elevenlabs_music", "music_generation",
            "elevenlabs_sound_effect", "sound_effect",
            "voice_clone",
            "audio_isolation",
        ],
        auto_route=_route_audio,
    ),
}


# ─────────────── Public API ───────────────

def resolve_model(
    tool: str,
    *,
    op: str | None = None,
    ctx: RouteContext | None = None,
    override: str | None = None,
) -> str:
    """
    Decide qual motor usar pra uma geração.

    Ordem de precedência:
      1. `override` explícito do user (passou model="xyz" no request)
      2. `auto_route(ctx)` se a tool tem
      3. `default` da tool

    Levanta KeyError se a tool não existe.
    """
    if tool not in TOOL_REGISTRY:
        raise KeyError(f"Unknown tool: {tool}")

    tdef = TOOL_REGISTRY[tool]

    if override:
        # Validação leve: aceita se está nas options OU se começa com prefixo
        # conhecido (hyperflux/seedance/etc) — confiamos no model_router pra
        # rejeitar IDs inexistentes.
        return override

    if ctx is not None:
        # Compõe ctx.intent a partir de op se não veio
        if op and ctx.intent is None:
            ctx.intent = op
        if tdef.auto_route is not None:
            picked = tdef.auto_route(ctx)
            if picked:
                return picked

    return tdef.default


def list_tools() -> list[str]:
    """Lista todas as tools registradas."""
    return sorted(TOOL_REGISTRY.keys())


def options_for(tool: str) -> list[str]:
    """Lista de modelos pra dropdown da tool no front."""
    if tool not in TOOL_REGISTRY:
        return []
    return list(TOOL_REGISTRY[tool].options)


def default_for(tool: str) -> str:
    """Default model da tool (fallback se a tool não existe: nano-banana-pro)."""
    if tool not in TOOL_REGISTRY:
        return "nano-banana-pro"
    return TOOL_REGISTRY[tool].default

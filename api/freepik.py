"""
Refine — Freepik master client.

Cobre todas as APIs Freepik usadas pela plataforma:
  Image:
    - nano_banana_pro     (text-to-image 4K)
    - mystic              (premium quality)
    - flux_dev / flux_pro (text-to-image)
    - imagen3             (Google Imagen via Freepik)
    - face_swap           (swap face em imagem)
  Video:
    - kling_v3 / kling_v2_1     (image-to-video)
    - hailuo                    (image-to-video alt)
    - wan_2_1                   (text-to-video)
    - runway                    (text/img-to-video)
  Enhancers:
    - magnific_upscaler         (4K-25MP upscaler)
    - skin_enhancer             (faithful/flexible)
    - background_remover
    - relighting

Rotação de API keys + retry com backoff + handling de daily caps.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Optional, Literal

import httpx

FREEPIK_BASE = "https://api.freepik.com"


# Buffer compartilhado entre processos (api/worker) via Redis.
# Em-memória como fallback se Redis indisponível.
from collections import deque
import json as _dbg_json
_DEBUG_BUFFER: deque = deque(maxlen=50)
_REDIS_DEBUG_KEY = "freepik:debug"


def _redis_client():
    try:
        import redis  # type: ignore
        url = os.environ.get("REDIS_URL", "")
        if not url:
            return None
        return redis.Redis.from_url(url, socket_timeout=2.0, socket_connect_timeout=2.0)
    except Exception:
        return None


def _record_debug(entry: dict) -> None:
    """Grava entry em Redis (compartilhado) + memória local (fallback)."""
    _DEBUG_BUFFER.append(entry)
    cli = _redis_client()
    if cli:
        try:
            cli.lpush(_REDIS_DEBUG_KEY, _dbg_json.dumps(entry, default=str))
            cli.ltrim(_REDIS_DEBUG_KEY, 0, 49)
        except Exception:
            pass


def get_debug_buffer() -> list[dict]:
    """Retorna buffer (preferindo Redis, fallback memória)."""
    cli = _redis_client()
    if cli:
        try:
            items = cli.lrange(_REDIS_DEBUG_KEY, 0, -1)
            return [_dbg_json.loads(i) for i in items]
        except Exception:
            pass
    return list(_DEBUG_BUFFER)


class FreepikError(Exception):
    """Erro retornado pela API Freepik."""
    def __init__(self, message: str, status: int = 0, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class FreepikQuotaExceeded(FreepikError):
    """Daily cap ou quota da key esgotada — rota pra próxima."""


class FreepikDeprecated(FreepikError):
    """Endpoint descontinuado pós rebrand Magnific — substituicao em desenvolvimento."""


# Endpoints removidos pelo Freepik no rebrand pra Magnific (2026-04-28).
# Curto-circuito: lança FreepikDeprecated antes mesmo do request, preservando
# créditos do user e dando mensagem amigável.
DEPRECATED_PATHS: dict[str, str] = {
    # Skin enhancer
    "/v1/ai/image-enhance/faithful": "Skin Enhancer indisponível (rebrand Magnific). Substituição em desenvolvimento.",
    # Edit / inpaint / outpaint
    "/v1/ai/image-inpaint": "Inpaint indisponível. Use Seedream Edit (em breve no front).",
    "/v1/ai/image-outpaint": "Outpaint indisponível (rebrand Magnific).",
    "/v1/ai/image-object-removal": "Remove Object indisponível (rebrand Magnific).",
    "/v1/ai/sketch-to-image": "Sketch to Image indisponível (rebrand Magnific).",
    "/v1/ai/style-transfer": "Style Transfer indisponível — endpoint mudou (em breve).",
    "/v1/ai/replace-background": "Replace Background indisponível (rebrand Magnific).",
    "/v1/ai/colorize": "Colorize indisponível (rebrand Magnific).",
    # Swap
    "/v1/ai/face-swap": "Face Swap indisponível (rebrand Magnific).",
    # Audio (Freepik removeu inteiramente)
    "/v1/ai/text-to-speech": "TTS removido pelo Freepik. Trocar provider (ElevenLabs).",
    "/v1/ai/voice-clone": "Voice Clone removido pelo Freepik.",
    "/v1/ai/sound-generation": "SFX removido pelo Freepik.",
    "/v1/ai/lip-sync": "Lipsync removido pelo Freepik.",
}


class FreepikClient:
    """
    Cliente master pra Freepik APIs com rotação de keys.

    Uso:
        client = FreepikClient(api_keys=[k1, k2, k3])
        task_id = await client.nano_banana_pro(prompt="...", size="2k")
        result = await client.poll_task(task_id, kind="image")
    """

    def __init__(self, api_keys: list[str], timeout: float = 120.0):
        if not api_keys:
            raise ValueError("At least one Freepik API key required")
        self.api_keys = api_keys
        self._key_idx = 0
        self.timeout = timeout
        # NOTA: NAO criar AsyncClient compartilhado aqui. httpx.AsyncClient fica
        # preso ao event loop ativo no momento da criacao. Em Celery + asyncio,
        # cada task cria/fecha um novo loop, e o cliente do loop antigo da
        # "Event loop is closed". Cada _request() cria seu cliente local.
        self._client = None  # mantido por compat com close()

    # ─────────────── Key rotation ───────────────

    @property
    def current_key(self) -> str:
        return self.api_keys[self._key_idx]

    def _rotate_key(self):
        self._key_idx = (self._key_idx + 1) % len(self.api_keys)

    # ─────────────── HTTP wrapper ───────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        retry_on_quota: bool = True,
    ) -> dict:
        """HTTP request com retry/rotação em quota errors."""
        # Curto-circuito: paths descontinuados pos rebrand Magnific
        for prefix, msg in DEPRECATED_PATHS.items():
            if path.startswith(prefix):
                raise FreepikDeprecated(msg, status=410)

        attempts = len(self.api_keys) if retry_on_quota else 1
        last_err: Optional[Exception] = None

        for attempt in range(attempts):
            headers = {
                "x-freepik-api-key": self.current_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            try:
                # Cliente local por request — evita "Event loop is closed"
                # quando Celery alterna loops entre tasks.
                async with httpx.AsyncClient(timeout=self.timeout, base_url=FREEPIK_BASE) as client:
                    resp = await client.request(
                        method, path, headers=headers, json=json, params=params
                    )
            except httpx.HTTPError as e:
                last_err = e
                await asyncio.sleep(1 + attempt)
                continue

            if resp.status_code == 429 or resp.status_code == 402:
                # Daily cap / quota
                self._rotate_key()
                last_err = FreepikQuotaExceeded(
                    f"Quota exceeded on key idx {self._key_idx}", status=resp.status_code,
                    body=resp.text,
                )
                await asyncio.sleep(0.5)
                continue

            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    # Extrai mensagem de erro estruturada pra exibir
                    err_msg = (
                        body.get("message")
                        or (body.get("detail") if isinstance(body.get("detail"), str) else None)
                        or str(body)[:200]
                    )
                except Exception:
                    body = resp.text
                    err_msg = body[:200] if body else "<empty>"
                raise FreepikError(
                    f"Freepik {method} {path} → {resp.status_code}: {err_msg}",
                    status=resp.status_code, body=body,
                )

            return resp.json()

        raise (last_err or FreepikError("All retries exhausted"))

    # ════════════════════════════════════════════════════════════════
    #                          IMAGE — TEXT-TO-IMAGE
    # ════════════════════════════════════════════════════════════════

    async def nano_banana_pro(
        self,
        prompt: str,
        *,
        reference_images: list[str] | None = None,
        aspect_ratio: str = "1:1",
        size: Literal["1k", "2k", "4k"] = "2k",
        resolution: Literal["1K", "2K", "4K"] | None = None,
        webhook_url: str | None = None,
    ) -> str:
        """nano-banana-pro (Gemini 2.5 Flash Image) — editorial.

        API real espera:
          aspect_ratio: "16:9", "1:1", "9:16", etc (formato simples, NAO "square_X_Y")
          resolution: "1K", "2K", "4K" (UPPERCASE)
          reference_images: lista de {"image": <base64>, "mime_type": "image/jpeg", "text": "..."}
                            OU lista de URLs (algumas versoes da API aceitam)
        """
        # Normaliza aspect_ratio: aceita "square_4_5" (legado) → "4:5"
        ar = aspect_ratio
        if ar.startswith("square_"):
            ar = ar.replace("square_", "").replace("_", ":")
        # Normaliza resolution UPPERCASE
        res = (resolution or size or "2k").upper().replace("K", "K")  # idempotente
        body: dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": ar,
            "resolution": res,
        }
        if reference_images:
            # API espera lista de OBJETOS {image: <base64>, mime_type, text}.
            # gen_scene.py local funciona porque manda esse formato.
            # Strings (URLs/data URIs) são IGNORADAS silenciosamente pela API.
            import re as _re
            REF_TEXT = (
                "Visual reference — preserve the exact subject, colors, shapes, "
                "proportions, and identity shown in this image. Do NOT generate "
                "a new subject; use THIS specific subject from the reference."
            )
            normalized = []
            for ref in reference_images:
                if isinstance(ref, dict):
                    # Já tá no formato certo
                    normalized.append(ref)
                    continue
                if not isinstance(ref, str) or not ref:
                    continue
                # Converte string (URL ou data URI) → objeto
                if ref.startswith("data:"):
                    data_uri = ref
                elif ref.startswith("http"):
                    try:
                        data_uri = await self._fetch_to_data_uri(ref)
                    except Exception as e:
                        print(f"[nano_banana_pro] falha download ref {ref[:60]}: {e}", flush=True)
                        continue
                else:
                    # base64 puro (sem prefix data:) — assume JPEG
                    data_uri = f"data:image/jpeg;base64,{ref}"
                # Extrai mime + b64
                m = _re.match(r"data:([^;]+);base64,(.+)", data_uri)
                if m:
                    normalized.append({
                        "image": m.group(2),
                        "mime_type": m.group(1),
                        "text": REF_TEXT,
                    })
            if normalized:
                body["reference_images"] = normalized
        if webhook_url:
            body["webhook_url"] = webhook_url
        return await self._post_task("/v1/ai/text-to-image/nano-banana-pro", body)

    async def nano_banana_2(
        self,
        prompt: str,
        *,
        reference_images: list[str] | None = None,
    ) -> str:
        """nano-banana-2 (Gemini 2.5 Flash Image Preview).

        Body MÍNIMO — só prompt + reference_images (URLs strings).
        Sem aspect_ratio, resolution, etc — endpoint ignora extras.
        Aspect ratio é controlado pelo PROMPT ("Aspect ratio 9:16") e pelas
        próprias proporções das imagens de referência.

        Reference_images: lista de URLs HTTP públicas (sem token).
        A ORDEM importa — prompt usa @img1, @img2 referenciando posição.
        """
        body: dict[str, Any] = {"prompt": prompt}
        if reference_images:
            # Aceita só strings URLs. Filtra outros formatos.
            urls = [r for r in reference_images if isinstance(r, str) and r.startswith("http")]
            if urls:
                body["reference_images"] = urls
        return await self._post_task("/v1/ai/gemini-2-5-flash-image-preview", body)

    async def mystic(
        self,
        prompt: str,
        *,
        resolution: Literal["1k", "2k", "4k"] = "2k",
        aspect_ratio: str = "square_1_1",
        engine: Literal["magnific_illusio", "magnific_sharpy", "magnific_sparkle"] = "magnific_sparkle",
        creative_detailing: int = 33,
        style_reference: str | None = None,
    ) -> str:
        """Mystic — premium quality image gen."""
        body = {
            "prompt": prompt,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "engine": engine,
            "creative_detailing": creative_detailing,
        }
        if style_reference:
            body["style_reference"] = style_reference
        return await self._post_task("/v1/ai/mystic", body)

    async def flux_dev(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        """Flux Dev — fast text-to-image."""
        return await self._post_task("/v1/ai/text-to-image/flux-dev",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio})

    async def flux_pro(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        """Flux Pro 1.1 — high quality text-to-image."""
        return await self._post_task("/v1/ai/text-to-image/flux-pro-v1-1",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio})

    async def imagen3(self, prompt: str, *, aspect_ratio: str = "square_1_1", num_images: int = 1) -> str:
        """Google Imagen 3 (legado — API atual usa imagen4)."""
        return await self._post_task("/v1/ai/text-to-image/imagen-3",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio,
                                      "num_images": num_images})

    # ════════════════════════════════════════════════════════════════
    #                          IMAGE — TRANSFORMS
    # ════════════════════════════════════════════════════════════════

    async def face_swap(self, source_image_url: str, target_image_url: str) -> str:
        """Face swap — coloca rosto de source no target."""
        body = {"source_image": source_image_url, "target_image": target_image_url}
        r = await self._request("POST", "/v1/ai/face-swap", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def background_remover(self, image_url: str) -> str:
        body = {"image": image_url}
        r = await self._request("POST", "/v1/ai/beta/background-remover", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def magnific_upscaler(
        self,
        image_url: str,
        *,
        scale: Literal[2, 4] = 2,
        engine: Literal["magnific_sparkle", "magnific_illusio", "magnific_sharpy"] = "magnific_sparkle",
        creativity: int = 0,
        hdr: int = 0,
        resemblance: int = 50,
        fractality: int = 0,
        engine_style: Literal["soft_portraits", "no_style", "cinematic"] = "soft_portraits",
    ) -> str:
        """Magnific upscaler — replica preset Magnific.ai ULT V6."""
        body = {
            "image": image_url,
            "scale_factor": scale,
            "engine": engine,
            "creativity": creativity,
            "hdr": hdr,
            "resemblance": resemblance,
            "fractality": fractality,
            "engine_style": engine_style,
        }
        r = await self._request("POST", "/v1/ai/image-upscaler", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def skin_enhancer(
        self,
        image_url: str,
        *,
        mode: Literal["faithful", "flexible"] = "faithful",
        skin_detail: int = 20,
        smart_grain: int = 0,
    ) -> str:
        """Skin Enhancer — combate AI plastic look. Faithful (conservador) ou flexible (transform_to_real)."""
        endpoint = (
            "/v1/ai/image-enhance/faithful/transform_to_real"
            if mode == "flexible"
            else "/v1/ai/image-enhance/faithful"
        )
        body = {"image": image_url, "skin_detail": skin_detail, "smart_grain": smart_grain}
        r = await self._request("POST", endpoint, json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def relight(self, image_url: str, prompt: str) -> str:
        """Relight via Freepik — muda iluminação preservando subject."""
        body = {"image": image_url, "prompt": prompt}
        r = await self._request("POST", "/v1/ai/image-relight", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    # ─────────────── IMAGE EDIT (inpaint, outpaint, etc) ───────────────

    async def inpaint(self, image_url: str, mask_url: str, prompt: str) -> str:
        """Inpaint — pinta região marcada pela mask com novo conteúdo."""
        body = {"image": image_url, "mask": mask_url, "prompt": prompt}
        r = await self._request("POST", "/v1/ai/image-inpaint", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def outpaint(self, image_url: str, *, prompt: str = "",
                       direction: Literal["all", "horizontal", "vertical", "left", "right", "top", "bottom"] = "all",
                       expansion_factor: float = 1.5) -> str:
        """Outpaint — expande canvas além do frame original."""
        body = {
            "image": image_url, "prompt": prompt,
            "direction": direction, "expansion_factor": expansion_factor,
        }
        r = await self._request("POST", "/v1/ai/image-outpaint", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def remove_object(self, image_url: str, mask_url: str) -> str:
        """Remove objeto sem deixar trace (content-aware fill)."""
        body = {"image": image_url, "mask": mask_url}
        r = await self._request("POST", "/v1/ai/image-object-removal", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def sketch_to_image(self, sketch_url: str, prompt: str, *,
                              strength: float = 0.7) -> str:
        """Sketch/rascunho → imagem realista guiada pelo prompt."""
        body = {"sketch": sketch_url, "prompt": prompt, "strength": strength}
        r = await self._request("POST", "/v1/ai/sketch-to-image", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def style_transfer(self, source_url: str, style_reference_url: str,
                             prompt: str = "", *, strength: float = 0.7) -> str:
        """Aplica estilo de uma imagem em outra (preserva conteúdo)."""
        body = {
            "source_image": source_url, "style_image": style_reference_url,
            "prompt": prompt, "strength": strength,
        }
        r = await self._request("POST", "/v1/ai/style-transfer", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def replace_background(self, image_url: str, prompt: str) -> str:
        """Substitui background mantendo subject (com alpha matting)."""
        body = {"image": image_url, "prompt": prompt}
        r = await self._request("POST", "/v1/ai/replace-background", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def expand_image(self, image_url: str, *, target_aspect_ratio: str = "16:9") -> str:
        """Expande imagem pra novo aspect ratio (uncrop)."""
        body = {"image": image_url, "target_aspect_ratio": target_aspect_ratio}
        r = await self._request("POST", "/v1/ai/image-expand", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def colorize(self, image_url: str, prompt: str = "") -> str:
        """P&B → colorido."""
        body = {"image": image_url, "prompt": prompt}
        r = await self._request("POST", "/v1/ai/colorize", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    # ─────────────── VIDEO EDIT ───────────────

    async def lip_sync(self, video_url: str, audio_url: str) -> str:
        """Lip sync — sincroniza boca do vídeo com áudio."""
        body = {"video": video_url, "audio": audio_url}
        r = await self._request("POST", "/v1/ai/lip-sync", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def video_upscale(self, video_url: str, *, scale: Literal[2, 4] = 2) -> str:
        """Upscale de vídeo."""
        body = {"video": video_url, "scale_factor": scale}
        r = await self._request("POST", "/v1/ai/video-upscaler", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    # ─────────────── AUDIO (ElevenLabs via Freepik) ───────────────

    async def text_to_speech(
        self,
        text: str,
        *,
        voice_id: str,
        model: str = "eleven_multilingual_v2",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0.0,
    ) -> str:
        """TTS via Freepik (ElevenLabs powered). Suporta PT-BR."""
        body = {
            "text": text,
            "voice_id": voice_id,
            "model_id": model,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style,
            },
        }
        r = await self._request("POST", "/v1/ai/text-to-speech", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def voice_clone(self, name: str, audio_sample_urls: list[str], *, description: str = "") -> str:
        """Voice clone via Freepik. Recebe URLs de samples (não bytes)."""
        body = {"name": name, "description": description, "samples": audio_sample_urls}
        r = await self._request("POST", "/v1/ai/voice-clone", json=body)
        return r.get("data", {}).get("voice_id") or r.get("voice_id")

    async def list_voices(self) -> list[dict]:
        """Lista vozes disponíveis (presets + clonadas pela conta)."""
        r = await self._request("GET", "/v1/ai/voices")
        return r.get("data", []) or r.get("voices", [])

    async def music_generation(self, prompt: str, *, duration: int = 30) -> str:
        """Music generation via Freepik."""
        body = {"prompt": prompt, "duration_seconds": duration}
        r = await self._request("POST", "/v1/ai/music-generation", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def sound_effect(self, prompt: str, *, duration: float | None = None) -> str:
        """Sound effect via Freepik."""
        body: dict = {"text": prompt}
        if duration:
            body["duration_seconds"] = duration
        r = await self._request("POST", "/v1/ai/sound-generation", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    # ════════════════════════════════════════════════════════════════
    #                          VIDEO
    # ════════════════════════════════════════════════════════════════

    async def kling_v3(
        self,
        image_url: str,
        prompt: str,
        *,
        duration: Literal["5", "10"] = "5",
        cfg_scale: float = 0.5,
        negative_prompt: str = "",
    ) -> str:
        """Kling V3 Pro — image-to-video. API real espera `image_url` (não `image`)."""
        body = {
            "image": image_url,
            "prompt": prompt,
            "duration": duration,
            "cfg_scale": cfg_scale,
            "negative_prompt": negative_prompt,
        }
        return await self._post_task("/v1/ai/video/kling-v3-pro", body)

    async def kling_v2_1(self, image_url: str, prompt: str, *, duration: str = "5",
                          tier: Literal["master", "pro", "std"] = "pro") -> str:
        """Kling V2.1 — fallback quando V3 daily cap esgota."""
        return await self._post_task(f"/v1/ai/image-to-video/kling-v2-1-{tier}", {"image": image_url, "prompt": prompt, "duration": duration})

    async def kling_v2_6(self, image_url: str, prompt: str, *, duration: str = "5") -> str:
        # API atual só tem kling-v2-5-pro (v2-6 foi removido)
        return await self._post_task("/v1/ai/image-to-video/kling-v2-5-pro", {"image": image_url, "prompt": prompt, "duration": duration})

    async def hailuo(self, image_url: str, prompt: str) -> str:
        """Hailuo — image-to-video alternativo."""
        # API atual só tem 1080p (768p foi removido)
        return await self._post_task("/v1/ai/image-to-video/minimax-hailuo-02-1080p", {"image": image_url, "prompt": prompt})

    async def wan_2_1(self, prompt: str, *, duration: int = 5, aspect_ratio: str = "16:9") -> str:
        """WAN 2.1 — text-to-video (legado, redireciona pra wan-2-5-t2v-720p)."""
        return await self._post_task("/v1/ai/text-to-video/wan-2-5-t2v-720p",
                                     {"prompt": prompt, "duration": duration, "aspect_ratio": aspect_ratio})

    async def runway(self, image_url: str, prompt: str, *, duration: int = 5) -> str:
        """Runway 4.5 (legado, mesmo endpoint)."""
        return await self._post_task("/v1/ai/image-to-video/runway-4-5", {"image": image_url, "prompt": prompt, "duration": duration})

    # ════════════════════════════════════════════════════════════════
    #                          POLLING
    # ════════════════════════════════════════════════════════════════

    # Mapa task_id → endpoint do POST (cada modelo Freepik tem seu próprio polling)
    # Populado automaticamente quando uma task é criada.
    _task_endpoints: dict[str, str] = {}

    async def get_task(self, task_id: str, kind: Literal["image", "video", "enhance"] = "image",
                       *, endpoint: str | None = None) -> dict:
        """Status de uma task. Cada modelo Freepik tem endpoint próprio (POST path + /{id})."""
        # 1. Endpoint explícito (preferido)
        if endpoint:
            return await self._request("GET", f"{endpoint}/{task_id}")

        # 2. Endpoint registrado quando a task foi criada
        if task_id in self._task_endpoints:
            return await self._request("GET", f"{self._task_endpoints[task_id]}/{task_id}")

        # 3. Fallback: nano-banana-pro (modelo default mais usado)
        try:
            return await self._request("GET", f"/v1/ai/text-to-image/nano-banana-pro/{task_id}")
        except FreepikError:
            return await self._request("GET", f"/v1/ai/tasks/{task_id}")

    async def poll_task(
        self,
        task_id: str,
        kind: Literal["image", "video", "enhance"] = "image",
        *,
        max_wait_s: int = 600,
        interval_s: float = 3.0,
        endpoint: str | None = None,
    ) -> dict:
        """Polla task até COMPLETED/FAILED ou timeout."""
        elapsed = 0.0
        while elapsed < max_wait_s:
            r = await self.get_task(task_id, kind=kind, endpoint=endpoint)
            data = r.get("data", r)
            status = (data.get("status") or "").upper()
            if status in ("COMPLETED", "SUCCESS"):
                return data
            if status in ("FAILED", "ERROR"):
                raise FreepikError(f"Task {task_id} failed: {data}", body=data)
            await asyncio.sleep(interval_s)
            elapsed += interval_s
        raise FreepikError(f"Task {task_id} timeout after {max_wait_s}s")

    # ════════════════════════════════════════════════════════════════
    #              EXTENDED MODELS — Image (catálogo completo)
    # ════════════════════════════════════════════════════════════════

    async def _fetch_to_data_uri(self, url: str) -> str:
        """Baixa URL e retorna data URI. Pra endpoints (ex: Kling) que não conseguem
        baixar URLs com tokens longos / signed Supabase."""
        if url.startswith("data:"):
            return url  # já é data URI, retorna como está
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(url, follow_redirects=True)
            r.raise_for_status()
            mime = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            import base64 as _b64
            b64 = _b64.b64encode(r.content).decode("ascii")
            return f"data:{mime};base64,{b64}"

    async def _post_task(self, path: str, body: dict) -> str:
        """Helper interno: POST + extrai task_id + registra endpoint pra polling."""
        import time as _t
        # Coleta info do body pra debug — sem dados pesados
        img_val = body.get("image_url") or body.get("image") or ""
        if isinstance(img_val, str):
            img_kind = "data_uri" if img_val.startswith("data:") else \
                       "http_url" if img_val.startswith("http") else \
                       "empty" if not img_val else "raw_b64"
            img_len = len(img_val)
        else:
            img_kind = type(img_val).__name__
            img_len = 0
        debug_entry = {
            "ts": _t.time(),
            "path": path,
            "body_keys": list(body.keys()),
            "image_kind": img_kind,
            "image_len": img_len,
            "prompt_preview": str(body.get("prompt", ""))[:80],
            "duration": body.get("duration"),
        }
        try:
            r = await self._request("POST", path, json=body)
            tid = r.get("data", {}).get("task_id") or r.get("task_id")
            debug_entry["task_id"] = tid
            debug_entry["ok"] = True
        except Exception as e:
            debug_entry["task_id"] = None
            debug_entry["ok"] = False
            debug_entry["error"] = str(e)[:200]
            _record_debug(debug_entry)
            raise
        _record_debug(debug_entry)
        if tid:
            self._task_endpoints[tid] = path
        return tid

    # ─── Flux family ───
    async def flux_2_turbo(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        return await self._post_task("/v1/ai/text-to-image/flux-2-turbo",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio})

    async def flux_2_pro(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        return await self._post_task("/v1/ai/text-to-image/flux-2-pro",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio})

    async def flux_2_klein(self, prompt: str, *, resolution: Literal["1k", "2k"] = "1k",
                           aspect_ratio: str = "square_1_1") -> str:
        return await self._post_task("/v1/ai/text-to-image/flux-2-klein",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio, "size": resolution})

    async def flux_kontext_pro(self, prompt: str, *, reference_images: list[str] | None = None,
                               aspect_ratio: str = "square_1_1") -> str:
        body = {"prompt": prompt, "aspect_ratio": aspect_ratio}
        if reference_images:
            body["reference_images"] = reference_images
        return await self._post_task("/v1/ai/text-to-image/flux-kontext-pro", body)

    async def hyperflux(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        return await self._post_task("/v1/ai/text-to-image/hyperflux",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio})

    async def reimagine_flux(self, image_url: str, *, prompt: str = "") -> str:
        body = {"image": image_url}
        if prompt:
            body["prompt"] = prompt
        return await self._post_task("/v1/ai/reimagine-flux", body)

    # ─── Imagen family ───
    async def imagen_4_fast(self, prompt: str, *, aspect_ratio: str = "square_1_1",
                            num_images: int = 1) -> str:
        return await self._post_task("/v1/ai/text-to-image/imagen4-fast",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio,
                                      "num_images": num_images})

    async def imagen_4_ultra(self, prompt: str, *, aspect_ratio: str = "square_1_1",
                             num_images: int = 1) -> str:
        return await self._post_task("/v1/ai/text-to-image/imagen4-ultra",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio,
                                      "num_images": num_images})

    # ─── Seedream family ───
    async def seedream_v4(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        return await self._post_task("/v1/ai/text-to-image/seedream-v4",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio})

    async def seedream_v4_5(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        return await self._post_task("/v1/ai/text-to-image/seedream-v4-5",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio})

    async def seedream_v5_lite(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        return await self._post_task("/v1/ai/text-to-image/seedream-v5-lite",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio})

    async def seedream_edit_v4(self, image_url: str, prompt: str) -> str:
        return await self._post_task("/v1/ai/seedream-edit-v4",
                                     {"image": image_url, "prompt": prompt})

    async def seedream_edit_v4_5(self, image_url: str, prompt: str) -> str:
        return await self._post_task("/v1/ai/seedream-edit-v4-5",
                                     {"image": image_url, "prompt": prompt})

    async def seedream_edit_v5_lite(self, image_url: str, prompt: str) -> str:
        return await self._post_task("/v1/ai/seedream-edit-v5-lite",
                                     {"image": image_url, "prompt": prompt})

    # ─── Z-Image ───
    async def z_image_turbo(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        return await self._post_task("/v1/ai/text-to-image/z-image-turbo",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio})

    # ─── Nano Banana Pro Flash (variante mais barata da Pro) ───
    async def nano_banana_pro_flash(
        self, prompt: str, *,
        reference_images: list[str] | None = None,
        aspect_ratio: str = "square_1_1",
        size: Literal["1k", "2k", "4k"] = "2k",
        google_search: bool = False,
    ) -> str:
        body: dict = {"prompt": prompt, "aspect_ratio": aspect_ratio, "size": size}
        if reference_images:
            body["reference_images"] = reference_images
        if google_search:
            body["enable_google_search"] = True
        return await self._post_task("/v1/ai/text-to-image/nano-banana-pro-flash", body)

    # ─── Runway T2I ───
    async def runway_t2i(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        return await self._post_task("/v1/ai/text-to-image/runway",
                                     {"prompt": prompt, "aspect_ratio": aspect_ratio})

    # ════════════════════════════════════════════════════════════════
    #              EXTENDED MODELS — Edit / Inpaint / Expand
    # ════════════════════════════════════════════════════════════════

    async def image_expand_ideogram(self, image_url: str, *, target_aspect_ratio: str = "16:9") -> str:
        return await self._post_task("/v1/ai/image-expand/ideogram",
                                     {"image": image_url, "target_aspect_ratio": target_aspect_ratio})

    async def image_expand_seedream(self, image_url: str, *, target_aspect_ratio: str = "16:9") -> str:
        return await self._post_task("/v1/ai/image-expand/seedream-v4-5",
                                     {"image": image_url, "target_aspect_ratio": target_aspect_ratio})

    async def image_expand_flux(self, image_url: str, *, target_aspect_ratio: str = "16:9",
                                 prompt: str = "") -> str:
        body = {"image": image_url, "target_aspect_ratio": target_aspect_ratio}
        if prompt:
            body["prompt"] = prompt
        return await self._post_task("/v1/ai/image-expand/flux", body)

    async def inpaint_ideogram(
        self, image_url: str, mask_url: str, prompt: str,
        *, level: Literal["turbo", "default", "quality"] = "default",
    ) -> str:
        return await self._post_task(f"/v1/ai/image-inpaint/ideogram-{level}",
                                     {"image": image_url, "mask": mask_url, "prompt": prompt})

    async def change_camera(self, image_url: str, *, angle: str = "side") -> str:
        return await self._post_task("/v1/ai/change-camera",
                                     {"image": image_url, "angle": angle})

    # ════════════════════════════════════════════════════════════════
    #              EXTENDED MODELS — Magnific Precision
    # ════════════════════════════════════════════════════════════════

    async def magnific_precision_v1(
        self, image_url: str, *, scale_factor: int = 2,
        engine: Literal["magnific_sparkle", "magnific_illusio", "magnific_sharpy"] = "magnific_sparkle",
    ) -> str:
        body = {"image": image_url, "scale_factor": scale_factor, "engine": engine}
        return await self._post_task("/v1/ai/image-upscaler-precision", body)

    async def magnific_precision_v2(
        self, image_url: str, *, scale_factor: int = 2,
        flavor: Literal["sublime", "photo", "photo_denoiser"] = "photo",
        sharpen: int = 7, smart_grain: int = 7, ultra_detail: int = 30,
    ) -> str:
        body = {
            "image": image_url, "scale_factor": scale_factor, "flavor": flavor,
            "sharpen": sharpen, "smart_grain": smart_grain, "ultra_detail": ultra_detail,
        }
        return await self._post_task("/v1/ai/image-upscaler-precision-v2", body)

    # ─── Skin Enhancer Flexible (5 presets) ───
    async def skin_enhancer_flexible(
        self, image_url: str, *,
        preset: Literal["enhance_skin", "improve_lighting", "enhance_everything",
                        "transform_to_real", "no_make_up"] = "transform_to_real",
        sharpen: int = 0, smart_grain: int = 2,
    ) -> str:
        body = {"image": image_url, "sharpen": sharpen, "smart_grain": smart_grain}
        return await self._post_task(f"/v1/ai/skin-enhancer/flexible/{preset}", body)

    async def skin_enhancer_creative(
        self, image_url: str, *, sharpen: int = 0, smart_grain: int = 2,
    ) -> str:
        body = {"image": image_url, "sharpen": sharpen, "smart_grain": smart_grain}
        return await self._post_task("/v1/ai/skin-enhancer/creative", body)

    # ════════════════════════════════════════════════════════════════
    #              EXTENDED MODELS — Video (catálogo completo)
    # ════════════════════════════════════════════════════════════════

    # ─── Hailuo (MiniMax) ───
    async def hailuo_02(self, image_url: str, prompt: str, *,
                        duration: Literal["6", "10"] = "6") -> str:
        # API atual: só 1080p
        body = {"image": image_url, "prompt": prompt, "duration": duration}
        return await self._post_task("/v1/ai/image-to-video/minimax-hailuo-02-1080p", body)

    async def hailuo_2_3(self, image_url: str, prompt: str, *,
                         duration: str = "6") -> str:
        # API atual: só minimax-hailuo-2-3-1080p (sem fast/standard variants)
        return await self._post_task("/v1/ai/image-to-video/minimax-hailuo-2-3-1080p", {"image": image_url, "prompt": prompt, "duration": duration})

    # ─── Pixverse ───
    async def pixverse_v5(self, image_url: str, prompt: str, *,
                          duration: int = 5) -> str:
        # API atual: pixverse-v5 sem resolução no path
        return await self._post_task("/v1/ai/image-to-video/pixverse-v5", {"image": image_url, "prompt": prompt, "duration": duration})

    async def pixverse_v5_transition(self, first_image_url: str, last_image_url: str, prompt: str, *,
                                     duration: int = 5) -> str:
        """Pixverse v5 transition — interpola entre 2 imagens."""
        return await self._post_task("/v1/ai/image-to-video/pixverse-v5-transition",
                                     {"first_image": first_image_url, "last_image": last_image_url,
                                      "prompt": prompt, "duration": duration})

    # ─── LTX 2.0 ───
    # LTX 2: API atual só tem text-to-video pro (sem fast e sem variantes de resolução)
    async def ltx_2_pro(self, _image_url_unused: str | None = None, prompt: str = "", *,
                        duration: int = 5) -> str:
        return await self._post_task("/v1/ai/text-to-video/ltx-2-pro",
                                     {"prompt": prompt, "duration": duration})

    async def ltx_2_fast(self, _image_url_unused: str | None = None, prompt: str = "", *,
                         duration: int = 5) -> str:
        # Endpoint de fast não existe — fallback pro pro
        return await self.ltx_2_pro(_image_url_unused, prompt=prompt, duration=duration)

    # ─── Seedance ───
    async def seedance_pro(self, image_url: str, prompt: str, *,
                           resolution: Literal["480p", "720p", "1080p"] = "720p",
                           duration: int = 5) -> str:
        path = f"/v1/ai/image-to-video/seedance-pro-{resolution}"
        return await self._post_task(path, {"image": image_url, "prompt": prompt, "duration": duration})

    async def seedance_lite(self, image_url: str, prompt: str, *,
                            duration: int = 5) -> str:
        # Lite removido — fallback pro pro 1080p
        return await self._post_task("/v1/ai/image-to-video/seedance-pro-1080p", {"image": image_url, "prompt": prompt, "duration": duration})

    async def seedance_1_5_pro(self, image_url: str, prompt: str, *,
                                duration: int = 5) -> str:
        # 1.5 não existe mais — fallback pro pro 1080p
        return await self._post_task("/v1/ai/image-to-video/seedance-pro-1080p", {"image": image_url, "prompt": prompt, "duration": duration})

    # ─── WAN ───
    async def wan_2_6(self, image_url: str, prompt: str, *,
                      duration: int = 5) -> str:
        # API atual: wan-v2-6-1080p (com `v2-6` e só 1080p)
        return await self._post_task("/v1/ai/image-to-video/wan-v2-6-1080p", {"image": image_url, "prompt": prompt, "duration": duration})

    async def wan_2_5_t2v(self, prompt: str, *,
                          resolution: Literal["480p", "720p", "1080p"] = "720p",
                          duration: int = 5) -> str:
        """Wan 2.5 text-to-video (puro, sem imagem inicial)."""
        return await self._post_task(f"/v1/ai/text-to-video/wan-2-5-t2v-{resolution}",
                                     {"prompt": prompt, "duration": duration})

    async def wan_2_5_i2v(self, image_url: str, prompt: str, *, duration: int = 5) -> str:
        """Wan 2.5 image-to-video."""
        return await self._post_task("/v1/ai/image-to-video/wan-2-5-i2v-1080p", {"image": image_url, "prompt": prompt, "duration": duration})

    async def wan_2_7(self, image_url: str | None, prompt: str, *, duration: int = 5,
                      mode: Literal["t2v", "i2v", "r2v"] = "i2v") -> str:
        # API atual: paths sem sufixo -i2v/-t2v
        path = f"/v1/ai/{'text' if mode == 't2v' else 'reference' if mode == 'r2v' else 'image'}-to-video/wan-2-7"
        body = {"prompt": prompt, "duration": duration}
        if mode != "t2v" and image_url:
            body["image"] = image_url
        return await self._post_task(path, body)

    # ─── Veo 3.1 ───
    async def veo_3_1(self, image_url: str | None, prompt: str, *,
                      duration: int = 5,
                      mode: Literal["t2v", "i2v", "r2v"] = "i2v") -> str:
        # API atual: paths simples sem sufixo de resolução/audio
        path = f"/v1/ai/{'text' if mode == 't2v' else 'reference' if mode == 'r2v' else 'image'}-to-video/veo-3-1"
        body = {"prompt": prompt, "duration": duration}
        if mode != "t2v" and image_url:
            body["image"] = image_url
        return await self._post_task(path, body)

    async def veo_3_1_fast(self, image_url: str | None, prompt: str, *,
                           duration: int = 5,
                           mode: Literal["t2v", "i2v"] = "i2v") -> str:
        path = f"/v1/ai/{'text' if mode == 't2v' else 'image'}-to-video/veo-3-1-fast"
        body = {"prompt": prompt, "duration": duration}
        if mode != "t2v" and image_url:
            body["image"] = image_url
        return await self._post_task(path, body)

    # ─── Runway (API atual: só runway-4-5, em i2v e t2v) ───
    async def runway_gen_4_5(self, image_url: str | None, prompt: str, *, duration: int = 5,
                              mode: Literal["t2v", "i2v"] = "i2v") -> str:
        path = f"/v1/ai/{'text' if mode == 't2v' else 'image'}-to-video/runway-4-5"
        body = {"prompt": prompt, "duration": duration}
        if mode == "i2v" and image_url:
            body["image"] = image_url
        return await self._post_task(path, body)

    async def runway_gen_4_turbo(self, image_url: str, prompt: str, *, duration: int = 5) -> str:
        # turbo foi removido — fallback pro 4.5
        return await self.runway_gen_4_5(image_url, prompt, duration=duration, mode="i2v")

    async def runway_act_two(self, video_url: str, prompt: str, *, duration: int = 5) -> str:
        """Runway Act Two — performance/character animation."""
        return await self._post_task("/v1/ai/video/runway-act-two",
                                     {"video": video_url, "prompt": prompt, "duration": duration})

    # ─── Kling V3 (path /v1/ai/video/, com pro/std variants) ───
    async def kling_v3_motion_control(self, image_url: str, prompt: str, *,
                                       quality: Literal["std", "pro"] = "pro",
                                       duration: str = "5") -> str:
        return await self._post_task(f"/v1/ai/video/kling-v3-motion-control-{quality}", {"image_url": image_url, "prompt": prompt, "duration": duration})

    async def kling_v3_omni(self, image_url: str, prompt: str, *,
                             quality: Literal["std", "pro"] = "pro",
                             duration: str = "5") -> str:
        return await self._post_task(f"/v1/ai/video/kling-v3-omni-{quality}", {"image": image_url, "prompt": prompt, "duration": duration})

    async def kling_v3_pro(self, image_url: str, prompt: str, *, duration: str = "5") -> str:
        """Kling V3 Pro — top de linha."""
        return await self._post_task("/v1/ai/video/kling-v3-pro", {"image": image_url, "prompt": prompt, "duration": duration})

    async def kling_v3_std(self, image_url: str, prompt: str, *, duration: str = "5") -> str:
        return await self._post_task("/v1/ai/video/kling-v3-std", {"image": image_url, "prompt": prompt, "duration": duration})

    async def kling_pro_2_5_turbo(self, image_url: str, prompt: str, *, duration: str = "5") -> str:
        # 2.5 turbo removido — fallback pro v2-5-pro
        return await self._post_task("/v1/ai/image-to-video/kling-v2-5-pro", {"image": image_url, "prompt": prompt, "duration": duration})

    async def kling_o1(self, image_url: str, prompt: str, *,
                        quality: Literal["std", "pro"] = "pro",
                        duration: str = "5") -> str:
        return await self._post_task(f"/v1/ai/image-to-video/kling-o1-{quality}", {"image": image_url, "prompt": prompt, "duration": duration})

    # ─── Specialty video ───
    async def omnihuman_1_5(self, image_url: str, audio_url: str) -> str:
        # API atual: path em /v1/ai/video/omni-human-1-5 (com hífen e em /video/)
        return await self._post_task("/v1/ai/video/omni-human-1-5", {"image": image_url, "audio": audio_url})

    async def veed_fabric(self, video_url: str, audio_url: str, *, fast: bool = False) -> str:
        path = "/v1/ai/lip-sync/veed-fabric-fast" if fast else "/v1/ai/lip-sync/veed-fabric"
        return await self._post_task(path, {"video": video_url, "audio": audio_url})

    async def latent_sync(self, video_url: str, audio_url: str) -> str:
        return await self._post_task("/v1/ai/lip-sync/latent-sync",
                                     {"video": video_url, "audio": audio_url})

    async def video_vfx(self, video_url: str, prompt: str) -> str:
        return await self._post_task("/v1/ai/video-vfx",
                                     {"video": video_url, "prompt": prompt})

    # ════════════════════════════════════════════════════════════════
    #              EXTENDED MODELS — Audio (catálogo completo)
    # ════════════════════════════════════════════════════════════════

    async def audio_isolation(self, audio_url: str) -> str:
        return await self._post_task("/v1/ai/audio-isolation",
                                     {"audio": audio_url})

    async def elevenlabs_music(self, prompt: str, *, duration: int = 30) -> str:
        return await self._post_task("/v1/ai/music-generation/elevenlabs",
                                     {"prompt": prompt, "duration_seconds": duration})

    async def elevenlabs_sound_effect(self, prompt: str, *, duration: float | None = None) -> str:
        body: dict = {"text": prompt}
        if duration:
            body["duration_seconds"] = duration
        return await self._post_task("/v1/ai/sound-generation/elevenlabs-v2", body)

    # ════════════════════════════════════════════════════════════════
    #              EXTENDED — Video Upscaler
    # ════════════════════════════════════════════════════════════════

    async def video_upscaler_standard(
        self, video_url: str, *,
        resolution: Literal["720p", "1k", "2k", "4k"] = "2k",
        creativity: int = 0, sharpen: int = 0, smart_grain: int = 0,
        flavor: Literal["vivid", "natural"] = "vivid",
        fps_boost: bool = False,
    ) -> str:
        body = {
            "video": video_url, "resolution": resolution, "creativity": creativity,
            "sharpen": sharpen, "smart_grain": smart_grain, "flavor": flavor,
            "fps_boost": fps_boost,
        }
        return await self._post_task("/v1/ai/video-upscaler", body)

    async def video_upscaler_turbo(
        self, video_url: str, *,
        resolution: Literal["720p", "1k", "2k", "4k"] = "2k",
        flavor: Literal["vivid", "natural"] = "vivid",
    ) -> str:
        return await self._post_task("/v1/ai/video-upscaler/turbo",
                                     {"video": video_url, "resolution": resolution, "flavor": flavor})

    async def video_upscaler_precision(
        self, video_url: str, *,
        resolution: Literal["720p", "1k", "2k", "4k"] = "2k",
    ) -> str:
        return await self._post_task("/v1/ai/video-upscaler-precision",
                                     {"video": video_url, "resolution": resolution})

    async def close(self):
        # Sem-op: nao usamos mais cliente compartilhado. Cada _request gerencia
        # o ciclo de vida do AsyncClient via "async with".
        if self._client is not None:
            try: await self._client.aclose()
            except Exception: pass


# ─────────────── Singleton helper ───────────────

_global: FreepikClient | None = None

def get_freepik() -> FreepikClient:
    global _global
    if _global is None:
        keys = [k.strip() for k in os.environ.get("FREEPIK_API_KEYS", "").split(",") if k.strip()]
        _global = FreepikClient(api_keys=keys)
    return _global

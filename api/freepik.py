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


class FreepikError(Exception):
    """Erro retornado pela API Freepik."""
    def __init__(self, message: str, status: int = 0, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class FreepikQuotaExceeded(FreepikError):
    """Daily cap ou quota da key esgotada — rota pra próxima."""


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
        self._client = httpx.AsyncClient(timeout=timeout, base_url=FREEPIK_BASE)

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
        attempts = len(self.api_keys) if retry_on_quota else 1
        last_err: Optional[Exception] = None

        for attempt in range(attempts):
            headers = {
                "x-freepik-api-key": self.current_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            try:
                resp = await self._client.request(
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
                except Exception:
                    body = resp.text
                raise FreepikError(
                    f"Freepik {method} {path} → {resp.status_code}",
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
        aspect_ratio: str = "square_1_1",
        size: Literal["2k", "4k"] = "2k",
        webhook_url: str | None = None,
    ) -> str:
        """nano-banana-pro (Gemini 2.5 Flash Image) — 4K editorial."""
        body: dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "size": size,
        }
        if reference_images:
            body["reference_images"] = reference_images
        if webhook_url:
            body["webhook_url"] = webhook_url
        r = await self._request("POST", "/v1/ai/gemini-2-5-flash-image-preview", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

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
        r = await self._request("POST", "/v1/ai/mystic", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def flux_dev(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        """Flux Dev — fast text-to-image."""
        body = {"prompt": prompt, "aspect_ratio": aspect_ratio}
        r = await self._request("POST", "/v1/ai/text-to-image/flux-dev", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def flux_pro(self, prompt: str, *, aspect_ratio: str = "square_1_1") -> str:
        """Flux Pro 1.1 — high quality text-to-image."""
        body = {"prompt": prompt, "aspect_ratio": aspect_ratio}
        r = await self._request("POST", "/v1/ai/text-to-image/flux-pro-v1-1", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def imagen3(self, prompt: str, *, aspect_ratio: str = "square_1_1", num_images: int = 1) -> str:
        """Google Imagen 3 via Freepik."""
        body = {"prompt": prompt, "aspect_ratio": aspect_ratio, "num_images": num_images}
        r = await self._request("POST", "/v1/ai/text-to-image/imagen3", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

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
        """Kling V3 — image-to-video premium."""
        body = {
            "image": image_url,
            "prompt": prompt,
            "duration": duration,
            "cfg_scale": cfg_scale,
            "negative_prompt": negative_prompt,
        }
        r = await self._request("POST", "/v1/ai/image-to-video/kling-v3", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def kling_v2_1(self, image_url: str, prompt: str, *, duration: str = "5") -> str:
        """Kling V2.1 — fallback quando V3 daily cap esgota."""
        body = {"image": image_url, "prompt": prompt, "duration": duration}
        r = await self._request("POST", "/v1/ai/image-to-video/kling-v2-1", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def kling_v2_6(self, image_url: str, prompt: str, *, duration: str = "5") -> str:
        body = {"image": image_url, "prompt": prompt, "duration": duration}
        r = await self._request("POST", "/v1/ai/image-to-video/kling-v2-6", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def hailuo(self, image_url: str, prompt: str) -> str:
        """Hailuo — image-to-video alternativo."""
        body = {"image": image_url, "prompt": prompt}
        r = await self._request("POST", "/v1/ai/image-to-video/minimax-hailuo-02-768p", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def wan_2_1(self, prompt: str, *, duration: int = 5, aspect_ratio: str = "16:9") -> str:
        """WAN 2.1 — text-to-video."""
        body = {"prompt": prompt, "duration": duration, "aspect_ratio": aspect_ratio}
        r = await self._request("POST", "/v1/ai/text-to-video/wan-v2-1", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    async def runway(self, image_url: str, prompt: str, *, duration: int = 5) -> str:
        """Runway Gen-3 via Freepik."""
        body = {"image": image_url, "prompt": prompt, "duration": duration}
        r = await self._request("POST", "/v1/ai/image-to-video/runway", json=body)
        return r.get("data", {}).get("task_id") or r.get("task_id")

    # ════════════════════════════════════════════════════════════════
    #                          POLLING
    # ════════════════════════════════════════════════════════════════

    async def get_task(self, task_id: str, kind: Literal["image", "video", "enhance"] = "image") -> dict:
        """Status de uma task. kind define o endpoint correto pra Freepik."""
        endpoints = {
            "image": f"/v1/ai/tasks/{task_id}",
            "video": f"/v1/ai/tasks/{task_id}",
            "enhance": f"/v1/ai/tasks/{task_id}",
        }
        return await self._request("GET", endpoints[kind])

    async def poll_task(
        self,
        task_id: str,
        kind: Literal["image", "video", "enhance"] = "image",
        *,
        max_wait_s: int = 600,
        interval_s: float = 3.0,
    ) -> dict:
        """Polla task até COMPLETED/FAILED ou timeout."""
        elapsed = 0.0
        while elapsed < max_wait_s:
            r = await self.get_task(task_id, kind=kind)
            data = r.get("data", r)
            status = (data.get("status") or "").upper()
            if status in ("COMPLETED", "SUCCESS"):
                return data
            if status in ("FAILED", "ERROR"):
                raise FreepikError(f"Task {task_id} failed: {data}", body=data)
            await asyncio.sleep(interval_s)
            elapsed += interval_s
        raise FreepikError(f"Task {task_id} timeout after {max_wait_s}s")

    async def close(self):
        await self._client.aclose()


# ─────────────── Singleton helper ───────────────

_global: FreepikClient | None = None

def get_freepik() -> FreepikClient:
    global _global
    if _global is None:
        keys = [k.strip() for k in os.environ.get("FREEPIK_API_KEYS", "").split(",") if k.strip()]
        _global = FreepikClient(api_keys=keys)
    return _global

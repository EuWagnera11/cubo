"""
Refine — Audio module.

Integrações:
  - ElevenLabs : TTS multilingual (PT-BR support), voice clone, sound effects
  - Suno-like  : music generation (via Freepik se disponível ou Suno API)
  - Lip sync   : delegado pro freepik.lip_sync()

Endpoints:
  text_to_speech(text, voice_id) -> audio_url
  voice_clone(name, samples) -> voice_id
  generate_music(prompt, duration) -> audio_url
  sound_effect(prompt, duration) -> audio_url
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional, Literal

import httpx

ELEVENLABS_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"

# Vozes ElevenLabs default (multilingual v2 suporta PT-BR perfeito)
DEFAULT_VOICES = {
    "feminina_jovem":   "EXAVITQu4vr4xnSDxMaL",  # Sarah (warm, young female)
    "feminina_mature":  "ThT5KcBeYPX3keUQqHPh",  # Dorothy (mature warm)
    "masculina_jovem":  "TxGEqnHWrfWFTfGW9XjX",  # Josh (young male)
    "masculina_mature": "VR6AewLTigWG4xSOukaG",  # Arnold (mature deep)
    "narrador":         "ErXwobaYiN019PkySvjV",  # Antoni (storytelling)
    "carismatico":      "pNInz6obpgDQGcFmaJgB",  # Adam (charismatic)
}


class AudioError(Exception):
    pass


class ElevenLabsClient:
    """Cliente ElevenLabs API."""

    def __init__(self, api_key: str = ELEVENLABS_KEY, timeout: float = 120.0):
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY required")
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=timeout,
            base_url=ELEVENLABS_BASE,
            headers={"xi-api-key": api_key, "Accept": "application/json"},
        )

    # ─────────────── TTS ───────────────

    async def text_to_speech(
        self,
        text: str,
        *,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0.0,
        output_format: str = "mp3_44100_128",
    ) -> bytes:
        """Gera áudio TTS — retorna bytes do MP3."""
        body = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style,
                "use_speaker_boost": True,
            },
        }
        r = await self._client.post(
            f"/text-to-speech/{voice_id}",
            json=body, params={"output_format": output_format},
            headers={"Accept": "audio/mpeg"},
        )
        if r.status_code >= 400:
            raise AudioError(f"ElevenLabs TTS failed: {r.status_code} {r.text[:200]}")
        return r.content

    async def text_to_speech_streaming(self, text: str, *, voice_id: str, **kwargs):
        """Stream TTS pra latência baixa (útil pra realtime)."""
        body = {
            "text": text,
            "model_id": kwargs.get("model_id", "eleven_multilingual_v2"),
            "voice_settings": {
                "stability": kwargs.get("stability", 0.5),
                "similarity_boost": kwargs.get("similarity_boost", 0.75),
            },
        }
        async with self._client.stream(
            "POST", f"/text-to-speech/{voice_id}/stream", json=body,
            headers={"Accept": "audio/mpeg"},
        ) as r:
            async for chunk in r.aiter_bytes():
                yield chunk

    # ─────────────── VOICE CLONE ───────────────

    async def voice_clone(self, name: str, audio_samples: list[bytes],
                          *, description: str = "") -> str:
        """Clona voz usando 1-25 samples (até 30 min total). Retorna voice_id."""
        files = []
        for i, sample in enumerate(audio_samples):
            files.append(("files", (f"sample_{i}.mp3", sample, "audio/mpeg")))
        data = {"name": name, "description": description}

        # ElevenLabs voice add expects multipart
        async with httpx.AsyncClient(timeout=120,
                                       headers={"xi-api-key": self.api_key}) as c:
            r = await c.post(f"{ELEVENLABS_BASE}/voices/add", data=data, files=files)
        if r.status_code >= 400:
            raise AudioError(f"Voice clone failed: {r.status_code} {r.text[:200]}")
        return r.json().get("voice_id")

    async def list_voices(self) -> list[dict]:
        r = await self._client.get("/voices")
        if r.status_code >= 400:
            raise AudioError(f"List voices failed: {r.status_code}")
        return r.json().get("voices", [])

    async def delete_voice(self, voice_id: str) -> bool:
        r = await self._client.delete(f"/voices/{voice_id}")
        return r.status_code < 400

    # ─────────────── SOUND EFFECTS ───────────────

    async def sound_effect(self, prompt: str, *, duration: float | None = None) -> bytes:
        """Gera sound effect a partir de descrição textual."""
        body: dict = {"text": prompt}
        if duration:
            body["duration_seconds"] = duration
        r = await self._client.post(
            "/sound-generation", json=body,
            headers={"Accept": "audio/mpeg"},
        )
        if r.status_code >= 400:
            raise AudioError(f"Sound effect failed: {r.status_code} {r.text[:200]}")
        return r.content

    # ─────────────── MUSIC (via ElevenLabs Music API beta) ───────────────

    async def generate_music(self, prompt: str, *, duration: int = 30) -> bytes:
        """ElevenLabs music generation (beta)."""
        body = {"prompt": prompt, "music_length_ms": duration * 1000}
        r = await self._client.post(
            "/music/generate", json=body,
            headers={"Accept": "audio/mpeg"},
        )
        if r.status_code >= 400:
            raise AudioError(f"Music gen failed: {r.status_code} {r.text[:200]}")
        return r.content

    async def close(self):
        await self._client.aclose()


# ─────────────── Singleton helper ───────────────

_global_el: ElevenLabsClient | None = None

def get_elevenlabs() -> ElevenLabsClient:
    global _global_el
    if _global_el is None:
        _global_el = ElevenLabsClient()
    return _global_el


def resolve_voice(preset_or_id: str) -> str:
    """Aceita preset name ('feminina_jovem') ou voice_id direto."""
    return DEFAULT_VOICES.get(preset_or_id, preset_or_id)

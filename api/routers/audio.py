"""Audio router — TTS, voice clone, music, sound effects, lip sync.
Tudo via Freepik API (ElevenLabs integrado por baixo).
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from ..freepik import get_freepik

router = APIRouter(prefix="/audio", tags=["audio"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)


# Voice presets (mapeados pra ElevenLabs voice_ids via Freepik)
DEFAULT_VOICES = {
    "feminina_jovem":   "EXAVITQu4vr4xnSDxMaL",
    "feminina_mature":  "ThT5KcBeYPX3keUQqHPh",
    "masculina_jovem":  "TxGEqnHWrfWFTfGW9XjX",
    "masculina_mature": "VR6AewLTigWG4xSOukaG",
    "narrador":         "ErXwobaYiN019PkySvjV",
    "carismatico":      "pNInz6obpgDQGcFmaJgB",
}


# ─────────────── Models ───────────────

class TTSReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = "feminina_jovem"
    language: str = "pt-BR"
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0


class MusicReq(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=500)
    duration: int = Field(30, ge=5, le=300)
    genre: Optional[str] = None
    mood: Optional[str] = None


class SoundEffectReq(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=500)
    duration: Optional[float] = Field(None, ge=0.5, le=22.0)


class VoiceCloneReq(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    sample_urls: list[str] = Field(..., min_length=1, max_length=25)


class LipSyncReq(BaseModel):
    video_url: str
    audio_url: str


def _resolve_voice(preset_or_id: str) -> str:
    return DEFAULT_VOICES.get(preset_or_id, preset_or_id)


# ─────────────── TTS ───────────────

@router.post("/tts")
async def text_to_speech(payload: TTSReq, user: AuthUser = Depends(get_current_user)) -> dict:
    """Text-to-speech (PT-BR e multilingual via Freepik)."""
    cost = max(1, len(payload.text) // 200)
    if user.credits < cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{cost})")

    voice_id = _resolve_voice(payload.voice)
    fp = get_freepik()
    task_id = await fp.text_to_speech(
        payload.text,
        voice_id=voice_id,
        stability=payload.stability,
        similarity_boost=payload.similarity_boost,
        style=payload.style,
    )

    deduct_credits(user.user_id, cost)

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO audio_generations
              (user_id, type, status, text_input, voice_id, voice_preset, language, credits_used, metadata)
            VALUES (:u, 'tts', 'processing', :t, :vid, :vp, :lang, :c, :m::jsonb) RETURNING id
        """), {
            "u": user.user_id, "t": payload.text[:5000], "vid": voice_id,
            "vp": payload.voice, "lang": payload.language, "c": cost,
            "m": f'{{"freepik_task_id":"{task_id}"}}',
        }).first()

    return {"id": str(row.id), "task_id": task_id, "credits_used": cost}


@router.get("/voices")
async def list_voices(user: AuthUser = Depends(get_current_user)) -> dict:
    """Lista vozes disponíveis (presets + Freepik account voices)."""
    fp = get_freepik()
    try:
        freepik_voices = await fp.list_voices()
    except Exception:
        freepik_voices = []

    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM voices WHERE user_id=:u OR is_public=true ORDER BY created_at DESC"
        ), {"u": user.user_id}).fetchall()
    user_voices = [dict(r._mapping) for r in rows]

    return {
        "presets": DEFAULT_VOICES,
        "freepik_voices": freepik_voices,
        "user_voices": user_voices,
    }


# ─────────────── Voice Clone ───────────────

@router.post("/voices/clone")
async def voice_clone(payload: VoiceCloneReq, user: AuthUser = Depends(get_current_user)) -> dict:
    """Clona voz via Freepik (passa URLs dos samples — upload prévio)."""
    cost = 50
    if user.credits < cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{cost})")

    fp = get_freepik()
    voice_id = await fp.voice_clone(
        name=payload.name,
        description=payload.description or "",
        audio_sample_urls=payload.sample_urls,
    )

    deduct_credits(user.user_id, cost)

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO voices (user_id, name, description, provider, external_voice_id, is_clone)
            VALUES (:u, :n, :d, 'freepik', :vid, true) RETURNING id
        """), {"u": user.user_id, "n": payload.name, "d": payload.description, "vid": voice_id}).first()

    return {"id": str(row.id), "voice_id": voice_id, "credits_used": cost}


@router.delete("/voices/{voice_id}")
def delete_voice(voice_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.begin() as conn:
        r = conn.execute(text(
            "DELETE FROM voices WHERE id=:id AND user_id=:u RETURNING id"
        ), {"id": voice_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return {"deleted": True}


# ─────────────── Music ───────────────

@router.post("/music")
async def generate_music(payload: MusicReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 5 + (payload.duration // 30) * 3
    if user.credits < cost:
        raise HTTPException(402)

    full_prompt = payload.prompt
    if payload.genre: full_prompt += f", genre: {payload.genre}"
    if payload.mood:  full_prompt += f", mood: {payload.mood}"

    fp = get_freepik()
    task_id = await fp.music_generation(full_prompt, duration=payload.duration)

    deduct_credits(user.user_id, cost)

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO audio_generations
              (user_id, type, status, text_input, music_genre, music_mood, duration_seconds, credits_used, metadata)
            VALUES (:u, 'music', 'processing', :t, :g, :m, :d, :c, :meta::jsonb) RETURNING id
        """), {
            "u": user.user_id, "t": payload.prompt, "g": payload.genre, "m": payload.mood,
            "d": payload.duration, "c": cost,
            "meta": f'{{"freepik_task_id":"{task_id}"}}',
        }).first()

    return {"id": str(row.id), "task_id": task_id, "duration": payload.duration, "credits_used": cost}


# ─────────────── Sound Effects ───────────────

@router.post("/sfx")
async def sound_effect(payload: SoundEffectReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 2
    if user.credits < cost:
        raise HTTPException(402)

    fp = get_freepik()
    task_id = await fp.sound_effect(payload.prompt, duration=payload.duration)

    deduct_credits(user.user_id, cost)

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO audio_generations (user_id, type, status, text_input, credits_used, metadata)
            VALUES (:u, 'sound_effect', 'processing', :t, :c, :m::jsonb) RETURNING id
        """), {
            "u": user.user_id, "t": payload.prompt[:500], "c": cost,
            "m": f'{{"freepik_task_id":"{task_id}"}}',
        }).first()

    return {"id": str(row.id), "task_id": task_id, "credits_used": cost}


# ─────────────── Lip Sync ───────────────

@router.post("/lip-sync")
async def lip_sync(payload: LipSyncReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 30
    if user.credits < cost:
        raise HTTPException(402)

    fp = get_freepik()
    task_id = await fp.lip_sync(payload.video_url, payload.audio_url)

    deduct_credits(user.user_id, cost)

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO audio_generations
              (user_id, type, status, source_video_url, reference_audio_url, credits_used, metadata)
            VALUES (:u, 'lip_sync', 'processing', :v, :a, :c, :m::jsonb) RETURNING id
        """), {
            "u": user.user_id, "v": payload.video_url, "a": payload.audio_url,
            "c": cost, "m": f'{{"freepik_task_id":"{task_id}"}}',
        }).first()

    return {"id": str(row.id), "task_id": task_id, "credits_used": cost}


# ─────────────── List + get ───────────────

@router.get("/{audio_id}")
def get_audio(audio_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.connect() as conn:
        r = conn.execute(text(
            "SELECT * FROM audio_generations WHERE id=:id AND user_id=:u"
        ), {"id": audio_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    return dict(r._mapping)


@router.get("")
def list_audio(user: AuthUser = Depends(get_current_user)) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM audio_generations WHERE user_id=:u ORDER BY created_at DESC LIMIT 50"
        ), {"u": user.user_id}).fetchall()
    return [dict(r._mapping) for r in rows]

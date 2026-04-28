"""Audio router — TTS, voice clone, music, lip sync."""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from supabase import create_client

from ..auth_dep import get_current_user, AuthUser, deduct_credits
from ..audio import get_elevenlabs, resolve_voice, DEFAULT_VOICES, AudioError
from ..freepik import get_freepik

router = APIRouter(prefix="/audio", tags=["audio"])
_engine = create_engine(os.environ.get("DATABASE_URL", "").replace("+asyncpg", ""), pool_pre_ping=True)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


# ─────────────── Models ───────────────

class TTSReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = "feminina_jovem"  # preset or voice_id
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


class LipSyncReq(BaseModel):
    video_url: str
    audio_url: str


def _save_audio(content: bytes, user_id: str, kind: str, ext: str = "mp3") -> str:
    """Upload bytes pro Supabase storage e retorna URL pública."""
    if not SUPABASE_URL:
        raise HTTPException(503, "Supabase não configurado")
    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    import uuid
    path = f"{user_id}/{kind}/{uuid.uuid4()}.{ext}"
    sb.storage.from_("generations").upload(path, content,
        file_options={"content-type": f"audio/{ext}", "upsert": "true"})
    url = sb.storage.from_("generations").get_public_url(path)
    return url


# ─────────────── TTS ───────────────

@router.post("/tts")
async def text_to_speech(payload: TTSReq, user: AuthUser = Depends(get_current_user)) -> dict:
    """Text-to-speech multilingual (PT-BR de qualidade)."""
    cost = max(1, len(payload.text) // 200)  # ~1 crédito a cada 200 chars
    if user.credits < cost:
        raise HTTPException(402, f"Créditos insuficientes ({user.credits}/{cost})")
    deduct_credits(user.user_id, cost)

    voice_id = resolve_voice(payload.voice)
    el = get_elevenlabs()
    try:
        content = await el.text_to_speech(
            payload.text, voice_id=voice_id,
            stability=payload.stability,
            similarity_boost=payload.similarity_boost,
            style=payload.style,
        )
    except AudioError as e:
        raise HTTPException(500, str(e))

    url = _save_audio(content, user.user_id, "tts")

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO audio_generations
              (user_id, type, status, text_input, voice_id, voice_preset, language, output_url, credits_used)
            VALUES (:u, 'tts', 'completed', :t, :vid, :vp, :lang, :url, :c) RETURNING id
        """), {
            "u": user.user_id, "t": payload.text[:5000], "vid": voice_id,
            "vp": payload.voice, "lang": payload.language, "url": url, "c": cost,
        }).first()

    return {"id": str(row.id), "url": url, "credits_used": cost}


@router.post("/tts/stream")
async def tts_stream(payload: TTSReq, user: AuthUser = Depends(get_current_user)):
    """TTS streaming pra player realtime."""
    cost = max(1, len(payload.text) // 200)
    if user.credits < cost:
        raise HTTPException(402)
    deduct_credits(user.user_id, cost)

    voice_id = resolve_voice(payload.voice)
    el = get_elevenlabs()

    async def generate():
        async for chunk in el.text_to_speech_streaming(payload.text, voice_id=voice_id,
                                                       stability=payload.stability,
                                                       similarity_boost=payload.similarity_boost):
            yield chunk

    return StreamingResponse(generate(), media_type="audio/mpeg")


# ─────────────── Voice Clone ───────────────

@router.post("/voices/clone")
async def voice_clone(
    name: str = Form(...),
    description: str = Form(""),
    samples: list[UploadFile] = File(...),
    user: AuthUser = Depends(get_current_user),
) -> dict:
    """Clona voz a partir de samples (1-25 arquivos áudio)."""
    cost = 50
    if user.credits < cost:
        raise HTTPException(402)
    if len(samples) < 1 or len(samples) > 25:
        raise HTTPException(400, "Envie 1-25 amostras")

    sample_bytes = [await s.read() for s in samples]
    el = get_elevenlabs()
    try:
        voice_id = await el.voice_clone(name=name, description=description, audio_samples=sample_bytes)
    except AudioError as e:
        raise HTTPException(500, str(e))

    deduct_credits(user.user_id, cost)
    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO voices (user_id, name, description, provider, external_voice_id, is_clone)
            VALUES (:u, :n, :d, 'elevenlabs', :vid, true) RETURNING id
        """), {"u": user.user_id, "n": name, "d": description, "vid": voice_id}).first()

    return {"id": str(row.id), "voice_id": voice_id, "credits_used": cost}


@router.get("/voices")
def list_voices(user: AuthUser = Depends(get_current_user)) -> dict:
    """Lista vozes do user + presets default."""
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM voices WHERE user_id=:u OR is_public=true ORDER BY created_at DESC"
        ), {"u": user.user_id}).fetchall()
    user_voices = [dict(r._mapping) for r in rows]
    return {"presets": DEFAULT_VOICES, "user_voices": user_voices}


@router.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _engine.begin() as conn:
        r = conn.execute(text(
            "DELETE FROM voices WHERE id=:id AND user_id=:u RETURNING external_voice_id, is_clone"
        ), {"id": voice_id, "u": user.user_id}).first()
    if not r:
        raise HTTPException(404)
    if r.is_clone and r.external_voice_id:
        try:
            el = get_elevenlabs()
            await el.delete_voice(r.external_voice_id)
        except Exception:
            pass
    return {"deleted": True}


# ─────────────── Music ───────────────

@router.post("/music")
async def generate_music(payload: MusicReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 5 + (payload.duration // 30) * 3  # base + extras por 30s
    if user.credits < cost:
        raise HTTPException(402)
    deduct_credits(user.user_id, cost)

    full_prompt = payload.prompt
    if payload.genre: full_prompt += f", genre: {payload.genre}"
    if payload.mood:  full_prompt += f", mood: {payload.mood}"

    el = get_elevenlabs()
    try:
        content = await el.generate_music(full_prompt, duration=payload.duration)
    except AudioError as e:
        raise HTTPException(500, str(e))

    url = _save_audio(content, user.user_id, "music")

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO music_tracks (user_id, name, prompt, genre, mood, duration_seconds, audio_url)
            VALUES (:u, :n, :p, :g, :m, :d, :url) RETURNING id
        """), {
            "u": user.user_id, "n": payload.prompt[:80], "p": payload.prompt,
            "g": payload.genre, "m": payload.mood, "d": payload.duration, "url": url,
        }).first()

    return {"id": str(row.id), "url": url, "credits_used": cost, "duration": payload.duration}


# ─────────────── Sound Effects ───────────────

@router.post("/sfx")
async def sound_effect(payload: SoundEffectReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 2
    if user.credits < cost:
        raise HTTPException(402)
    deduct_credits(user.user_id, cost)

    el = get_elevenlabs()
    try:
        content = await el.sound_effect(payload.prompt, duration=payload.duration)
    except AudioError as e:
        raise HTTPException(500, str(e))

    url = _save_audio(content, user.user_id, "sfx")

    with _engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO audio_generations (user_id, type, status, text_input, output_url, credits_used)
            VALUES (:u, 'sound_effect', 'completed', :t, :url, :c)
        """), {"u": user.user_id, "t": payload.prompt[:500], "url": url, "c": cost})

    return {"url": url, "credits_used": cost}


# ─────────────── Lip Sync ───────────────

@router.post("/lip-sync")
async def lip_sync(payload: LipSyncReq, user: AuthUser = Depends(get_current_user)) -> dict:
    cost = 30
    if user.credits < cost:
        raise HTTPException(402)
    deduct_credits(user.user_id, cost)

    fp = get_freepik()
    task_id = await fp.lip_sync(payload.video_url, payload.audio_url)

    with _engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO audio_generations (user_id, type, status, source_video_url, reference_audio_url, credits_used, metadata)
            VALUES (:u, 'lip_sync', 'processing', :v, :a, :c, :m::jsonb) RETURNING id
        """), {
            "u": user.user_id, "v": payload.video_url, "a": payload.audio_url,
            "c": cost, "m": f'{{"freepik_task_id": "{task_id}"}}',
        }).first()

    return {"id": str(row.id), "task_id": task_id, "credits_used": cost}


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

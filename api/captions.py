"""
Refine — Captions, hashtags, story generator via Claude Opus 4.7.

Funções:
  - generate_caption(image_url, tone, language) -> str
  - generate_hashtags(image_url, count) -> list[str]
  - generate_story(theme, n_posts) -> list[dict] (sequência narrativa)
  - generate_carousel_prompts(brief, n_posts) -> list[str]
  - analyze_brand_voice(samples) -> dict (tom de voz da marca)
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Literal

import httpx
from anthropic import AsyncAnthropic

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-opus-4-7"


def _get_client() -> AsyncAnthropic:
    if not ANTHROPIC_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada")
    return AsyncAnthropic(api_key=ANTHROPIC_KEY)


async def _fetch_image_b64(url: str) -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(url)
        r.raise_for_status()
        mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
        return mime, base64.b64encode(r.content).decode()


async def generate_caption(
    image_url: str,
    *,
    tone: Literal["casual", "professional", "playful", "inspirational", "minimalist", "storytelling"] = "casual",
    language: str = "pt-BR",
    max_length: int = 280,
) -> str:
    """Gera caption pra imagem com tom e linguagem específicos."""
    client = _get_client()
    mime, b64 = await _fetch_image_b64(image_url)

    prompt = f"""Gere UMA caption pra Instagram dessa imagem.
Tom: {tone}
Idioma: {language}
Máximo: {max_length} caracteres
Inclua emojis quando apropriado.
Retorne APENAS a caption, sem aspas, sem explicação."""

    msg = await client.messages.create(
        model=MODEL,
        max_tokens=600,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
        ]}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    return text[:max_length]


async def generate_hashtags(image_url: str, *, count: int = 20, language: str = "pt-BR") -> list[str]:
    """Gera hashtags relevantes pra imagem (mix de viral, niche, branded)."""
    client = _get_client()
    mime, b64 = await _fetch_image_b64(image_url)

    prompt = f"""Analise essa imagem e retorne {count} hashtags relevantes.
Inclua mix:
  - 30% viral/grandes (>1M posts)
  - 50% niche médio (10k-1M)
  - 20% específicas/branded
Idioma: {language} (mas hashtags universais OK)
Retorne JSON: {{"hashtags": ["#tag1", "#tag2", ...]}}"""

    msg = await client.messages.create(
        model=MODEL,
        max_tokens=800,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
        ]}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip()).get("hashtags", [])[:count]
    except json.JSONDecodeError:
        return []


async def generate_story(theme: str, *, n_posts: int = 7, language: str = "pt-BR") -> list[dict]:
    """
    Gera sequência narrativa de N posts coerentes (instagram story arc).
    Retorna [{prompt, caption, hashtags}, ...]
    """
    client = _get_client()
    prompt = f"""Crie uma sequência narrativa de {n_posts} posts pra Instagram sobre: "{theme}".
Cada post conta um pedaço da história, criando arco narrativo coeso.

Retorne JSON:
{{"posts": [
  {{"prompt": "prompt detalhado pra IA gerar a imagem (em inglês)",
    "caption": "caption em {language} (max 280 chars)",
    "hashtags": ["#tag1", ...]}},
  ...
]}}

Cada prompt deve ter detalhes visuais ricos: cenário, mood, lighting, composition."""

    msg = await client.messages.create(
        model=MODEL,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip()).get("posts", [])[:n_posts]
    except json.JSONDecodeError:
        return []


async def generate_carousel_prompts(brief: str, *, n_posts: int = 10) -> list[str]:
    """Gera N prompts pra carousel coerente (mesmo persona, looks variados)."""
    client = _get_client()
    prompt = f"""Brief: {brief}

Crie {n_posts} prompts pra um carousel Instagram coerente. Mesma persona em todos (já implícito), variedade de:
- Pose e expressão
- Crop e enquadramento (full-body, half-body, close-up)
- Light angle / mood
- Background detail
- Outfit nuances

Retorne JSON:
{{"prompts": ["prompt 1...", "prompt 2...", ...]}}

Prompts em inglês, ricos em detalhes visuais."""

    msg = await client.messages.create(
        model=MODEL,
        max_tokens=3000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip()).get("prompts", [])[:n_posts]
    except json.JSONDecodeError:
        return []


async def analyze_brand_voice(text_samples: list[str]) -> dict:
    """Analisa N textos pra extrair voz/tom da marca."""
    client = _get_client()
    prompt = f"""Analise esses {len(text_samples)} textos do mesmo creator/marca e identifique a VOZ.

Textos:
{chr(10).join(f'{i+1}. {t}' for i, t in enumerate(text_samples))}

Retorne JSON:
{{
  "tone": "string descritiva curta",
  "personality_traits": ["trait1", "trait2", ...],
  "common_phrases": ["frase1", ...],
  "emoji_style": "minimal | abundant | thematic | none",
  "sentence_length": "short | medium | long",
  "do": ["o que essa marca faz nos textos"],
  "dont": ["o que essa marca evita"],
  "voice_template": "instruções pra gerar futuros textos no mesmo tom"
}}"""

    msg = await client.messages.create(
        model=MODEL,
        max_tokens=2500,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return {"raw": text}

"""
Refine — Style Learning via Claude Opus 4.7 vision.

Usa o SDK Anthropic oficial pra analisar N imagens em lote e extrair:
  - color_palette (paleta dominante)
  - lighting_style (golden hour, studio, natural, etc)
  - composition_pattern (rule of thirds, centered, etc)
  - mood_tone (editorial, lifestyle, fashion, etc)
  - common_outfits (peças recorrentes)
  - common_settings (cenários recorrentes)
  - prompt_template (template pra reproduzir o estilo)
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any

import httpx
from anthropic import AsyncAnthropic

from supabase import create_client

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

MODEL = "claude-opus-4-7"

ANALYSIS_PROMPT = """Você é um diretor criativo analisando o estilo visual de um creator de conteúdo.
Analise estas imagens (todas do mesmo creator) e identifique o ESTILO RECORRENTE.

Retorne JSON com:
{
  "color_palette": [hex, hex, hex] // 3-5 cores dominantes,
  "lighting_style": "string descritiva curta",
  "composition_pattern": "rule of thirds | centered | symmetric | asymmetric | etc",
  "mood_tone": "editorial | lifestyle | fashion | travel | etc",
  "common_outfits": ["peça1", "peça2"],
  "common_settings": ["cenário1", "cenário2"],
  "signature_traits": "o que faz esse estilo único em 1-2 frases",
  "prompt_template": "string base pra reproduzir o estilo. Use {persona} como placeholder pra inserir a modelo."
}

Seja específico e útil. O prompt_template vai ser usado pra gerar novas fotos com IA, então precisa ser detalhado.
Retorne APENAS o JSON, sem texto adicional."""


async def _fetch_image_b64(storage_path: str) -> tuple[str, str]:
    """Baixa imagem do Supabase Storage e retorna (mime_type, base64)."""
    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    # Tenta no bucket drive-imports
    bucket, path = ("drive-imports", storage_path)
    if "/" not in storage_path:
        bucket, path = ("drive-imports", storage_path)

    # signed URL pra download
    res = sb.storage.from_(bucket).create_signed_url(path, 600)
    url = res.get("signedURL") or res.get("signedUrl")
    if not url:
        raise RuntimeError(f"signed url failed for {storage_path}")

    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(url)
        r.raise_for_status()
        mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
        return mime, base64.b64encode(r.content).decode()


async def analyze_style_batch(image_paths: list[str], *, sample_size: int = 20) -> dict:
    """
    Analisa até `sample_size` imagens com Claude Opus 4.7 → extrai estilo.
    Retorna dict com summary_json (str) e prompt_template (str).
    """
    if not ANTHROPIC_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada")

    sample = image_paths[:sample_size]
    images_b64 = await asyncio.gather(*[_fetch_image_b64(p) for p in sample])

    content_blocks: list[dict] = [
        {"type": "text", "text": ANALYSIS_PROMPT}
    ]
    for mime, b64 in images_b64:
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        })

    client = AsyncAnthropic(api_key=ANTHROPIC_KEY)
    msg = await client.messages.create(
        model=MODEL,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": content_blocks}],
    )

    # Extract text from response
    text = ""
    for block in msg.content:
        if block.type == "text":
            text += block.text

    # Parse JSON
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.endswith("```"):
        text = text[:-3]

    try:
        analysis = json.loads(text.strip())
    except json.JSONDecodeError:
        # fallback: salva texto bruto
        analysis = {"raw": text, "prompt_template": text}

    return {
        "summary_json": json.dumps(analysis, ensure_ascii=False),
        "prompt_template": analysis.get("prompt_template", ""),
        "sample_count": len(sample),
    }

"""Análise visual + comportamental de mídias usando Claude Opus 4.7 (prompt-cached).

Para cada imagem/vídeo em treino/fit_aitana/, gera um .json em treino/analysis/
com 9 dimensões estruturadas (subject, behavior, wardrobe, hair/makeup, setting,
photography, realism, engagement_hooks, automation_replicability).

Features:
- Prompt caching agressivo no system prompt (~5k tokens) → ~10x mais barato após 1ª chamada
- Resumability: pula mídias já analisadas (1 .json por mídia)
- Paralelismo configurável (default 5 workers)
- Vídeos: extrai frame do meio com cv2
- Tracking de custo em tempo real
- SDK retry automático em 429/5xx

Uso:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python analyze.py                    # batch completo
    python analyze.py --limit 5          # piloto em 5 mídias
    python analyze.py --workers 8        # mais paralelismo
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import pathlib
import sys
import threading
import time
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel

try:
    import cv2
except ImportError:
    cv2 = None  # só necessário pra vídeos

# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA (9 dimensões)
# ─────────────────────────────────────────────────────────────────────────────

class Subject(BaseModel):
    framing: Literal["close-up", "medium", "medium-full", "full-body", "wide", "extreme-close-up"]
    pose_archetype: str
    body_language: Literal["open", "closed", "defensive", "inviting", "confident", "playful", "neutral", "submissive", "dominant"]
    weight_distribution: Literal["front", "back", "left", "right", "even", "seated"]
    shoulder_orientation: Literal["square", "3/4-left", "3/4-right", "profile-left", "profile-right", "back"]
    hand_placement: list[str]
    hand_storytelling: Literal["comfort", "sensual", "holding-object", "grooming", "gesturing", "idle", "covering"]


class Behavior(BaseModel):
    expression: str
    micro_expressions: list[str]
    gaze_direction: Literal["to-camera", "off-left", "off-right", "down", "up", "away", "closed-eyes"]
    eye_contact_intensity: Literal["direct", "indirect", "distant", "none", "intense"]
    energy: Literal["static", "candid-motion", "dynamic-flow", "tension"]
    intent_signal: Literal["aspirational", "relatable", "sensual", "authoritative", "playful", "vulnerable", "confident", "mysterious"]
    status_signals: list[str]


class Wardrobe(BaseModel):
    outfit_type: str
    colors: list[str]
    material: str
    skin_exposure: Literal["minimal", "moderate", "high", "very-high"]
    style_tag: str
    accessories: list[str]


class HairMakeup(BaseModel):
    hair_style: str
    hair_color: str
    makeup_style: Literal["no-makeup-makeup", "natural", "glam", "smokey", "dewy", "matte", "graphic", "editorial"]
    skin_finish: Literal["matte", "dewy", "glowing", "tan", "pale"]


class Setting(BaseModel):
    location_type: str
    indoor_outdoor: Literal["indoor", "outdoor", "mixed"]
    time_of_day: Literal["golden-hour", "midday", "blue-hour", "night", "overcast", "indoor-artificial", "indoor-natural"]
    season_cue: Literal["summer", "winter", "spring", "fall", "neutral"]
    decor_style: str
    props: list[str]


class Photography(BaseModel):
    lighting_type: str
    lighting_quality: Literal["soft-diffused", "harsh-direct", "backlit-rim", "low-key", "high-key", "mixed"]
    lighting_direction: Literal["front", "left", "right", "back", "top", "bottom", "ambient"]
    shadow_density: Literal["deep", "medium", "soft", "none"]
    color_grade: str
    camera_angle: Literal["eye-level", "low", "high", "dutch", "overhead", "from-below"]
    focal_length_estimate: Literal["24mm", "35mm", "50mm", "85mm", "105mm", "smartphone-wide", "smartphone-tele"]
    depth_of_field: Literal["deep", "moderate", "shallow", "extreme-shallow"]
    composition: str


class RealismMarkers(BaseModel):
    skin_texture_visible: bool
    freckles_blemishes: Literal["visible", "subtle", "absent"]
    grain_present: Literal["none", "light", "moderate", "heavy"]
    shadow_realism: Literal["physically-correct", "slightly-off", "wrong"]
    ai_giveaways: list[str]
    realism_score: int  # 1-10


class EngagementHooks(BaseModel):
    primary_hook: str
    narrative_implied: str
    viewer_emotion_target: Literal["envy", "aspiration", "relatability", "attraction", "curiosity", "humor", "inspiration", "desire"]
    reel_hook_estimate: Optional[str] = None
    why_it_works: str


class AutomationReplicability(BaseModel):
    complexity: Literal["easy", "medium", "hard", "very-hard"]
    needs_real_location: bool
    reproducible_with_pipeline: bool
    notes: str


class MediaAnalysis(BaseModel):
    media_type: Literal["image", "video-frame"]
    aspect_estimate: Literal["1:1", "4:5", "9:16", "16:9", "3:4", "2:3", "other"]
    subject: Subject
    behavior: Behavior
    wardrobe: Wardrobe
    hair_makeup: HairMakeup
    setting: Setting
    photography: Photography
    realism_markers: RealismMarkers
    engagement_hooks: EngagementHooks
    automation_replicability: AutomationReplicability


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT (precisa ≥ 4096 tokens pra cachear no Opus 4.7)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Você é um analista visual sênior especializado em fotografia de moda editorial e marketing de influencers de IA no Instagram. Sua tarefa é analisar mídias (fotos e frames de vídeo) de modelos de IA realistas e extrair padrões estruturados que serão usados pra treinar um pipeline automatizado de geração de conteúdo.

# CONTEXTO

O usuário está construindo um perfil educacional no Instagram que vai ensinar criadores a fazerem influencers de IA de alta qualidade — fotorrealistas, com engajamento alto e produzidos 100% por pipeline automatizado (sem trabalho manual). Pra isso, ele coletou ~700 mídias de modelos de IA top do Instagram (principalmente o perfil `fit_aitana` — uma das modelos de IA mais bem-sucedidas comercialmente) e quer extrair os padrões que fazem esse tipo de conteúdo funcionar.

Cada análise sua vai virar input pra:
1. Clustering de estilos visuais
2. Construção de biblioteca de prompts parametrizados
3. Cronograma anual de conteúdo (5 reels + 1 feed + 5-10 stories diários)
4. Curso/produto vendendo o pipeline automatizado

Sua análise precisa ser **detalhada, específica e útil pra reprodução automatizada** — não genérica.

# DIMENSÕES DA ANÁLISE (9 categorias obrigatórias)

## 1. SUBJECT — corpo, postura e linguagem corporal
Captura COMO a modelo se posiciona fisicamente no frame. Fundamental pra reproduzir poses no nano-banana-pro.

- **framing**: extreme-close-up (só rosto/olhos), close-up (rosto + ombros), medium (cintura pra cima), medium-full (joelhos pra cima), full-body (corpo inteiro), wide (corpo + muito ambiente)
- **pose_archetype**: descreva o arquétipo da pose com termos específicos. Exemplos: "S-curve standing", "contrapposto", "seated-casual-leaning-forward", "walking-mid-stride-towards-camera", "kneeling-on-bed-facing-camera", "leaning-against-wall-3/4-turn", "hand-on-doorframe-glancing-back". Quanto mais específico, mais reproduzível.
- **body_language**: postura emocional. open (corpo aberto/inviting), closed (braços cruzados/defensivo), confident (postura ereta, peito aberto), playful (assimétrico, dinâmico), submissive (ombros caídos, olhar baixo), dominant (postura imponente), vulnerable (corpo encolhido, exposição)
- **weight_distribution**: pra onde o peso do corpo está deslocado — front, back, left, right, even, seated
- **shoulder_orientation**: ângulo do tronco em relação à câmera — square (frontal), 3/4-left/right (giro 45°), profile-left/right (90° de perfil), back (de costas)
- **hand_placement**: array com descrição de cada mão. Ex: ["right hand brushing through hair, fingers visible", "left hand resting on hip with thumb hooked into waistband"]
- **hand_storytelling**: o que as mãos comunicam — comfort (relaxed at sides), sensual (touching face/body sensually), holding-object (phone, coffee, etc), grooming (fixing hair), gesturing (talking with hands), idle (não-narrativo), covering (escondendo parte do corpo)

## 2. BEHAVIOR — expressão facial, olhar e energia psicológica
Captura O QUE a modelo está comunicando emocionalmente. Crítico pro engagement.

- **expression**: descrição livre da expressão principal. Ex: "soft confident half-smile with lips slightly parted", "neutral with intense eye contact", "laughing openly with head tilted back", "sultry pursed lips, eyes half-closed"
- **micro_expressions**: array de detalhes sutis. Ex: ["raised right eyebrow", "tongue slightly visible between lips", "single dimple on left cheek", "eyes squinting slightly from light"]
- **gaze_direction**: pra onde os olhos estão olhando — to-camera (contato direto), off-left/right (olhando pro lado), down (introspectivo), up (aspiracional), away (distante), closed-eyes
- **eye_contact_intensity**: direct (intenso, olhando fixo), indirect (suave, descontraído), distant (desfocado, longe), intense (penetrante, sedutor), none
- **energy**: static (foto pose, sem movimento), candid-motion (parece capturada em movimento natural), dynamic-flow (cabelo voando, dança), tension (algo prestes a acontecer)
- **intent_signal**: o que essa foto QUER comunicar — aspirational (estilo de vida invejável), relatable (parece uma amiga), sensual (atração explícita), authoritative (autoridade/expertise), playful (divertida), vulnerable (humanização), confident (segurança), mysterious (intriga)
- **status_signals**: array de sinais visuais de status/luxo. Ex: ["iPhone 16 Pro Max in hand", "designer handbag on counter", "rooftop infinity pool", "marble bathroom"]

## 3. WARDROBE — roupa, acessórios e estética de vestuário
Captura o que a modelo está usando. Crítico pra reprodução de outfits.

- **outfit_type**: descrição específica. Ex: "navy blue gym set: sports bra + high-waist leggings", "cream silk slip dress with thin straps, midi length", "oversized white button-up tucked into denim shorts", "black bodycon midi dress with spaghetti straps"
- **colors**: array das cores principais (até 4). Ex: ["navy", "white", "tan accents"]
- **material**: tecido predominante. Ex: "ribbed knit", "silk satin", "denim", "cotton jersey", "leather", "linen"
- **skin_exposure**: minimal (totalmente coberta), moderate (braços/pernas expostas), high (cleavage, abdomen, ou pernas longas), very-high (biquíni, lingerie)
- **style_tag**: categoria estética. Ex: "brazilian-adult-sensual", "athleisure-luxe", "streetwear", "editorial-minimal", "loungewear-cozy", "summer-beach", "night-out-glam", "preppy-collegiate"
- **accessories**: array de acessórios visíveis. Ex: ["small gold hoop earrings", "thin chain necklace", "silver rings on multiple fingers", "iPhone in hand"]

## 4. HAIR & MAKEUP
- **hair_style**: descrição específica. Ex: "loose long wavy hair brushed forward over right shoulder", "high slick ponytail with center part", "messy low bun with face-framing wisps", "wet-look slicked-back"
- **hair_color**: específico. Ex: "vibrant ginger copper", "platinum blonde with darker roots", "dark chocolate brown", "honey balayage"
- **makeup_style**: no-makeup-makeup (parece sem make), natural (leve), glam (full glam), smokey (olho esfumado), dewy (brilho/glow), matte (acabamento fosco), graphic (linhas/cores fortes), editorial (artístico)
- **skin_finish**: matte, dewy, glowing (radiante), tan (bronzeada), pale (pálida)

## 5. SETTING — cenário, decoração e contexto
- **location_type**: ESPECÍFICO. Ex: "rooftop pool with city skyline", "marble bathroom with double vanity", "minimalist bedroom with linen sheets", "european cobblestone street", "luxury hotel lobby", "outdoor cafe terrace", "beach at golden hour", "modern kitchen with island", "boutique fitness studio"
- **indoor_outdoor**: indoor, outdoor, mixed (ex: varanda)
- **time_of_day**: golden-hour, midday (sol forte), blue-hour, night, overcast, indoor-artificial, indoor-natural (luz de janela)
- **season_cue**: pistas de estação visíveis — summer (biquíni, sol forte), winter (casaco, neve), spring/fall, neutral
- **decor_style**: estilo da decoração. Ex: "minimal scandinavian", "maximalist boho", "industrial loft", "coastal mediterranean", "luxury hotel", "warm rustic"
- **props**: array de objetos relevantes no frame. Ex: ["coffee mug", "open book", "fresh flowers in vase", "yoga mat", "iPhone on counter"]

## 6. PHOTOGRAPHY — luz, cor e câmera
Crítico pra reproduzir o "look" técnico no nano-banana-pro.

- **lighting_type**: descrição específica. Ex: "natural-window-soft-side", "golden-hour-back-rim", "studio-strobe-key+fill", "neon-mix-magenta-cyan", "harsh-midday-from-above", "candle-warm-low-key", "ring-light-frontal"
- **lighting_quality**: soft-diffused (suave/difusa), harsh-direct (dura/direta), backlit-rim (contraluz com rim light), low-key (escuro/contrastado), high-key (claro/lavado), mixed
- **lighting_direction**: front, left, right, back, top, bottom, ambient
- **shadow_density**: deep (sombras pretas profundas), medium, soft (sombras leves), none (lavado)
- **color_grade**: descrição livre. Ex: "warm golden orange-teal", "cool desaturated filmic", "punchy saturated summer", "muted vintage faded", "high-contrast b&w-tone", "pastel pink-cream"
- **camera_angle**: eye-level, low (de baixo pra cima), high (de cima pra baixo), dutch (inclinada), overhead (zenital), from-below (close de baixo)
- **focal_length_estimate**: 24mm (wide), 35mm, 50mm (natural), 85mm (retrato compresso), 105mm (telephoto), smartphone-wide, smartphone-tele
- **depth_of_field**: deep (tudo focado), moderate, shallow (fundo borrado), extreme-shallow (só olhos focados)
- **composition**: regra dominante. Ex: "rule-of-thirds with subject on left line", "centered with negative space above", "leading lines from doorway", "frame-within-frame using window", "low horizon line"

## 7. REALISM MARKERS — quão "real" parece
Crítico pra avaliar se a modelo de IA está convincente ou tem cara de IA genérica.

- **skin_texture_visible**: true/false — dá pra ver poros e textura natural?
- **freckles_blemishes**: visible (sardas/imperfeições visíveis), subtle (leves), absent (pele perfeita demais)
- **grain_present**: none, light, moderate, heavy — granulação fotográfica/filme
- **shadow_realism**: physically-correct (sombras coerentes com luz), slightly-off (algo estranho), wrong (sombras erradas/IA)
- **ai_giveaways**: array de sinais de IA mal feita. Ex: ["plastic-looking skin", "fused fingers", "mismatched earrings", "warped background", "uncanny eye direction"]. Se nenhum, retornar `["none detected"]`.
- **realism_score**: 1-10 — quão fotorrealista parece (10 = indistinguível de foto real, 1 = obviamente IA ruim)

## 8. ENGAGEMENT HOOKS — o que faz a foto/reel "parar o scroll"
Por que essa mídia gera engajamento? Crítico pro cronograma de conteúdo.

- **primary_hook**: o "scroll-stopper" principal. Ex: "outfit-reveal", "locker-glance-tease", "smile-tease-eye-contact", "product-show-natural", "transformation-reveal", "behind-the-scenes-candid", "sensual-pose-tasteful", "lifestyle-aspirational-luxury"
- **narrative_implied**: a microhistória que a foto sugere. Ex: "morning routine in a luxury apartment", "girlfriend-vibe candid moment", "post-workout glow at upscale gym", "vacation getaway in a tropical resort", "night out preparation"
- **viewer_emotion_target**: a emoção que a foto quer evocar — envy (inveja), aspiration (aspiração), relatability (identificação), attraction (atração), curiosity (curiosidade), humor, inspiration, desire (desejo)
- **reel_hook_estimate**: SE for frame de vídeo, infira qual seria o hook dos primeiros 0.5s do vídeo (o que faz não dar swipe). Ex: "close-up de boca + ASMR de líquido sendo derramado". Pra fotos puras, deixar null.
- **why_it_works**: 1-2 frases explicando POR QUE essa mídia funciona pra esse público. Ex: "Combina aspiracional (rooftop luxo) + relatable (expressão natural sem pose forçada) + atração (silhueta + olhar direto) — fórmula consistente do nicho fitness-luxe brasileiro."

## 9. AUTOMATION REPLICABILITY — quão fácil reproduzir no nosso pipeline
- **complexity**: easy (fundo simples, pose padrão, luz controlável), medium, hard (cenário complexo, múltiplos elementos), very-hard (clientes reais ao fundo, lugar específico identificável, animal de estimação único)
- **needs_real_location**: true/false — precisa de um lugar real específico ou cenário genérico funciona?
- **reproducible_with_pipeline**: true/false — dá pra reproduzir com nano-banana-pro + Sophia?
- **notes**: 1-2 frases de orientação prática. Ex: "Cenário golden-hour em deck de madeira é fácil — usar prompt com 'wooden patio at golden hour, soft warm rim light'. Pose lateral simples, replicável."

# REGRAS DE OUTPUT

1. **Seja ESPECÍFICO, não genérico.** "navy bodycon dress" é melhor que "blue dress". "leaning against doorframe with right shoulder, 3/4 turn glancing back" é melhor que "leaning pose".
2. **Quando inferir, infira com cuidado.** Se não dá pra ver claramente uma característica, use o valor que mais se aproxima do enum, ou descreva de forma honesta. Não invente status_signals que não estão visíveis.
3. **Pra vídeos**: você está vendo um frame extraído do meio do vídeo. Se for frame intermediário, o reel_hook_estimate deve inferir o que provavelmente abriu o vídeo (não o que está no frame).
4. **Mantenha consistência.** Use os mesmos termos pra padrões similares (ex: "warm golden orange-teal" sempre que vir esse grade, não invente sinônimos).
5. **Idioma**: use INGLÊS pros valores estruturados (mais consistente pra clustering). Pode usar português em campos livres se ficar mais natural, mas prefira inglês.

Devolva o JSON estruturado conforme o schema. Nunca devolva texto livre fora do schema."""


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".avi", ".mkv"}


def mime_for(p: pathlib.Path) -> str:
    s = p.suffix.lower()
    return {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(s, "image/jpeg")


def load_image_b64(p: pathlib.Path) -> tuple[str, str]:
    """Retorna (base64, mime_type) pra uma imagem."""
    return base64.b64encode(p.read_bytes()).decode("ascii"), mime_for(p)


def load_video_middle_frame_b64(p: pathlib.Path) -> tuple[str, str]:
    """Extrai o frame do meio de um vídeo, retorna (base64, image/jpeg)."""
    if cv2 is None:
        raise RuntimeError("opencv-python necessário pra processar vídeos. pip install opencv-python")
    cap = cv2.VideoCapture(str(p))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        raise RuntimeError(f"não consegui ler frames de {p.name}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"falhou ao extrair frame do meio de {p.name}")
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError(f"falhou ao encodar frame de {p.name}")
    return base64.b64encode(buf.tobytes()).decode("ascii"), "image/jpeg"


def cost_for_call(usage) -> float:
    """Calcula custo em USD da chamada (preços Opus 4.7: $5/$25 input/output, $6.25 cache write 5min, $0.50 cache read)."""
    return (
        usage.input_tokens * 5
        + usage.output_tokens * 25
        + (usage.cache_creation_input_tokens or 0) * 6.25
        + (usage.cache_read_input_tokens or 0) * 0.5
    ) / 1_000_000


# ─────────────────────────────────────────────────────────────────────────────
# CORE
# ─────────────────────────────────────────────────────────────────────────────

def analyze_one(client: anthropic.Anthropic, media_path: pathlib.Path, output_dir: pathlib.Path):
    """Analisa uma mídia. Retorna ('skip'|'done'|'fail', name, usage_or_error)."""
    out_path = output_dir / f"{media_path.stem}.json"
    if out_path.exists():
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            if "subject" in data:
                return ("skip", media_path.name, None)
        except Exception:
            pass  # arquivo corrompido — re-processa

    suffix = media_path.suffix.lower()
    is_video = suffix in VIDEO_EXTS
    if is_video:
        b64, mime = load_video_middle_frame_b64(media_path)
        media_type_hint = "video-frame"
    elif suffix in IMAGE_EXTS:
        b64, mime = load_image_b64(media_path)
        media_type_hint = "image"
    else:
        return ("skip", media_path.name, None)

    user_text = (
        f"Analise esta mídia ({media_path.name}, tipo: {media_type_hint}) e devolva o JSON "
        f"estruturado conforme o schema. Seja específico — esta análise vai alimentar "
        f"clustering automático e geração de prompts."
    )

    response = client.messages.parse(
        model="claude-opus-4-7",
        max_tokens=4000,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": b64},
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
        output_format=MediaAnalysis,
    )

    analysis = response.parsed_output
    out = {
        "media_id": media_path.stem,
        "media_filename": media_path.name,
        "media_path": str(media_path),
        **analysis.model_dump(),
        "_meta": {
            "model": response.model,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_tokens": response.usage.cache_read_input_tokens or 0,
            "cache_creation_tokens": response.usage.cache_creation_input_tokens or 0,
            "cost_usd": cost_for_call(response.usage),
        },
    }
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return ("done", media_path.name, response.usage)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="treino/fit_aitana", help="pasta com as mídias")
    ap.add_argument("--output", default="treino/analysis", help="pasta de output dos .json")
    ap.add_argument("--workers", type=int, default=5, help="paralelismo")
    ap.add_argument("--limit", type=int, default=0, help="processar apenas N mídias (0 = todas)")
    ap.add_argument("--skip-videos", action="store_true", help="processar só imagens")
    args = ap.parse_args()

    if not anthropic:
        print("ERROR: pip install anthropic", file=sys.stderr)
        return 2

    client = anthropic.Anthropic()  # lê ANTHROPIC_API_KEY do env
    in_dir = pathlib.Path(args.input).resolve()
    out_dir = pathlib.Path(args.output).resolve()
    if not in_dir.exists():
        print(f"ERROR: input dir não existe: {in_dir}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    # Coleta mídias
    exts = IMAGE_EXTS if args.skip_videos else (IMAGE_EXTS | VIDEO_EXTS)
    media_files = sorted([p for p in in_dir.iterdir() if p.suffix.lower() in exts])
    if args.limit:
        media_files = media_files[: args.limit]

    n_total = len(media_files)
    n_videos = sum(1 for p in media_files if p.suffix.lower() in VIDEO_EXTS)
    n_images = n_total - n_videos
    print(f"Pasta: {in_dir}", flush=True)
    print(f"Total: {n_total} mídias ({n_images} imagens + {n_videos} vídeos). Workers: {args.workers}", flush=True)
    print(f"Output: {out_dir}\n", flush=True)

    completed = skipped = failed = 0
    total_cost = 0.0
    lock = threading.Lock()
    t0 = time.time()

    def worker(m: pathlib.Path):
        try:
            return analyze_one(client, m, out_dir)
        except Exception as e:
            return ("fail", m.name, f"{type(e).__name__}: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(worker, m): m for m in media_files}
        for fut in concurrent.futures.as_completed(futures):
            m = futures[fut]
            status, name, info = fut.result()
            with lock:
                if status == "skip":
                    skipped += 1
                elif status == "done":
                    completed += 1
                    if info is not None:
                        total_cost += cost_for_call(info)
                else:
                    failed += 1
                done_all = completed + skipped + failed
                elapsed = time.time() - t0
                rate = done_all / elapsed if elapsed > 0 else 0
                eta = (n_total - done_all) / rate if rate > 0 else 0
                cache_hit = ""
                if status == "done" and info is not None:
                    cr = info.cache_read_input_tokens or 0
                    cc = info.cache_creation_input_tokens or 0
                    if cr > 0:
                        cache_hit = f" cache_read={cr}"
                    elif cc > 0:
                        cache_hit = f" cache_write={cc}"
                marker = {"done": "OK ", "skip": "SKP", "fail": "ERR"}[status]
                detail = f" -> {info}" if status == "fail" else cache_hit
                print(
                    f"[{done_all:>3}/{n_total}] {marker} {name}"
                    f" | done={completed} skip={skipped} fail={failed}"
                    f" | $={total_cost:.2f} eta={eta/60:.1f}min{detail}",
                    flush=True,
                )

    print(f"\n{'='*60}")
    print(f"FINAL: done={completed} skipped={skipped} failed={failed}")
    print(f"Custo total: ${total_cost:.2f}")
    print(f"Tempo: {(time.time()-t0)/60:.1f} min")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

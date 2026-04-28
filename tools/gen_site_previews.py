"""
Gera imagens pro site Refine direto via Freepik (sem DB).

Gera 4 grupos:
  - 3 spotlights      (1280x720, 16:9)
  - 6 pinned tools    (1024x1024, square)
  - 30 model presets  (768x960, 4:5 portrait)
  - 40 worlds         (1280x720, 16:9 landscape)

Total: ~79 imagens, ~$6.3 (R$ 32), ~15 min com concurrency=5.

Output: C:/Users/wagne/out/refine_previews/<group>/<slug>.jpg
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

import httpx

OUT_DIR = Path("C:/Users/wagne/out/refine_previews")
KEYS = [
    "FPSX7cda60e66084c11bcb00a9d810064e92",
    "FPSXbb496615c05fe6ce3f06aab025e4c682",
]
CONCURRENCY = 4
SUFFIX = ", professional editorial photography, 4K quality, magazine grade, premium lighting"


def slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s[:60]


# ═══════════════════════ PROMPTS ═══════════════════════

SPOTLIGHTS = [
    ("calendar",   "30-day content calendar grid layout, multiple aesthetic photos arranged in calendar format, instagram preview mockup, modern editorial dashboard interface, copper accent on dates", "16:9"),
    ("nano4k",     "stunning 4K editorial portrait of a brazilian model in golden hour, hyper-detailed skin texture, cinematic depth of field, magazine cover quality", "16:9"),
    ("kling",      "cinematic film still, dynamic motion blur on hair flowing, dramatic lighting, hollywood movie poster style, anamorphic lens", "16:9"),
]

PINNED = [
    ("image-gen",  "ai image generation interface preview, multiple stylish portraits floating in 3d space, copper glow particles", "1:1"),
    ("video-gen",  "cinematic video generation, film strip with multiple frames showing motion, golden hour lighting, copper accents", "1:1"),
    ("face-swap",  "split portrait mid-transition between two identities, particle dissolve effect, dramatic lighting", "1:1"),
    ("upscale",    "image being upscaled with magnification effect, before-after split with detail revealed in zoom, sharp luxury aesthetic", "1:1"),
    ("audio-tts",  "audio waveforms in copper tones flowing across dark background, vintage microphone silhouette, sound visualization", "1:1"),
    ("calendar-pin","monthly content calendar grid filling automatically with editorial photos, copper highlight on today, dark theme", "1:1"),
]

PRESETS = [
    # BR FEMININAS
    ("sophia",     "mediterranean redhead brazilian woman portrait, copper hair flowing, hazel eyes, freckles, refined editorial, neutral studio background, 4:5 full body"),
    ("camila",     "sun-kissed brazilian beach girl portrait, wavy brown hair, athletic body, beach lifestyle, golden hour, full body"),
    ("bia",        "rio de janeiro carioca woman, curly black hair, golden skin, natural curves, vibrant brazilian beauty editorial portrait"),
    ("larissa",    "são paulo urban chic brazilian, straight brown hair, fashion-forward editorial portrait, modern studio"),
    ("mariana",    "minas gerais natural beauty brazilian woman, wavy chestnut hair, warm smile, soft editorial portrait"),
    ("yasmin",     "nordestina brazilian sun beauty, dark wavy hair, bronze skin, vibrant colorful editorial portrait"),
    ("beatriz",    "brazilian blonde beach beauty, beach hair, blue-green eyes, surf lifestyle editorial portrait"),
    ("ana-asian",  "asian-brazilian fusion woman, straight black hair, almond eyes, modern minimalist editorial portrait"),
    # INTERNACIONAIS FEMININAS
    ("aurora",     "italian elegant woman portrait, dark wavy hair, olive skin, refined sophisticated editorial"),
    ("emma",       "nordic blonde woman, ice-blue eyes, scandinavian minimalist style portrait"),
    ("yuki",       "japanese street style woman, black hair bob, kawaii editorial portrait"),
    ("maya",       "indian beauty woman, long dark hair, expressive eyes, cultural fashion editorial"),
    ("zara",       "middle eastern elegance woman, dark eyes, sophisticated luxury fashion portrait"),
    ("nia",        "african beauty woman, dark skin, natural hair, editorial fashion portrait"),
    ("chloe",      "parisian chic french woman, brunette wavy bob, effortless french style portrait"),
    ("olivia",     "california girl, beach blonde, athletic, lifestyle influencer portrait"),
    # MASCULINOS
    ("lucas",      "brazilian male model portrait, dark hair, athletic build, beach lifestyle"),
    ("rafael",     "italian-brazilian male, dark wavy hair, mediterranean style portrait"),
    ("diego",      "brazilian surfer man, sun-bleached hair, beach body, chill lifestyle portrait"),
    ("pedro",      "corporate brazilian executive man, sharp suit, refined business attire portrait"),
    ("marco",      "european male model, sharp jawline, fashion editorial portrait"),
    ("akira",      "japanese street style male, black hair, modern minimalist portrait"),
    ("andre",      "fitness influencer man, muscular athletic body, gym lifestyle portrait"),
    ("gabriel",    "high fashion male model, slim, defined cheekbones, editorial portrait"),
    # NICHOS
    ("carol-fit",  "fitness girl, athletic toned body, gym wellness lifestyle portrait"),
    ("julia-yoga", "yoga instructor woman, calm spiritual energy, natural neutral tones portrait"),
    ("renata",     "high fashion runway model woman, runway-ready, editorial luxury portrait"),
    ("fernanda",   "plus-size beauty woman, confident curves, body-positive fashion portrait"),
    ("helena",     "mature elegant woman, sophisticated mid-life, refined luxury editorial portrait"),
    ("cristina",   "modern mom, lifestyle influencer woman, family content style portrait"),
]

WORLDS = [
    # LIFESTYLE
    ("cafe-premium-sp",      "cozy specialty café in São Paulo, exposed brick, hanging plants, warm lighting, third-wave coffee aesthetic, intimate, no people"),
    ("mansao-hamptons",      "luxury hamptons estate, white modern architecture, infinity pool, ocean view, summer evening, no people"),
    ("loft-brooklyn",        "industrial brooklyn loft interior, exposed brick walls, large factory windows, vintage furniture, urban no people"),
    ("vinicola-toscana",     "tuscany vineyard at sunset, rolling hills, cypress trees, rustic stone villa, no people"),
    # TRAVEL
    ("santorini-caldera",    "santorini greek caldera view, white-washed buildings, blue domes, aegean sea sunset, no people"),
    ("maldives-overwater",   "maldives overwater bungalow, crystal turquoise water, palm trees, tropical paradise, no people"),
    ("tokyo-shibuya-night",  "tokyo shibuya crossing at night, neon signs, rain reflections, cyberpunk aesthetic, no people"),
    ("dubai-marina",         "dubai marina skyline, luxury yachts, glass skyscrapers, golden sunset, no people"),
    ("paris-eiffel-sunset",  "paris eiffel tower at golden hour, parisian rooftops view, romantic, no people"),
    ("nyc-times-square",     "new york times square at night, dynamic neon billboards, urban energy, no people"),
    ("bali-rice-terraces",   "bali ubud rice terraces, lush green, morning mist, tropical zen, no people"),
    ("marrakech-riad",       "marrakech moroccan riad courtyard, intricate tiles, lanterns, exotic, no people"),
    ("iceland-glacier",      "iceland glacier blue ice cave, dramatic lighting, otherworldly, no people"),
    ("amalfi-coast",         "amalfi coast italy, colorful cliffside houses, mediterranean sea, lemon trees, no people"),
    ("joshua-tree-desert",   "joshua tree california desert, golden dunes, dramatic boulders, sunset, no people"),
    ("iguazu-falls",         "iguazu waterfalls brazil, massive cascades, rainforest mist, no people"),
    # BEACH
    ("trancoso-praia",       "trancoso bahia praia, brazilian wild beach, palm trees, sand dunes, sunset golden hour, no people"),
    ("ibiza-sunset",         "ibiza beach club sunset, white cabanas, mediterranean party vibes, no people"),
    ("tulum-playa",          "tulum mexico playa, white sand, palm trees, boho beach club, no people"),
    ("noronha",              "fernando de noronha brazil, paradise beach, crystal turquoise water, no people"),
    # EDITORIAL
    ("studio-branco",        "pure white seamless studio, soft beauty lighting, fashion editorial empty backdrop"),
    ("studio-concrete",      "concrete studio backdrop, dramatic moody lighting, high fashion editorial empty space"),
    ("garden-botanic",       "lush botanical garden, natural soft light, romantic editorial, no people"),
    ("vintage-hotel",        "vintage hotel interior, 70s aesthetic, mood lighting, retro editorial, no people"),
    # URBAN
    ("rooftop-nyc",          "manhattan rooftop, skyline view, golden hour magic, no people"),
    ("underground-subway",   "NYC subway gritty underground, neon lights, urban grunge editorial, no people"),
    ("avenida-paulista",     "são paulo avenida paulista skyline, brazilian metropolis at night, no people"),
    ("la-venice",            "venice beach california, palm-lined boardwalk, california cool, no people"),
    # LUXURY
    ("yacht-mediterranean",  "luxury super-yacht mediterranean coast, marble deck, champagne lifestyle, no people"),
    ("private-jet",          "private jet cabin interior, cream leather, champagne flute, jetset luxury, no people"),
    ("aman-spa",             "aman resort spa, infinity pool, zen minimal architecture, wellness luxury, no people"),
    ("monaco-penthouse",     "monaco penthouse, floor-to-ceiling windows, mediterranean view, opulent, no people"),
    # COZY
    ("reading-nook",         "cozy reading nook with throw blanket, warm tea, books, autumn light, no people"),
    ("kitchen-sunlight",     "minimalist kitchen morning sunlight, marble countertop, fresh fruits, no people"),
    ("home-office",          "aesthetic home office, plants, macbook, vinyl, productive vibe, no people"),
    # NIGHTLIFE
    ("speakeasy-bar",        "underground speakeasy interior, dim moody lighting, art deco, cocktail glasses, no people"),
    ("rooftop-cocktail",     "rooftop bar at night, city lights, golden ambient lighting, cocktail glasses, no people"),
    ("club-vip",             "exclusive nightclub vip booth, neon, dynamic energy, party luxury, no people"),
    # EXTRAS
    ("kyoto-bamboo",         "kyoto arashiyama bamboo grove, traditional zen serenity path, no people"),
    ("patagonia-mountain",   "patagonia torres del paine mountains, dramatic landscape, adventure no people"),
]


# ═══════════════════════ FREEPIK CLIENT ═══════════════════════

class FP:
    def __init__(self):
        self.idx = 0
        self.client = httpx.AsyncClient(timeout=180, base_url="https://api.freepik.com")

    @property
    def key(self): return KEYS[self.idx]

    def rotate(self): self.idx = (self.idx + 1) % len(KEYS)

    async def gen(self, prompt: str, ratio: str) -> str | None:
        ratio_map = {
            "1:1":  "square_1_1",
            "4:5":  "portrait_4_5",
            "16:9": "widescreen_16_9",
        }
        body = {
            "prompt": prompt + SUFFIX,
            "aspect_ratio": ratio_map[ratio],
            "size": "2k",
        }
        for _ in range(len(KEYS)):
            try:
                r = await self.client.post(
                    "/v1/ai/gemini-2-5-flash-image-preview",
                    headers={"x-freepik-api-key": self.key, "Content-Type": "application/json"},
                    json=body,
                )
                if r.status_code in (429, 402):
                    self.rotate()
                    continue
                if r.status_code >= 400:
                    print(f"  [HTTP {r.status_code}] {r.text[:200]}")
                    return None
                tid = r.json().get("data", {}).get("task_id")
                if not tid:
                    return None
                # Poll — endpoint correto pro modelo Gemini 2.5 Flash
                t0 = time.time()
                while time.time() - t0 < 180:
                    await asyncio.sleep(3)
                    p = await self.client.get(
                        f"/v1/ai/gemini-2-5-flash-image-preview/{tid}",
                        headers={"x-freepik-api-key": self.key},
                    )
                    if p.status_code >= 400: continue
                    d = p.json().get("data", {})
                    s = (d.get("status") or "").upper()
                    if s in ("COMPLETED", "SUCCESS"):
                        gen = d.get("generated") or []
                        if gen:
                            return gen[0] if isinstance(gen, list) else gen
                    if s in ("FAILED", "ERROR"):
                        return None
                return None
            except Exception as e:
                print(f"  [EXC] {e}")
                self.rotate()
        return None

    async def close(self):
        await self.client.aclose()


# ═══════════════════════ EXECUTION ═══════════════════════

async def download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


async def gen_one(fp: FP, group: str, name: str, prompt: str, ratio: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        out_path = OUT_DIR / group / f"{slug(name)}.jpg"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if out_path.exists() and out_path.stat().st_size > 5000:
            print(f"  [SKIP] {group}/{name}")
            return {"name": name, "group": group, "path": str(out_path), "skipped": True}

        print(f"  -> {group}/{name}")
        url = await fp.gen(prompt, ratio)
        if not url:
            print(f"    [ERR] {name} failed")
            return {"name": name, "group": group, "path": None, "error": True}
        try:
            content = await download(url)
            out_path.write_bytes(content)
            kb = len(content) // 1024
            print(f"    [OK] {name} ({kb} KB)")
            return {"name": name, "group": group, "path": str(out_path), "url": url}
        except Exception as e:
            print(f"    [ERR] download: {e}")
            return {"name": name, "group": group, "error": True}


async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fp = FP()
    sem = asyncio.Semaphore(CONCURRENCY)

    tasks: list = []

    print("\n[SPOTLIGHTS] 3 imgs 16:9")
    for name, prompt, ratio in SPOTLIGHTS:
        tasks.append(gen_one(fp, "spotlights", name, prompt, ratio, sem))

    print("\n[PINNED TOOLS] 6 imgs 1:1")
    for name, prompt, ratio in PINNED:
        tasks.append(gen_one(fp, "pinned", name, prompt, ratio, sem))

    print("\n[PRESETS] 30 imgs 4:5")
    for name, prompt in PRESETS:
        tasks.append(gen_one(fp, "presets", name, prompt, "4:5", sem))

    print("\n[WORLDS] 40 imgs 16:9")
    for name, prompt in WORLDS:
        tasks.append(gen_one(fp, "worlds", name, prompt, "16:9", sem))

    t0 = time.time()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    dt = time.time() - t0

    ok = sum(1 for r in results if isinstance(r, dict) and r.get("path"))
    fail = sum(1 for r in results if not isinstance(r, dict) or r.get("error"))
    skip = sum(1 for r in results if isinstance(r, dict) and r.get("skipped"))

    print(f"\n{'='*60}")
    print(f"Total: {dt/60:.1f}min")
    print(f"OK: {ok - skip}")
    print(f"Skipped: {skip}")
    print(f"Failed: {fail}")
    print(f"Output: {OUT_DIR}")

    await fp.close()


if __name__ == "__main__":
    asyncio.run(main())

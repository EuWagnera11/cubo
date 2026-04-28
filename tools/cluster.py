"""Clusterização dos 718 JSONs em ~25-30 templates utilizáveis pelo SaaS.

Estratégia:
1. Normaliza campos free-text (location, framing, style_tag) em categorias macro via keywords.
2. Cada mídia recebe um conjunto de "canonical tags" (location_macro, framing_macro, scene_type).
3. Agrupa mídias por combinação de tags → clusters.
4. Filtra clusters com >= 3 mídias.
5. Gera content_clusters.json (machine-readable) + content_clusters.md (legível).
"""
from __future__ import annotations
import json, pathlib, re
from collections import Counter, defaultdict
from typing import Optional

ANALYSIS_DIR = pathlib.Path("treino/analysis")
OUT_JSON = pathlib.Path("treino/strategy/content_clusters.json")
OUT_MD = pathlib.Path("treino/strategy/content_clusters.md")

# ─────────────────────────────────────────────────────────────────
# Keyword maps — normalizam free-text → categoria macro
# ─────────────────────────────────────────────────────────────────

LOCATION_MACRO = {
    "beach": ["beach", "praia", "ocean", "shore", "sand", "tropical island", "caribbean", "bikini", "seaside"],
    "pool": ["pool", "infinity pool", "poolside", "pool deck", "swimming pool"],
    "yacht": ["yacht", "boat", "marina", "sailing"],
    "café": ["café", "cafe", "coffee shop", "espresso bar", "starbucks", "matcha", "cafeteria", "coffeehouse", "brunch spot"],
    "restaurant": ["restaurant", "trattoria", "bistro", "fine dining", "dinner table", "tapas", "ramen"],
    "rooftop": ["rooftop", "roof terrace", "rooftop bar", "terrace bar", "skybar"],
    "bedroom": ["bedroom", "bed ", "white linen sheets", "boudoir", "in bed", "headboard"],
    "bathroom": ["bathroom", "bathtub", "vanity", "marble bathroom", "shower"],
    "kitchen": ["kitchen", "countertop", "domestic kitchen", "stove"],
    "closet": ["closet", "walk-in closet", "wardrobe", "dressing room"],
    "living_room": ["living room", "couch", "sofa", "lounge", "fireplace"],
    "hotel": ["hotel suite", "hotel room", "hotel lobby", "hotel terrace", "hotel restaurant"],
    "gym": ["gym", "fitness studio", "weight room", "squat rack", "treadmill", "yoga studio"],
    "car": ["car interior", "passenger seat", "driver", "in-car", "car selfie", "car back-seat", "uber"],
    "luxury_car": ["lamborghini", "porsche", "bugatti", "mercedes", "g-wagon"],
    "street_urban": ["street", "sidewalk", "cobblestone", "city street", "urban street", "alley"],
    "city_landmark": ["selarón", "park güell", "casa milà", "casa batlló", "sagrada familia", "louvre", "eiffel", "wembley", "burj khalifa", "pão de açúcar", "cristo", "copacabana", "ipanema"],
    "festival_event": ["feria", "festival", "concert", "fan-cam", "wembley", "oasis", "twenty one pilots", "rock", "vip platform"],
    "conference": ["conference", "podcast set", "step-and-repeat", "expo", "convention", "upscale conf", "potencia digital"],
    "studio": ["studio backdrop", "white seamless cyc", "cyc backdrop", "photo studio", "model-test", "studio set"],
    "bedroom_intimate": ["intimate bedroom", "boudoir", "white linen sheets bed"],
    "spa_salon": ["spa", "salon", "llongueras", "facial", "treatment"],
    "park_garden": ["park", "garden", "jardin", "botanical", "majorelle"],
    "desert": ["desert", "sahara", "dunes", "sonoran", "joshua tree"],
    "mountain": ["mountain", "alpine", "ski", "piste", "patagonia cliff", "snow", "chairlift"],
    "tropical_villa": ["villa", "tropical villa", "mediterranean villa", "tuscan villa", "moroccan riad", "riad"],
    "european_street": ["spanish street", "european cobblestone", "barcelona", "paris", "florence", "saint-tropez"],
    "airport_travel": ["airport", "lavatory", "airplane", "lounge", "private jet", "gulfstream"],
    "podcast_studio": ["podcast", "talking-head", "microphone", "podcast set"],
    "ranch_country": ["ranch", "cowgirl", "wild west", "horse", "stable"],
    "neon_nightclub": ["nightclub", "neon", "club", "bar"],
    "cinema_theater": ["cinema", "theater", "cinema seats", "private cinema"],
    "stadium": ["stadium", "tennis court", "padel court", "football pitch", "madrid open"],
    "graphic_template": ["graphic design template", "no real location", "infographic"],
    "thai_temple": ["thai temple", "wat ", "buddhist", "thailand", "thai"],
}

FRAMING_MACRO = {
    "close_up": ["close-up", "close up", "extreme-close", "headshot", "bust"],
    "medium": ["medium-close", "medium-full", "medium", "mid-thigh", "half-body", "waist-up"],
    "full_body": ["full-body", "full body", "head to feet", "full"],
    "wide": ["wide", "establishing"],
    "pov": ["pov", "point of view", "first person"],
    "back_view": ["back-view", "back view", "from behind"],
}

STYLE_MACRO = {
    "bodycon_brazilian": ["bodycon", "brazilian", "fitted dress", "bandage dress", "tight dress"],
    "athleisure": ["athleisure", "gym set", "workout", "leggings", "sports bra", "nike", "alo yoga", "lululemon"],
    "streetstyle_european": ["streetwear", "streetstyle", "european", "ootd-cozy", "cozy oversized"],
    "editorial_studio": ["editorial", "studio campaign", "high-fashion", "couture"],
    "loungewear_cozy": ["loungewear", "cozy", "pajamas", "robe", "set"],
    "swimwear_bikini": ["bikini", "swimwear", "swim", "thong", "high-leg"],
    "slip_dress_intimate": ["slip dress", "satin slip", "spaghetti strap", "midi slip"],
    "evening_glam": ["sequin", "evening gown", "cocktail", "glam", "going-out"],
    "boho_resort": ["boho", "kaftan", "resort wear", "linen flowy"],
    "leather_rocker": ["leather jacket", "leather corset", "rocker", "rock", "studded"],
    "y2k_fashion": ["y2k", "2000s", "low-rise", "rhinestone"],
    "tailored_suiting": ["blazer", "suit", "pinstripe", "tailored", "power-suit"],
    "festival_traditional": ["flamenca", "kaftan moroccan", "carnival", "feria"],
    "preppy_collegiate": ["preppy", "collegiate", "polo"],
    "business_pro": ["business pro", "office", "blazer"],
    "winter_outerwear": ["puffer", "moncler", "fur coat", "ski jacket", "trench"],
}

INTENT_MACRO = {
    "aspirational": ["aspirational"],
    "sensual": ["sensual"],
    "relatable": ["relatable"],
    "playful": ["playful"],
    "confident": ["confident"],
    "authoritative": ["authoritative"],
    "mysterious": ["mysterious"],
    "vulnerable": ["vulnerable"],
}

FILLER_CONTENT_MACRO = {
    "food_flatlay": ["food", "brunch", "breakfast", "ramen", "pizza", "pasta", "tapas", "cocktail flat"],
    "drinks_cocktails": ["cocktail", "drinks", "wine", "beer", "champagne", "rebujito"],
    "landscape_iconic": ["landmark", "monument", "iconic", "skyline", "vista panoramic", "selarón"],
    "landscape_natural": ["beach landscape", "mountain", "ocean", "sunset", "alpine plateau"],
    "fashion_detail": ["flat-lay", "flatlay", "ootd-detail", "shoes", "bag", "rings", "jewelry"],
    "pet_humanization": ["cat", "dog", "puppy", "pet"],
    "interior_details": ["interior detail", "decor", "vanity", "candle", "vase"],
    "events_venue": ["stadium", "concert venue", "expo venue", "stage"],
    "transport_pov": ["airport", "subway", "robotaxi", "waymo"],
}

# ─────────────────────────────────────────────────────────────────


def match_macro(text: str, mapping: dict[str, list[str]]) -> Optional[str]:
    """Retorna a 1ª categoria macro cujo keyword aparece em text. None se nada bate."""
    if not text: return None
    t = text.lower()
    for macro, keywords in mapping.items():
        for kw in keywords:
            if kw.lower() in t:
                return macro
    return None


def normalize_media(d: dict) -> dict:
    """Extrai canonical tags de 1 JSON."""
    tags = {
        "media_id": d.get("media_id"),
        "media_type": d.get("media_type", "image"),
        "subject_present": d.get("subject_present", True) if "subject_present" in d else (d.get("subject") is not None),
    }

    # Setting
    setting = d.get("setting") or {}
    location_text = (setting.get("location_type") or "") + " " + (setting.get("decor_style") or "")
    tags["location_macro"] = match_macro(location_text, LOCATION_MACRO) or "other"
    tags["indoor_outdoor"] = setting.get("indoor_outdoor", "unknown")
    tags["time_of_day"] = setting.get("time_of_day", "unknown")

    # Subject (só se presente)
    subj = d.get("subject") or {}
    if subj:
        tags["framing_macro"] = match_macro(subj.get("framing", ""), FRAMING_MACRO) or "medium"
        tags["pose_archetype"] = subj.get("pose_archetype", "")
    else:
        tags["framing_macro"] = "no_subject"
        tags["pose_archetype"] = ""

    # Behavior
    beh = d.get("behavior") or {}
    if beh:
        tags["intent_macro"] = match_macro(beh.get("intent_signal", ""), INTENT_MACRO) or "aspirational"
    else:
        tags["intent_macro"] = "filler"

    # Wardrobe
    wb = d.get("wardrobe") or {}
    if wb:
        style_text = wb.get("style_tag", "") + " " + (wb.get("outfit_type") or "")
        tags["style_macro"] = match_macro(style_text, STYLE_MACRO) or "general"
    else:
        tags["style_macro"] = "no_subject"

    # Filler categorization (sem pessoa)
    if not tags["subject_present"]:
        cat = d.get("content_category", "")
        full_text = cat + " " + location_text
        tags["filler_type"] = match_macro(full_text, FILLER_CONTENT_MACRO) or "other"

    # Video format
    if tags["media_type"] == "video":
        vga = d.get("video_global_analysis") or {}
        tags["video_format"] = vga.get("format_label", "unknown")

    # Engagement
    eh = d.get("engagement_hooks") or {}
    tags["primary_hook"] = eh.get("primary_hook", "")
    tags["why_it_works"] = eh.get("why_it_works", "")

    # Automation
    auto = d.get("automation_replicability") or {}
    tags["complexity"] = auto.get("complexity", "medium")
    tags["reproducible"] = auto.get("reproducible_with_pipeline", True)

    # Aspect
    fmt = d.get("format") or {}
    tags["aspect"] = fmt.get("aspect") or d.get("aspect_estimate", "4:5")

    return tags


def cluster_key(t: dict) -> str:
    """Define a chave do cluster pra cada mídia."""
    if not t["subject_present"]:
        return f"FILLER::{t.get('filler_type', 'other')}"

    if t["media_type"] == "video":
        # Videos: clusterizar por format
        fmt = t.get("video_format", "unknown").lower()
        for keyword, macro in [
            ("talking", "talking_head"),
            ("q&a", "talking_head"),
            ("vlog", "travel_vlog"),
            ("travel", "travel_vlog"),
            ("packing", "packing_vlog"),
            ("ootd", "outfit_reveal"),
            ("outfit", "outfit_reveal"),
            ("grwm", "grwm_routine"),
            ("skincare", "grwm_routine"),
            ("mirror", "mirror_selfie_loop"),
            ("car", "in_car_loop"),
            ("dance", "dance_lookbook"),
            ("brand", "brand_ad"),
            ("manifesto", "talking_head"),
            ("origin", "talking_head"),
            ("lookbook", "outfit_reveal"),
            ("thirst-trap", "thirst_trap_loop"),
            ("loop", "vibe_loop"),
            ("photo-dump", "photo_dump"),
            ("collage", "photo_dump"),
            ("cinematic", "cinematic_film"),
        ]:
            if keyword in fmt:
                return f"VIDEO::{macro}"
        return f"VIDEO::other"

    # Imagens com pessoa: cluster por location + framing
    loc = t["location_macro"]
    framing = t["framing_macro"]
    return f"IMG::{loc}::{framing}"


def main():
    jsons = sorted([p for p in ANALYSIS_DIR.glob("*.json") if not p.stem.startswith("_")])
    print(f"Loading {len(jsons)} JSONs...")

    all_normalized = []
    errors = 0
    for p in jsons:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            all_normalized.append(normalize_media(d))
        except Exception as e:
            errors += 1
    print(f"Normalized: {len(all_normalized)} ({errors} errors)")

    # Cluster
    clusters = defaultdict(list)
    for t in all_normalized:
        key = cluster_key(t)
        clusters[key].append(t)

    # Filter: clusters com >= 3 mídias
    sized = [(k, v) for k, v in clusters.items() if len(v) >= 3]
    sized.sort(key=lambda x: -len(x[1]))

    print(f"\nClusters totais: {len(clusters)}")
    print(f"Clusters com >= 3 mídias: {len(sized)}")
    print(f"\nTop clusters:")
    for k, v in sized[:40]:
        print(f"  {len(v):4d}  {k}")

    # Build clusters JSON
    clusters_data = []
    for cid, (key, items) in enumerate(sized, 1):
        type_, *parts = key.split("::")
        category = type_.lower()

        # Pick best example (highest realism, easy complexity)
        example = items[0]
        for item in items:
            if item.get("complexity") == "easy" and item.get("reproducible"):
                example = item
                break

        # Build template entry
        if type_ == "FILLER":
            name = f"Filler — {parts[0].replace('_', ' ').title()}"
            description = f"Conteúdo lifestyle sem pessoa. Tipo: {parts[0]}."
        elif type_ == "VIDEO":
            name = f"Video — {parts[0].replace('_', ' ').title()}"
            description = f"Formato vídeo: {parts[0]}."
        else:
            loc, framing = parts
            name = f"{loc.replace('_', ' ').title()} — {framing.replace('_', ' ').title()}"
            description = f"Modelo em {loc.replace('_', ' ')}, framing {framing.replace('_', ' ')}."

        # Tags agregados
        intent_counter = Counter(i.get("intent_macro") for i in items if i.get("intent_macro"))
        style_counter = Counter(i.get("style_macro") for i in items if i.get("style_macro"))
        time_counter = Counter(i.get("time_of_day") for i in items if i.get("time_of_day"))
        complexity_counter = Counter(i.get("complexity") for i in items if i.get("complexity"))

        clusters_data.append({
            "id": f"tpl_{cid:03d}",
            "name": name,
            "category": category,
            "description": description,
            "size": len(items),
            "media_ids": [i["media_id"] for i in items[:20]],   # primeiros 20 ids exemplo
            "tags": {
                "type": type_,
                "details": parts,
            },
            "stats": {
                "top_intents": dict(intent_counter.most_common(3)),
                "top_styles": dict(style_counter.most_common(3)),
                "top_times": dict(time_counter.most_common(3)),
                "complexity_distribution": dict(complexity_counter),
            },
            "example_media": {
                "media_id": example["media_id"],
                "pose_archetype": example.get("pose_archetype", ""),
                "primary_hook": example.get("primary_hook", ""),
                "why_it_works": example.get("why_it_works", ""),
                "aspect": example.get("aspect", "4:5"),
            },
        })

    # Save JSON
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "total_jsons_analyzed": len(all_normalized),
            "total_clusters": len(clusters_data),
            "clusters": clusters_data,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Saved JSON: {OUT_JSON}")

    # Build Markdown
    md = ["# Content Clusters — 718 mídias agrupadas em templates",
          "",
          f"**Total de mídias analisadas:** {len(all_normalized)}",
          f"**Total de clusters identificados:** {len(clusters_data)}",
          f"**Clusters com 3+ mídias** (relevantes pra templates):",
          "",
          "Estes clusters viram **templates do SaaS Cubo**. Cada um já vem com:",
          "- Categoria/tipo",
          "- Stats (top intents, styles, times)",
          "- Exemplo representativo",
          "- IDs das mídias do dataset que pertencem ao cluster",
          "",
          "---",
          ""]

    # Group by category for readability
    by_cat = defaultdict(list)
    for c in clusters_data:
        by_cat[c["tags"]["type"]].append(c)

    for cat in ["IMG", "FILLER", "VIDEO"]:
        if cat not in by_cat: continue
        cat_label = {"IMG": "📸 Imagens com modelo",
                     "FILLER": "🍽️ Filler (sem pessoa, humanização)",
                     "VIDEO": "🎬 Vídeos"}[cat]
        md.append(f"## {cat_label}")
        md.append("")

        for c in by_cat[cat]:
            md.append(f"### {c['id']} — {c['name']}")
            md.append(f"**Categoria:** {c['category']}")
            md.append(f"**Tamanho:** {c['size']} mídias")
            md.append(f"**Descrição:** {c['description']}")
            md.append("")
            md.append(f"**Stats:**")
            stats = c['stats']
            if stats['top_intents']:
                md.append(f"- Intents: {', '.join(f'{k} ({v})' for k, v in stats['top_intents'].items())}")
            if stats['top_styles']:
                md.append(f"- Styles: {', '.join(f'{k} ({v})' for k, v in stats['top_styles'].items())}")
            if stats['top_times']:
                md.append(f"- Times: {', '.join(f'{k} ({v})' for k, v in stats['top_times'].items())}")
            if stats['complexity_distribution']:
                md.append(f"- Complexity: {', '.join(f'{k} ({v})' for k, v in stats['complexity_distribution'].items())}")
            md.append("")
            ex = c['example_media']
            if ex['pose_archetype']:
                md.append(f"**Exemplo representativo (`{ex['media_id']}`):**")
                md.append(f"- Pose: {ex['pose_archetype']}")
                if ex['primary_hook']:
                    md.append(f"- Hook: {ex['primary_hook']}")
                if ex['why_it_works']:
                    md.append(f"- Why works: {ex['why_it_works'][:200]}")
                md.append(f"- Aspect: {ex['aspect']}")
            md.append("")
            md.append("---")
            md.append("")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"[OK] Saved MD: {OUT_MD}")


if __name__ == "__main__":
    main()

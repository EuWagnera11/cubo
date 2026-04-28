"""Pipeline: video → frame → swap → motion control com a modelo de IA.

Para cada vídeo de referência (motion source):
  1. Download → kling_tmp/videos/video_N.mp4
  2. Extrai 1º frame → kling_tmp/frames/frame_N.png
  3. Nano-banana: troca a pessoa pela modelo → kling_out/fotos/foto_N.png
  4. Upload do vídeo original num CDN público (catbox.moe / tmpfiles.org)
  5. Kling V3 Motion Control Pro: foto + vídeo → kling_out/finals/final_N.mp4
     (V2.6 fallback se V3 estourar daily cap)

Pré-requisitos:
  - Variáveis de ambiente: FREEPIK_API_KEY ou FREEPIK_API_KEYS=key1,key2,...
  - Arquivos LOCAIS na mesma pasta:
      modelo_ref.png   — foto full-body da modelo (referência principal)
      modelo_face.png  — recorte só do rosto (opcional, mas o pipeline original usa)
  - kling_folder_list.json — lista [(file_id, name), ...] dos vídeos no Drive
"""
from __future__ import annotations
import base64, json, os, pathlib, subprocess, sys, time, urllib.request, urllib.error
import cv2

API_KEYS = [k.strip() for k in os.environ.get("FREEPIK_API_KEYS", os.environ.get("FREEPIK_API_KEY", "")).split(",") if k.strip()]
if not API_KEYS: sys.exit(2)
API_KEY = API_KEYS[0]  # default for nano-banana / general use
_key_state = {k: {"v3_exhausted": False, "v26_exhausted": False, "nano_exhausted": False} for k in API_KEYS}

def pick_key(category="nano"):
    """Returns first available key for category (nano | v3 | v26). None if all exhausted."""
    for k in API_KEYS:
        if not _key_state[k][f"{category}_exhausted"]:
            return k
    return None

def mark_exhausted(key, category):
    _key_state[key][f"{category}_exhausted"] = True
    print(f"  KEY exhausted: ...{key[-6:]} category={category}")

NANO_POST = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro"
NANO_STATUS = "https://api.freepik.com/v1/ai/text-to-image/nano-banana-pro/{tid}"
KLING_POST = "https://api.freepik.com/v1/ai/video/kling-v3-motion-control-pro"
KLING_STATUS = "https://api.freepik.com/v1/ai/video/kling-v3-motion-control-pro/{tid}"
KLING_FALLBACK_POST = "https://api.freepik.com/v1/ai/video/kling-v2-6-motion-control-pro"
KLING_FALLBACK_STATUS = "https://api.freepik.com/v1/ai/image-to-video/kling-v2-6/{tid}"

HERE = pathlib.Path(__file__).parent
OUT = HERE / "kling_out"
TMP = HERE / "kling_tmp"
STATE_PATH = HERE / "kling_state.json"

MODEL_FULL = HERE / "modelo_ref.png"
MODEL_FACE = HERE / "modelo_face.png"

# TODO: ajustar prompt de swap conforme a nova modelo (idade/etnia/restrições)
SWAP_PROMPT = (
    "Place the woman from the SECOND reference into the exact scene, setting and pose shown in the FIRST reference. "
    "Match the lighting, atmosphere, position, color grading, clothes of first reference, framing and composition of the first image perfectly. "
    "Preserve the woman's facial features, hair, body shape and overall identity exactly from the second image. "
    "Photorealistic editorial portrait, natural skin texture, sharp focus, professional photography."
)


def http_json(method, url, body=None, retries=3, key=None, category=None):
    """If key is None, uses API_KEY (default). If category given, rotates through pool on 429."""
    data = json.dumps(body).encode("utf-8") if body else None
    last = None
    keys_to_try = [key] if key else (API_KEYS if category else [API_KEY])
    for k in keys_to_try:
        if category and _key_state.get(k, {}).get(f"{category}_exhausted"): continue
        for i in range(retries):
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("x-freepik-api-key", k)
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body_txt = e.read().decode("utf-8", "replace")
                last = RuntimeError(f"HTTP {e.code}: {body_txt[:300]}")
                if e.code == 429 and category:
                    mark_exhausted(k, category)
                    break  # try next key
                if e.code in (500, 502, 503, 504):
                    time.sleep(2 ** i * 3); continue
                raise last
            except (urllib.error.URLError, TimeoutError) as e:
                last = e; time.sleep(2 ** i * 3)
    if last is None:
        raise RuntimeError(f"HTTP 429: all {category} keys exhausted")
    raise last


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:
        f.write(r.read())


def upload_public(local_path: pathlib.Path) -> str:
    """Upload a file to a public temp host and return the public URL.
    Tries catbox.moe first, falls back to tmpfiles.org."""
    # 1) catbox.moe
    r = subprocess.run(
        ["curl", "-sS", "-F", "reqtype=fileupload", "-F", f"fileToUpload=@{local_path}",
         "https://catbox.moe/user/api.php"],
        capture_output=True, text=True, timeout=600
    )
    out = (r.stdout or "").strip()
    if out.startswith("http"):
        return out
    # 2) tmpfiles.org
    r = subprocess.run(
        ["curl", "-sS", "-F", f"file=@{local_path}", "https://tmpfiles.org/api/v1/upload"],
        capture_output=True, text=True, timeout=600
    )
    try:
        d = json.loads(r.stdout)
        url = d.get("data", {}).get("url", "")
        if url.startswith("http"):
            # tmpfiles returns an HTML viewer URL — convert to direct
            return url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
    except Exception:
        pass
    raise RuntimeError(f"upload failed. catbox stdout={out[:200]} tmpfiles stdout={r.stdout[:200]}")


def extract_first_frame(video: pathlib.Path, out_png: pathlib.Path):
    cap = cv2.VideoCapture(str(video))
    ok, frame = cap.read()
    cap.release()
    if not ok: raise RuntimeError(f"can't read first frame of {video}")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_png), frame, [cv2.IMWRITE_PNG_COMPRESSION, 5])


def nano_swap(frame_path: pathlib.Path, max_attempts=4) -> tuple[str, bytes]:
    """Returns (signed_freepik_url, downloaded_bytes)."""
    img = cv2.imread(str(frame_path))
    h, w = img.shape[:2]
    crop = img[: int(h * 0.65), :]
    nw = min(480, crop.shape[1])
    nh = int(crop.shape[0] * nw / crop.shape[1])
    safe = cv2.resize(crop, (nw, nh))
    safe_path = frame_path.with_name(frame_path.stem + "_safe.png")
    cv2.imwrite(str(safe_path), safe)

    scene_b64 = base64.b64encode(safe_path.read_bytes()).decode("ascii")
    body = {
        "prompt": SWAP_PROMPT,
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "reference_images": [
            {"image": scene_b64,                                                "mime_type": "image/png", "text": "FIRST reference: scene, setting, pose, lighting, background, framing"},
            {"image": base64.b64encode(MODEL_FULL.read_bytes()).decode("ascii"), "mime_type": "image/png", "text": "SECOND reference: the woman whose facial features, hair, body shape and identity must be preserved"},
        ],
    }
    last_err = None
    for attempt in range(max_attempts):
        try:
            tid = http_json("POST", NANO_POST, body, category="nano")["data"]["task_id"]
            delay = 4.0
            deadline = time.time() + 600
            while time.time() < deadline:
                time.sleep(delay)
                r = http_json("GET", NANO_STATUS.format(tid=tid), category="nano")
                st = r.get("data", {}).get("status")
                if st == "COMPLETED":
                    imgs = r["data"].get("generated", []) or []
                    if not imgs: break
                    url = imgs[0]
                    with urllib.request.urlopen(url, timeout=180) as rr:
                        return url, rr.read()
                if st == "FAILED": break
                delay = min(delay * 1.15, 10.0)
        except Exception as e:
            last_err = e
            print(f"    swap attempt {attempt+1}: {e}")
    raise RuntimeError(f"nano-banana swap failed after {max_attempts} attempts: {last_err}")


def kling_motion(image_url: str, video_url: str, timeout_s=900) -> str:
    """Returns final video URL. V3 Motion Control Pro primary, V2.6 fallback if 429 daily cap."""
    body = {
        "image_url": image_url,
        "video_url": video_url,
        "character_orientation": "video",
        "cfg_scale": 0.55,
        "prompt": (
            "Generate clean photorealistic motion video. Anatomy must be perfectly clean: "
            "exactly two arms, two legs, five fingers per hand, one head, no duplicated/extra limbs, "
            "no morphing, no body warping. Movement follows natural human biomechanics — smooth joint articulation, "
            "no impossible angles. Preserve facial features stable across all frames, no face flicker. "
            "Identity locked to the input image."
        ),
        "negative_prompt": (
            "extra limbs, duplicated arms, duplicated legs, three arms, three legs, "
            "missing fingers, extra fingers, fused fingers, deformed hand, twisted body, "
            "morphing limbs, body warping, jelly arms, bent joints in impossible angle, "
            "face flicker, identity drift, blurry face, cross-eyed, strabismus, "
            "low quality, glitchy artifacts, distortion."
        ),
    }
    # try V3 with multi-key pool — track which key created the task
    used_key = None
    status_url = None
    for k in API_KEYS:
        if _key_state[k]["v3_exhausted"]: continue
        try:
            tid = http_json("POST", KLING_POST, body, key=k)["data"]["task_id"]
            used_key = k
            status_url = KLING_STATUS
            print(f"    kling V3 task_id={tid} (key=...{k[-6:]})")
            break
        except RuntimeError as e:
            if "429" in str(e):
                mark_exhausted(k, "v3")
                continue
            raise
    if used_key is None:
        # all V3 exhausted — fallback V2.6
        print(f"    V3 all keys exhausted, trying V2.6 fallback...")
        for k in API_KEYS:
            if _key_state[k]["v26_exhausted"]: continue
            try:
                tid = http_json("POST", KLING_FALLBACK_POST, body, key=k)["data"]["task_id"]
                used_key = k
                status_url = KLING_FALLBACK_STATUS
                print(f"    kling V2.6 task_id={tid} (key=...{k[-6:]})")
                break
            except RuntimeError as e:
                if "429" in str(e):
                    mark_exhausted(k, "v26")
                    continue
                raise
        if used_key is None:
            raise RuntimeError("HTTP 429: all v3+v26 keys exhausted")
    delay = 8.0
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(delay)
        r = http_json("GET", status_url.format(tid=tid), key=used_key)
        st = r.get("data", {}).get("status")
        print(f"    kling: {st}")
        if st == "COMPLETED":
            vids = r["data"].get("generated", []) or []
            if not vids: raise RuntimeError("no video generated")
            return vids[0]
        if st == "FAILED": raise RuntimeError(f"kling failed: {json.dumps(r)[:300]}")
        delay = min(delay * 1.1, 15.0)
    raise TimeoutError("kling timeout")


def load_state():
    if STATE_PATH.exists(): return json.loads(STATE_PATH.read_text())
    return {"items": {}}


def save_state(s): STATE_PATH.write_text(json.dumps(s, indent=2))


def process(num: int, fid: str, original_name: str, state):
    key = fid
    item = state["items"].setdefault(key, {"num": num, "name": original_name, "stages": {}})
    if num != item["num"]:
        item["num"] = num

    video_path = TMP / "videos" / f"video_{num}.mp4"
    frame_path = TMP / "frames" / f"frame_{num}.png"
    foto_path  = OUT / "fotos" / f"foto_{num}.png"
    final_path = OUT / "finals" / f"final_{num}.mp4"

    # 1. download
    if "downloaded" not in item["stages"]:
        print(f"[{num}] downloading {original_name}")
        download(f"https://drive.google.com/uc?export=download&id={fid}", video_path)
        # Drive may serve HTML for big videos — sniff
        head = video_path.read_bytes()[:64]
        if head.startswith(b"<!DOCTYPE") or head.startswith(b"<html"):
            # large file confirmation page — try alt URL
            video_path.unlink()
            download(f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=yes", video_path)
        item["stages"]["downloaded"] = str(video_path)
        save_state(state)

    # 2. extract first frame + check 9:16 aspect
    if "frame" not in item["stages"]:
        print(f"[{num}] extracting first frame")
        extract_first_frame(video_path, frame_path)
        # validate aspect ratio (must be ~9:16, vertical)
        cap = cv2.VideoCapture(str(video_path))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        ratio = w / h if h else 0
        target = 9 / 16  # 0.5625
        if not (0.50 <= ratio <= 0.62):
            item["stages"]["skipped"] = f"aspect {w}x{h} ratio={ratio:.3f} not 9:16"
            save_state(state)
            print(f"[{num}] SKIP — aspect not 9:16 ({w}x{h})")
            return
        item["stages"]["frame"] = str(frame_path)
        save_state(state)

    # 3. nano-banana swap
    if "foto" not in item["stages"]:
        print(f"[{num}] nano-banana swap")
        url, raw = nano_swap(frame_path)
        foto_path.parent.mkdir(parents=True, exist_ok=True)
        foto_path.write_bytes(raw)
        item["stages"]["foto"] = str(foto_path)
        item["stages"]["foto_url"] = url
        save_state(state)

    # PHASE GATE: 'fotos' phase stops here
    if os.environ.get("_KLING_PIPELINE_PHASE") == "fotos":
        print(f"[{num}] DONE-FOTO")
        return

    # 3.5. ensure foto_url exists (Freepik signed URLs expire in 24h)
    # if foto_url missing or expired, re-upload to catbox
    if "foto_public_url" not in item["stages"]:
        print(f"[{num}] uploading foto to public host (for Kling)")
        item["stages"]["foto_public_url"] = upload_public(foto_path)
        save_state(state)
        print(f"  ->{item['stages']['foto_public_url']}")

    # 4. upload video to public host
    if "video_url" not in item["stages"]:
        print(f"[{num}] uploading video to public host")
        public_url = upload_public(video_path)
        item["stages"]["video_url"] = public_url
        save_state(state)
        print(f"  ->{public_url}")

    # 5. kling motion control
    if "final" not in item["stages"]:
        print(f"[{num}] kling motion control")
        # use public URL (catbox) since freepik signed URL may have expired
        img_url = item["stages"].get("foto_public_url") or item["stages"].get("foto_url")
        final_url = kling_motion(img_url, item["stages"]["video_url"])
        # download para arquivo temporário
        raw_path = final_path.with_name(final_path.stem + "_raw" + final_path.suffix)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(final_url, timeout=600) as r, open(raw_path, "wb") as f:
            f.write(r.read())
        # re-encoda para 720x1280 (9:16 720p) com áudio AAC silencioso (necessário pra IG)
        try:
            import imageio_ffmpeg, subprocess
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = [
                ffmpeg, "-y",
                "-i", str(raw_path),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-filter:v", "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black",
                "-map", "0:v", "-map", "1:a",
                "-r", "30",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-b:v", "3M", "-profile:v", "high",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-movflags", "+faststart",
                str(final_path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"  ffmpeg failed, keeping raw: {res.stderr[-300:]}")
                raw_path.replace(final_path)
            else:
                raw_path.unlink()
        except Exception as e:
            print(f"  re-encode skipped ({e}); keeping raw")
            raw_path.replace(final_path)
        item["stages"]["final"] = str(final_path)
        item["stages"]["final_url"] = final_url
        save_state(state)
        print(f"  ->{final_path}")

    print(f"[{num}] DONE")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["fotos", "videos", "all"], default="all",
                    help="fotos: para após swap; videos: só completa o que falta; all: tudo")
    ap.add_argument("--from", dest="from_num", type=int, default=1, help="processar a partir deste num (default 1)")
    ap.add_argument("--to", dest="to_num", type=int, default=999, help="processar até este num (default tudo)")
    args = ap.parse_args()
    os.environ["_KLING_PIPELINE_PHASE"] = args.phase

    OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)

    folder_list = json.loads((HERE / "kling_folder_list.json").read_text(encoding="utf-8"))
    state = load_state()
    print(f"phase={args.phase} range=[{args.from_num}..{args.to_num}]")
    for i, (fid, name) in enumerate(folder_list, start=1):
        if i < args.from_num or i > args.to_num: continue
        try:
            process(i, fid, name, state)
        except Exception as e:
            print(f"[{i}] ERROR: {e}")


if __name__ == "__main__":
    sys.exit(main() or 0)

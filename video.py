"""
Faceless vertical Short, "editor" style:
  * har scene mein 1-3 photos (Pexels), slow zoom/pan, hard cuts
  * dark overlay + header card (label + title), optional big stat, link pill, disclaimer
  * bade word-pop captions (important words yellow/green)
  * voice: Gemini TTS (realistic) -> fallback edge-tts
  * audio mastering (loudnorm ~ -14 LUFS) + optional soft background pad
"""
import asyncio
import base64
import os
import random
import re
import subprocess
import tempfile
import time

import requests
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30

GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
TTS_MODELS = []
for _m in [os.environ.get("TTS_MODEL") or "gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"]:
    if _m not in TTS_MODELS:
        TTS_MODELS.append(_m)
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Puck")
GEMINI_STYLE = os.environ.get(
    "GEMINI_STYLE", "energetic, confident, natural Hinglish, brisk YouTube Shorts pace"
)
EDGE_VOICE_HI = os.environ.get("TTS_VOICE_HI", "hi-IN-MadhurNeural")
EDGE_VOICE_EN = os.environ.get("TTS_VOICE", "en-IN-PrabhatNeural")
EDGE_RATE = os.environ.get("TTS_RATE", "+8%")

PEXELS_KEY = (os.environ.get("PEXELS_API_KEY") or "").strip()
BG_MUSIC = os.environ.get("BG_MUSIC", "0") == "1"
MUSIC_VOL = float(os.environ.get("MUSIC_VOL", "0.04"))
MAX_MB = float(os.environ.get("MAX_VIDEO_MB", "46"))
LINK_PILL = os.environ.get("LINK_PILL_TEXT", "TELEGRAM  |  LINK DESCRIPTION MEIN")
FOOTER = "Not financial advice  |  Crypto risky hai  |  DYOR"

YELLOW, GREEN, WHITE = (255, 214, 10), (80, 235, 130), (255, 255, 255)
UA = {"User-Agent": "Mozilla/5.0 (compatible; CryptoBot/2.0)"}


# ----------------------------------------------------------------- helpers
def log(msg):
    print(msg, flush=True)


def clean_text(t):
    """Emoji aur markdown hataye; Devanagari (matras) safe rehta hai."""
    t = t or ""
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]", "", t)
    t = re.sub(r"[*_`#\[\]{}<>|~^\\]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def has_devanagari(t):
    return bool(re.search(r"[\u0900-\u097F]", t or ""))


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} fail: {r.stderr[-600:]}")
    return r.stdout


def _duration(path):
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.strip())


# ------------------------------------------------------------------- fonts
def _find_fonts():
    """(pil_font_path, ass_font_name). Montserrat mile to wahi, warna DejaVu."""
    try:
        out = subprocess.run(["fc-list", ":", "file", "family", "style"], capture_output=True, text=True).stdout
    except Exception:
        out = ""
    best = None
    for line in out.splitlines():
        low = line.lower()
        if "montserrat" in low and "italic" not in low:
            score = 3 if "extrabold" in low else (2 if "bold" in low else 0)
            if score and (best is None or score > best[0]):
                best = (score, line.split(":")[0].strip(), "Montserrat ExtraBold" if score == 3 else "Montserrat")
    if best:
        return best[1], best[2]
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if os.path.exists(p):
            return p, "DejaVu Sans"
    return None, "DejaVu Sans"


FONT_PATH, ASS_FONT = _find_fonts()


def _font(size):
    if FONT_PATH:
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _shadow_text(d, xy, text, font, fill, off=4):
    x, y = xy
    d.text((x + off, y + off), text, font=font, fill=(0, 0, 0, 190))
    d.text((x, y), text, font=font, fill=fill)


# ---------------------------------------------------------------- overlays
def make_overlay(path, scene):
    """Transparent PNG: gradients + header card + stat + link pill + footer."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(0, 700):  # top shade
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(175 * (1 - y / 700))))
    for y in range(900, H):  # bottom shade
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(215 * ((y - 900) / (H - 900)))))

    # --- header card (label pill + title)
    label = clean_text(scene.get("label", "")).upper()[:26] or "CRYPTO UPDATE"
    title = clean_text(scene.get("title", "")).upper() or "UPDATE"
    size = 84
    while size > 44:
        tf = _font(size)
        lines = _wrap(d, title, tf, 840)
        if len(lines) <= 2:
            break
        size -= 6
    line_h = int(size * 1.22)
    card_top = 190
    card_h = 70 + len(lines) * line_h + 36
    d.rounded_rectangle([70, card_top, W - 70, card_top + card_h], radius=40,
                        fill=(8, 10, 18, 214), outline=(255, 255, 255, 55), width=2)
    pf = _font(36)
    pw = int(d.textlength(label, font=pf)) + 70
    px0 = (W - pw) // 2
    d.rounded_rectangle([px0, card_top - 32, px0 + pw, card_top + 32], radius=32, fill=YELLOW + (255,))
    d.text((px0 + 35, card_top - 21), label, font=pf, fill=(15, 15, 15, 255))
    y = card_top + 58
    for ln in lines:
        w = d.textlength(ln, font=tf)
        d.text(((W - w) / 2, y), ln, font=tf, fill=WHITE + (255,))
        y += line_h

    # --- optional big stat
    stat = clean_text(scene.get("stat", ""))[:14]
    if stat:
        slabel = clean_text(scene.get("stat_label", "")).upper()[:34]
        sz = 230
        while sz > 90 and d.textlength(stat, font=_font(sz)) > 900:
            sz -= 10
        sf = _font(sz)
        sy = 860
        if slabel:
            lf = _font(46)
            _shadow_text(d, ((W - d.textlength(slabel, font=lf)) / 2, sy - 90), slabel, lf, (215, 215, 235, 255), 3)
        _shadow_text(d, ((W - d.textlength(stat, font=sf)) / 2, sy), stat, sf, GREEN + (255,), 6)

    # --- link pill + footer
    lf = _font(34)
    tw = d.textlength(LINK_PILL, font=lf)
    x0 = (W - tw) / 2 - 36
    d.rounded_rectangle([x0, 1545, x0 + tw + 72, 1615], radius=35, fill=(0, 0, 0, 175),
                        outline=(255, 255, 255, 90), width=2)
    d.text((x0 + 36, 1562), LINK_PILL, font=lf, fill=WHITE + (255,))
    ff = _font(30)
    d.text(((W - d.textlength(FOOTER, font=ff)) / 2, 1800), FOOTER, font=ff, fill=(200, 200, 222, 235))
    img.save(path)


def make_gradient_photo(path, idx):
    """Pexels na mile to dark textured gradient (kabhi fail nahi hota)."""
    palettes = [((8, 14, 40), (40, 20, 80)), ((6, 28, 40), (10, 70, 80)),
                ((30, 12, 30), (90, 30, 60)), ((10, 20, 15), (30, 80, 55))]
    a, b = palettes[idx % len(palettes)]
    img = Image.new("RGB", (1080, 1920))
    d = ImageDraw.Draw(img)
    for y in range(1920):
        k = y / 1920
        d.line([(0, y), (1080, y)], fill=tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3)))
    rnd = random.Random(idx)
    for _ in range(40):  # soft bokeh circles
        x, y, r = rnd.randint(0, 1080), rnd.randint(0, 1920), rnd.randint(60, 220)
        c = tuple(min(255, int(b[i] + 40)) for i in range(3))
        d.ellipse([x - r, y - r, x + r, y + r], outline=c, width=2)
    img.save(path, quality=92)


# ------------------------------------------------------------------ photos
def _download(url, path):
    with requests.get(url, headers=UA, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)


def fetch_photos(queries, need, workdir, used):
    """Pexels se portrait photos. Kam mile to jo mile wahi (baaki gradient)."""
    paths = []
    if not PEXELS_KEY:
        return paths
    for q in queries:
        if len(paths) >= need:
            break
        try:
            r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": PEXELS_KEY},
                             params={"query": q, "orientation": "portrait", "size": "large", "per_page": 12},
                             timeout=25)
            r.raise_for_status()
            for p in r.json().get("photos", []):
                if p["id"] in used:
                    continue
                src = p.get("src", {})
                url = src.get("large2x") or src.get("large") or src.get("original")
                if not url:
                    continue
                fp = os.path.join(workdir, f"photo_{p['id']}.jpg")
                _download(url, fp)
                used.add(p["id"])
                paths.append(fp)
                break
        except Exception as e:
            log(f"Pexels fail ({q}): {e}")
    return paths


# ------------------------------------------------------------------- voice
def gemini_tts(text, path, model):
    from google import genai

    client = genai.Client(api_key=GEMINI_API_KEY)
    last = None
    for attempt in range(3):
        try:
            it = client.interactions.create(
                model=model,
                input=[{"type": "user_input", "content": [{
                    "type": "text", "text": text,
                    "annotations": [{"type": "speech_metadata", "style": GEMINI_STYLE}],
                }]}],
                response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": GEMINI_VOICE}]},
            )
            with open(path, "wb") as f:
                f.write(base64.b64decode(it.output_audio.data))
            return
        except Exception as e:
            last = e
            msg = str(e).lower()
            if any(k in msg for k in ("429", "resource_exhausted", "quota", "rate", "503", "unavailable", "overloaded")):
                wait = 15 * (attempt + 1)
                log(f"Gemini TTS rate/limit, {wait}s ruk raha hoon...")
                time.sleep(wait)
                continue
            raise
    raise last


def edge_tts_save(text, path):
    import edge_tts

    voice = EDGE_VOICE_HI if has_devanagari(text) else EDGE_VOICE_EN
    asyncio.run(edge_tts.Communicate(text, voice, rate=EDGE_RATE).save(path))


def synth_all(scenes, tmp):
    """Poori video ek hi engine se (voice mix na ho). Gemini -> edge fallback."""
    engines = []
    if GEMINI_API_KEY:
        engines += [("gemini", m) for m in TTS_MODELS]
    engines.append(("edge", None))
    last = None
    for kind, model in engines:
        try:
            out = []
            for i, sc in enumerate(scenes):
                text = clean_text(sc.get("speech") or sc.get("caption") or "")
                p = os.path.join(tmp, f"voice{i}_{kind}.{'wav' if kind == 'gemini' else 'mp3'}")
                if kind == "gemini":
                    gemini_tts(text, p, model)
                    time.sleep(1.0)
                else:
                    edge_tts_save(text, p)
                out.append(p)
            log(f"Voice engine: {kind} {model or ''}")
            return out
        except Exception as e:
            log(f"TTS engine fail ({kind} {model}): {str(e)[:200]}")
            last = e
    raise RuntimeError(f"Koi voice engine nahi chala: {last}")


# ---------------------------------------------------------------- captions
def _ts(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _ass_color(rgb):
    r, g, b = rgb
    return f"&H00{b:02X}{g:02X}{r:02X}&"


def write_ass(path, caption, emphasis, dur):
    words = clean_text(caption).upper().split()
    emph = {re.sub(r"\W", "", e.upper()) for e in (emphasis or []) if e}
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 3 or (len(cur) == 2 and sum(len(x) for x in cur) > 14):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    total_chars = sum(len(" ".join(g)) for g in groups) or 1
    span = max(dur - 0.25, 0.5)
    t, events = 0.05, []
    for g in groups:
        d = span * len(" ".join(g)) / total_chars
        parts = []
        for w in g:
            key = re.sub(r"\W", "", w)
            if any(c in w for c in "$%₹") or re.search(r"\d", w):
                parts.append("{\\c%s}%s{\\c%s}" % (_ass_color(GREEN), w, _ass_color(WHITE)))
            elif key in emph:
                parts.append("{\\c%s}%s{\\c%s}" % (_ass_color(YELLOW), w, _ass_color(WHITE)))
            else:
                parts.append(w)
        text = "{\\fscx86\\fscy86\\t(0,90,\\fscx100\\fscy100)}" + " ".join(parts)
        events.append(f"Dialogue: 0,{_ts(t)},{_ts(t + d)},Cap,,0,0,0,,{text}")
        t += d
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,{ASS_FONT},96,&H00FFFFFF&,&H000000FF&,&H00000000&,&H80000000&,1,0,0,0,100,100,0,0,1,7,3,2,60,60,455,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")


# ------------------------------------------------------------------ render
def _motion(i, frames):
    """Photo i ke liye zoom/pan expression (editor-style variety)."""
    n = max(frames, 2)
    k = i % 4
    if k == 0:   # zoom in, center
        return f"1+0.13*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if k == 1:   # zoom out
        return f"1.13-0.13*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if k == 2:   # zoom + pan right
        return f"1.08+0.05*on/{n}", f"(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"
    return f"1.08+0.05*on/{n}", f"(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"


def render_scene(photos, overlay, ass, audio, dur, seg):
    n = len(photos)
    frames_each = [int(round(dur * FPS / n))] * n
    frames_each[-1] += 3  # thoda extra, -t se kat jayega
    inputs, chains = [], []
    for i, p in enumerate(photos):
        inputs += ["-i", p]
        z, x, y = _motion(i, frames_each[i])
        chains.append(
            f"[{i}:v]scale=1350:2400:force_original_aspect_ratio=increase,crop=1350:2400,"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames_each[i]}:s={W}x{H}:fps={FPS},setsar=1[p{i}]"
        )
    cat = "".join(f"[p{i}]" for i in range(n))
    chains.append(f"{cat}concat=n={n}:v=1:a=0[bg]" if n > 1 else "[p0]null[bg]")
    chains.append("[bg]eq=brightness=-0.06:saturation=0.92[bgd]")
    chains.append(f"[bgd][{n}:v]overlay=0:0:format=auto[ov]")
    fonts_dir = os.path.dirname(FONT_PATH) if FONT_PATH else None
    sub = f"subtitles='{ass}'" + (f":fontsdir='{fonts_dir}'" if fonts_dir else "")
    chains.append(f"[ov]{sub}[v]")
    cmd = ["ffmpeg", "-y", *inputs, "-i", overlay, "-i", audio,
           "-filter_complex", ";".join(chains),
           "-map", "[v]", "-map", f"{n + 1}:a",
           "-af", "aresample=48000,apad",
           "-ac", "2", "-t", f"{dur:.2f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", seg]
    _run(cmd)


def finalize(concat_path, out_path, total_sec):
    vbit = int(max(1800, min(3500, MAX_MB * 8 * 1024 / total_sec - 260)))
    voice = "[0:a]highpass=f=70,acompressor=threshold=-20dB:ratio=3:attack=5:release=90,aresample=48000[v]"
    loud = "loudnorm=I=-14:TP=-1.0:LRA=7"
    cmd = ["ffmpeg", "-y", "-i", concat_path]
    if BG_MUSIC:
        pad = ("(0.5*sin(2*PI*110*t)+0.35*sin(2*PI*164.81*t)+0.3*sin(2*PI*220*t)+0.2*sin(2*PI*277.18*t))"
               "*(0.65+0.35*sin(2*PI*0.08*t))")
        cmd += ["-f", "lavfi", "-i", f"aevalsrc={pad}|{pad}:s=48000:d={total_sec + 1:.1f}"]
        fc = (f"{voice};[1:a]volume={MUSIC_VOL},lowpass=f=2200[m];"
              f"[v][m]amix=inputs=2:duration=first:dropout_transition=0[mix];[mix]{loud}[a]")
    else:
        fc = f"{voice};[v]{loud}[a]"
    cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-b:v", f"{vbit}k", "-maxrate", f"{int(vbit * 1.35)}k",
            "-bufsize", f"{vbit * 2}k", "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out_path]
    _run(cmd)
    log(f"Final: {os.path.getsize(out_path) / 1e6:.1f} MB, video {vbit} kbps")


def make_video(scenes, out_path, tts_func=None, photo_func=None):
    """scenes -> mp4. Returns seconds. tts_func/photo_func sirf testing ke liye."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    used, total = set(), 0.0
    with tempfile.TemporaryDirectory() as tmp:
        if tts_func:
            audios = []
            for i, sc in enumerate(scenes):
                p = os.path.join(tmp, f"voice{i}.wav")
                tts_func(clean_text(sc.get("speech") or sc.get("caption") or ""), p)
                audios.append(p)
        else:
            audios = synth_all(scenes, tmp)
        segs = []
        for i, sc in enumerate(scenes):
            dur = max(_duration(audios[i]) + 0.3, 2.5)
            need = max(1, min(3, int(round(dur / 3.2))))
            queries = [q for q in (sc.get("photo_queries") or []) if q]
            photos = (photo_func or fetch_photos)(queries, need, tmp, used)
            while len(photos) < need:
                gp = os.path.join(tmp, f"grad{i}_{len(photos)}.jpg")
                make_gradient_photo(gp, i + len(photos))
                photos.append(gp)
            ov = os.path.join(tmp, f"ov{i}.png")
            make_overlay(ov, sc)
            ass = os.path.join(tmp, f"cap{i}.ass")
            write_ass(ass, sc.get("caption") or sc.get("speech") or "", sc.get("emphasis"), dur)
            seg = os.path.join(tmp, f"seg{i}.mp4")
            render_scene(photos, ov, ass, audios[i], dur, seg)
            segs.append(seg)
            total += dur
            log(f"Scene {i + 1}/{len(scenes)} ready ({dur:.1f}s, {len(photos)} photos)")
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.write("".join(f"file '{s}'\n" for s in segs))
        joined = os.path.join(tmp, "joined.mp4")
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])
        finalize(joined, out_path, total)
    return total

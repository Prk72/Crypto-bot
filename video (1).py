"""
Scenes -> vertical (9:16) YouTube Short mp4

Har scene: Pillow se slide (title text) + edge-tts se voice -> ffmpeg se jod kar ek video.
Koi copyrighted music/clip/image use nahi hota - sab kuch code se banta hai.
"""
import asyncio
import os
import re
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
TTS_VOICE = os.environ.get("TTS_VOICE", "en-IN-PrabhatNeural")  # Hinglish (Roman) ke liye en-IN voice theek rehti hai
TTS_RATE = os.environ.get("TTS_RATE", "+0%")

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
ACCENTS = [(0, 200, 255), (255, 170, 0), (120, 255, 150), (255, 90, 140)]


def _font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def clean_text(t):
    t = re.sub(r"[*_`#\[\]{}<>|~^]", "", t or "")
    t = re.sub(r"[^\w\s\-\$%.,:!?'&/()+₹@]", "", t, flags=re.UNICODE)  # emoji hatao
    return re.sub(r"\s+", " ", t).strip()


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


def make_slide(path, title, idx, total):
    accent = ACCENTS[idx % len(ACCENTS)]
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    top, bottom = (10, 14, 40), (45, 18, 70)
    for y in range(H):  # vertical gradient
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)))

    d.rounded_rectangle([60, 120, 60 + 520, 120 + 90], radius=45, outline=accent, width=5)
    d.text((90, 142), "CRYPTO UPDATE", font=_font(46), fill=accent)

    title = clean_text(title) or "Crypto Update"
    size = 110
    while size > 50:
        f = _font(size)
        lines = _wrap(d, title, f, W - 160)
        line_h = int(size * 1.25)
        if len(lines) * line_h <= 1000:
            break
        size -= 6
    block_h = len(lines) * line_h
    y = (H - block_h) // 2 - 40
    for ln in lines:
        w = d.textlength(ln, font=f)
        d.text(((W - w) / 2, y), ln, font=f, fill=(255, 255, 255))
        y += line_h

    # progress bar
    bar_x0, bar_x1, bar_y = 80, W - 80, 1730
    d.rounded_rectangle([bar_x0, bar_y, bar_x1, bar_y + 16], radius=8, fill=(70, 70, 100))
    filled = bar_x0 + (bar_x1 - bar_x0) * (idx + 1) / max(total, 1)
    d.rounded_rectangle([bar_x0, bar_y, filled, bar_y + 16], radius=8, fill=accent)

    foot = "Not financial advice  |  DYOR"
    ff = _font(38)
    d.text(((W - d.textlength(foot, font=ff)) / 2, 1800), foot, font=ff, fill=(190, 190, 215))
    img.save(path)


async def _tts(text, path):
    import edge_tts

    await edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE).save(path)


def tts(text, path):
    asyncio.run(_tts(text, path))


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} fail: {r.stderr[-400:]}")
    return r.stdout


def _duration(path):
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.strip())


def make_video(scenes, out_path, tts_func=tts):
    """scenes = [{"title": ..., "narration": ...}, ...]; returns total seconds."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    total_sec = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        segs = []
        for i, sc in enumerate(scenes):
            narr = clean_text(sc.get("narration", ""))
            if not narr:
                continue
            audio = os.path.join(tmp, f"a{i}.mp3")
            tts_func(narr, audio)
            dur = _duration(audio) + 0.35
            png = os.path.join(tmp, f"s{i}.png")
            make_slide(png, sc.get("title", ""), i, len(scenes))
            seg = os.path.join(tmp, f"seg{i}.mp4")
            _run([
                "ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", png, "-i", audio,
                "-af", "apad", "-t", f"{dur:.2f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", seg,
            ])
            segs.append(seg)
            total_sec += dur
            print(f"Scene {i + 1}/{len(scenes)} ready ({dur:.1f}s)")
        if not segs:
            raise RuntimeError("Koi scene nahi bana")
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.write("".join(f"file '{s}'\n" for s in segs))
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
              "-movflags", "+faststart", out_path])
    print(f"Video ready: {out_path} ({total_sec:.0f}s, {os.path.getsize(out_path) / 1e6:.1f} MB)")
    return total_sec

"""
Crypto news -> Gemini (Hinglish video script) -> Telegram

Purane setup ki problems fix:
  * CryptoPanic 403 -> free RSS feeds (no API key)
  * gemini-1.5-flash (retired) + google.generativeai (deprecated) -> google-genai + gemini-2.5-flash
  * Gemini fail ho to bhi headlines Telegram pe aati hain
  * Telegram error clearly log hota hai aur job fail dikhata hai
"""
import os
import sys
import html
import json
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "716191921").strip()  # secret mile to wo, warna default
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
LINK_HUB_URL = (os.environ.get("LINK_HUB_URL") or "").strip()  # aapka Telegram link (har video description mein)
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "24"))
NUM_HEADLINES = int(os.environ.get("NUM_HEADLINES", "3"))

FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "Bitcoin Magazine": "https://bitcoinmagazine.com/.rss/full/",
}
# YouTube channels: sirf TOPIC IDEAS ke liye (titles). Inka content copy nahi hota.
YT_CHANNELS = {
    "Wise Advice (crypto)": "UC_d3dOruc-Y0CNzoNRLPDzw",
    "The No SL Zone (prop firm offers)": "UCyqi1uZWAiN7zWy1avAj3sw",
}
YT_PER_CHANNEL = int(os.environ.get("YT_PER_CHANNEL", "2"))
ATOM = "{http://www.w3.org/2005/Atom}"
UA = {"User-Agent": "Mozilla/5.0 (compatible; CryptoBot/1.0)"}


def parse_date(s):
    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def fetch_crypto_news():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    items, seen = [], set()
    for name, url in FEEDS.items():
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            n = 0
            for it in root.iter("item"):
                title = html.unescape((it.findtext("title") or "").strip())
                pub = parse_date(it.findtext("pubDate") or "")
                if not title or title.lower() in seen:
                    continue
                if pub and pub < cutoff:
                    continue
                seen.add(title.lower())
                items.append((pub or datetime.min.replace(tzinfo=timezone.utc), name, title))
                n += 1
            print(f"{name}: {n} items")
        except Exception as e:
            print(f"{name} feed fail: {e}")
    items.sort(reverse=True)
    top = items[:NUM_HEADLINES]
    return "".join(f"- {title}\n" for _, _, title in top)


def fetch_youtube_topics():
    """Har channel ke latest video titles (sirf topic idea ke liye)."""
    lines = []
    for label, cid in YT_CHANNELS.items():
        try:
            r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", headers=UA, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            titles = [(e.findtext(f"{ATOM}title") or "").strip() for e in root.iter(f"{ATOM}entry")]
            titles = [t for t in titles if t][:YT_PER_CHANNEL]
            for t in titles:
                lines.append(f"- ({label}) {t}")
            print(f"{label}: {len(titles)} topics")
        except Exception as e:
            print(f"YouTube feed fail ({label}): {e}")
    return "\n".join(lines)


def generate_script(news_text, yt_topics=""):
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY nahi mili.")
        return ""
    try:
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "Create a short, engaging video script in Hinglish for a crypto influencer "
            f"based on these news headlines:\n{news_text}\n"
        )
        if yt_topics:
            prompt += (
                "\nTrending topic ideas from other creators (sirf inspiration ke liye):\n"
                f"{yt_topics}\n"
            )
        prompt += (
            "\nRULES:\n"
            "- Script 100% ORIGINAL ho: kisi creator ki line, structure ya phrasing copy mat karo, "
            "kisi channel ka naam mat lo.\n"
            "- Topic ideas ko apne naye angle, explanation aur opinion ke saath cover karo.\n"
            "- Koi guaranteed profit, 'free money' ya 'risk-free' claim mat karo. Prop firm/funded "
            "account ki baat ho to bolo ki terms official site pe verify karo.\n"
            "- End mein 1 line short disclaimer: 'Ye financial advice nahi hai, apna research khud karein.'\n"
        )
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return (resp.text or "").strip()
    except Exception as e:
        print(f"Error generating script with Gemini: {e}")
        return ""


def build_youtube_metadata(script, news_text):
    """Title + description (hub link, bot link, disclosure ke saath) - copy-paste ya auto-upload ke liye."""
    title, desc, tags = "", "", ""
    if GEMINI_API_KEY:
        try:
            from google import genai

            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = (
                "Is video script ke liye YouTube metadata do, Hinglish mein. Exact format:\n"
                "TITLE: <max 70 characters, misleading/clickbait false claim nahi>\n"
                "DESC: <2-3 line description>\n"
                "TAGS: <8 hashtags, space separated>\n\nSCRIPT:\n" + script[:3000]
            )
            text = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text or ""
            m = re.search(r"TITLE:\s*(.+)", text)
            title = m.group(1).strip() if m else ""
            m = re.search(r"DESC:\s*(.+?)\s*TAGS:", text, re.S)
            desc = m.group(1).strip() if m else ""
            m = re.search(r"TAGS:\s*(.+)", text)
            tags = m.group(1).strip() if m else ""
        except Exception as e:
            print(f"Metadata generation fail: {e}")
    if not title:
        first = news_text.splitlines()[0].lstrip("- ").strip() if news_text else "Crypto Update"
        title = ("Crypto Update: " + first)[:70]

    parts = [desc] if desc else []
    if LINK_HUB_URL:
        parts.append(f"📲 Telegram pe link & updates: {LINK_HUB_URL}")
    else:
        print("LINK_HUB_URL set nahi hai - description mein link add nahi hua.")
    parts.append(
        "⚠️ Disclosure: Is description mein affiliate/referral links ho sakte hain, jinse mujhe commission mil sakta hai. "
        "Offer ki terms official site pe verify karein. Ye financial advice nahi hai."
    )
    if tags:
        parts.append(tags)
    return f"📋 YOUTUBE TITLE:\n{title}\n\n📝 DESCRIPTION (copy-paste):\n" + "\n\n".join(parts)


CTA_SCENE = {
    "title": "Link & updates: description mein Telegram link",
    "narration": "Link aur updates ke liye description mein diya Telegram link check karo, aur follow karna mat bhoolna. "
                 "Ye financial advice nahi hai, apna research khud karein.",
}


def script_to_scenes(script):
    """Script -> clean scenes (title + sirf bolne wala text) JSON."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = (
        "Neeche ek video script hai. Isse YouTube Shorts (vertical, 60-80 second) ke scenes mein badlo.\n"
        'Sirf valid JSON do: {"scenes":[{"title":"on-screen text, max 7 words, no emoji",'
        '"narration":"bolne wala Hinglish text, 1-3 chhote sentences"}]}\n'
        "Rules: 5 se 7 scenes; pehla scene strong hook ho; total narration 170 words se kam; "
        "stage directions, speaker labels (Influencer:), brackets, emoji, markdown BILKUL nahi; "
        "koi guaranteed profit claim nahi; last mein disclaimer mat daalo (wo alag se judta hai).\n\n"
        "SCRIPT:\n" + script[:6000]
    )
    resp = client.models.generate_content(
        model=GEMINI_MODEL, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    raw = (resp.text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    data = json.loads(raw)
    scenes = [
        {"title": str(x.get("title", "")).strip(), "narration": str(x.get("narration", "")).strip()}
        for x in data.get("scenes", []) if x.get("narration")
    ]
    if not scenes:
        raise RuntimeError("Gemini ne scenes nahi diye")
    return scenes[:8]


def send_telegram_video(path, caption=""):
    if os.path.getsize(path) > 49 * 1024 * 1024:
        print("Video 50MB se badi hai - Telegram pe nahi ja sakti.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    with open(path, "rb") as f:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption[:1000], "supports_streaming": "true",
                  "width": 1080, "height": 1920},
            files={"video": f}, timeout=300,
        )
    print(f"Telegram sendVideo: {r.status_code} {r.text[:200]}")
    return r.ok


def make_and_send_video(script):
    """Video banao aur Telegram pe bhejo. Fail ho to baaki flow nahi rukta."""
    try:
        import video

        scenes = script_to_scenes(script) + [CTA_SCENE]
        out = os.path.join("output", "short.mp4")
        secs = video.make_video(scenes, out)
        ok = send_telegram_video(out, f"🎬 Auto-generated Short ({int(secs)}s). Review karke upload karo.")
        if not ok:
            send_telegram_message("⚠️ Video ban gayi par Telegram pe nahi ja saki. GitHub Actions ke Artifacts se download karo.")
    except Exception as e:
        print(f"Video generation fail: {e}")
        send_telegram_message(f"⚠️ Video generation fail hui: {str(e)[:300]}")


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN nahi mila.")
        sys.exit(1)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Telegram limit 4096 chars -> chunks
    for i in range(0, len(message), 3800):
        try:
            r = requests.post(url, json={"chat_id": CHAT_ID, "text": message[i:i + 3800]}, timeout=20)
        except Exception as e:
            print(f"Error sending Telegram message: {e}")
            sys.exit(1)
        print(f"Telegram Response Code: {r.status_code}")
        print(f"Telegram Response Text: {r.text}")
        if not r.ok:
            sys.exit(1)  # job red ho jaye taaki pata chale


if __name__ == "__main__":
    print("Workflow started...")
    if "--test" in sys.argv:
        send_telegram_message("✅ Crypto bot test: Telegram connection working!")
        sys.exit(0)

    news = fetch_crypto_news()
    if not news:
        print("No news fetched from any feed.")
        sys.exit(0)

    print("News fetched successfully.")
    yt_topics = fetch_youtube_topics()
    script = generate_script(news, yt_topics)
    if script:
        print("--- Generated Video Script ---")
        print(script)
        send_telegram_message(script)
        send_telegram_message(build_youtube_metadata(script, news))
        make_and_send_video(script)
    else:
        print("Script generation failed - headlines bhej raha hoon.")
        send_telegram_message("⚠️ Gemini script fail hui. Aaj ki headlines:\n" + news)

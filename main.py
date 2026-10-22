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
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "716191921").strip()  # secret mile to wo, warna default
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "24"))
NUM_HEADLINES = int(os.environ.get("NUM_HEADLINES", "3"))

FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "Bitcoin Magazine": "https://bitcoinmagazine.com/.rss/full/",
}
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


def generate_script(news_text):
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY nahi mili.")
        return ""
    try:
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "Create a short, engaging video script in Hinglish for a crypto influencer "
            f"based on these news headlines:\n{news_text}"
        )
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return (resp.text or "").strip()
    except Exception as e:
        print(f"Error generating script with Gemini: {e}")
        return ""


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
    script = generate_script(news)
    if script:
        print("--- Generated Video Script ---")
        print(script)
        send_telegram_message(script)
    else:
        print("Script generation failed - headlines bhej raha hoon.")
        send_telegram_message("⚠️ Gemini script fail hui. Aaj ki headlines:\n" + news)

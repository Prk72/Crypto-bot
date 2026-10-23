"""
Crypto Shorts bot v2  (har 3 ghante)

Modes (slot ke hisaab se rotate hote hain):
  airdrop   - airdrops / trading rewards & competitions (Google Search grounded, safety-first)
  news      - latest crypto headlines
  market    - market research snapshot (CoinGecko prices + Fear&Greed + headlines)
  funded    - free funded account / prop firm offers (Google Search grounded + YouTube topic ideas)
  referral  - referral & earn education (evergreen topics)

Output (Telegram): 1) ready faceless Short (mp4)  2) YouTube title + description + verify links
Upload aap Buffer se schedule karte ho.
"""
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
TELEGRAM_BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "716191921").strip()
LINK_HUB_URL = (os.environ.get("LINK_HUB_URL") or "").strip()
FORCE_MODE = (os.environ.get("FORCE_MODE") or "auto").strip().lower()

TEXT_MODELS = []
for _m in [os.environ.get("GEMINI_MODEL") or "gemini-flash-latest", "gemini-flash-lite-latest",
           "gemini-3.1-flash-lite", "gemini-2.5-flash"]:
    if _m not in TEXT_MODELS:
        TEXT_MODELS.append(_m)

STATE_PATH = "state.json"
IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (compatible; CryptoBot/2.0)"}

# UTC hour//3 -> mode  (00,03,06,09,12,15,18,21 UTC)
SLOT_MODES = ["news", "funded", "airdrop", "market", "funded", "airdrop", "news", "referral"]
MODE_LABEL = {"news": "📰 News", "market": "📊 Market research", "funded": "🎁 Free funded offers",
              "airdrop": "🪂 Airdrops & trading rewards", "referral": "💰 Earn ways"}

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
ATOM = "{http://www.w3.org/2005/Atom}"

REFERRAL_TOPICS = [
    "Crypto mein free earn karne ke tareeke: airdrops, trading rewards, referral, bounties - risks ke saath",
    "Free funded account se trading shuru karne ka sahi tareeka (aur kya dhyan rakhein)",
    "Airdrop farming ki sachchai: time, risk aur kitna realistic hai",
    "Beginner ke liye zero-investment earn ideas: kya sach hai, kya scam",
    "Referral program kaise kaam karta hai (exchange / prop firm)",
    "Referral aur affiliate mein kya fark hota hai",
    "Referral link se earning ki sachchai: kitna realistic hai",
    "Fake referral aur MLM jaisi schemes ko kaise pehchanein",
    "Prop firm ka affiliate program kaise kaam karta hai",
    "Referral link share karte waqt disclosure kyun zaroori hai",
    "Crypto exchange ke fee-discount referral kya hote hain",
    "Referral income ko track karne ka simple tareeka",
    "Free funded account offers ki chhupi hui shartein",
    "Audience ka trust banao, phir referral: sahi tareeka",
    "Pehle audience banao phir earning: step by step",
    "Referral kamaayi par tax ka basic idea (CA se confirm karna zaroori)",
]

CTA_SCENE = {
    "label": "FOLLOW KARO",
    "title": "Link description mein",
    "stat": "",
    "stat_label": "",
    "caption": "Link description mein hai, aur follow karna mat bhoolna. Ye financial advice nahi hai.",
    "speech": "लिंक description में है, और follow करना मत भूलना। ये financial advice नहीं है, अपनी research खुद करें।",
    "emphasis": ["follow", "description"],
    "photo_queries": ["smartphone in hand dark", "city skyline night"],
}


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------ state
def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            s = json.load(f)
            return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    except Exception as e:
        log(f"State save fail: {e}")


# ----------------------------------------------------------------- Gemini
def gemini_text(prompt, tools=None, json_mode=False):
    """503/429 par lamba wait + retry, phir agle backup model par."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    last = None
    for model in TEXT_MODELS:
        for attempt in range(3):
            try:
                cfg = types.GenerateContentConfig(
                    tools=tools or None,
                    response_mime_type="application/json" if json_mode else None,
                )
                resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
                if not (resp.text or "").strip():
                    raise RuntimeError("empty response")
                return resp
            except Exception as e:
                last = e
                msg = str(e).lower()
                log(f"Gemini fail ({model}, try {attempt + 1}/3): {str(e)[:120]}")
                busy = any(k in msg for k in ("429", "resource_exhausted", "quota", "503", "500",
                                              "unavailable", "overloaded", "deadline", "timeout"))
                if not busy:
                    break  # model hi nahi mila / galat request -> seedha agla model
                if attempt < 2:
                    wait = 15 * (2 ** attempt)  # 15s, 30s
                    log(f"Server busy, {wait}s ruk raha hoon...")
                    time.sleep(wait)
    raise RuntimeError(f"Gemini text fail (sab models): {last}")


def grounding_urls(resp):
    urls = []
    try:
        for ch in resp.candidates[0].grounding_metadata.grounding_chunks or []:
            if ch.web and ch.web.uri:
                urls.append(ch.web.uri + (f"  ({ch.web.title})" if ch.web.title else ""))
    except Exception:
        pass
    return urls[:6]


# -------------------------------------------------------------- research
def _parse_date(s):
    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def fetch_headlines(used, hours=24, limit=5):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items, seen = [], set(used)
    for name, url in FEEDS.items():
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            for it in ET.fromstring(r.content).iter("item"):
                title = html.unescape((it.findtext("title") or "").strip())
                link = (it.findtext("link") or "").strip()
                pub = _parse_date(it.findtext("pubDate") or "")
                if not title or title.lower() in seen or (pub and pub < cutoff):
                    continue
                seen.add(title.lower())
                items.append((pub or datetime.min.replace(tzinfo=timezone.utc), name, title, link))
        except Exception as e:
            log(f"{name} feed fail: {e}")
    items.sort(reverse=True)
    return [{"source": s, "title": t, "link": l} for _, s, t, l in items[:limit]]


def youtube_topics(per_channel=2):
    lines = []
    for label, cid in YT_CHANNELS.items():
        try:
            r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", headers=UA, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            for e in list(root.iter(f"{ATOM}entry"))[:per_channel]:
                t = (e.findtext(f"{ATOM}title") or "").strip()
                if t:
                    lines.append(f"- ({label}) {t}")
        except Exception as e:
            log(f"YouTube feed fail ({label}): {e}")
    return "\n".join(lines)


def market_data():
    lines = []
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price", timeout=20, headers=UA, params={
            "ids": "bitcoin,ethereum,solana,binancecoin", "vs_currencies": "usd,inr", "include_24hr_change": "true"})
        r.raise_for_status()
        d = r.json()
        for key, name in [("bitcoin", "Bitcoin"), ("ethereum", "Ethereum"), ("solana", "Solana"), ("binancecoin", "BNB")]:
            if key in d:
                x = d[key]
                lines.append(f"{name}: ${x['usd']:,.0f} (Rs {x['inr']:,.0f}), 24h {x.get('usd_24h_change', 0):+.1f}%")
    except Exception as e:
        log(f"CoinGecko fail: {e}")
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=20, headers=UA)
        r.raise_for_status()
        v = r.json()["data"][0]
        lines.append(f"Fear & Greed Index: {v['value']} ({v['value_classification']})")
    except Exception as e:
        log(f"Fear&Greed fail: {e}")
    return lines


def research(mode, state):
    """returns (context_text, sources, state_hint)"""
    used_heads = [h.lower() for h in state.get("used_headlines", [])]

    if mode == "news":
        heads = fetch_headlines(used_heads, limit=3)
        if len(heads) < 2:
            log("Naya news kam hai -> market mode")
            return research("market", state) + ("market",)
        ctx = "LATEST HEADLINES:\n" + "\n".join(f"- [{h['source']}] {h['title']}" for h in heads)
        return ctx, [h["link"] for h in heads], {"mode": "news", "headlines": [h["title"] for h in heads]}

    if mode == "market":
        data = market_data()
        heads = fetch_headlines(used_heads, limit=2)
        if not data and not heads:
            raise RuntimeError("Market data aur headlines dono nahi mile")
        ctx = "MARKET DATA (live):\n" + "\n".join(f"- {x}" for x in data)
        if heads:
            ctx += "\n\nCONTEXT HEADLINES:\n" + "\n".join(f"- [{h['source']}] {h['title']}" for h in heads)
        return ctx, ["https://www.coingecko.com", "https://alternative.me/crypto/fear-and-greed-index/"] + \
            [h["link"] for h in heads], {"mode": "market", "headlines": [h["title"] for h in heads]}

    if mode == "funded":
        from google.genai import types

        used = ", ".join(state.get("used_offers", [])[-30:]) or "koi nahi"
        today = datetime.now(IST).strftime("%d %B %Y")
        prompt = (
            f"Aaj {today} hai. Web search se un prop trading firms (forex/crypto/futures) ke abhi-live "
            "'free funded account', 'free challenge' ya giveaway offers dhundho. Har offer ke liye likho: "
            "firm ka naam | offer kya hai | mukhya shartein (KYC, evaluation/challenge, profit split, expiry, region limits) "
            "| official website. SIRF wahi likho jo search results mein saaf dikhe; yaad se ya andaze se kuch mat likho. "
            f"Maximum 3 offers. Pehle cover ho chuke (dobara mat lo): {used}. "
            "Agar koi pakka offer na mile to sirf 'NONE' likho."
        )
        offers, sources = "", []
        try:
            resp = gemini_text(prompt, tools=[types.Tool(google_search=types.GoogleSearch())])
            offers = (resp.text or "").strip()
            sources = grounding_urls(resp)
        except Exception as e:
            log(f"Funded research fail: {e}")
        if not offers or offers.upper().startswith("NONE"):
            offers = ""
        yt = youtube_topics()
        if offers:
            ctx = "VERIFIED-BY-SEARCH OFFERS:\n" + offers
        else:
            ctx = ("Koi pakka naya offer nahi mila. Isliye educational video banao: free funded account offers "
                   "check karne ka tareeka aur scam red flags (fees chhupi hui, unrealistic payout, fake reviews, "
                   "unregulated firm).")
        if yt:
            ctx += "\n\nCREATORS KE RECENT TOPICS (sirf idea ke liye, copy nahi):\n" + yt
        return ctx, sources, {"mode": "funded"}

    if mode == "airdrop":
        from google.genai import types

        used = ", ".join(state.get("used_airdrops", [])[-30:]) or "koi nahi"
        today = datetime.now(IST).strftime("%d %B %Y")
        prompt = (
            f"Aaj {today} hai. Web search se abhi-live crypto airdrops aur trading rewards/competitions dhundho jo "
            "reputed sources se verify ho (major exchanges ke official announcement pages, ya known protocols ke official "
            "blog/docs). Har item ke liye likho: naam | kya milta hai (airdrop / trading competition / reward) | "
            "participate kaise (high level) | eligibility, shartein, expiry | official link. SIRF wahi likho jo search "
            "results mein saaf dikhe; yaad se ya andaze se kuch mat likho. Aisa koi item mat lo jisme seed phrase, "
            "private key, ya kisi unknown site pe wallet connect karke claim karna pade. Maximum 3 items. "
            f"Pehle cover ho chuke (dobara mat lo): {used}. Agar koi pakka item na mile to sirf 'NONE' likho."
        )
        items, sources = "", []
        try:
            resp = gemini_text(prompt, tools=[types.Tool(google_search=types.GoogleSearch())])
            items = (resp.text or "").strip()
            sources = grounding_urls(resp)
        except Exception as e:
            log(f"Airdrop research fail: {e}")
        if not items or items.upper().startswith("NONE"):
            items = ""
        if items:
            ctx = "VERIFIED-BY-SEARCH AIRDROPS / REWARDS:\n" + items
        else:
            ctx = ("Koi pakka naya item nahi mila. Isliye educational video banao: airdrop scams se kaise bachein "
                   "(wallet drainer, fake claim sites, seed phrase kabhi share nahi, alag chhota wallet use karo, "
                   "official source se hi claim karo).")
        return ctx, sources, {"mode": "airdrop"}

    # referral
    idx = int(state.get("referral_idx", 0)) % len(REFERRAL_TOPICS)
    topic = REFERRAL_TOPICS[idx]
    return f"TOPIC: {topic}", [], {"mode": "referral", "referral_idx": idx + 1}


# ------------------------------------------------------------------- plan
MODE_RULES = {
    "news": "Mode: crypto NEWS. 3 headlines ko alag scenes mein explain karo (kya hua, kyun matter karta hai). "
            "Apna angle do, headlines copy mat karo.",
    "market": "Mode: MARKET RESEARCH snapshot. MARKET DATA ke numbers se bolo (BTC/ETH price, 24h move, Fear&Greed mood). "
              "Headlines se context do. End mein risk-management tip. Koi buy/sell call nahi.",
    "funded": "Mode: FREE FUNDED ACCOUNT offers. CONTEXT ke offers hi cover karo: firm, kya milta hai, 1-2 mukhya shartein, "
              "'official site pe verify karo'. Ek scene 'SHARTEIN' ya 'RED FLAGS' ka rakho. "
              "Audience ko follow aur description mein Telegram link ke liye bolo. Koi income promise nahi.",
    "airdrop": "Mode: AIRDROPS & TRADING REWARDS. CONTEXT ke items hi cover karo: kya milta hai, participate kaise, "
               "eligibility/expiry, 'official site se hi'. Ek scene SAFETY ka zaroor rakho: seed phrase ya private key "
               "kabhi share mat karo, unknown site pe wallet connect mat karo. Bolo ki airdrop ya reward guaranteed nahi hota. "
               "Audience ko follow aur description mein Telegram link ke liye bolo.",
    "referral": "Mode: EARN WAYS education (referral sirf ek tareeka hai). Honest aur practical samjhao: earning guarantee nahi hoti, "
                "audience/trust/mehnat chahiye. Ek scene mein bolo ki referral link share karte waqt disclosure zaroori hai.",
}


def build_prompt(mode, ctx):
    return (
        "Tum ek faceless Hinglish crypto/trading YouTube Shorts ke scriptwriter ho. CONTEXT se 65-80 second ka "
        "Short plan banao. Sirf valid JSON do (extra text nahi):\n"
        '{"video_title":"","description":"","hashtags":[],"topics_covered":[],'
        '"scenes":[{"label":"","title":"","stat":"","stat_label":"","caption":"","speech":"","emphasis":[],"photo_queries":[]}]}\n\n'
        f"{MODE_RULES[mode]}\n\nRULES:\n"
        "- 6 se 8 scenes. Scene 1 = strong hook (sawal ya surprising fact, CONTEXT se).\n"
        "- caption: Roman Hinglish, 1-2 chhote sentences (screen pe dikhega).\n"
        "- speech: wahi baat Hindi (Devanagari) mein, natural bolchaal jaise YouTuber bolta hai; common English words "
        "(Bitcoin, Coinbase, fine, account, market, profit, offer) Latin script mein hi rehne do.\n"
        "- Total speech 170 words se kam.\n"
        "- title max 6 words; label max 3 words (jaise BREAKING, MARKET UPDATE, FREE OFFER, SHARTEIN).\n"
        "- stat: sirf agar CONTEXT mein real number ho (jaise $3.6M, 62%), warna khali; stat_label 2-3 words.\n"
        "- emphasis: caption ke 1-3 important words.\n"
        "- photo_queries: har scene ke liye 2 English descriptions (5-8 words), jaise insaan se bolte ho, keyword stuffing nahi (jaise 'a shiny gold bitcoin coin on a dark desk', 'city skyline at night with lights', 'laptop screen showing trading charts'); koi insaan, chehra, brand ya logo nahi.\n"
        "- SIRF CONTEXT ke facts aur numbers use karo. Apni taraf se numbers, offers ya claims invent mat karo.\n"
        "- Koi guaranteed profit, 'paisa double', 'risk-free', 'free paisa' jaisa claim nahi. Financial advice nahi.\n"
        "- video_title honest ho, max 70 characters. description 2-3 line Hinglish. hashtags 6-8 (#Shorts zaroor).\n"
        "- topics_covered: cover kiye firms/topics ke short naam.\n\n"
        f"CONTEXT:\n{ctx}\n"
    )


def parse_plan(text):
    raw = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    data = json.loads(raw)
    scenes = []
    for x in data.get("scenes", []):
        if not (x.get("speech") or x.get("caption")):
            continue
        scenes.append({
            "label": str(x.get("label", ""))[:26], "title": str(x.get("title", ""))[:60],
            "stat": str(x.get("stat", "") or "")[:14], "stat_label": str(x.get("stat_label", "") or "")[:34],
            "caption": str(x.get("caption", "")).strip(), "speech": str(x.get("speech", "")).strip(),
            "emphasis": [str(e) for e in (x.get("emphasis") or [])][:3],
            "photo_queries": [str(q) for q in (x.get("photo_queries") or [])][:3],
        })
    if len(scenes) < 4:
        raise RuntimeError("Plan mein 4 se kam scenes")
    data["scenes"] = scenes[:8]
    return data


def generate_plan(mode, ctx):
    last = None
    for attempt in range(2):
        try:
            resp = gemini_text(build_prompt(mode, ctx), json_mode=True)
            return parse_plan(resp.text)
        except Exception as e:
            last = e
            log(f"Plan parse/gen fail (try {attempt + 1}): {str(e)[:160]}")
    raise RuntimeError(f"Plan nahi bana: {last}")


def build_metadata(plan, mode, sources):
    title = (plan.get("video_title") or "Crypto Update").strip()[:70]
    parts = [(plan.get("description") or "").strip()]
    if LINK_HUB_URL:
        parts.append(f"📲 Telegram pe link & updates: {LINK_HUB_URL}")
    disc = ("⚠️ Disclosure: Is description mein affiliate/referral links ho sakte hain, jinse mujhe commission mil sakta "
            "hai. Offer ki terms official site pe verify karein. Ye financial advice nahi hai.")
    if mode == "funded":
        disc += " Offers kabhi bhi badal ya khatam ho sakte hain."
    if mode == "airdrop":
        disc += " Airdrop/rewards guaranteed nahi hote. Seed phrase ya private key kisi ke saath share mat karein."
    parts.append(disc)
    tags = " ".join(h if h.startswith("#") else f"#{h}" for h in plan.get("hashtags", [])[:8])
    if tags:
        parts.append(tags)
    msg = f"{MODE_LABEL[mode]}\n\n📋 YOUTUBE TITLE:\n{title}\n\n📝 DESCRIPTION (copy-paste):\n" + "\n\n".join(p for p in parts if p)
    if sources:
        msg += "\n\n🔎 POST SE PEHLE VERIFY KARO:\n" + "\n".join(sources[:6])
    return title, msg


# --------------------------------------------------------------- Telegram
def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        log("TELEGRAM_BOT_TOKEN nahi mila.")
        sys.exit(1)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for i in range(0, len(message), 3800):
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": message[i:i + 3800],
                                     "disable_web_page_preview": True}, timeout=30)
        log(f"Telegram sendMessage: {r.status_code}")
        if not r.ok:
            log(r.text[:300])
            sys.exit(1)


def send_telegram_video(path, caption=""):
    if os.path.getsize(path) > 49 * 1024 * 1024:
        log("Video 50MB se badi hai - Telegram pe nahi ja sakti.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    with open(path, "rb") as f:
        r = requests.post(url, data={"chat_id": CHAT_ID, "caption": caption[:1000], "supports_streaming": "true",
                                     "width": 1080, "height": 1920}, files={"video": f}, timeout=300)
    log(f"Telegram sendVideo: {r.status_code} {r.text[:160]}")
    return r.ok


# ------------------------------------------------------------------- main
def pick_mode():
    if FORCE_MODE in MODE_LABEL:
        return FORCE_MODE
    return SLOT_MODES[(datetime.now(timezone.utc).hour // 3) % len(SLOT_MODES)]


def update_state(state, hint, plan):
    if hint.get("headlines"):
        used = state.get("used_headlines", []) + hint["headlines"]
        state["used_headlines"] = used[-300:]
    if hint.get("mode") == "funded":
        state["used_offers"] = (state.get("used_offers", []) + [str(t) for t in plan.get("topics_covered", [])])[-60:]
    if hint.get("mode") == "airdrop":
        state["used_airdrops"] = (state.get("used_airdrops", []) + [str(t) for t in plan.get("topics_covered", [])])[-60:]
    if "referral_idx" in hint:
        state["referral_idx"] = hint["referral_idx"]
    state["last_run"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")


def main():
    log("Workflow started...")
    if "--test" in sys.argv:
        send_telegram_message("✅ Crypto bot test: Telegram connection working!")
        return

    state = load_state()
    mode = pick_mode()
    log(f"Mode: {mode}")
    try:
        res = research(mode, state)
        if len(res) == 4:  # news -> market fallback
            mode = res[3]
        ctx, sources, hint = res[0], res[1], res[2]
        plan = generate_plan(mode, ctx)
    except Exception as e:
        log(f"Research/plan fail: {e}")
        send_telegram_message(f"⚠️ {MODE_LABEL.get(mode, mode)}: content nahi ban paya.\n{str(e)[:300]}")
        sys.exit(1)

    title, meta = build_metadata(plan, mode, sources)
    scenes = plan["scenes"] + [CTA_SCENE]

    try:
        import video

        out = os.path.join("output", "short.mp4")
        secs = video.make_video(scenes, out)
        ok = send_telegram_video(out, f"🎬 {title}\n({int(secs)}s) Buffer pe schedule karo")
        if not ok:
            send_telegram_message("⚠️ Video ban gayi par Telegram pe nahi ja saki. GitHub Actions Artifacts se download karo.")
    except Exception as e:
        log(f"Video generation fail: {e}")
        send_telegram_message(f"⚠️ Video generation fail hui: {str(e)[:300]}")

    send_telegram_message(meta)
    update_state(state, hint, plan)
    save_state(state)


if __name__ == "__main__":
    main()

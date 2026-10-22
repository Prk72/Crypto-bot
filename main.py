import os
import requests
import google.generativeai as genai

# Apni API keys aur tokens GitHub Secrets se lein
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = "716191921"

genai.configure(api_key=GEMINI_API_KEY)

def fetch_crypto_news():
    url = "https://cryptopanic.com/api/v1/posts/?auth_token=free&public=true"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            posts = response.json().get("results", [])
            news_text = ""
            for post in posts[:3]:
                news_text += f"- {post.get('title')}\n"
            return news_text
        print(f"CryptoPanic API Error: {response.status_code}")
        return ""
    except Exception as e:
        print(f"Error fetching crypto news: {e}")
        return ""

def generate_script(news_text):
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY nahi mili.")
        return ""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"Create a short, engaging video script in Hinglish for a crypto influencer based on these news headlines:\n{news_text}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error generating script with Gemini: {e}")
        return ""

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN nahi mila.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    try:
        response = requests.post(url, json=payload)
        print(f"Telegram Response Code: {response.status_code}")
        print(f"Telegram Response Text: {response.text}")
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

if __name__ == "__main__":
    print("Workflow started...")
    news = fetch_crypto_news()
    if news:
        print("News fetched successfully.")
        script = generate_script(news)
        if script:
            print("--- Generated Video Script ---")
            print(script)
            send_telegram_message(script)
        else:
            print("Script generation failed.")
    else:
        print("No news fetched or API failed.")
        

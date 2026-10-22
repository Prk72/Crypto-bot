import os
import requests
import google.generativeai as genai

# Apni Gemini API key GitHub Secrets me save karein
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
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
        return ""
    except Exception as e:
        print(f"Error: {e}")
        return ""

def generate_script(news_text):
    if not GEMINI_API_KEY:
        print("API key nahi mili.")
        return ""
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"Create a short, engaging video script in Hinglish for a crypto influencer based on these news headlines:\n{news_text}"
    response = model.generate_content(prompt)
    return response.text

if __name__ == "__main__":
    news = fetch_crypto_news()
    if news:
        script = generate_script(news)
        print("--- Generated Video Script ---")
        print(script)
        

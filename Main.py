import os
import requests

# Cryptocurrency News Bot
# Ye bot crypto news fetch karega aur aapko update dega.

def fetch_crypto_news():
    # Free CryptoPanic API use kar rahe hain news ke liye
    url = "https://cryptopanic.com/api/v1/posts/?auth_token=free&public=true"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            posts = data.get("results", [])
            print("--- Latest Crypto News ---")
            for post in posts[:5]:  # Top 5 news items
                title = post.get("title")
                source = post.get("source", {}).get("title")
                print(f"- {title} (Source: {source})")
        else:
            print("News fetch karne mein kuch dikkat aayi.")
    except Exception as e:
        print(f"Error aaya hai: {e}")

if __name__ == "__main__":
    fetch_crypto_news()

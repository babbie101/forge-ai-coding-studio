"""Manual Groq API key smoke check; this is not part of the automated test suite.

Run with ``python scripts/check_groq_connection.py`` after setting ``GROQ_API_KEY``.
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

def main():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your-groq-api-key-here":
        print("Error: GROQ_API_KEY is not set or is still the placeholder.")
        print("Paste your real key into the .env file and try again.")
        raise SystemExit(1)

    client = OpenAI(base_url="https://api.groq.com/openai/v1/", api_key=api_key)
    print("Checking API key...")
    try:
        models = client.models.list()
        print(f"Key is valid. Available models: {len(models.data)}")
        for model in models.data[:5]:
            print(f"  - {model.id}")
    except Exception as error:
        print(f"API call failed: {error}")
        raise SystemExit(1)

    print("\nTesting chat completion...")
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "Say hello in one word."}],
            max_tokens=10,
        )
        print(f"Reply: {response.choices[0].message.content}")
    except Exception as error:
        print(f"Chat failed: {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

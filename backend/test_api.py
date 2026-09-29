import os

import openai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise RuntimeError("OPENROUTER_API_KEY is not set in the environment or .env file.")

print("Testing OpenRouter API...")
client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key,
)

try:
    response = client.chat.completions.create(
        model="qwen/qwen-2.5-72b-instruct",
        messages=[{"role": "user", "content": "Say 'API Working'"}],
    )
    print("✅ SUCCESS:", response.choices[0].message.content)
except Exception as e:
    print("❌ FAILED:", str(e))
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI()

r = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Responde solo: OK"}],
)
print(r.choices[0].message.content)
print("tokens:", r.usage.total_tokens)
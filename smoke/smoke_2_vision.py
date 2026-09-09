import base64
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI()

path = "data/test_contracts/documento1_original.jpg"
with open(path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode("utf-8")

r = client.chat.completions.create(
    model="gpt-4o",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "Transcribe el texto de este documento tal cual aparece."},
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}},
        ],
    }],
)
print(r.choices[0].message.content)
print("\ntokens:", r.usage.total_tokens)
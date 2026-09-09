import base64
import difflib
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI()

IMG_DIR = Path("data/test_contracts")
OUT_DIR = Path("outputs/prep")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PROMPT = (
    "Transcribe el texto de este contrato exactamente como aparece. "
    "Respeta la numeracion y los titulos de las clausulas. "
    "Cada clausula en una linea. No agregues comentarios ni resumas."
)


def transcribir(path: Path) -> str:
    destino = OUT_DIR / f"{path.stem}.txt"
    if destino.exists():
        print(f"  (ya existe) {destino.name}")
        return destino.read_text(encoding="utf-8")

    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    r = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}},
            ],
        }],
    )
    texto = r.choices[0].message.content
    destino.write_text(texto, encoding="utf-8")
    print(f"  transcrito {path.name} -> {r.usage.total_tokens} tokens")
    return texto


for n in (1, 2, 3):
    print(f"\n--- Documento {n} ---")
    original = transcribir(IMG_DIR / f"documento{n}_original.jpg")
    enmienda = transcribir(IMG_DIR / f"documento{n}_enmienda.jpg")

    diff = difflib.unified_diff(
        original.splitlines(),
        enmienda.splitlines(),
        fromfile="original",
        tofile="enmienda",
        lineterm="",
        n=0,
    )
    reporte = "\n".join(diff)
    (OUT_DIR / f"documento{n}_diff.txt").write_text(reporte, encoding="utf-8")

    quitadas = sum(1 for l in reporte.splitlines() if l.startswith("-") and not l.startswith("---"))
    agregadas = sum(1 for l in reporte.splitlines() if l.startswith("+") and not l.startswith("+++"))
    print(f"  diff: {quitadas} lineas quitadas, {agregadas} agregadas")

print(f"\nListo. Revisa {OUT_DIR}")
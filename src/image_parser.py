"""
Parsing multimodal de imagenes de contratos.

Responsabilidades del modulo:
  - validar el archivo de entrada antes de gastar tokens
  - codificar la imagen en base64 con su tipo MIME correcto
  - llamar a GPT-4o Vision con un prompt de transcripcion fiel
  - reintentar errores transitorios de API y fallar rapido ante los permanentes
  - devolver el texto junto con las metricas de uso para el trazado
"""

import base64
import time
from dataclasses import dataclass
from pathlib import Path

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    RateLimitError,
)

# --- Configuracion ---------------------------------------------------------

MODELO_VISION = "gpt-4o"
EXTENSIONES_VALIDAS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
TAMANO_MAXIMO_MB = 20
REINTENTOS = 3
ESPERA_BASE_SEG = 2

PROMPT_VISION = """Eres un transcriptor de documentos legales. Tu unica tarea es
copiar el texto del documento, no interpretarlo.

Reglas:
1. Transcribe el texto completo tal como aparece, sin resumir, corregir ni reformular.
2. Conserva la numeracion y los titulos de las clausulas exactamente como estan.
3. Escribe cada clausula en una linea, precedida por su numero y titulo.
4. No uses formato markdown: ni asteriscos, ni vinetas, ni encabezados.
5. Si un fragmento es ilegible, escribe [ILEGIBLE] en su lugar. Nunca completes
   ni deduzcas un dato que no puedas leer con certeza.

Devuelve unicamente la transcripcion."""


# --- Resultado -------------------------------------------------------------


@dataclass
class ContratoParseado:
    """Texto extraido de una imagen, junto con las metricas de la llamada."""

    texto: str
    archivo: str
    modelo: str
    tokens_prompt: int
    tokens_respuesta: int
    tokens_total: int
    latencia_seg: float


# --- Funciones -------------------------------------------------------------


def validar_imagen(ruta: str) -> Path:
    """Verifica que el archivo exista, tenga formato soportado y peso razonable.

    Falla antes de cualquier llamada a la API para no gastar tokens en vano.
    """
    path = Path(ruta)

    if not path.exists():
        raise FileNotFoundError(f"No se encontro la imagen: {path}")

    if not path.is_file():
        raise ValueError(f"La ruta no apunta a un archivo: {path}")

    extension = path.suffix.lower()
    if extension not in EXTENSIONES_VALIDAS:
        soportadas = ", ".join(sorted(EXTENSIONES_VALIDAS))
        raise ValueError(
            f"Formato no soportado '{extension}' en {path.name}. Se admiten: {soportadas}"
        )

    tamano_mb = path.stat().st_size / (1024 * 1024)
    if tamano_mb == 0:
        raise ValueError(f"El archivo esta vacio: {path.name}")
    if tamano_mb > TAMANO_MAXIMO_MB:
        raise ValueError(
            f"La imagen pesa {tamano_mb:.1f} MB y supera el limite de {TAMANO_MAXIMO_MB} MB: {path.name}"
        )

    return path


def codificar_imagen(path: Path) -> tuple[str, str]:
    """Convierte la imagen a base64 y devuelve (cadena_base64, tipo_mime).

    La API viaja como JSON, que es texto: los bytes crudos de la imagen no se
    pueden enviar directamente. Base64 los traduce a caracteres transmisibles.
    """
    try:
        contenido = path.read_bytes()
    except OSError as e:
        raise OSError(f"No se pudo leer {path.name}: {e}") from e

    b64 = base64.b64encode(contenido).decode("utf-8")
    mime = EXTENSIONES_VALIDAS[path.suffix.lower()]
    return b64, mime


def _construir_mensaje(b64: str, mime: str) -> list[dict]:
    """Arma el mensaje multimodal: instruccion de texto + imagen en una data URI."""
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT_VISION},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
                },
            ],
        }
    ]


def _llamar_con_reintentos(client: OpenAI, mensajes: list[dict]):
    """Llama a la API reintentando solo los errores que se resuelven solos.

    Transitorios (se reintentan con espera creciente): timeout, caida de red,
    limite de tasa. Permanentes (fallan de inmediato): credenciales invalidas,
    peticion malformada. Reintentar una key invalida solo alarga la espera.
    """
    ultimo_error = None

    for intento in range(1, REINTENTOS + 1):
        try:
            return client.chat.completions.create(
                model=MODELO_VISION,
                messages=mensajes,
                temperature=0,
            )
        except (APITimeoutError, APIConnectionError, RateLimitError) as e:
            ultimo_error = e
            if intento == REINTENTOS:
                break
            espera = ESPERA_BASE_SEG * (2 ** (intento - 1))
            print(f"  [reintento {intento}/{REINTENTOS}] {type(e).__name__}; espero {espera}s")
            time.sleep(espera)
        except AuthenticationError as e:
            raise RuntimeError(
                "Credenciales de OpenAI invalidas. Revisa OPENAI_API_KEY en el .env"
            ) from e
        except BadRequestError as e:
            raise RuntimeError(f"La API rechazo la peticion: {e}") from e

    raise RuntimeError(
        f"La API fallo tras {REINTENTOS} intentos: {type(ultimo_error).__name__}: {ultimo_error}"
    ) from ultimo_error


def parse_contract_image(ruta: str, client: OpenAI | None = None) -> ContratoParseado:
    """Extrae el texto de una imagen de contrato usando GPT-4o Vision.

    El cliente se recibe por parametro para reutilizar una sola conexion en todo
    el pipeline y para poder sustituirlo en pruebas.
    """
    client = client or OpenAI()

    path = validar_imagen(ruta)
    b64, mime = codificar_imagen(path)
    mensajes = _construir_mensaje(b64, mime)

    inicio = time.perf_counter()
    respuesta = _llamar_con_reintentos(client, mensajes)
    latencia = time.perf_counter() - inicio

    texto = respuesta.choices[0].message.content
    if not texto or not texto.strip():
        raise RuntimeError(f"El modelo devolvio una transcripcion vacia para {path.name}")

    uso = respuesta.usage
    return ContratoParseado(
        texto=texto.strip(),
        archivo=path.name,
        modelo=respuesta.model,
        tokens_prompt=uso.prompt_tokens,
        tokens_respuesta=uso.completion_tokens,
        tokens_total=uso.total_tokens,
        latencia_seg=round(latencia, 2),
    )


# --- Prueba manual del modulo ---------------------------------------------

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    resultado = parse_contract_image("data/test_contracts/documento1_original.jpg")

    print(resultado.texto)
    print("\n--- metricas ---")
    print(f"archivo:  {resultado.archivo}")
    print(f"modelo:   {resultado.modelo}")
    print(f"tokens:   {resultado.tokens_prompt} -> {resultado.tokens_respuesta} "
          f"(total {resultado.tokens_total})")
    print(f"latencia: {resultado.latencia_seg}s")

    print("\n--- validacion de errores ---")
    for caso in ("data/test_contracts/no_existe.jpg", "requirements.txt"):
        try:
            validar_imagen(caso)
        except (FileNotFoundError, ValueError) as e:
            print(f"  OK, rechazado: {e}")

"""
Demostracion del manejo de errores del sistema.

Recorre las tres capas de defensa: validacion de entrada antes de llamar a la API,
validacion de insumos entre agentes, y validacion del esquema de salida.

No realiza ninguna llamada a la API ni consume tokens: todos los fallos se producen
antes de que haya red de por medio. Es seguro ejecutarlo en vivo.

Uso:
    python demo_errores.py
"""

import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agents.contextualization_agent import ContextualizationAgent  # noqa: E402
from agents.extraction_agent import ExtractionAgent  # noqa: E402
from image_parser import validar_imagen  # noqa: E402
from models import ContractAnalysis, ContractChangeOutput  # noqa: E402

# Construir un ChatOpenAI exige la credencial aunque no se llegue a llamar a la API.
# Los fallos de esta demo ocurren antes de cualquier llamada: no se consumen tokens.
load_dotenv()


def titulo(texto: str) -> None:
    print(f"\n{'=' * 70}")
    print(texto)
    print("=" * 70)


def capa_1_entrada() -> None:
    titulo("CAPA 1 — Validacion de archivos, antes de gastar tokens")
    print("Cada caso falla sin llegar a llamar a la API.\n")

    casos = [
        ("archivo inexistente", "data/test_contracts/no_existe.jpg"),
        ("extension no soportada", "requirements.txt"),
        ("ruta que es un directorio", "data/test_contracts"),
    ]

    for etiqueta, ruta in casos:
        try:
            validar_imagen(ruta)
            print(f"  FALLO: '{etiqueta}' fue aceptado y no debia serlo")
        except (FileNotFoundError, ValueError) as e:
            print(f"  Rechazado ({etiqueta}):\n     {type(e).__name__}: {e}\n")


def capa_2_insumos() -> None:
    titulo("CAPA 2 — Validacion de insumos entre agentes")
    print("Un agente no llama al modelo si recibe un insumo vacio.\n")

    contextualizador = ContextualizationAgent()
    extractor = ExtractionAgent()

    casos = [
        (
            "contextualizacion sin texto original",
            lambda: contextualizador.construir_mapa("", "texto de la enmienda"),
        ),
        (
            "contextualizacion sin texto de enmienda",
            lambda: contextualizador.construir_mapa("texto original", "   "),
        ),
        (
            "extraccion sin mapa de correspondencias",
            lambda: extractor.extraer_cambios("original", "enmienda", ""),
        ),
    ]

    for etiqueta, accion in casos:
        try:
            accion()
            print(f"  FALLO: '{etiqueta}' fue aceptado y no debia serlo")
        except ValueError as e:
            print(f"  Rechazado ({etiqueta}):\n     {e}\n")


def capa_3_esquema() -> None:
    titulo("CAPA 3 — Validacion del esquema de salida")
    print("Cinco formas distintas de salida invalida, cada una atajada por una regla.\n")

    casos = [
        (
            "tipo de cambio fuera del vocabulario",
            {"change_type": "modificado", "summary": "La tarifa cambia de valor.",
             "sections_changed": ["Clausula 3"]},
            "Literal cerrado: impide que 'modificado', 'modificacion' y 'cambio' "
            "entren como tres valores distintos",
        ),
        (
            "resumen sin contenido util",
            {"change_type": "modification", "summary": "Cambio.",
             "sections_changed": ["Clausula 3"]},
            "longitud minima: un resumen de una palabra no le sirve a Compliance",
        ),
        (
            "cambio sin seccion identificada",
            {"change_type": "modification", "summary": "La tarifa anual sube un 25%.",
             "sections_changed": []},
            "min_length: sin seccion no se sabe donde ocurrio el cambio",
        ),
        (
            "secciones en blanco",
            {"change_type": "modification", "summary": "La tarifa anual sube un 25%.",
             "sections_changed": ["  ", ""]},
            "validador propio: el tipado acepta cadenas vacias, la regla de dominio no",
        ),
        (
            "campo inventado por el modelo",
            {"change_type": "modification", "summary": "La tarifa anual sube un 25%.",
             "sections_changed": ["Clausula 3"], "confidence": 0.9},
            "extra='forbid': una alucinacion de campo falla en vez de ignorarse",
        ),
    ]

    for etiqueta, datos, regla in casos:
        try:
            ContractChangeOutput.model_validate(datos)
            print(f"  FALLO: '{etiqueta}' fue aceptado y no debia serlo")
        except ValidationError as e:
            print(f"  Rechazado ({etiqueta}):")
            print(f"     {e.errors()[0]['msg']}")
            print(f"     regla: {regla}\n")


def capa_3b_contenedor() -> None:
    titulo("CAPA 3b — El contenedor tambien valida")
    print("Un analisis sin cambios no es un resultado valido: es un fallo silencioso.\n")

    try:
        ContractAnalysis.model_validate({"changes": []})
        print("  FALLO: un analisis vacio fue aceptado")
    except ValidationError as e:
        print(f"  Rechazado (analisis sin ningun cambio):\n     {e.errors()[0]['msg']}\n")


def main() -> None:
    print("\nDemostracion del manejo de errores — sin llamadas a la API")

    capa_1_entrada()
    capa_2_insumos()
    capa_3_esquema()
    capa_3b_contenedor()

    titulo("RESUMEN")
    print(
        "Las tres capas cubren momentos distintos del pipeline:\n\n"
        "  1. Entrada    evita gastar tokens en archivos invalidos\n"
        "  2. Insumos    evita llamar al modelo con contexto incompleto\n"
        "  3. Esquema    impide entregar datos que no cumplen el contrato de salida\n\n"
        "No cubiertos por esta demo, por requerir condiciones reales de red:\n"
        "  - Errores transitorios de API (timeout, rate limit): se reintentan con\n"
        "    espera creciente, hasta tres veces.\n"
        "  - Errores permanentes (credenciales invalidas): fallan de inmediato, sin\n"
        "    reintentar, porque reintentar una clave invalida solo alarga la espera.\n"
    )


if __name__ == "__main__":
    main()

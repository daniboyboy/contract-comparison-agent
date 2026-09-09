"""
Validacion sobre conjunto reservado.

Los documentos 1 y 3 se usaron como conjunto de desarrollo: sobre ellos se iteraron
los prompts de ambos agentes. El documento 2 no intervino en ninguna de esas
iteraciones y se reserva aqui como conjunto de validacion.

El objetivo es distinguir entre un sistema que generaliza y uno sobreajustado a los
casos con los que fue afinado. Si el documento 2 produce sus cambios esperados sin
haber influido en el diseno de los prompts, hay evidencia de generalizacion.

Verdad de referencia del documento 2, obtenida por diff determinista antes de
cualquier ejecucion del sistema: 7 cambios.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agents.contextualization_agent import ContextualizationAgent  # noqa: E402
from agents.extraction_agent import ExtractionAgent  # noqa: E402

ESPERADOS = {
    "total": 7,
    "por_tipo": {"modification": 6, "addition": 1, "deletion": 0},
    "detalle": [
        "Titulo: agrega '- ENMIENDA' (formal)",
        "Preambulo: se presenta como enmienda del contrato (formal)",
        "Clausula de servicios: agrega 'y analisis regulatorio'",
        "Plazo: 6 -> 9 meses",
        "Tarifa: USD 8.000 -> 9.500 mensuales",
        "Reportes: mensuales -> quincenales",
        "Propiedad Intelectual: clausula nueva (addition)",
    ],
}


def main() -> None:
    load_dotenv()

    prep = Path("outputs/prep")
    original = (prep / "documento2_original.txt").read_text(encoding="utf-8")
    enmienda = (prep / "documento2_enmienda.txt").read_text(encoding="utf-8")

    mapa = ContextualizationAgent().construir_mapa(original, enmienda)
    analisis = ExtractionAgent().extraer_cambios(original, enmienda, mapa)

    conteo = {"modification": 0, "addition": 0, "deletion": 0}
    for cambio in analisis.changes:
        conteo[cambio.change_type] += 1

    print("=" * 70)
    print("VALIDACION — Documento 2 (conjunto reservado)")
    print("=" * 70)

    print("\nEsperado segun diff determinista:")
    for linea in ESPERADOS["detalle"]:
        print(f"  - {linea}")

    print(f"\nDetectado: {len(analisis.changes)} cambios "
          f"(esperados: {ESPERADOS['total']})\n")

    for i, cambio in enumerate(analisis.changes, 1):
        print(f"{i}. [{cambio.change_type}] {', '.join(cambio.sections_changed)}")
        print(f"   {cambio.summary}\n")

    print("-" * 70)
    print("Conteo por tipo:")
    for tipo, esperado in ESPERADOS["por_tipo"].items():
        marca = "OK" if conteo[tipo] == esperado else "REVISAR"
        print(f"  {tipo:<14} detectado {conteo[tipo]}, esperado {esperado}   [{marca}]")

    total_ok = len(analisis.changes) == ESPERADOS["total"]
    print(f"\nTotal: {'OK' if total_ok else 'REVISAR'}")
    print(
        "\nNota: el conteo es una senal, no un veredicto. La revision del contenido de "
        "cada resumen es parte de la validacion."
    )


if __name__ == "__main__":
    main()

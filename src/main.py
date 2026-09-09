"""
Orquestador del pipeline de comparacion de contratos.

Uso:
    python src/main.py <original.jpg> <enmienda.jpg> [--output <archivo.json>]

Encadena las cuatro etapas del analisis bajo una unica traza de Langfuse:

    contract-analysis                (traza raiz)
    |- parse_original_contract       (vision)
    |- parse_amended_contract        (vision)
    |- contextualization_agent       (alineacion de secciones)
    |- extraction_agent              (clasificacion y resumen)

Cada observacion declara su input al abrirse y recibe su output al cerrarse. Las
observaciones creadas manualmente no capturan entradas ni salidas por si solas: sin
asignarlas explicitamente, aparecen vacias en el dashboard y la traza pierde su valor
de auditoria.

Las dos etapas de vision se registran como generaciones y no como spans genericos.
Langfuse solo contabiliza uso y costo en observaciones de tipo generacion: como spans,
sus tokens quedaban fuera del agregado de la traza y el costo total reportado
subestimaba casi la mitad del gasto real del pipeline. Las llamadas de los agentes no
necesitan este tratamiento porque el CallbackHandler de LangChain ya las registra como
generaciones.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.contextualization_agent import ContextualizationAgent  # noqa: E402
from agents.extraction_agent import ExtractionAgent  # noqa: E402
from image_parser import MODELO_VISION, parse_contract_image  # noqa: E402
from models import ContractAnalysis  # noqa: E402

DIRECTORIO_SALIDA = Path("outputs")


def verificar_esquema(analisis: ContractAnalysis) -> ContractAnalysis:
    """Segunda validacion explicita sobre el resultado ya estructurado.

    El agente de extraccion devuelve un objeto que `with_structured_output` ya valido.
    Esta comprobacion es deliberadamente redundante: es la red que atrapa una salida
    corrupta si el camino principal cambia, y hace explicito en el orquestador el
    punto donde el sistema se niega a entregar datos que no cumplen el contrato.
    """
    try:
        return ContractAnalysis.model_validate(analisis.model_dump())
    except ValidationError as e:
        detalle = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:5]
        )
        raise RuntimeError(
            f"El analisis no cumple el esquema de salida y no se entregara: {detalle}"
        ) from e


def analizar_contratos(ruta_original: str, ruta_enmienda: str) -> dict:
    """Ejecuta el pipeline completo bajo una unica traza jerarquica."""
    langfuse = get_client()
    handler = CallbackHandler()

    with langfuse.start_as_current_observation(
        as_type="span",
        name="contract-analysis",
        input={"contrato_original": ruta_original, "contrato_enmendado": ruta_enmienda},
    ) as traza:

        # --- Etapa 1: parseo del contrato original --------------------------
        print("[1/4] Parseando contrato original...")
        with langfuse.start_as_current_observation(
            as_type="generation",
            name="parse_original_contract",
            model=MODELO_VISION,
            model_parameters={"temperature": 0, "detail": "high"},
            input={"archivo": ruta_original},
        ) as generacion:
            original = parse_contract_image(ruta_original)
            generacion.update(
                output={"texto": original.texto},
                usage_details={
                    "input": original.tokens_prompt,
                    "output": original.tokens_respuesta,
                },
                metadata={"latencia_seg": original.latencia_seg},
            )
        print(f"      {original.tokens_total} tokens, {original.latencia_seg}s")

        # --- Etapa 2: parseo de la enmienda ---------------------------------
        print("[2/4] Parseando contrato enmendado...")
        with langfuse.start_as_current_observation(
            as_type="generation",
            name="parse_amended_contract",
            model=MODELO_VISION,
            model_parameters={"temperature": 0, "detail": "high"},
            input={"archivo": ruta_enmienda},
        ) as generacion:
            enmienda = parse_contract_image(ruta_enmienda)
            generacion.update(
                output={"texto": enmienda.texto},
                usage_details={
                    "input": enmienda.tokens_prompt,
                    "output": enmienda.tokens_respuesta,
                },
                metadata={"latencia_seg": enmienda.latencia_seg},
            )
        print(f"      {enmienda.tokens_total} tokens, {enmienda.latencia_seg}s")

        # --- Etapa 3: contextualizacion -------------------------------------
        print("[3/4] Alineando secciones (agente de contextualizacion)...")
        with langfuse.start_as_current_observation(
            as_type="span",
            name="contextualization_agent",
            input={"texto_original": original.texto, "texto_enmienda": enmienda.texto},
        ) as span:
            mapa = ContextualizationAgent().construir_mapa(
                original.texto, enmienda.texto, config={"callbacks": [handler]}
            )
            span.update(
                output={"mapa_de_correspondencias": mapa},
                metadata={"rol": "alineacion mecanica de secciones, sin interpretacion"},
            )

        # --- Etapa 4: extraccion --------------------------------------------
        print("[4/4] Clasificando cambios (agente de extraccion)...")
        with langfuse.start_as_current_observation(
            as_type="span",
            name="extraction_agent",
            input={
                "texto_original": original.texto,
                "texto_enmienda": enmienda.texto,
                "mapa_de_correspondencias": mapa,
            },
        ) as span:
            analisis = ExtractionAgent().extraer_cambios(
                original.texto, enmienda.texto, mapa, config={"callbacks": [handler]}
            )
            analisis = verificar_esquema(analisis)
            span.update(
                output=analisis.model_dump(),
                metadata={"cambios_detectados": len(analisis.changes)},
            )

        # El id de traza enlaza el resultado con la evidencia de como se produjo.
        try:
            trace_id = langfuse.get_current_trace_id()
        except Exception:
            trace_id = None

        resultado = {
            "contrato_original": ruta_original,
            "contrato_enmendado": ruta_enmienda,
            "fecha_analisis": datetime.now().isoformat(timespec="seconds"),
            "trace_id": trace_id,
            "tokens_parsing": original.tokens_total + enmienda.tokens_total,
            "cambios_detectados": len(analisis.changes),
            "analisis": analisis.model_dump(),
        }

        traza.update(output={"cambios_detectados": len(analisis.changes)})

    langfuse.flush()
    return resultado


def guardar(resultado: dict, destino: str | None) -> Path:
    DIRECTORIO_SALIDA.mkdir(parents=True, exist_ok=True)

    if destino:
        path = Path(destino)
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre = Path(resultado["contrato_original"]).stem
        path = DIRECTORIO_SALIDA / f"analisis_{nombre}_{marca}.json"

    path.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def imprimir_resumen(resultado: dict) -> None:
    cambios = resultado["analisis"]["changes"]

    print(f"\n{'=' * 70}")
    print(f"{len(cambios)} cambios detectados")
    print("=" * 70)

    for i, cambio in enumerate(cambios, 1):
        secciones = ", ".join(cambio["sections_changed"])
        print(f"\n{i}. [{cambio['change_type']}] {secciones}")
        print(f"   {cambio['summary']}")

    if resultado["trace_id"]:
        print(f"\nTraza: {resultado['trace_id']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compara dos versiones de un contrato a partir de sus imagenes."
    )
    parser.add_argument("original", help="Ruta a la imagen del contrato original")
    parser.add_argument("enmienda", help="Ruta a la imagen del contrato enmendado")
    parser.add_argument("--output", help="Ruta del JSON de salida (opcional)")
    args = parser.parse_args()

    load_dotenv()

    try:
        resultado = analizar_contratos(args.original, args.enmienda)
    except (FileNotFoundError, ValueError) as e:
        print(f"\nError en los archivos de entrada: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"\nError durante el analisis: {e}", file=sys.stderr)
        return 1

    imprimir_resumen(resultado)
    destino = guardar(resultado, args.output)
    print(f"Resultado guardado en: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

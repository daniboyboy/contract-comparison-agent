"""
Agente 1: contextualizacion.

Responsabilidad unica: alinear las secciones del contrato original con las de la
enmienda y registrar de forma mecanica las diferencias textuales entre cada par. No
clasifica ni interpreta los cambios; eso es trabajo del agente de extraccion.

El registro es deliberadamente mecanico (texto suprimido, texto agregado, valores
modificados) y no interpretativo. Una nota en prosa del tipo "cambio en el alcance de
la licencia" ancla al agente 2 en esa lectura y le hace pasar por alto otras
diferencias del mismo par. Tres listas crudas no anclan: obligan a que toda supresion
quede visible aunque el resto de la clausula se haya reescrito.

Por que existe: si un solo agente recibe los dos contratos completos, debe hacer
dos trabajos a la vez, alinear clausulas y analizar diferencias. Cuando hay
clausulas renumeradas o insertadas en el medio, el modelo se equivoca alineando y
arrastra ese error al analisis. Separar la alineacion produce un mapa explicito que
el agente 2 recibe como insumo: no repite el trabajo, se apoya en el.

La salida es texto estructurado y no JSON de forma deliberada. El mapa es un insumo
intermedio que consume otro LLM, no codigo. Validar con Pydantic aqui agregaria un
punto de falla sin beneficio; la salida estructurada se reserva para el resultado
final, que si consume una maquina.
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

MODELO = "gpt-4o"

SYSTEM_PROMPT = """Eres un analista documental especializado en contratos. Tu unica
tarea es alinear las secciones de dos versiones de un mismo contrato y registrar de
forma mecanica las diferencias textuales entre ellas. No interpretas ni evaluas la
importancia de los cambios: eso lo hace otro analista despues.

Procede asi:

1. Identifica las secciones de cada documento. Trata como secciones tambien el TITULO
   del documento y el PREAMBULO (la frase inicial que identifica a las partes y la
   fecha), aunque no esten numerados.
2. Empareja cada seccion del original con su contraparte en la enmienda. La numeracion
   puede haber cambiado: guiate por el contenido, no por el numero.
3. Para cada par, registra las diferencias textuales en tres listas mecanicas.

REGLA CRITICA 1 — texto suprimido:
Compara palabra por palabra. Toda palabra o frase que aparezca en el original y no en
la enmienda va en la lista de texto suprimido, aunque el resto de la clausula se haya
reescrito y aunque la supresion parezca menor. No decidas si es importante: registrala.
La supresion de un solo adjetivo puede eliminar una restriccion sustantiva.

REGLA CRITICA 2 — grupo de identicas:
Una seccion solo puede declararse identica si su texto coincide palabra por palabra.
Cualquier diferencia la excluye de ese grupo. Ante la duda, listala como par a
inspeccionar.

Responde exactamente con este formato, sin markdown ni comentarios adicionales:

PARES A INSPECCIONAR
- [seccion del original] <-> [seccion de la enmienda]
  * texto suprimido: [palabras o frases del original ausentes en la enmienda | ninguno]
  * texto agregado: [palabras o frases nuevas en la enmienda | ninguno]
  * valores modificados: [valor anterior -> valor nuevo, separados por comas | ninguno]
- ...

SIN CONTRAPARTE
- [seccion] | presente solo en: [original | enmienda]
- ...
(escribe "ninguna" si no hay)

IDENTICAS PALABRA POR PALABRA
- [lista de secciones separadas por comas]
(escribe "ninguna" si no hay)"""

USER_PROMPT = """CONTRATO ORIGINAL:
{original}

CONTRATO ENMENDADO:
{enmienda}

Produce el mapa de correspondencias."""


class ContextualizationAgent:
    """Alinea las secciones de dos versiones de un contrato."""

    def __init__(self, modelo: str = MODELO, temperatura: float = 0):
        self.llm = ChatOpenAI(model=modelo, temperature=temperatura)
        self.prompt = ChatPromptTemplate.from_messages(
            [("system", SYSTEM_PROMPT), ("user", USER_PROMPT)]
        )
        self.chain = self.prompt | self.llm

    def construir_mapa(self, original: str, enmienda: str, config: dict | None = None) -> str:
        """Devuelve el mapa de correspondencias entre ambos documentos.

        `config` permite inyectar los callbacks de Langfuse desde el orquestador
        sin que el agente conozca nada del sistema de trazado.
        """
        if not original or not original.strip():
            raise ValueError("El texto del contrato original esta vacio")
        if not enmienda or not enmienda.strip():
            raise ValueError("El texto de la enmienda esta vacio")

        respuesta = self.chain.invoke(
            {"original": original, "enmienda": enmienda},
            config=config or {},
        )

        mapa = respuesta.content
        if not mapa or not mapa.strip():
            raise RuntimeError("El agente de contextualizacion devolvio un mapa vacio")

        return mapa.strip()


# --- Prueba manual del modulo ---------------------------------------------

if __name__ == "__main__":
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv()

    # Se usan las transcripciones ya cacheadas para no volver a pagar vision.
    PREP = Path("outputs/prep")

    agente = ContextualizationAgent()

    for n in (3, 1):
        etiqueta = "CASO SIMPLE" if n == 3 else "CASO COMPLEJO"
        original = (PREP / f"documento{n}_original.txt").read_text(encoding="utf-8")
        enmienda = (PREP / f"documento{n}_enmienda.txt").read_text(encoding="utf-8")

        print(f"\n{'=' * 70}")
        print(f"Documento {n} — {etiqueta}")
        print("=" * 70)
        print(agente.construir_mapa(original, enmienda))

"""
Agente 2: extraccion y clasificacion de cambios.

Responsabilidad unica: a partir de los dos textos y del mapa producido por el agente
de contextualizacion, identificar cada cambio sustantivo, clasificarlo y resumirlo en
una estructura validada.

Handoff: este agente no repite la alineacion. Recibe el mapa como insumo y lo usa para
saber donde mirar, de modo que puede dedicar su atencion a analizar diferencias en
lugar de emparejar clausulas.

Salida: `ContractAnalysis` validado por Pydantic mediante `.with_structured_output()`.
Si la validacion falla, se reintenta una vez devolviendo al modelo el mensaje de error
concreto, que suele bastar para que corrija el campo problematico.
"""

import sys
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

# Permite ejecutar este modulo suelto para probarlo, sin romper el import desde main.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import ContractAnalysis  # noqa: E402

MODELO = "gpt-4o"
REINTENTOS = 2

SYSTEM_PROMPT = """Eres un analista legal de un equipo de Compliance. Recibes dos
versiones de un contrato y un mapa de correspondencias entre sus secciones, elaborado
previamente por un analista documental. Tu tarea es identificar cada cambio sustantivo,
clasificarlo y resumirlo.

Como usar el mapa:
El mapa registra, para cada par de secciones, tres listas mecanicas: texto suprimido,
texto agregado y valores modificados. Incluye tambien el titulo y el preambulo como
secciones. Usa esas listas como punto de partida, pero verifica el texto por tu cuenta:
el mapa puede ser incompleto, nunca al reves.

REGLA DE CORRESPONDENCIA: cuando un par tenga texto suprimido distinto de "ninguno",
determina si ese texto fue REEMPLAZADO por otro equivalente en la misma posicion.

La prueba se aplica ELEMENTO POR ELEMENTO, no a la clausula completa. Para cada
elemento suprimido preguntate: existe en la enmienda algo que cumpla la MISMA FUNCION
que cumplia ese elemento?

- Si existe, es parte de una 'modification'. Un monto sustituido por otro monto, un
  plazo por otro plazo, un porcentaje por otro porcentaje.
- Si no existe, es un 'deletion' y debes reportarlo como cambio independiente, ademas
  de cualquier modificacion del mismo par.

ADVERTENCIA: que una clausula haya sido reescrita NO significa que sus elementos
suprimidos hayan sido reemplazados. Presta atencion especial a restricciones,
prohibiciones, condiciones y calificadores que desaparecen (adjetivos como
"intransferible", "exclusiva", adverbios como "unicamente"). Si un calificador
desaparece y la nueva redaccion no impone ninguna limitacion equivalente, eso es una
eliminacion, aunque el resto de la clausula se haya reformulado por completo.

Ejemplos:
- "USD 1.200" pasa a "USD 1.250": hay reemplazo funcional. Es 'modification'.
- "licencia no exclusiva e intransferible" pasa a "licencia no exclusiva": nada cumple
  la funcion de "intransferible" en la nueva redaccion. Es 'deletion', ademas de
  cualquier otra modificacion en la misma clausula.

Reglas de analisis:

1. Una misma clausula puede contener mas de un cambio. Si una clausula elimina una
   obligacion o restriccion y ademas modifica terminos, repórtalos como dos cambios
   separados, no como uno solo.

2. Presta especial atencion a las palabras o frases que desaparecen dentro de una
   clausula reformulada. La supresion de un adjetivo o de una condicion puede alterar
   derechos sustantivos y es facil de pasar por alto cuando el resto de la clausula se
   reescribe. Clasifica esos casos como 'deletion'.

3. Se exhaustivo: reporta TODOS los cambios, por minimos que sean, incluidos los
   del titulo y del preambulo. No omitas ninguna diferencia de contenido. Cuando un
   cambio sea formal y no altere obligaciones de las partes, dilo explicitamente en
   el resumen (por ejemplo: "cambio formal, no altera obligaciones"), pero
   repórtalo igual.

3b. La unica excepcion son las diferencias atribuibles a la transcripcion de las
   imagenes: espaciado irregular, tipo de comillas, acentos faltantes o errores de
   lectura evidentes. Esas no son cambios del documento sino de su lectura, y
   afirmar lo contrario seria un error factual sobre un documento legal. No las
   reportes.

4. El tipo de cambio lo determina la SECCION, no el texto. Solo es 'addition' una
   seccion completa que no tenia contraparte en el original. Si la seccion existe en
   ambas versiones y gana contenido, es 'modification'. El titulo y el preambulo
   existen en ambas versiones: sus cambios son siempre 'modification'.

5. No cuentes el mismo fragmento dos veces. Si una frase suprimida ya se reporto como
   'deletion', la modificacion asociada a ese par debe describir lo que efectivamente
   se reformulo, sin repetir la supresion ya reportada.

6. Identifica las secciones con la numeracion y el titulo que usa el contrato.

7. No reportes cambios que no puedas sustentar citando el texto de ambas versiones.
   Es preferible omitir una diferencia dudosa a inventar una."""

USER_PROMPT = """CONTRATO ORIGINAL:
{original}

CONTRATO ENMENDADO:
{enmienda}

MAPA DE CORRESPONDENCIAS:
{mapa}

Identifica y clasifica todos los cambios sustantivos.{correccion}"""


class ExtractionAgent:
    """Extrae y clasifica los cambios entre dos versiones de un contrato."""

    def __init__(self, modelo: str = MODELO, temperatura: float = 0):
        self.llm = ChatOpenAI(model=modelo, temperature=temperatura)
        self.prompt = ChatPromptTemplate.from_messages(
            [("system", SYSTEM_PROMPT), ("user", USER_PROMPT)]
        )
        self.chain = self.prompt | self.llm.with_structured_output(ContractAnalysis)

    def extraer_cambios(
        self,
        original: str,
        enmienda: str,
        mapa: str,
        config: dict | None = None,
    ) -> ContractAnalysis:
        """Devuelve los cambios detectados, validados contra el esquema.

        Ante un fallo de validacion se reintenta una vez incluyendo en el prompt el
        error concreto que devolvio Pydantic. Un mensaje del tipo "change_type debe ser
        addition, deletion o modification" suele ser suficiente para que el modelo
        corrija el campo, y evita descartar todo el analisis por un valor mal escrito.
        """
        for campo, valor in (("original", original), ("enmienda", enmienda), ("mapa", mapa)):
            if not valor or not valor.strip():
                raise ValueError(f"El insumo '{campo}' esta vacio")

        correccion = ""
        ultimo_error = None

        for intento in range(1, REINTENTOS + 1):
            try:
                resultado = self.chain.invoke(
                    {
                        "original": original,
                        "enmienda": enmienda,
                        "mapa": mapa,
                        "correccion": correccion,
                    },
                    config=config or {},
                )
                if resultado is None:
                    raise ValidationError.from_exception_data("ContractAnalysis", [])
                return resultado

            except ValidationError as e:
                ultimo_error = e
                detalle = "; ".join(
                    f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                    for err in e.errors()[:5]
                )
                print(f"  [validacion fallida, intento {intento}/{REINTENTOS}] {detalle}")
                correccion = (
                    f"\n\nTu respuesta anterior no cumplio el esquema requerido. "
                    f"Errores detectados: {detalle}. "
                    f"Corrige esos campos y responde de nuevo respetando el esquema."
                )

        raise RuntimeError(
            f"El agente de extraccion no produjo una salida valida tras {REINTENTOS} "
            f"intentos. Ultimo error: {ultimo_error}"
        ) from ultimo_error


# --- Prueba manual del modulo ---------------------------------------------

if __name__ == "__main__":
    from dotenv import load_dotenv

    from agents.contextualization_agent import ContextualizationAgent

    load_dotenv()

    PREP = Path("outputs/prep")

    contextualizador = ContextualizationAgent()
    extractor = ExtractionAgent()

    for n in (3, 1):
        etiqueta = "CASO SIMPLE (4 cambios esperados)" if n == 3 else "CASO COMPLEJO (9 cambios esperados)"
        original = (PREP / f"documento{n}_original.txt").read_text(encoding="utf-8")
        enmienda = (PREP / f"documento{n}_enmienda.txt").read_text(encoding="utf-8")

        print(f"\n{'=' * 70}")
        print(f"Documento {n} — {etiqueta}")
        print("=" * 70)

        mapa = contextualizador.construir_mapa(original, enmienda)
        analisis = extractor.extraer_cambios(original, enmienda, mapa)

        print(f"\nCambios detectados: {len(analisis.changes)}\n")
        for i, cambio in enumerate(analisis.changes, 1):
            print(f"{i}. [{cambio.change_type}] {', '.join(cambio.sections_changed)}")
            print(f"   {cambio.summary}\n")

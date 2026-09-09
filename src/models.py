"""
Modelos de datos de salida del sistema.

Definen el contrato estructurado que produce el agente de extraccion. Las
descripciones de cada campo no son documentacion interna: cuando se usa
`.with_structured_output()`, LangChain traduce estos modelos a un esquema JSON
que viaja a la API, y esas descripciones llegan al modelo como instrucciones.
Son, en la practica, parte del prompt.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TipoDeCambio = Literal["addition", "deletion", "modification"]


class ContractChangeOutput(BaseModel):
    """Un cambio individual detectado entre el contrato original y su enmienda.

    Se modela un cambio por objeto, no un objeto por documento: una enmienda
    puede contener adiciones, eliminaciones y modificaciones a la vez, de modo
    que un unico `change_type` para todo el documento seria inexacto. Ademas,
    un cambio por objeto permite que cada uno se apruebe o se marque para
    revision de forma independiente.
    """

    model_config = ConfigDict(extra="forbid")

    change_type: TipoDeCambio = Field(
        description=(
            "Tipo de cambio. 'addition' si la enmienda incorpora una clausula o "
            "disposicion que no existia. 'deletion' si elimina una obligacion, "
            "restriccion o derecho presente en el original, incluso cuando la "
            "eliminacion ocurre dentro de una clausula reformulada. "
            "'modification' si altera terminos existentes (montos, plazos, "
            "porcentajes, alcance)."
        )
    )

    summary: str = Field(
        min_length=15,
        description=(
            "Resumen del cambio en lenguaje claro, orientado a un equipo de "
            "Compliance. Debe indicar que se modifico y cual es su implicancia "
            "practica. Cuando hay valores concretos, citar el valor anterior y "
            "el nuevo."
        ),
    )

    sections_changed: list[str] = Field(
        min_length=1,
        description=(
            "Identificadores de las secciones afectadas, tal como aparecen en el "
            "documento (por ejemplo 'Clausula 3. Pago'). No inventar numeracion: "
            "usar la del contrato."
        ),
    )

    @field_validator("sections_changed")
    @classmethod
    def secciones_no_vacias(cls, valor: list[str]) -> list[str]:
        """Rechaza listas con cadenas en blanco.

        El tipado garantiza que sean strings, no que identifiquen algo. Un cambio
        sin seccion identificable no le sirve a Compliance.
        """
        limpias = [s.strip() for s in valor if s and s.strip()]
        if not limpias:
            raise ValueError("sections_changed no puede contener solo cadenas vacias")
        return limpias

    @field_validator("summary")
    @classmethod
    def resumen_con_contenido(cls, valor: str) -> str:
        limpio = valor.strip()
        if len(limpio) < 15:
            raise ValueError("summary es demasiado breve para describir el cambio")
        return limpio


class ContractAnalysis(BaseModel):
    """Conjunto de cambios detectados en una comparacion de contratos."""

    model_config = ConfigDict(extra="forbid")

    changes: list[ContractChangeOutput] = Field(
        min_length=1,
        description=(
            "Lista de todos los cambios sustantivos detectados entre el contrato "
            "original y su enmienda. Excluir cambios puramente formales, como la "
            "modificacion del titulo o del preambulo cuando el documento se "
            "presenta como enmienda: no alteran obligaciones de las partes."
        ),
    )


# --- Prueba manual del modulo ---------------------------------------------

if __name__ == "__main__":
    from pydantic import ValidationError

    print("--- caso valido ---")
    cambio = ContractChangeOutput(
        change_type="modification",
        summary="La tarifa anual de licencia sube de USD 12.000 a USD 15.000, un 25% mas.",
        sections_changed=["Clausula 3. Pago"],
    )
    print(cambio.model_dump_json(indent=2))

    print("\n--- casos que deben ser rechazados ---")
    casos_invalidos = [
        (
            "tipo de cambio fuera del enum",
            {"change_type": "modificado", "summary": "La tarifa cambia de valor.",
             "sections_changed": ["Clausula 3"]},
        ),
        (
            "resumen demasiado breve",
            {"change_type": "modification", "summary": "Cambio.",
             "sections_changed": ["Clausula 3"]},
        ),
        (
            "sin secciones identificadas",
            {"change_type": "modification", "summary": "La tarifa anual sube un 25%.",
             "sections_changed": []},
        ),
        (
            "secciones en blanco",
            {"change_type": "modification", "summary": "La tarifa anual sube un 25%.",
             "sections_changed": ["  ", ""]},
        ),
        (
            "campo inventado por el modelo",
            {"change_type": "modification", "summary": "La tarifa anual sube un 25%.",
             "sections_changed": ["Clausula 3"], "confidence": 0.9},
        ),
    ]

    for etiqueta, datos in casos_invalidos:
        try:
            ContractChangeOutput.model_validate(datos)
            print(f"  FALLO: '{etiqueta}' fue aceptado y no debia serlo")
        except ValidationError as e:
            motivo = e.errors()[0]["msg"]
            print(f"  OK, rechazado ({etiqueta}): {motivo}")

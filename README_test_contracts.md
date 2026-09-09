# Contratos de prueba

Tres pares de documentos escaneados en JPEG, cada uno con un contrato original y su
enmienda. Provistos con la consigna del proyecto.

Los cambios listados aquí se obtuvieron comparando las transcripciones con `difflib`, un
diff determinista, antes de ejecutar el sistema por primera vez. Se usan como verdad de
referencia para evaluar la detección. No se generaron con un modelo de lenguaje: usar el
mismo modelo que después realiza la extracción habría significado evaluarlo con su propia
tarea.

---

## Roles

| Documento | Tipo de contrato | Rol | Cambios |
|---|---|---|---|
| `documento1_*` | Licencia de software | Desarrollo | 10 |
| `documento2_*` | Consultoría | **Validación** | 7 |
| `documento3_*` | Servicio SaaS | Desarrollo | 4 |

Los prompts se iteraron usando únicamente los documentos 1 y 3. El documento 2 se mantuvo
reservado y solo se ejecutó una vez terminado el desarrollo, para verificar que el sistema
generaliza en lugar de estar ajustado a sus propios casos de prueba.

---

## documento1 — Licencia de software (caso complejo)

TechNova S.A. y DataBridge Soluciones S.R.L. Contiene los tres tipos de cambio.

| Sección | Cambio | Tipo |
|---|---|---|
| Título | Agrega "– ENMIENDA" | modification (formal) |
| Preámbulo | Se presenta como enmienda del contrato | modification (formal) |
| 1. Otorgamiento de Licencia | Desaparece "e intransferible" | **deletion** |
| 1. Otorgamiento de Licencia | Desaparece "únicamente" | **deletion** |
| 1. Otorgamiento de Licencia | "fines internos de la empresa" → "operaciones internas de negocio" | modification |
| 2. Plazo | 12 → 24 meses | modification |
| 3. Pago | USD 12.000 → 15.000 anuales | modification |
| 4. Soporte | Agrega canal de chat | modification |
| 5. Terminación | 30 → 60 días de preaviso | modification |
| 7. Protección de Datos | Cláusula nueva | **addition** |

Es el caso más exigente. Las dos supresiones de la cláusula 1 ocurren dentro de un párrafo
que además se reformula, de modo que un análisis superficial las reporta como un simple
cambio de redacción. Legalmente son lo más relevante del documento: levantan la restricción
de transferencia de la licencia y amplían el uso permitido.

---

## documento2 — Consultoría (validación)

Orion Consulting Group y GreenWave Energía S.A.

| Sección | Cambio | Tipo |
|---|---|---|
| Título | Agrega "– ENMIENDA" | modification (formal) |
| Preámbulo | Se presenta como enmienda del contrato | modification (formal) |
| 1. Alcance del Servicio | Agrega "y análisis regulatorio" | modification |
| 2. Duración | 6 → 9 meses | modification |
| 3. Honorarios | USD 8.000 → 9.500 mensuales | modification |
| 4. Entregables | Reportes mensuales → quincenales | modification |
| 7. Propiedad Intelectual | Cláusula nueva | **addition** |

Sin eliminaciones: todo lo que se suprime tiene reemplazo funcional.

---

## documento3 — Servicio SaaS (caso simple)

CloudMetrics Ltd. y RetailPulse S.A.

| Sección | Cambio | Tipo |
|---|---|---|
| Título | Agrega "– VERSIÓN ACTUALIZADA" | modification (formal) |
| 3. Precio | USD 1.200 → 1.250 mensuales | modification |
| 4. Disponibilidad del Servicio | 99,5% → 99,9% | modification |
| 5. Soporte | Agrega sistema de tickets en línea | modification |

Solo modificaciones, sin adiciones ni eliminaciones. Sirve como caso de referencia mínimo.

---

## Reproducir la comparación

```bash
python prep_ground_truth.py
```

Transcribe las seis imágenes, guarda los textos en `outputs/prep/` y genera un diff por
cada par. Las transcripciones se cachean: correr el script de nuevo no repite las llamadas
al modelo de visión.

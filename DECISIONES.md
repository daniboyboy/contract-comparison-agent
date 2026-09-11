# Decisiones de diseño

Registro de las decisiones técnicas del proyecto, sus justificaciones, las alternativas
descartadas y el historial de iteración de los prompts con sus mediciones.

Este documento se escribió durante el desarrollo, no después: cada decisión quedó
registrada al momento de tomarla, junto con el problema que la motivó. El objetivo es que
el razonamiento detrás del sistema sea verificable y no solo afirmado.

---

## 1. Contexto

Sistema multi-agente que recibe imágenes escaneadas de un contrato y su enmienda,
extrae el texto con un modelo de visión, y mediante dos agentes especializados
identifica y resume los cambios legales, devolviendo un JSON validado y trazado.

---

## 2. Decisiones de diseño

### 2.1 Qué significa "agente" en esta implementación

**Decisión:** dos clases propias, cada una con su system prompt y una chain LCEL
(`ChatPromptTemplate | ChatOpenAI`). No se usa `AgentExecutor` ni un agente ReAct
con herramientas.

**Justificación:** no hay herramientas externas que invocar. Un loop de razonamiento
sin tools agrega latencia, no determinismo y puntos de falla en una demo en vivo,
sin aportar capacidad. La consigna pide responsabilidades especializadas y un
handoff de contexto, no autonomía.

**Cómo defenderlo:** son agentes en el sentido de *rol especializado con contrato de
entrada/salida propio y estado que se traspasa*, no en el sentido de *loop autónomo
con tools*. 

### 2.2 Modelos

**Decisión:** `gpt-4o` para el parsing de visión y para ambos agentes. `temperature=0`
en todo el pipeline. `detail="high"` en las llamadas de visión.

**Justificación:** la rúbrica nombra GPT-4o explícitamente (criterio 1.1).
`detail="high"` cuesta más tokens pero en `low` la imagen se comprime a 512×512 y se
pierde texto pequeño: en un contrato, perder un número es perder todo.

**Alternativa descartada:** `gpt-4o-mini` para el Agente 1, por ahorro. Se descartó
por consistencia.

### 2.3 Validación

**Decisión:** camino principal con `.with_structured_output(ContractChangeOutput)` en
el Agente 2. Red de seguridad con `model_validate()` explícito en `main.py`, dentro de
un `try/except ValidationError` con un reintento que devuelve el mensaje de error al
modelo.

**Justificación:** cubre las dos formas que admite la consigna y produce algo
demostrable: en la defensa se puede forzar un fallo y mostrar que el sistema no se cae.
La rúbrica pide literalmente "maneja excepciones de validación con elegancia".

### 2.4 Trazabilidad

**Decisión:** traza raíz `contract-analysis` con context managers de Langfuse y cuatro
spans hijos (parse original, parse enmienda, contextualización, extracción). El
`CallbackHandler` de LangChain se usa dentro de esos spans.

**Justificación:** los spans manuales representan etapas de negocio; el handler rellena
solo el detalle técnico de cada llamada. No hay que instrumentar a mano lo interno.

### 2.5 Verdad de referencia por diff determinista

**Decisión:** el inventario de cambios esperados se generó comparando las
transcripciones con `difflib`, no con un LLM.

**Justificación:** un diff algorítmico es determinista e independiente del criterio del
modelo que se está evaluando. Si el inventario lo generara el mismo GPT-4o que después
extrae los cambios, se estaría calificando al modelo con su propia tarea.

**Cómo defenderlo:** responde también a "¿por qué no resolviste todo con difflib?" —
el diff detecta *qué* texto cambió, pero no puede clasificar el cambio como adición,
eliminación o modificación con criterio legal, ni detectar que una frase eliminada
dentro de una cláusula reformulada es lo jurídicamente relevante.

---

### 2.6 Un objeto por cambio, no uno por documento

**Decision:** `ContractChangeOutput` modela un cambio individual. El agente de
extraccion devuelve un contenedor `ContractAnalysis` con la lista de todos ellos.

**Justificacion:** una enmienda puede contener adiciones, eliminaciones y
modificaciones a la vez (el documento 1 tiene las tres), de modo que un unico
`change_type` para todo el documento seria factualmente incorrecto. Ademas, un objeto
por cambio permite que Compliance apruebe unos y marque otros para revision de forma
independiente; con un objeto monolitico solo se puede aceptar o rechazar todo.

**Alternativa descartada:** un solo objeto por documento. Mas simple, pero produce un
resultado inexacto.

### 2.7 Validacion mas alla del tipado

**Decision:** ademas de los tipos, se agregan `Literal` cerrado en `change_type`,
longitud minima en `summary`, `min_length=1` en las listas, validadores propios que
rechazan cadenas en blanco, y `extra="forbid"` en ambos modelos.

**Justificacion:** el tipado garantiza que `sections_changed` sea una lista de strings,
no que identifique algo. Un `str` libre en `change_type` aceptaria "modificado",
"modificacion" y "cambio de clausula" como valores distintos y validos; el `Literal`
fuerza un vocabulario unico y dispara el reintento ante cualquier otra cosa.
`extra="forbid"` hace que un campo inventado por el modelo falle en vez de ignorarse
en silencio. Las descripciones de los campos no son documentacion interna: con
`.with_structured_output()` viajan al modelo como parte del prompt.

---

### 2.8 Exhaustividad total, con una sola excepción

**Decisión:** el sistema reporta TODOS los cambios entre las dos versiones, por
mínimos que sean, incluidos los del título y del preámbulo. Cuando un cambio es formal
y no altera obligaciones, se reporta igual y se indica esa condición en el `summary`.

**Única excepción:** las diferencias atribuibles a la transcripción de las imágenes
—espaciado, tipo de comillas, acentos, errores de lectura evidentes— no se reportan.
No son cambios del documento sino de su lectura; afirmar que el contrato cambió cuando
lo que cambió fue la lectura es un error factual sobre un documento legal, y más grave
que una omisión.

**Justificación:** un revisor de Compliance quiere ver todo lo que cambió en el papel y
decidir él qué es relevante. La distinción entre sustantivo y formal la aporta el
resumen, no la omisión. Ejemplo del riesgo que motiva la excepción: en una corrida la
visión transcribió "yDataBridge" sin espacio, y en el documento 2 alternó comillas
curvas y rectas; reportar eso como modificación contractual sería un falso positivo.

---

### 2.9 El mapa se registra de forma mecánica, no interpretativa

**Decisión:** el agente de contextualización no anota una "diferencia aparente" en
prosa por cada par de secciones. Registra tres listas crudas: **texto suprimido**,
**texto agregado** y **valores modificados**. Además trata el título y el preámbulo
como secciones, aunque no estén numerados.

En el agente de extracción se agrega una regla de correspondencia: si un par tiene
texto suprimido distinto de "ninguno", eso implica necesariamente un cambio `deletion`
que debe reportarse por separado de cualquier modificación del mismo par.

**Justificación:** ver el hallazgo de la Etapa 6 más abajo. Una nota en prosa del tipo
"cambio en el alcance de la licencia" ancla al agente 2 en esa lectura y le hace pasar
por alto otras diferencias del mismo par. Tres listas mecánicas no anclan: obligan a
que toda supresión quede visible aunque el resto de la cláusula se haya reescrito.

**Efecto secundario en la arquitectura:** la división de responsabilidades queda más
nítida. El agente 1 es un detector mecánico de diferencias textuales; el agente 2 es el
intérprete legal que clasifica y resume. Ninguno hace el trabajo del otro.

---

## 3. Entorno

- Proyecto en `C:\PIM4`, fuera de OneDrive. Venv propio en `.venv`.
- Rama `main`. `.env` protegido por `.gitignore` (verificado con `git status`).
- Proyecto de Langfuse nuevo, exclusivo del M4.

**Versiones instaladas:**

| Paquete | Versión |
|---|---|
| openai | 3.11.0 |
| langchain | 1.4.0 |
| langchain-openai | 1.6.1 |
| langfuse | 4.15.2 |
| pydantic | 2.13.5 |
| python-dotenv | 1.2.3 |

**Nota de API:** Langfuse 4.x usa `start_as_current_observation(as_type="span")`.
El `start_as_current_span` de v3 y el parámetro `update_trace` del `CallbackHandler`
ya no aplican. El material del curso muestra la sintaxis anterior.

---

## 4. Verificación por smoke tests

Tres scripts aislados antes de escribir el pipeline, para que cada falla apunte a un
solo culpable: credenciales de OpenAI, visión sobre imágenes reales, y trazado con
jerarquía en Langfuse. Los tres pasaron.

Resultado del test de trazado: jerarquía confirmada en el dashboard —
`smoke-root > hijo-1 > RunnableSequence > ChatOpenAI`, con tokens y latencia en el
nivel del modelo.

**Deuda detectada:** los spans creados a mano no capturan input/output solos
(aparecían como `null`/`undefined`). Hay que asignarlos con `span.update(...)` en cada
etapa del pipeline. La rúbrica lo exige explícitamente.

---

## 5. Datos de costo y rendimiento

- Parsing de visión: ~1.300–1.500 tokens y ~8,7 s por imagen con `detail="high"`.
- Costo de visión por corrida del pipeline (2 imágenes): ~2.750–3.000 tokens, ~17 s.
- Latencia estimada del pipeline completo con los dos agentes: 25–30 s. Conviene
  saberlo antes de la demo en vivo para no esperar en silencio frente a la consola.
- Transcripción de los 6 documentos de prueba: ~8.100 tokens, ejecutada una sola vez
  (los textos quedan cacheados en disco).

---

## 6. Verdad de referencia — contratos de prueba

### Documento 3 — CASO SIMPLE (demo)
Contrato de servicio SaaS. **4 cambios esperados** (3 sustantivos + 1 formal):

| Cláusula | Cambio | Tipo |
|---|---|---|
| Pago | USD 1.200 → 1.250 | Modificación |
| SLA | 99,5% → 99,9% | Modificación |
| Soporte | Agrega sistema de tickets en línea | Modificación |
| Título | Agrega "VERSIÓN ACTUALIZADA" | Modificación (formal) |

### Documento 1 — CASO COMPLEJO (demo)
Contrato de licencia de software. **10 cambios esperados** (8 sustantivos + 2 formales), con los tres tipos:

| Cláusula | Cambio | Tipo |
|---|---|---|
| 1. Otorgamiento | Cae "e intransferible" | **Eliminación embebida** |
| 1. Otorgamiento | Cae "únicamente" | **Eliminación embebida** |
| 1. Otorgamiento | Alcance de uso reformulado | Modificación |
| 2. Plazo | 12 → 24 meses | Modificación |
| 3. Pago | USD 12.000 → 15.000 | Modificación |
| 4. Soporte | Agrega canal de chat | Modificación |
| 5. Terminación | 30 → 60 días de preaviso | Modificación |
| 7. Protección de Datos | Cláusula nueva | Adición |
| Título | Agrega "ENMIENDA" | Modificación (formal) |
| Preámbulo | Se presenta como enmienda del contrato | Modificación (formal) |

### Documento 2 — RESERVA (en el repo, sin demo)
Contrato de consultoría. **7 cambios esperados:** título, preámbulo, alcance de servicios, plazo (6 → 9 meses),
tarifa (USD 8.000 → 9.500), frecuencia de reportes (mensual → quincenal), y adición
de cláusula de Propiedad Intelectual.

---

## 7. Hallazgos que orientan el diseño

**La eliminación embebida es la prueba de fuego.** En el documento 1, "e intransferible"
desaparece dentro de una cláusula que además se reformula. El diff lo registra como una
línea modificada, pero legalmente es la eliminación de una restricción de
transferibilidad: lo primero que revisaría un abogado. Un sistema que reporta solo "se
modificó el alcance de la licencia" está fallando en lo importante. El prompt del
Agente 2 debe forzar comparación a nivel de frase, no de cláusula.

**Los cambios de título y preámbulo son formales, no contractuales.** Las tres enmiendas
cambian el encabezado y la frase de apertura porque se presentan como enmienda. No son
modificaciones sustantivas y el agente no debería contarlas como tales.

**La visión varía entre corridas.** En una transcripción del documento 1 apareció
"yDataBridge" sin espacio, cuando en otra corrida salió correcto. `temperature=0` reduce
la variación pero no la elimina. Va al README como limitación honesta.

---

## 8. Historial de desarrollo

| Etapa | Estado |
|---|---|
| 1. Entorno y smoke tests | Cerrada |
| 2. Insumos y verdad de referencia | Cerrada |
| 3. `image_parser.py` | Cerrada |
| 4. `models.py` | Cerrada |
| 5. `ContextualizationAgent` | Cerrada |
| 6. `ExtractionAgent` | Cerrada |
| 7. `main.py` + Langfuse | Cerrada |
| 8. README y repo | Documentación escrita, falta publicar el repo |
| 9. Preparación de la defensa | Pendiente |

**Etapa 3 — resultado.** Transcripción íntegra con numeración y títulos preservados.
Las dos validaciones de entrada rechazaron correctamente un archivo inexistente y una
extensión no soportada. El prompt de visión asigna rol de transcriptor (no de analista),
exige preservar numeración, prohíbe markdown y obliga a marcar `[ILEGIBLE]` en lugar de
completar datos que no se leen con certeza: en un contrato, un dato inventado es peor
que un hueco visible.

El manejo de errores distingue dos familias: transitorios (timeout, caída de red, rate
limit) con reintento y espera creciente; permanentes (credenciales inválidas, petición
malformada) con fallo inmediato, porque reintentar una key inválida solo alarga la
espera hasta el mismo error.

**Etapa 4 — resultado.** Los cinco casos inválidos fueron rechazados con mensajes
distintos y precisos: enum fuera de rango, resumen corto, lista vacía, cadenas en
blanco y campo inventado.

**Etapa 5 — resultado.** Alineación correcta contra la verdad de referencia en ambos
documentos de demo: los tres pares del doc 3, los cinco del doc 1, la cláusula 7
detectada como presente solo en la enmienda y la 6 marcada como idéntica. Los cambios
de título y preámbulo quedaron fuera sin instrucción explícita.

**Hallazgo — riesgo de anclaje.** En la cláusula 1 del documento 1, la nota del mapa
señaló "fines internos de la empresa" vs "operaciones internas de negocio", pero no
mencionó la desaparición de "e intransferible". La alineación es correcta y el par
queda disponible, pero la nota puede anclar al agente de extracción en la diferencia
menos relevante. Mitigación: el prompt del agente 2 instruye que la nota del mapa es un
puntero a dónde mirar, no una conclusión sobre qué cambió, y que dentro de cada par la
comparación se hace frase por frase.

**Decisión derivada:** una cláusula puede contener más de un cambio. La cláusula 1 del
documento 1 tiene una eliminación (la restricción de transferibilidad) y una
modificación (el alcance de uso), y deben reportarse como dos objetos separados.
Reportarlas como una sola perdería la eliminación. El total esperado del documento 1
sube a siete cambios.

**Regla del bloque "idénticas".** Una sección solo entra ahí si coincide palabra por
palabra. Cualquier diferencia de redacción obliga a listarla como par a inspeccionar.
Sin esa regla, la cláusula 1 del documento 1 podría barrerse como "sin cambios" y la
eliminación se perdería sin remedio.

**Nota metodológica:** el inventario generado con `difflib` nunca entra a los prompts.
Es la referencia contra la cual se evalúa el sistema; darlo como insumo convertiría la
detección en una copia.

**Etapa 6 — primera corrida y fallo documentado.**

| Documento | Esperados | Detectados |
|---|---|---|
| 3 (simple) | 4 | 4 — correcto, incluido el cambio formal de título |
| 1 (complejo) | 9 | **6** |

Faltaron tres: la eliminación de "e intransferible", el cambio de título y el de
preámbulo. Además, el resumen del primer cambio reproducía casi literalmente la nota
del mapa, lo que confirmó el riesgo de anclaje anotado en la Etapa 5: el agente 2 no
estaba comparando por su cuenta, estaba desarrollando lo que el agente 1 le había
señalado.

**Diagnóstico — el mapa define el espacio de búsqueda.** El agente 1 solo listaba
secciones numeradas, así que título y preámbulo nunca entraron al mapa y el agente 2
no los miró. En el documento 3 los detectó igual porque es corto y hay poco que
procesar; en el complejo, con siete secciones compitiendo por atención, se limitó al
mapa. La instrucción de exhaustividad en el agente 2 no alcanza si el insumo ya viene
recortado: la causa estaba aguas arriba.

**Corrección aplicada:** ver decisión 2.9. Título y preámbulo entran al mapa como
secciones; la nota interpretativa se reemplaza por tres listas mecánicas; y el agente 2
recibe la regla de correspondencia entre texto suprimido y cambio `deletion`.

**Valor para la defensa:** este ciclo —fallo medido contra una verdad de referencia
independiente, diagnóstico de causa raíz aguas arriba, corrección en el prompt del
agente responsable, y nueva medición— es evidencia directa de iteración sobre prompts.
Conservar la salida de 6/9 junto a la corregida: mostrar el fallo y su corrección vale
más que mostrar solo el resultado final.

**Etapa 6 — segunda corrida: conteos correctos, clasificación imprecisa.**

| Documento | Esperados | Detectados |
|---|---|---|
| 3 (simple) | 4 | 4 |
| 1 (complejo) | 9 | 9 |

La corrección funcionó: la eliminación de "e intransferible" quedó detectada como
`deletion` independiente, el título y el preámbulo entraron al análisis, y la cláusula 1
se desdobló en dos cambios distintos.

**Problema nuevo — frontera difusa entre `addition` y `modification`.** El modelo
clasificó como `addition` el cambio de título (doc 1 y doc 3) y la incorporación de un
canal de soporte dentro de una cláusula existente (doc 1 y doc 3). Ninguno es una
adición: el título ya existía y la cláusula de Soporte también. El modelo estaba
interpretando "se agregó texto" como `addition`, porque la descripción del campo no
distinguía entre agregar una sección y agregar contenido dentro de una sección.

**Corrección aplicada:** la definición de `change_type` en `models.py` ahora establece
que el tipo lo determina la SECCIÓN, no el texto. Solo es `addition` una sección
completa sin contraparte en el original; si la sección existe en ambas versiones y gana
contenido, es `modification`. Título y preámbulo existen en ambas versiones, de modo que
sus cambios son siempre `modification`. Se agregó además una regla contra el doble
conteo de un mismo fragmento.

**Resultado esperado tras la corrección:** doc 3 con cuatro `modification` y ninguna
`addition`; doc 1 con una sola `addition`, la cláusula 7 de Protección de Datos.

**Nota de método:** las dos correcciones de esta etapa se aplicaron en distintos
lugares por una razón. La primera (anclaje, secciones no numeradas) era un problema de
insumo y se corrigió aguas arriba, en el agente 1. La segunda es un problema de
definición del vocabulario de salida y se corrigió en el esquema Pydantic, que es donde
vive esa definición y desde donde viaja al modelo como parte del prompt.

**Etapa 6 — tercera corrida: la corrección anterior sobredisparó.**

| Documento | Esperados | Detectados |
|---|---|---|
| 3 (simple) | 4 | 6 |
| 1 (complejo) | 9 | 10 |

La frontera `addition`/`modification` quedó bien: `addition` se usó solo en la cláusula 7
de Protección de Datos, que es la única sección sin contraparte. Pero apareció el
problema inverso al de la corrida anterior.

**Diagnóstico — la regla de correspondencia sobredispara.** La regla introducida en la
segunda corrida decía que todo texto suprimido implica un `deletion`. El mapa registra
"USD 1.200" como texto suprimido en la cláusula de Precio, así que el agente reportaba
una eliminación del precio original además de la modificación. Lo mismo con el SLA y con
el preámbulo. Pero un valor reemplazado no es una eliminación: nada desapareció, cambió.

**Tensión precisión / exhaustividad.** Al corregir el falso negativo de la corrida
anterior (la eliminación embebida que se perdía) se introdujo un falso positivo
(reemplazos contados como eliminaciones). Cada ajuste de un prompt mueve el sistema en
las dos direcciones a la vez; el trabajo no es "mejorar el prompt" sino encontrar el
criterio que separa los dos casos.

**Criterio adoptado:** una supresión CON reemplazo es modificación; una supresión SIN
reemplazo es eliminación. "e intransferible" desaparece y nada ocupa su lugar, de modo
que sigue siendo `deletion`. "USD 1.200" es sustituido por "USD 15.000" en la misma
posición: es `modification`. El preámbulo también, "se celebra" fue reemplazado por
"modifica".

Aplicado en los dos lugares donde vive la definición: la regla operativa en el prompt
del agente 2, y la definición del vocabulario en la descripción de `change_type`.

**Etapa 6 — cuarta corrida: el criterio de reemplazo absorbió la eliminación.**

| Documento | Esperados | Detectados |
|---|---|---|
| 3 (simple) | 4 | 4 — correcto, todos `modification` |
| 1 (complejo) | 9 | 8 |

Los falsos positivos de la corrida anterior desaparecieron, pero la eliminación de
"intransferible" volvió a absorberse dentro de la modificación de la cláusula 1.

**Diagnóstico — nivel de aplicación de la prueba.** El modelo evaluaba el reemplazo a
nivel de cláusula, no del elemento suprimido: razonaba "la cláusula se reformuló, luego
lo suprimido fue reemplazado por la nueva redacción". La pregunta correcta es por
elemento: ¿existe en la enmienda algo que cumpla la función que cumplía ese elemento?
No hay nada que cumpla la función de "intransferible"; que la cláusula se haya reescrito
alrededor no la reemplaza.

**Corrección aplicada:** la prueba de reemplazo se declara explícitamente elemento por
elemento, con advertencia sobre restricciones, prohibiciones, condiciones y
calificadores, y con dos ejemplos contrastantes (un monto sustituido por otro monto
frente a un calificador que desaparece).

**Advertencia metodológica — riesgo de sobreajuste.** Cuatro iteraciones ajustando los
prompts sobre los mismos dos documentos. Existe el riesgo real de estar afinando para
estos casos concretos y no para el problema. Por eso el documento 2 nunca se usó para
ajustar y se reserva como conjunto de validación: si al final produce sus 7 cambios
esperados sin haber intervenido en el diseño de los prompts, hay evidencia de
generalización; si falla, hubo sobreajuste. Esta separación entre conjunto de desarrollo
(docs 1 y 3) y conjunto de validación (doc 2) es material directo para la defensa.

**Etapa 6 — quinta corrida: conjunto de desarrollo correcto.**

| Documento | Esperados | Detectados |
|---|---|---|
| 3 (simple) | 4 | 4 — todos `modification` |
| 1 (complejo) | 9 | 9 — un `deletion`, una `addition`, siete `modification` |

La eliminación de "intransferible" se reporta como cambio independiente y la cláusula 7
como única adición. Clasificación correcta en ambos documentos.

**Validación sobre conjunto reservado — documento 2: 7 de 7.**

| Tipo | Detectado | Esperado |
|---|---|---|
| modification | 6 | 6 |
| addition | 1 | 1 |
| deletion | 0 | 0 |

El documento 2 no intervino en ninguna de las cinco iteraciones de prompts. Produjo
exactamente los cambios de su verdad de referencia, con los tipos correctos y resúmenes
factualmente exactos. Es evidencia de que el sistema generaliza y no está sobreajustado
a los casos con los que fue afinado.

La validación quedó en el repo como `validate_holdout.py`, con la verdad de referencia
declarada en el propio script, para que la separación entre conjunto de desarrollo y
conjunto de validación sea verificable y no solo afirmada.

**Resumen de la iteración de prompts en la Etapa 6** — cinco corridas, cada una con un
diagnóstico distinto:

| # | Resultado | Problema | Dónde se corrigió |
|---|---|---|---|
| 1 | 4/4 y 6/9 | El mapa recortaba el espacio de búsqueda; anclaje en la nota interpretativa | Agente 1: título y preámbulo como secciones; listas mecánicas en vez de prosa |
| 2 | 4/4 y 9/9 | `addition` usado para secciones existentes que ganan texto | Esquema: el tipo lo determina la sección, no el texto |
| 3 | 6/4 y 10/9 | La regla de correspondencia convertía todo reemplazo en eliminación | Prompt y esquema: supresión con reemplazo es modificación |
| 4 | 4/4 y 8/9 | La prueba de reemplazo se aplicaba a la cláusula, no al elemento | Prompt y esquema: prueba elemento por elemento, con ejemplos contrastantes |
| 5 | 4/4 y 9/9 | — | Validado contra conjunto reservado: 7/7 |

**Etapa 7 — trazado verificado y un hallazgo de costo.**

Traza `contract-analysis` confirmada en el dashboard con los cuatro spans hijos, input y
output con contenido real en cada uno, y las llamadas de LangChain anidadas bajo cada
agente con sus tokens y costo. La deuda del `null`/`undefined` detectada en el smoke
test quedó saldada.

**Hallazgo — el costo agregado subreportaba casi la mitad del gasto.** La traza raíz
mostraba 4.694 tokens y $0,01637, cifra que solo cubría las llamadas instrumentadas por
el `CallbackHandler` de LangChain (contextualización y extracción). Los dos parseos de
visión —3.076 tokens, la parte más cara del pipeline— quedaban fuera del agregado porque
estaban registrados como spans genéricos, con sus métricas en el campo `metadata`, donde
Langfuse no las contabiliza como consumo.

**Corrección:** Langfuse solo rastrea uso y costo en observaciones de tipo *generation*.
Los dos parseos pasaron a registrarse con `as_type="generation"`, declarando `model` y
`usage_details`; el costo se infiere de la definición de modelo. Las llamadas de los
agentes no necesitan este tratamiento porque el `CallbackHandler` ya las registra como
generaciones.

**Para la defensa:** si el corrector pregunta cuánto cuesta analizar un par de contratos,
la cifra de la traza ahora es completa. Antes de la corrección, señalar ese número
habría sido subreportar el gasto real.

**Hallazgo — variación en la granularidad, no en el contenido.** Dos corridas del
documento 1 con el mismo prompt y `temperature=0` dieron 9 y 10 cambios. La diferencia
no es de contenido: en la corrida de 10, el sistema separó las supresiones de
"intransferible" y de "únicamente" en dos eliminaciones distintas, en vez de agruparlas.
Ambas lecturas son defendibles y la de 10 es más fiel al criterio de exhaustividad
adoptado, de modo que se corrigió la verdad de referencia del documento 1 a 10 cambios,
no el prompt.

**Consecuencia para la demo:** presentar el resultado por contenido y no por conteo.
"Detecta las dos supresiones de calificadores en la cláusula 1, la adición de la
cláusula 7 y clasifica correctamente los cambios de valores" se cumple siempre;
"detecta 10 cambios" es una promesa innecesaria que puede fallar en vivo.

**Etapa 7 — cifras verificadas tras la corrección.**

Traza `925b9a85cdc674e383c90653199dbc9e` (documento 3, pipeline completo desde imágenes):

| Observación | Latencia | Tokens | Costo |
|---|---|---|---|
| `parse_original_contract` (generation) | 3,03 s | 1.265 → 131 (Σ1.396) | $0,004473 |
| `parse_amended_contract` (generation) | 2,61 s | 1.265 → 145 (Σ1.410) | $0,004613 |
| `contextualization_agent` | 3,40 s | 808 → 254 (Σ1.062) | $0,004560 |
| `extraction_agent` | 2,81 s | — | $0,005180 |
| **contract-analysis (raíz)** | **11,84 s** | **~5.400** | **$0,018825** |

**Dato para la defensa:** el parsing de visión representa el **48% del costo total**
($0,0091 de $0,0188), y era justamente la porción que quedaba invisible antes de la
corrección. Permite cuantificar el precio de la decisión `detail="high"` en vez de
justificarla solo cualitativamente.

**Viabilidad a escala:** ~$0,019 y ~12 s por par de contratos. Mil pares cuestan menos
de veinte dólares. Responde por sí sola la pregunta de si el sistema es viable para el
volumen de LegalMove.

**Auditoría verificada:** el input del span de contextualización muestra el texto
completo de ambos contratos, legible. Desde el resultado se puede reconstruir qué vio
cada agente en cada etapa.

**Etapa 8 — enfoque del README.** Estructurado para responder las preguntas del corrector
antes de que las haga: qué hace, cómo se corre, por qué está construido así, qué tan bien
funciona y dónde falla. La sección de limitaciones es deliberada y va explícita: un README
que solo declara lo que funciona invita a buscar lo que no.

Cinco limitaciones declaradas: variación de la transcripción entre corridas, granularidad
no determinista del conteo, ausencia de verificación cruzada del parsing, alcance probado
(una página, español, cláusulas numeradas) y el hecho de que el sistema no evalúa riesgo
legal sino que clasifica y resume.

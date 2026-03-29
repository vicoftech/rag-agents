# Prompt: mejoras RAG — embeddings, ingestión y búsqueda semántica

Usa este documento como **prompt único** para un asistente de código o para un ticket de implementación. El objetivo es corregir y mejorar el pipeline de `rag_lmbd_embeddings`, la búsqueda en `rag_lmbd_query` y la coherencia con el agente, en el orden de prioridad indicado.

---

## Contexto del repositorio

- **Ingesta / embeddings:** `apps/rag_lmbd_embeddings/index.py` (handler desplegado: `index.handler`, según Terraform).
- **Búsqueda + LLM:** `apps/rag_lmbd_query/index.py`.
- **Cliente agente (invocación opcional):** `apps/agent/tools/lambda_client.py` (`invoke_embeddings_lambda`).
- **Esquema BD:** tablas por tenant en PostgreSQL + pgvector (`ddl.sql`, creación dinámica en `ensure_tenant_schema_exists`).
- **Modelo actual (típico):** `cohere.embed-v4:0` vía Bedrock; vectores `VECTOR(1536)` en tablas.

No trates `apps/rag_lmbd_embeddings/utils.py` ni `main.py` como fuente de verdad del despliegue salvo que se decida integrarlos o eliminarlos explícitamente.

---

## Instrucciones generales

1. Implementa los ítems **en orden de prioridad** (Alta → Media). Dentro de cada nivel, respeta el orden numérico.
2. Tras cada cambio relevante, verifica que indexación y búsqueda usen el **mismo modelo**, la **misma dimensionalidad** y los **`input_type` correctos** para Cohere Embed v4.
3. Extrae la lógica duplicada (p. ej. parseo de respuesta Bedrock, `embed` con `input_type` parametrizable) a un módulo compartido **solo si** reduce duplicación entre `rag_lmbd_embeddings` y `rag_lmbd_query` sin ensuciar el empaquetado de las Lambdas; si no es viable, duplica el mínimo necesario pero **comportamiento idéntico**.
4. Añade comentarios breves solo donde el contrato API (Bedrock / esquema tenant / S3) no sea obvio.

---

## Prioridad ALTA

### A1 — `input_type` correcto para Cohere Embed v4 (búsqueda asimétrica)

- **Problema:** Corpus y consulta no deben usar el mismo `input_type`. AWS documenta: corpus con `search_document`, consultas con `search_query`.
- **Acción:**
  - En `apps/rag_lmbd_embeddings/index.py`, mantener `input_type: "search_document"` al embeddear **chunks** (ingesta).
  - En `apps/rag_lmbd_query/index.py`, usar `input_type: "search_query"` al embeddear la **pregunta del usuario** en `semantic_search` / `embed` usado para la query.
- **Criterio de éxito:** Una consulta de prueba recupera chunks más alineados con la intención (smoke test manual o test unitario con mock de Bedrock que verifique el payload).

### A2 — Parser robusto de la respuesta de embeddings (Cohere v4 + compatibilidad)

- **Problema:** La respuesta puede ser `embeddings_floats` con `embeddings` como `list[list[float]]`, o estructuras con `embeddings.float`, u otros formatos legacy.
- **Acción:** Implementar una función única (p. ej. `parse_embedding_vector(result: dict) -> list[float]`) que cubra:
  - `embeddings` es lista de listas → tomar el vector del índice 0 cuando hay un solo texto.
  - `embeddings` es dict con clave `"float"` (u otros tipos si se piden en el request).
  - Caso legacy: dict con una sola clave cuyo valor sea `[[...]]` o similar.
- **Usar** esta función en **ambas** lambdas donde se parsea la respuesta de Bedrock.
- **Criterio de éxito:** Tests unitarios con fixtures JSON para cada forma de respuesta; sin `TypeError` al acceder a `["float"]` sobre una lista.

### A3 — Evitar duplicados y basura en BD al re-subir el mismo documento

- **Problema:** Cada evento S3 genera un `document_id` nuevo y reinserta chunks sin borrar versiones anteriores del mismo archivo lógico.
- **Acción:**
  - Definir una política clara: p. ej. borrar filas en `{schema}.documents` donde coincidan `agent_id`, `document_name` (y tenant implícito por esquema) **antes** de insertar los nuevos chunks; o usar un `document_id` estable derivado de metadatos (etag + key normalizada) y reemplazar por ese id.
  - Documentar en comentario o en el mensaje de commit la regla elegida.
- **Criterio de éxito:** Re-subir el mismo PDF no multiplica filas para el mismo `(agent_id, document_name)`; la búsqueda no devuelve trozos duplicados obsoletos del mismo archivo.

---

## Prioridad MEDIA

### M1 — Contrato consistente de `tenant_id` (S3 vs API de query)

- **Problema:** Ingesta usa `parts[0]` del key como nombre de esquema (p. ej. `tenant_gp`); la query arma `tenant_{tenant_id}`. Si el cliente envía `tenant_gp` vs `gp`, el esquema puede ser incorrecto (`tenant_tenant_gp`).
- **Acción:**
  - Elegir un contrato único (recomendado: API recibe slug **sin** prefijo `tenant_`; SQL usa `tenant_{slug}`), o normalizar en un solo lugar (helper `resolve_schema_name(tenant_id: str) -> str`).
  - Validar y devolver error 400 claro si el formato no cumple el contrato.
- **Criterio de éxito:** Documentar el contrato en el propio código (docstring breve) y test del helper si aplica.

### M2 — Validación de la estructura del key S3

- **Problema:** Keys como `tenant_x/documents/file.pdf` hacen que `parts[1]` sea `documents` en lugar de un UUID de agente.
- **Acción:** Tras `split("/")`, validar número mínimo de segmentos y que `agent_id` sea UUID (o el patrón real del producto). Si falla, log + error controlado (no insertar datos corruptos).
- **Criterio de éxito:** Evento con key inválido no crea agentes/chunks incorrectos.

### M3 — Índice vectorial (IVFFlat vs HNSW, mantenimiento)

- **Problema:** IVFFlat con `lists = 100` puede dar bajo recall con pocos datos o necesitar ajuste con muchos datos.
- **Acción:**
  - Evaluar migración a **HNSW** si la versión de pgvector en Aurora lo permite; si no, documentar cuándo reindexar y cómo elegir `lists`.
  - Opcional: script o pasos en comentarios para `REINDEX` tras cargas masivas.
- **Criterio de éxito:** Decisión explícita en código o comentario + coherencia con el DDL desplegado.

### M4 — Batch de embeddings en ingestión

- **Problema:** Un `invoke_model` por chunk aumenta latencia, coste y superficie de fallos.
- **Acción:** Agrupar chunks en lotes (hasta el límite documentado por Bedrock/Cohere, p. ej. 96 textos), embeddear en batch, insertar en transacción. Mantener `search_document` para todos los textos del lote.
- **Criterio de éxito:** Mismo resultado semántico (o equivalente dentro de tolerancia numérica) con menos llamadas a Bedrock para el mismo PDF.

### M5 — Chunking, truncado y extracción PDF

- **Problema:** Corte por caracteres (`MAX_EMBED_TEXT_LENGTH`), pdfplumber sin layout en PDFs complejos, sin `truncate` explícito en la request Cohere.
- **Acción:**
  - Alinear truncado: o chunks más pequeños en tokens aproximados, o fijar `truncate` en la API de forma acorde a la estrategia de negocio.
  - Valorar Textract u otra ruta para PDFs con tablas/columnas cuando `use_textract` sea true; revisar umbrales en `_get_chunk_config`.
  - Opcional: prefijo ligero de metadatos en el texto embebido (`document_name` corto) para mejorar discriminación en retrieval.
- **Criterio de éxito:** Comportamiento documentado; sin regresiones en PDFs ya soportados (tests manuales mínimos).

### M6 — Lambda de embeddings invocada directamente desde el agente

- **Problema:** `invoke_embeddings_lambda` envía `{"text": ...}` y espera `embedding` en la respuesta; `index.handler` solo procesa eventos S3.
- **Acción (elegir una):**
  - Añadir en `index.handler` un branch para invocación directa (payload con `text` / `input_type` opcional) y respuesta API Gateway-compatible con `embedding`; **o**
  - Extraer función de embedding a una lambda pequeña dedicada y actualizar Terraform + `LAMBDA_EMBEDDINGS`; **o**
  - Deprecar `embed_text` si no se usa y alinear documentación.
- **Criterio de éxito:** Comportamiento definido y coherente con tests del cliente en `apps/agent/tests`.

---

## Entregables esperados

- Cambios en código en `apps/rag_lmbd_embeddings` y `apps/rag_lmbd_query` (y shared si aplica).
- Tests unitarios nuevos o actualizados para parser de embeddings y, si es posible, contrato `tenant_id` / key S3.
- Sin ampliar el alcance a refactors no listados (mantener el diff enfocado).

---

## Checklist final antes de cerrar

- [ ] Ingesta: `search_document`; query: `search_query`.
- [ ] Parser de respuesta Bedrock probado para formatos Cohere v4.
- [ ] Re-ingesta no duplica chunks obsoletos del mismo documento lógico.
- [ ] `tenant_id` y keys S3 validados según contrato acordado.
- [ ] Índice vectorial: decisión HNSW/IVFFlat documentada o implementada.
- [ ] Batch de embeddings en ingestión (si se alcanzó en este ciclo).
- [ ] Agente / invocación directa resuelta o explícitamente deprecada.

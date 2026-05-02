# Refactor: Lambda monolítica de ingesta RAG → Step Functions con fan-out por SQS y task token

## Contexto

Hoy existe una Lambda (`rag_lmbd_embeddings_async` o equivalente) que hace todo el pipeline de ingesta de PDFs para RAG en un solo proceso: descarga de S3, extracción de texto, chunking, generación de embeddings con Bedrock e inserción en Aurora PostgreSQL + pgvector. Esto genera timeouts con PDFs grandes, mala observabilidad, reintentos de grano grueso, y acopla responsabilidades.

Stack objetivo: **AWS Lambda (Python 3.12) + Step Functions Standard + SQS + DynamoDB + Aurora PostgreSQL con pgvector + Bedrock (Cohere Multilingual v3) + Terraform**.

## Objetivo del refactor

Separar el pipeline en **tres Lambdas** orquestadas por una **Step Function Standard** que:

1. Extrae texto y genera chunks (fase CPU/IO liviana).
2. Hace fan-out a una cola SQS donde cada mensaje es un **lote de chunks** (no un PDF).
3. Un pool de workers consume la cola, llama a Bedrock en batch y hace `execute_values` contra Aurora.
4. **La Step Function espera a que TODOS los lotes terminen** (éxito o fallo real) antes de marcar el job como `SUCCEEDED` / `FAILED`. No debe dar success solo porque encoló.

## Arquitectura target

```
S3 (PutObject PDF)
  └─> EventBridge Rule
        └─> StartExecution Step Function (input: {bucket, key, tenant_id, agent_id, document_id, document_name, created_at})

Step Function (Standard):

  [1] RegisterJob (Lambda: job-registrar)
      · Crea registro en DynamoDB `alert-ingestion-jobs-{env}` con job_id = execution_id
      · Estado inicial: {status: "SPLITTING", total_batches: null, completed_batches: 0, failed_batches: 0}

  [2] SplitDocument (Lambda: rag-split)
      · Descarga PDF de S3
      · Extrae texto (PyMuPDF → fallback pdfplumber → fallback Textract si USE_TEXTRACT=true)
      · Chunking con tamaños dinámicos según nº páginas
      · DELETE WHERE document_id = ... en Aurora (idempotencia del documento)
      · Parte en lotes de BATCH_SIZE (default 64)
      · Devuelve: {batches: [...], total_batches: N, job_id}
      · NO encola todavía

  [3] PersistTaskToken (inline Pass + Lambda: token-persister)
      · Step Function entra en estado Task con .waitForTaskToken
      · El Lambda token-persister recibe el taskToken y lo guarda en DynamoDB:
        UPDATE (DDB) alert-ingestion-jobs: task_token, total_batches, status = "EMBEDDING"

  [4] FanOut (Lambda: rag-fanout)
      · Lee el resultado de SplitDocument
      · Por cada batch, envía un SendMessage a chunk-batches-queue con payload:
        {job_id, tenant_id, agent_id, document_id, document_name, chunk_index_base, texts: [...], created_at}
      · Usa SendMessageBatch (10 msgs por request) para reducir latencia
      · Devuelve éxito inmediato — la ejecución del SFN queda BLOQUEADA esperando task token

  [5] (Fuera del SFN, en paralelo) Lambda rag-embed-worker
      · Trigger: SQS chunk-batches-queue (batch_size=1 para aislar fallos)
      · Por cada mensaje:
        a) Llama a Bedrock embed_texts_batch (Cohere Multilingual v3) con los textos
        b) INSERT con execute_values a Aurora pgvector con ON CONFLICT DO UPDATE
           (clave: document_id + chunk_index)
        c) UPDATE atómico en DynamoDB:
           UPDATE (DDB) alert-ingestion-jobs
           SET completed_batches = completed_batches + 1
           WHERE job_id = ?
           RETURNING completed_batches, total_batches, task_token, status
        d) Si completed_batches == total_batches Y status == "EMBEDDING":
           · UPDATE status = "SUCCEEDED"
           · stepfunctions.send_task_success(task_token, output={...})
      · Si falla el batch y agota reintentos → va a DLQ

  [6] (Fuera del SFN) Lambda rag-dlq-handler
      · Trigger: SQS chunk-batches-dlq
      · UPDATE atómico failed_batches += 1 en DynamoDB
      · Si es el primer fallo del job (failed_batches transitions 0→1):
        · UPDATE status = "FAILED"
        · stepfunctions.send_task_failure(task_token, error="BatchProcessingFailed", cause=...)
      · Si no es el primero, solo registra (ya se notificó el fallo)

  [7] FinalizeJob (post task token, dentro del SFN)
      · Lee de DynamoDB el estado final del job
      · Si status == SUCCEEDED: emite evento EventBridge "DocumentIngested"
      · Si status == FAILED: emite evento "DocumentIngestionFailed" con detalle
      · Termina el SFN con el estado correspondiente
```

## Tabla DynamoDB: `alert-ingestion-jobs-{env}` (RAG v2, prefijo `alert` en Terraform)

```
PK: job_id (string, = SFN execution ARN o UUID)
Atributos:
  - tenant_id (string)
  - agent_id (string)
  - document_id (string)
  - document_name (string)
  - status (string: SPLITTING | EMBEDDING | SUCCEEDED | FAILED | TIMED_OUT)
  - total_batches (number)
  - completed_batches (number)
  - failed_batches (number)
  - task_token (string)
  - created_at (ISO)
  - updated_at (ISO)
  - error (map, opcional)
GSI1: tenant_id + created_at (para listar jobs por tenant)
TTL: 7 días en atributo ttl (limpieza)
```

Los UPDATEs de `completed_batches` y `failed_batches` deben usar `UpdateItem` con `ADD` + `ReturnValues=ALL_NEW` para leer el valor resultante de forma atómica. La transición a `SUCCEEDED`/`FAILED` debe usar `ConditionExpression` para evitar doble notificación del task token (ej. `status = :embedding AND completed_batches = :total`).

## Requisitos funcionales

1. **Idempotencia**: reprocesar el mismo `document_id` debe funcionar (el DELETE en SplitDocument + ON CONFLICT en workers lo garantiza).
2. **Un solo DELETE por documento**: en la Lambda `rag-split`, nunca en los workers.
3. **Orden de chunks preservado**: el payload del batch incluye `chunk_index_base` y cada texto su índice relativo; el worker calcula `chunk_index = chunk_index_base + i`.
4. **Visibilidad SQS**: timeout de visibilidad de `chunk-batches-queue` = 6× timeout del worker (si worker = 60s, visibility = 360s).
5. **Timeout del task token**: estado `waitForTaskToken` con `TimeoutSeconds=1800` (30 min). Si expira, el SFN falla y un handler marca el job como `TIMED_OUT`.
6. **Heartbeat opcional**: el worker puede llamar `SendTaskHeartbeat` cada N batches procesados para extender el timeout en docs grandes.
7. **Fallbacks de extracción de texto** en `rag-split`: PyMuPDF → pdfplumber → Textract (solo si flag `USE_TEXTRACT=true` y los dos anteriores devolvieron < MIN_TEXT_THRESHOLD caracteres).
8. **Separación de rutas sync**: la ruta del agente que solo necesita `embed(text)` (sin SQS, sin ingesta) debe quedar en una Lambda aparte `rag-embed-sync` que expone el API directo a Bedrock. No reusar la cola.

## Requisitos no funcionales

- **Observabilidad**: cada Lambda emite métricas CloudWatch custom (`BatchesEnqueued`, `BatchesCompleted`, `BatchesFailed`, `DocumentIngestionDuration`). Traza distribuida con X-Ray habilitado en SFN + Lambdas + SQS.
- **Logging estructurado**: JSON con `job_id`, `document_id`, `batch_index`, `tenant_id` en cada log line. Usar `aws-lambda-powertools` para Logger/Tracer/Metrics.
- **Configuración por env vars**: `BATCH_SIZE`, `EMBEDDING_MODEL_ID`, `AURORA_SECRET_ARN`, `JOBS_TABLE_NAME`, `CHUNK_BATCHES_QUEUE_URL`, `USE_TEXTRACT`, `MIN_TEXT_THRESHOLD`.
- **Secrets**: credenciales de Aurora vía Secrets Manager, con caché in-memory por cold start.
- **Reintentos**: workers con `maxReceiveCount=3` antes de DLQ. Dentro del worker, reintentos manuales con backoff solo para errores transitorios de Bedrock (ThrottlingException, ModelTimeoutException). Errores de DB → falla directo al primer intento para no duplicar.
- **Concurrencia**: Lambda `rag-embed-worker` con `reserved_concurrency` configurable (default 10) para no saturar Bedrock ni Aurora.

## Estructura del repo esperada

```
infra/
  terraform/
    modules/
      rag-ingestion/
        main.tf              # SFN, SQS, DynamoDB, EventBridge rule, IAM
        lambdas.tf           # definición de las 5 Lambdas
        variables.tf
        outputs.tf
    envs/
      dev/
      prod/
src/
  lambdas/
    job_registrar/
      handler.py
      requirements.txt
    rag_split/
      handler.py
      text_extraction.py     # PyMuPDF + pdfplumber + Textract
      chunking.py
      requirements.txt
    rag_fanout/
      handler.py
      requirements.txt
    rag_embed_worker/
      handler.py
      bedrock_client.py
      aurora_writer.py
      jobs_table.py          # helpers de DynamoDB con conditional updates
      requirements.txt
    rag_dlq_handler/
      handler.py
      requirements.txt
    rag_embed_sync/          # ruta sync separada
      handler.py
      requirements.txt
  shared/
    models.py                # Pydantic: JobRecord, BatchMessage, ChunkPayload
    sfn_client.py            # wrappers send_task_success/failure/heartbeat
sfn/
  rag_ingestion.asl.json     # definición Amazon States Language
tests/
  unit/
  integration/               # con moto + localstack para SQS/DynamoDB
```

## Esquemas JSON canónicos

**Input del SFN:**
```json
{
  "bucket": "rag-documents-qa-ACCOUNT",
  "key": "tenant123/agent456/doc789.pdf",
  "tenant_id": "tenant123",
  "agent_id": "agent456",
  "document_id": "doc789",
  "document_name": "manual-tecnico-v3.pdf",
  "created_at": "2026-04-24T12:00:00Z"
}
```

**Mensaje en `chunk-batches-queue`:**
```json
{
  "job_id": "arn:aws:states:...:execution:...",
  "task_token_available": true,
  "tenant_id": "tenant123",
  "agent_id": "agent456",
  "document_id": "doc789",
  "document_name": "manual-tecnico-v3.pdf",
  "chunk_index_base": 128,
  "batch_index": 2,
  "total_batches": 5,
  "texts": ["chunk texto 1...", "chunk texto 2...", "..."],
  "created_at": "2026-04-24T12:00:00Z"
}
```

## Tareas concretas a realizar por Cursor

1. Crear la estructura de carpetas completa descrita arriba.
2. Escribir la definición ASL de la Step Function en `sfn/rag_ingestion.asl.json` con todos los estados (`RegisterJob`, `SplitDocument`, `PersistTaskToken` como `Task` con `.waitForTaskToken`, `FanOut`, `FinalizeJob`, manejo de `Catch` global y `Retry` por estado).
3. Implementar las 5 Lambdas con las responsabilidades descritas. Cada una con:
   - Handler con `aws-lambda-powertools` (Logger, Tracer, Metrics).
   - Modelos Pydantic para validación de entrada/salida.
   - Tests unitarios con pytest + moto.
4. Escribir el módulo Terraform `rag-ingestion` con:
   - SFN Standard con logging a CloudWatch y X-Ray tracing.
   - 2 SQS (main + DLQ) con visibility timeout correcto y redrive policy.
   - Tabla DynamoDB con GSI y TTL.
   - EventBridge Rule para disparar SFN desde S3.
   - IAM roles mínimos: cada Lambda solo puede hacer lo suyo (principio de menor privilegio).
   - Reserved concurrency en el worker.
5. En `shared/jobs_table.py`, implementar los UPDATEs condicionales con `ReturnValues=ALL_NEW` y la lógica de transición a `SUCCEEDED`/`FAILED` con `ConditionExpression` para evitar doble notificación de task token.
6. Documentar en `README.md` del módulo cómo deployar, cómo debuggear un job en curso consultando DynamoDB, y cómo reprocesar mensajes desde la DLQ.
7. Incluir un diagrama Mermaid del flujo completo en el README.

## Criterios de aceptación

- Un PDF de 500 páginas ingesta correctamente y el SFN termina en `SUCCEEDED` solo cuando la última fila fue insertada en Aurora.
- Si un batch falla y agota reintentos, el SFN termina en `FAILED` con el detalle del batch que rompió.
- Si todos los batches exceden 30 min totales, el SFN termina en `TIMED_OUT` y DynamoDB refleja el estado.
- Reprocesar el mismo `document_id` no duplica filas en Aurora.
- Ningún worker hace `DELETE` del documento — solo el split.
- El endpoint sync de embeddings (`rag-embed-sync`) sigue funcionando independientemente, sin pasar por SQS.

## Lo que NO hacer

- No usar Distributed Map de SFN (perdemos el task token unificado).
- No contar batches completados con EventBridge "cola vacía" (frágil con reintentos).
- No meter la lógica de Bedrock en la Lambda de split (acopla y lentifica).
- No usar el mismo Lambda para sync e ingesta.
- No hardcodear el `BATCH_SIZE` ni el modelo de embeddings.

Arrancá creando la estructura de carpetas, después el ASL, después las Lambdas en orden topológico (registrar → split → fanout → worker → dlq-handler → finalize), y al final Terraform. Pedime confirmación antes de generar los archivos de Terraform para revisar el diseño de IAM.

# rag_lmbd_alert_creation-[env]

## Context

You are implementing an AWS Lambda function (Python 3.12) triggered by SQS that bridges two PostgreSQL schemas in the same Aurora cluster.

There are two schemas in the same Aurora PostgreSQL cluster:

**Schema `tenant_anmat`** (RAG store — read only from Lambda):

```sql
CREATE TABLE tenant_anmat.agents (
    agent_id uuid NOT NULL,
    agent_name text NOT NULL,
    description text NULL,
    prompt_template text NOT NULL,
    created_at timestamp DEFAULT now() NULL,
    CONSTRAINT agents_pkey PRIMARY KEY (agent_id)
);

CREATE TABLE tenant_anmat.documents (
    id serial4 NOT NULL,
    agent_id uuid NOT NULL,
    document_id uuid NOT NULL,
    document_name text NOT NULL,
    chunk_text text NOT NULL,
    embedding public.vector NULL,
    created_at timestamp DEFAULT now() NULL,
    chunk_index int4 NULL,
    fts_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('spanish'::regconfig, COALESCE(chunk_text, ''::text))
    ) STORED NULL,
    CONSTRAINT documents_pkey PRIMARY KEY (id)
);
```

**Schema `public`** (legacy alert system — write target):

```sql
CREATE TABLE public.disposicion (
    id serial4 NOT NULL,
    descripcion varchar(255) NULL,
    disposicion_id varchar(255) NOT NULL,
    eliminado bool NOT NULL,
    fecha_de_aparicion timestamp NOT NULL,
    fecha_de_publicacion timestamp NOT NULL,
    fechayhora_revision timestamp NULL,
    nombre_pdf varchar(255) NULL,
    revisado bool NOT NULL,
    url varchar(255) NOT NULL,
    archivo varchar(255) NULL,
    CONSTRAINT disposicion_pkey PRIMARY KEY (id)
);

CREATE TABLE public.disposicion_contenido (
    id bigserial NOT NULL,
    contenido text NULL,
    disposicion_id int4 NULL,
    embedding_vector public.vector NULL,
    CONSTRAINT disposicion_contenido_pkey PRIMARY KEY (id),
    CONSTRAINT fk_disposicion_contenido_disposicion
        FOREIGN KEY (disposicion_id) REFERENCES public.disposicion(id)
);

CREATE TABLE public.alerta_generada (
    id serial4 NOT NULL,
    eliminado bool NOT NULL,
    enviada bool NOT NULL,
    estado_alerta int4 NULL,
    fechayhora_ocurrencia timestamp NULL,
    leido bool NOT NULL,
    busqueda_id int4 NOT NULL,
    disposicion_id int4 NULL,
    CONSTRAINT alerta_generada_pkey PRIMARY KEY (id),
    CONSTRAINT fk6r4luvqhhiwod8ttxt1idpgjk
        FOREIGN KEY (disposicion_id) REFERENCES public.disposicion(id),
    CONSTRAINT fkrgjqbcam8dm6da6xnkx3et92h
        FOREIGN KEY (busqueda_id) REFERENCES public.busqueda(id)
);
```

---

## What the Lambda must do

Receive an SQS message and execute the following steps **inside a single database transaction**:

**Step 1 — Upsert `public.disposicion`**

The SQS message contains the document metadata. Insert into `public.disposicion` if `disposicion_id` does not exist, otherwise retrieve the existing `id`. Use `ON CONFLICT (disposicion_id) DO NOTHING` followed by a `SELECT` to always get the `id`.

**Step 2 — Insert matched chunks into `public.disposicion_contenido`**

The SQS message contains a list of `tenant_anmat.documents.id` values that matched the semantic search. For each one, query `tenant_anmat.documents` to retrieve `chunk_text` and `embedding`, then insert a row into `public.disposicion_contenido` with:
- `contenido = chunk_text`
- `embedding_vector = embedding`
- `disposicion_id` from Step 1

**Step 3 — Insert `public.alerta_generada`**

Insert one row into `public.alerta_generada` using:
- `busqueda_id` from the message
- `disposicion_id` from Step 1
- `estado_alerta` and `fechayhora_ocurrencia` from the message
- Default `enviada = false`, `leido = false`, `eliminado = false`

---

## SQS message schema

```json
{
  "busqueda_id": 42,
  "estado_alerta": 1,
  "fechayhora_ocurrencia": "2026-05-07T14:30:00",
  "disposicion": {
    "disposicion_id": "ANMAT-2026-123",
    "descripcion": "Disposición sobre medicamento X",
    "url": "https://anmat.gov.ar/.../disp_123.pdf",
    "nombre_pdf": "disp_123.pdf",
    "archivo": null,
    "fecha_de_aparicion": "2026-05-01T00:00:00",
    "fecha_de_publicacion": "2026-05-02T00:00:00"
  },
  "matched_chunk_ids": [101, 245, 389]
}
```

`matched_chunk_ids` are `tenant_anmat.documents.id` integer values.

---

## Implementation requirements

- Runtime: **Python 3.12**
- DB credentials from **AWS Secrets Manager** via `DB_SECRET_ARN` env var. The secret contains `host`, `port`, `dbname`, `username`, `password`
- Use **`psycopg2`**. Open **one connection per Lambda invocation**, not per SQS record
- Use **partial batch response**: return `{ "batchItemFailures": [...] }` with the `messageId` of any failed record. Successful records in the same batch must not be retried
- Each SQS record is processed in its **own transaction**. If one record fails, roll back only that transaction and add it to `batchItemFailures`
- Log `alerta_id`, `disposicion_id`, `busqueda_id` and count of chunks inserted on success
- Validate required fields (`busqueda_id`, `disposicion.disposicion_id`, `matched_chunk_ids`) and raise `ValueError` with a descriptive message if any is missing
- Handle the case where a `matched_chunk_ids` entry does **not exist** in `tenant_anmat.documents` — log a warning and skip that chunk, do **not** fail the entire record

---

## File structure

```
handler.py         ← single file, no submodules
requirements.txt   ← psycopg2-binary==2.9.9
```

---

## Do not include

- Terraform
- Unit tests
- Docker
- CI/CD configuration

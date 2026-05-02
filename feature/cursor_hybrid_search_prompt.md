# Cursor Prompt — Migración a Búsqueda Híbrida (pgvector + FTS + RRF)

## Contexto

El código a modificar corresponde a la Lambda **`rag_lmbd_query`**.

Tengo un sistema RAG sobre AWS con pgvector (Postgres). La búsqueda actual es puramente vectorial con embeddings de Cohere y falla al buscar keywords exactas (siglas, términos técnicos) porque el cosine distance entre una query corta y un chunk largo es alto aunque la palabra esté presente.

## Objetivo

Migrar la búsqueda a un modelo híbrido: vectorial (Cohere embeddings) + léxica (PostgreSQL full-text search con `tsvector`) mergeadas con Reciprocal Rank Fusion (RRF), todo dentro del mismo Postgres. Sin infraestructura adicional.

---

## DDL actual de referencia

```sql
CREATE TABLE IF NOT EXISTS {{TENANT_SCHEMA}}.documents (
    id BIGSERIAL PRIMARY KEY,
    agent_id UUID NOT NULL,
    document_id UUID NOT NULL,
    document_name TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(1536),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_embedding
    ON {{TENANT_SCHEMA}}.documents
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

---

## PASO 1 — Crear script de migración SQL

Crear el archivo `migrations/add_hybrid_search.sql` con el siguiente contenido exacto. Mantener el placeholder `{{TENANT_SCHEMA}}` para reemplazar antes de ejecutar por schema.

```sql
-- Migración: Hybrid Search Support
-- Reemplazar {{TENANT_SCHEMA}} antes de ejecutar.
-- Prerequisito: tabla {{TENANT_SCHEMA}}.documents ya existe con columna chunk_text TEXT.

-- 1. Columna tsvector generada automáticamente (se actualiza sola en INSERT/UPDATE)
ALTER TABLE {{TENANT_SCHEMA}}.documents
    ADD COLUMN IF NOT EXISTS fts_vector tsvector
    GENERATED ALWAYS AS (to_tsvector('spanish', coalesce(chunk_text, ''))) STORED;

-- 2. Índice GIN para full-text search
CREATE INDEX IF NOT EXISTS idx_documents_fts_{{TENANT_SCHEMA}}
    ON {{TENANT_SCHEMA}}.documents
    USING GIN(fts_vector);

-- 3. Reemplazar IVFFlat por HNSW (mejor recall, no requiere datos previos al indexar)
DROP INDEX IF EXISTS {{TENANT_SCHEMA}}.idx_documents_embedding;

CREATE INDEX IF NOT EXISTS idx_documents_hnsw_{{TENANT_SCHEMA}}
    ON {{TENANT_SCHEMA}}.documents
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Verificación post-migración (ejecutar manualmente)
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_schema = '{{TENANT_SCHEMA}}' AND table_name = 'documents';
```

---

## PASO 2 — Reemplazar `semantic_search` en el Lambda

Ubicar el archivo Python de la Lambda **`rag_lmbd_query`** que contiene la función `semantic_search` y reemplazarla **completamente** por la siguiente implementación. No modificar ninguna otra función del archivo.

```python
def semantic_search(
    query,
    tenant_id,
    document_name=None,
    agent_id=None,
    chunk_text=None,
    created_at_day=None,
    k=50,
    rrf_k=60,            # Constante RRF estándar (no modificar salvo tuning fino)
    vector_weight=0.5,   # Peso rama semántica  — subir para queries conversacionales
    lexical_weight=0.5,  # Peso rama léxica     — subir para keywords/siglas exactas
):
    # ── 1. Embedding de la query ──────────────────────────────────────────────
    q_emb = embed(query, input_type="search_query")

    if not isinstance(q_emb, list):
        raise ValueError("El embedding debe ser una lista")
    if len(q_emb) != EXPECTED_EMBEDDING_DIM:
        raise ValueError(
            f"Embedding query tiene {len(q_emb)} dims; se esperaban {EXPECTED_EMBEDDING_DIM}"
        )

    q_emb_str = "[" + ",".join(str(float(x)) for x in q_emb) + "]"

    # ── 2. Preparar filtros compartidos por ambas ramas ───────────────────────
    schema = resolve_schema_name(tenant_id)
    conn = get_connection()
    cur = conn.cursor()

    filter_clauses = []
    filter_params = []

    if document_name:
        filter_clauses.append("document_name = %s")
        filter_params.append(document_name)
    if agent_id:
        filter_clauses.append("agent_id = %s")
        filter_params.append(agent_id)
    if chunk_text:
        filter_clauses.append("chunk_text = %s")
        filter_params.append(chunk_text)
    if created_at_day is not None:
        start_utc = datetime.combine(created_at_day, time.min, tzinfo=timezone.utc)
        end_utc   = start_utc + timedelta(days=1)
        filter_clauses.append("created_at >= %s AND created_at < %s")
        filter_params.append(start_utc.replace(tzinfo=None))
        filter_params.append(end_utc.replace(tzinfo=None))

    where_sql = ("WHERE " + " AND ".join(filter_clauses)) if filter_clauses else ""

    # ── 3. Query híbrida con RRF en una sola llamada SQL ──────────────────────
    #
    # Estructura de CTEs:
    #   base           → aplica filtros y calcula vector_distance una sola vez
    #   vector_ranked  → top-K por cosine distance (rama semántica)
    #   lexical_ranked → top-K por ts_rank_cd      (rama léxica)
    #   rrf            → FULL OUTER JOIN + score RRF ponderado
    #   (query final)  → ORDER BY rrf_score DESC LIMIT k
    #
    sql = f"""
        WITH base AS (
            SELECT
                ctid,
                chunk_text,
                document_name,
                embedding <=> %s::vector AS vector_distance
            FROM {schema}.documents
            {where_sql}
        ),

        vector_ranked AS (
            SELECT
                ctid,
                chunk_text,
                document_name,
                vector_distance,
                ROW_NUMBER() OVER (ORDER BY vector_distance ASC) AS vec_rank
            FROM base
            ORDER BY vector_distance ASC
            LIMIT %s
        ),

        lexical_ranked AS (
            SELECT
                d.ctid,
                d.chunk_text,
                d.document_name,
                ts_rank_cd(d.fts_vector, query, 32) AS lex_score,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank_cd(d.fts_vector, query, 32) DESC
                ) AS lex_rank
            FROM {schema}.documents d,
                 plainto_tsquery('spanish', %s) AS query
            {where_sql}
            ORDER BY lex_score DESC
            LIMIT %s
        ),

        rrf AS (
            SELECT
                COALESCE(v.ctid,          l.ctid)          AS ctid,
                COALESCE(v.chunk_text,    l.chunk_text)    AS chunk_text,
                COALESCE(v.document_name, l.document_name) AS document_name,
                v.vector_distance,
                (
                    COALESCE(%s::float / (%s + v.vec_rank::float), 0)
                  + COALESCE(%s::float / (%s + l.lex_rank::float), 0)
                ) AS rrf_score
            FROM      vector_ranked v
            FULL OUTER JOIN lexical_ranked l ON v.ctid = l.ctid
        )

        SELECT chunk_text, document_name, vector_distance, rrf_score
        FROM rrf
        ORDER BY rrf_score DESC
        LIMIT %s
    """

    # ORDEN DE PARAMS — no reordenar sin revisar el SQL
    # 1. q_emb_str          → embedding <=> en base CTE
    # 2. *filter_params      → WHERE en base CTE
    # 3. k                   → LIMIT vector_ranked
    # 4. query (texto)       → plainto_tsquery('spanish', %s)
    # 5. *filter_params      → WHERE en lexical_ranked (mismo WHERE, mismos valores)
    # 6. k                   → LIMIT lexical_ranked
    # 7. vector_weight, rrf_k → coeficientes RRF rama vectorial
    # 8. lexical_weight, rrf_k → coeficientes RRF rama léxica
    # 9. k                   → LIMIT final
    params = [
        q_emb_str,                        # 1
        *filter_params,                   # 2
        k,                                # 3
        query,                            # 4
        *filter_params,                   # 5
        k,                                # 6
        vector_weight, rrf_k,             # 7
        lexical_weight, rrf_k,            # 8
        k,                                # 9
    ]

    # ── 4. Ejecutar ───────────────────────────────────────────────────────────
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception as e:
        print(f"[retrieval] ERROR en hybrid search: {e}")
        raise
    finally:
        cur.close()
        conn.close()

    print(
        f"[retrieval] hybrid search returned {len(rows)} rows "
        f"(k={k}, schema={schema}, vector_w={vector_weight}, lexical_w={lexical_weight})"
    )

    # ── 5. Filtrar por distancia semántica ────────────────────────────────────
    # rows: (chunk_text, document_name, vector_distance, rrf_score)
    # Un chunk que solo matchea por léxica tiene vector_distance=None → lo incluimos siempre
    matched_rows = [
        row for row in rows
        if row[2] is None or row[2] <= MAX_SEMANTIC_DISTANCE
    ]

    # Fallback: si ninguno pasa el umbral, devolver el mejor por rrf_score
    if not matched_rows and rows:
        n = min(max(1, SEMANTIC_FALLBACK_TOP_N), len(rows))
        matched_rows = rows[:n]
        dists = [round(float(r[2]), 4) for r in matched_rows if r[2] is not None]
        print(
            f"[retrieval] no chunk under MAX_SEMANTIC_DISTANCE={MAX_SEMANTIC_DISTANCE}; "
            f"using best {n} by rrf_score, vector_distances={dists}"
        )
    elif not rows:
        print(
            "[retrieval] 0 rows: revisá tenant_id, agent_id, columna fts_vector, "
            "document_name/chunk_text/created_at o datos en BD"
        )

    chunks    = [row[0] for row in matched_rows]
    documents = sorted(set(row[1] for row in matched_rows))

    return chunks, documents
```

---

## PASO 3 — Guía de tuning de pesos post-deploy

Una vez deployado, ajustar `vector_weight` y `lexical_weight` según el tipo de query predominante. Los dos valores **no necesitan sumar 1.0** (RRF es un ranking, no una probabilidad), pero es conveniente para razonar sobre la influencia relativa.

| Escenario de uso | `vector_weight` | `lexical_weight` |
|---|---|---|
| Keywords exactas: siglas, códigos, nombres propios | 0.3 | 0.7 |
| Mixto (punto de partida recomendado) | 0.5 | 0.5 |
| Queries conversacionales / conceptuales | 0.7 | 0.3 |
| Documentos muy técnicos con jerga de dominio | 0.4 | 0.6 |

> **Para el dominio bancario** (SWIFT, ISO 20022, COPP, pain.001, etc.) empezar con `vector_weight=0.4` / `lexical_weight=0.6`.

---

## PASO 4 — Test de regresión mínimo (ejecutar localmente antes de deploy)

Agregar este script como `tests/test_hybrid_search.py`:

```python
"""
Test de regresión para validar que hybrid search encuentra keywords exactas
que la búsqueda puramente vectorial perdía.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Importar la función desde el módulo correspondiente
from lambda_handler import semantic_search   # ajustar import según estructura del proyecto

TEST_TENANT_ID  = os.environ["TEST_TENANT_ID"]
TEST_AGENT_ID   = os.environ["TEST_AGENT_ID"]

# Casos que DEBEN encontrarse (keywords que fallaban antes)
MUST_FIND = [
    "SWIFT",
    "ISO 20022",
    "pain.001",
    "COPP",
]

# Casos semánticos que deben seguir funcionando
SEMANTIC_CASES = [
    "transferencias internacionales",
    "procesamiento de pagos en lote",
]

def test_keyword(keyword):
    chunks, docs = semantic_search(
        query=keyword,
        tenant_id=TEST_TENANT_ID,
        agent_id=TEST_AGENT_ID,
        k=20,
    )
    found = any(keyword.lower() in c.lower() for c in chunks)
    status = "✅ PASS" if found else "❌ FAIL"
    print(f"{status} | keyword='{keyword}' | chunks_returned={len(chunks)} | docs={docs}")
    return found

if __name__ == "__main__":
    print("\n=== Keywords exactas (críticas) ===")
    kw_results = [test_keyword(kw) for kw in MUST_FIND]

    print("\n=== Queries semánticas (regresión) ===")
    sem_results = [test_keyword(q) for q in SEMANTIC_CASES]

    total = len(kw_results) + len(sem_results)
    passed = sum(kw_results) + sum(sem_results)
    print(f"\nResultado: {passed}/{total} tests pasaron")

    if not all(kw_results):
        print("⚠️  Alguna keyword crítica no fue encontrada — revisar pesos o migración SQL")
        sys.exit(1)
```

---

## Notas importantes para Cursor

- **No modificar** la firma pública de `semantic_search` — el handler existente la llama sin los parámetros nuevos (`rrf_k`, `vector_weight`, `lexical_weight`) y los defaults son suficientes.
- **La columna `fts_vector`** es `GENERATED ALWAYS AS ... STORED`, por lo tanto Postgres la mantiene automáticamente. No hay que modificar el código de ingesta/upload de documentos.
- **`ctid`** es el identificador físico de fila en Postgres. Es válido como join key dentro de una transacción/query pero **no persistirlo** en ningún lado (cambia con VACUUM FULL).
- **Si el idioma de los documentos no es español**, cambiar `'spanish'` por `'english'` o `'simple'` en ambas ocurrencias del SQL (`to_tsvector` y `plainto_tsquery`). `'simple'` no aplica stemming y es más predecible para siglas y términos técnicos.
- **Orden de ejecución**: primero el SQL de migración en cada schema de tenant, luego el deploy del Lambda.

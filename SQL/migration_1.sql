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
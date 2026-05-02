-- Migración: Hybrid Search Support
-- Reemplazar {{TENANT_SCHEMA}} antes de ejecutar.
-- Prerequisito: tabla {{TENANT_SCHEMA}}.documents ya existe con columna chunk_text TEXT.
--
-- Si ves: "memory required is X MB, maintenance_work_mem is Y MB"
-- → subí memoria para esta sesión ANTES de los CREATE INDEX (GIN/HNSW consumen maintenance_work_mem):
--     SET maintenance_work_mem = '256MB';   -- o 512MB / 1GB en tablas muy grandes
-- En RDS/Aurora también podés subir el parámetro del parameter group (maintenance_work_mem)
-- y reiniciar / aplicar según corresponda, para que el default del servidor sea mayor.

-- Misma sesión: más RAM para construcción de índices (válido en la mayoría de roles).
SET maintenance_work_mem = '256MB';

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

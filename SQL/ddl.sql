-- Reemplazar {{TENANT_SCHEMA}} antes de ejecutar.
-- Ejemplo: alert_prod

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS {{TENANT_SCHEMA}};

CREATE TABLE IF NOT EXISTS {{TENANT_SCHEMA}}.agents (
    agent_id UUID PRIMARY KEY,
    agent_name TEXT NOT NULL,
    description TEXT,
    prompt_template TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {{TENANT_SCHEMA}}.documents (
    id BIGSERIAL PRIMARY KEY,
    agent_id UUID NOT NULL,
    document_id UUID NOT NULL,
    document_name TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(1536),
    chunk_index INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_embedding
    ON {{TENANT_SCHEMA}}.documents
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_documents_agent_id
    ON {{TENANT_SCHEMA}}.documents(agent_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_doc_chunk
    ON {{TENANT_SCHEMA}}.documents(document_id, chunk_index);

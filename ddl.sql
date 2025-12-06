CREATE SCHEMA IF NOT EXISTS {tenant_name};

CREATE TABLE IF NOT EXISTS {tenant_name}.agents (
    agent_id       UUID PRIMARY KEY,
    agent_name     TEXT NOT NULL,
    description    TEXT,
    prompt_template TEXT NOT NULL,   -- agregado como solicitaste
    created_at     TIMESTAMP DEFAULT NOW()
);

drop table {tenant_name}.documents
CREATE TABLE IF NOT EXISTS {tenant_name}.documents (
    id serial4 NOT NULL,     -- PK único por chunk
    agent_id       UUID not null,
    document_id     UUID  NOT NULL,     -- mismo valor para todos los chunks del documento
    document_name   TEXT NOT NULL,     -- nombre del archivo original
    chunk_text      TEXT          NOT NULL,     -- contenido del chunk
    embedding       VECTOR(1536),    -- posición del chunk en el documento
    created_at      TIMESTAMP     DEFAULT NOW(),
    CONSTRAINT documents_pkey PRIMARY KEY (id)
);

CREATE INDEX ON {tenant_name}.documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);



CREATE INDEX IF NOT EXISTS idx_agents 
    ON {tenant_name}.agents(agent_id);

INSERT INTO {tenant_name}.agents (
    agent_id,
    agent_name,
    description,
    prompt_template
)
VALUES (
    {agent_id},
    'Agent Title ',
    'Agent Description',
    'Prompt template especializado para el tenant {tenant_name}."  --- CONTEXTO ---
{context}

--- PREGUNTA ---
{query}

Responde con precisión y sin inventar.'
);

UPDATE {tenant_name}.agents
SET prompt_template = 'Eres un Agente para facilitar y disponibilizar informacion de Arquitectura de Software corporativa,
Responde únicamente usando el contexto provisto.
Si la información no está en el contexto, responde: No tengo información suficiente para responder.  --- CONTEXTO ---
{context}

--- PREGUNTA ---
{query}

Responde con precisión y sin inventar.'
WHERE agent_id = 'tu-agent-uuid-aquí';

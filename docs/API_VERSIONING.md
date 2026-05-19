# API Versioning - Sistema RAG

**Versión:** 1.1
**Fecha:** 2026-05-19
**Estado:** Implementado
**Task:** TASK-398

---

## Resumen

El endpoint `/query` del sistema RAG soporta variantes versionadas y una variante sin prefijo configurable.

Decisión vigente TASK-399: `/query` usa por defecto el contrato paginado v2. No requiere cambios de API Gateway ni Terraform para cambiar la URL pública.

| Endpoint | Versión | Comportamiento |
|----------|---------|---------------|
| `/query` | Configurable, default código: v2 | URL pública legacy con contrato v2 paginado |
| `/v1/query` | v1 explícito | Contrato legacy explícito |
| `/v2/query` | v2 | Nueva respuesta con paginado estándar |

---

## Endpoints

### POST /query

Endpoint público principal. Por defecto usa contrato v2. Para rollback puntual se puede configurar:

```env
UNVERSIONED_QUERY_API_VERSION=v1
```

Esto permite volver temporalmente al contrato legacy sin cambiar rutas. El valor por defecto del código es `v2`.

**Request:**
```json
{
  "query": "ibuprofeno",
  "page": 1,
  "pageSize": 10,
  "sort": "relevance",
  "start_at": "2026-01-01",
  "end_at": "2026-05-31"
}
```

**Response:**
```json
{
  "data": [
    {
      "rank": 0,
      "document_name": "aviso_2026_20260315_default_123456.pdf",
      "chunk_text": "El ibuprofeno es...",
      "distance": 0.12,
      "created_at": "2026-03-15T10:30:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "pageSize": 10,
    "hasNext": true,
    "hasPrevious": false
  },
  "metadata": {
    "response": "El ibuprofeno es...",
    "retrieval_config": {...}
  }
}
```

### POST /v1/query

Contrato legacy explícito. Usar solo si un cliente necesita la respuesta plana v1.

### POST /v2/query

Contrato paginado estándar. Mismo comportamiento esperado que `/query` por defecto.

**Request:**
```json
{
  "query": "ibuprofeno",
  "page": 1,
  "pageSize": 10,
  "sort": "relevance",
  "start_at": "2026-01-01",
  "end_at": "2026-05-31"
}
```

**Response:**
```json
{
  "data": [
    {
      "rank": 0,
      "document_name": "aviso_2026_20260315_default_123456.pdf",
      "chunk_text": "El ibuprofeno es...",
      "distance": 0.12,
      "created_at": "2026-03-15T10:30:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "pageSize": 10,
    "hasNext": true,
    "hasPrevious": false
  },
  "metadata": {
    "response": "El ibuprofeno es...",
    "retrieval_config": {...}
  }
}
```

---

## Parámetros

### v1 (`/v1/query`)

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `query` | string | - (obligatorio) | Texto de búsqueda |
| `retrieval_limit` | int | 10 | Máximo de resultados (max 500) |
| `sort_by` | string | "relevance" | Orden: "relevance", "hybrid", "date_desc" |
| `start_at` | string | - | Fecha inicio (YYYY-MM-DD) |
| `end_at` | string | - | Fecha fin (YYYY-MM-DD) |
| `tenant_id` | string | - (obligatorio) | ID del tenant |
| `agent_id` | string | - (obligatorio) | ID del agente |

### v2 (`/query` configurado, `/v2/query`)

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `query` | string | - (obligatorio) | Texto de búsqueda |
| `page` | int | 1 | Número de página (desde 1) |
| `pageSize` | int | 10 | Items por página (1-50) |
| `sort` | string | "relevance" | Orden: "relevance", "hybrid", "date_desc" |
| `start_at` | string | - | Fecha inicio (YYYY-MM-DD) |
| `end_at` | string | - | Fecha fin (YYYY-MM-DD) |
| `tenant_id` | string | - (obligatorio) | ID del tenant |
| `agent_id` | string | - (obligatorio) | ID del agente |

---

## Migración de v1 a v2

### Request: cambios de nombres

| v1 | v2 | Nota |
|----|----|------|
| `retrieval_limit` | `pageSize` | Mismo valor, distinto nombre |
| `sort_by` | `sort` | Mismo valor, distinto nombre |
| - | `page` | Nuevo parámetro (default 1) |

### Response: nueva estructura

La respuesta v2 envuelve los datos en una estructura con 3 secciones:

- **`data`**: Array de `context_items` paginados.
- **`pagination`**: Metadatos de paginación (`page`, `pageSize`, `hasNext`, `hasPrevious`)
- **`metadata`**: Contiene `response` y `retrieval_config`.

### Código de ejemplo: TypeScript

```typescript
// Legacy explícito (v1)
const resp = await api.post('/v1/query', { query: 'ibuprofeno', retrieval_limit: 10 });
console.log(resp.response, resp.contexts);

// Actual (v2 sobre /query)
const resp = await api.post('/query', { query: 'ibuprofeno', page: 1, pageSize: 10 });
console.log(resp.metadata.response, resp.data);
console.log('Pagina:', resp.pagination.page, 'Siguiente:', resp.pagination.hasNext);
```

---

## Validaciones v2

- `page >= 1` — caso contrario error 400
- `pageSize >= 1 y <= 50` — caso contrario error 400
- `sort` acepta los mismos valores que `sort_by` en v1

---

## Compatibilidad hacia atrás (v2)

v2 también acepta parámetros v1 como fallback:
- Si llega `retrieval_limit` en vez de `pageSize`, se usa `retrieval_limit`
- v1 **no** acepta parámetros v2 (legacy estricto)

---

## Cache (dispatcher async)

La cache del dispatcher incluye `api_version` en la key para evitar mezclar respuestas con formato distinto entre v1 y v2.

---

## Implementación

El versionado usa routing interno en el mismo Lambda (`rag_lmbd_query/index.py`) y en el dispatcher async:

1. `_extract_version_from_path()` detecta la versión desde `api_version`, la URL o `UNVERSIONED_QUERY_API_VERSION`.
2. `handler()` enruta según versión detectada
3. `_normalize_v2_body()` transforma params v2 a formato interno v1
4. `_build_v2_response()` wrappea la respuesta v1 en estructura paginada
5. El dispatcher propaga `api_version` al worker SQS para que el resultado async mantenga el formato correcto.

**Archivos modificados:**
- `rag-agents/apps/rag_lmbd_query/index.py`
- `rag-agents/apps/rag_lmbd_query_dispatcher/index.py`

**Tests:**
- `rag-agents/tests/test_api_versioning.py`

---

## Referencias

- [VERSIONADO_API.md](VERSIONADO_API.md) — Estrategia general de versionado
- [PAGINADO_ESTANDAR.md](PAGINADO_ESTANDAR.md) — Especificación de paginado
- TASK-398: Versionado de API en RAG

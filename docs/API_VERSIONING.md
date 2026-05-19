# API Versioning - Sistema RAG

**Versión:** 1.0
**Fecha:** 2026-05-19
**Estado:** Implementado
**Task:** TASK-398

---

## Resumen

El endpoint `/query` del sistema RAG soporta 3 variantes de URL para permitir evolución del API sin romper clientes existentes.

| Endpoint | Versión | Comportamiento |
|----------|---------|---------------|
| `/query` | Legacy (v1) | Sin cambios, compatibilidad total |
| `/v1/query` | v1 explícito | Idéntico a `/query` |
| `/v2/query` | v2 | Nueva respuesta con paginado estándar |

---

## Endpoints

### POST /query (legacy)

Comportamiento original sin cambios. Usa parámetros v1.

**Request:**
```json
{
  "query": "ibuprofeno",
  "retrieval_limit": 10,
  "sort_by": "relevance",
  "start_at": "2026-01-01",
  "end_at": "2026-05-31"
}
```

**Response:**
```json
{
  "response": "El ibuprofeno es...",
  "contexts": [...],
  "documents": [...],
  "context_items": [...],
  "retrieval_config": {...}
}
```

### POST /v1/query

Idéntico a `/query`. Mismos parámetros y misma respuesta.

### POST /v2/query

Nueva versión con paginado estándar.

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
  "data": {
    "response": "El ibuprofeno es...",
    "contexts": [...],
    "context_items": [...],
    "documents": [...]
  },
  "pagination": {
    "page": 1,
    "pageSize": 10,
    "hasNext": true,
    "hasPrevious": false
  },
  "metadata": {
    "retrieval_config": {...}
  }
}
```

---

## Parámetros

### v1 (`/query`, `/v1/query`)

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `query` | string | - (obligatorio) | Texto de búsqueda |
| `retrieval_limit` | int | 10 | Máximo de resultados (max 500) |
| `sort_by` | string | "relevance" | Orden: "relevance", "hybrid", "date_desc" |
| `start_at` | string | - | Fecha inicio (YYYY-MM-DD) |
| `end_at` | string | - | Fecha fin (YYYY-MM-DD) |
| `tenant_id` | string | - (obligatorio) | ID del tenant |
| `agent_id` | string | - (obligatorio) | ID del agente |

### v2 (`/v2/query`)

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

- **`data`**: Contiene `response`, `contexts`, `context_items`, `documents` (equivalente a la respuesta v1 plana)
- **`pagination`**: Metadatos de paginación (`page`, `pageSize`, `hasNext`, `hasPrevious`)
- **`metadata`**: Contiene `retrieval_config` (antes directo en la raíz)

### Código de ejemplo: TypeScript

```typescript
// Antes (v1)
const resp = await api.post('/query', { query: 'ibuprofeno', retrieval_limit: 10 });
console.log(resp.response, resp.contexts);

// Después (v2)
const resp = await api.post('/v2/query', { query: 'ibuprofeno', page: 1, pageSize: 10 });
console.log(resp.data.response, resp.data.contexts);
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

El versionado usa routing interno en el mismo Lambda (`rag_lmbd_query/index.py`):

1. `_extract_version_from_path()` detecta la versión desde la URL
2. `handler()` enruta según versión detectada
3. `_normalize_v2_body()` transforma params v2 a formato interno v1
4. `_build_v2_response()` wrappea la respuesta v1 en estructura paginada

**Archivos modificados:**
- `rag-agents/apps/rag_lmbd_query/index.py`
- `rag-agents/apps/rag_lmbd_query_dispatcher/index.py`

**Tests:**
- `rag-agents/tests/test_api_versioning.py` (21 tests)

---

## Referencias

- [VERSIONADO_API.md](VERSIONADO_API.md) — Estrategia general de versionado
- [PAGINADO_ESTANDAR.md](PAGINADO_ESTANDAR.md) — Especificación de paginado
- TASK-398: Versionado de API en RAG

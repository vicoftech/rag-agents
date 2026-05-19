# Especificación de Paginado Estándar - Proyecto Alert

**Versión:** 1.0
**Fecha:** 2026-05-19
**Estado:** Aprobado para implementación en API v2

> **Nota:** Este documento es agnóstico al asistente de IA utilizado. Es compatible con Claude Code, ChatGPT Codex, OpenCode y otros agentes de desarrollo. Ver [AGENTS.md](../AGENTS.md) para más información sobre el entorno multi-agente del proyecto.

---

## 1. Resumen Ejecutivo

Este documento define el estándar de paginado para todas las APIs del proyecto Alert (backend Java, Lambdas Python, frontend Angular). El objetivo es tener una interfaz común, predecible y fácil de usar en todo el sistema.

**Implementación:** Este estándar se implementará en **API v2**. Ver [VERSIONADO_API.md](VERSIONADO_API.md) para estrategia de migración.

---

## 2. Estrategia de Paginado

### 2.1. Tipo de paginado: **Offset-based**

Se utiliza paginado basado en offset (página + tamaño) por las siguientes razones:

- ✅ Más intuitivo para usuarios (página 1, 2, 3...)
- ✅ Compatible con UI de paginación tradicional
- ✅ Adecuado para datos estables (documentos RAG, alertas, búsquedas históricas)
- ✅ Soportado nativamente por PostgreSQL (OFFSET/LIMIT)
- ✅ Cacheable en query dispatcher

**Casos especiales:** Para listados con modificaciones frecuentes o streaming, considerar cursor-based en futuras versiones.

---

## 3. Interfaz Común de Request

### 3.1. Parámetros de Request

Todos los endpoints paginados deben aceptar estos parámetros (query params o body):

| Parámetro | Tipo | Obligatorio | Default | Descripción |
|-----------|------|-------------|---------|-------------|
| `page` | integer | No | 1 | Número de página (base 1) |
| `pageSize` | integer | No | 10 | Cantidad de items por página |
| `sort` | string | No | (depende del endpoint) | Campo de ordenamiento (ej: `created_at`, `relevance`) |
| `order` | string | No | `asc` o `desc` | Dirección del ordenamiento |

**Alias aceptados (compatibilidad):**
- `page` → `pageNumber`, `p`
- `pageSize` → `limit`, `size`, `perPage`

### 3.2. Validaciones

**Reglas obligatorias:**
- `page` >= 1
- `pageSize` >= 1 y <= `MAX_PAGE_SIZE` (default: 100)
- Si `page` o `pageSize` son inválidos → Error 400

**Límites recomendados por tipo de endpoint:**

| Tipo de endpoint | Default pageSize | Max pageSize | Razón |
|------------------|------------------|--------------|-------|
| Búsqueda RAG | 10 | 50 | LLM context, costo, latencia |
| Listado simple (alertas, usuarios) | 20 | 100 | Performance estándar |
| Reportes/exports | 50 | 500 | Batch processing |

### 3.3. Ejemplos de Request

**GET con query params:**
```http
GET /api/alertas?page=2&pageSize=20&sort=created_at&order=desc
```

**POST con body (búsqueda RAG):**
```json
{
  "query": "ibuprofeno",
  "start_at": "2026-01-01",
  "end_at": "2026-05-31",
  "page": 1,
  "pageSize": 10,
  "sort": "relevance"
}
```

---

## 4. Interfaz Común de Response

### 4.1. Estructura de Response

Todos los endpoints paginados deben devolver esta estructura:

```json
{
  "data": [...],
  "pagination": {
    "page": 2,
    "pageSize": 20,
    "totalItems": 157,
    "totalPages": 8,
    "hasNext": true,
    "hasPrevious": true
  },
  "metadata": {
    ...
  }
}
```

### 4.2. Campos de Response

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `data` | array | Items de la página actual |
| `pagination` | object | Información de paginado |
| `pagination.page` | integer | Página actual (base 1) |
| `pagination.pageSize` | integer | Tamaño de página solicitado |
| `pagination.totalItems` | integer | Total de items disponibles |
| `pagination.totalPages` | integer | Total de páginas (`ceil(totalItems / pageSize)`) |
| `pagination.hasNext` | boolean | Hay página siguiente |
| `pagination.hasPrevious` | boolean | Hay página anterior |
| `metadata` | object | Metadatos específicos del endpoint (opcional) |

### 4.3. Cálculos

```
totalPages = ceil(totalItems / pageSize)
hasNext = page < totalPages
hasPrevious = page > 1
```

**Caso especial:** Si `totalItems` es desconocido (ej: búsqueda vectorial costosa), se puede omitir `totalItems` y `totalPages`, pero mantener `hasNext`/`hasPrevious` basado en resultados.

### 4.4. Ejemplos de Response

**Response completa:**
```json
{
  "data": [
    {"id": 1, "nombre": "Alerta A"},
    {"id": 2, "nombre": "Alerta B"}
  ],
  "pagination": {
    "page": 2,
    "pageSize": 20,
    "totalItems": 157,
    "totalPages": 8,
    "hasNext": true,
    "hasPrevious": true
  },
  "metadata": {
    "query_time_ms": 234
  }
}
```

**Response sin total (búsqueda costosa):**
```json
{
  "data": [...],
  "pagination": {
    "page": 1,
    "pageSize": 10,
    "hasNext": true,
    "hasPrevious": false
  },
  "metadata": {
    "retrieval_config": {
      "max_semantic_distance": 0.45
    }
  }
}
```

---

## 5. Casos de Uso por Componente

### 5.1. Backend Java (Spring Boot)

**Endpoints afectados:**
- `/api/alertas` - Listado de alertas generadas
- `/api/busquedas` - Historial de búsquedas
- `/api/disposiciones` - Listado de disposiciones ANMAT
- `/api/usuarios` - Gestión de usuarios

**Implementación sugerida:**
```java
public class PagedResponse<T> {
    private List<T> data;
    private Pagination pagination;
    private Map<String, Object> metadata;
}

public class Pagination {
    private int page;
    private int pageSize;
    private long totalItems;
    private int totalPages;
    private boolean hasNext;
    private boolean hasPrevious;
}
```

### 5.2. Lambda Python (RAG)

**Endpoints afectados:**
- `/query` - Búsqueda RAG síncrona
- `/query` (async dispatcher) - Búsqueda RAG asíncrona
- `/busqueda/historica` - Búsquedas históricas

**Consideraciones especiales:**
- Búsqueda vectorial costosa → omitir `totalItems` si requiere COUNT(*) adicional
- `pageSize` en RAG debe respetar límites (max 50)
- Cache en dispatcher debe incluir `page` + `pageSize` en la clave

**Implementación sugerida:**
```python
def paginate_response(items, page, page_size, total_items=None):
    total_pages = math.ceil(total_items / page_size) if total_items else None
    return {
        "data": items,
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "totalItems": total_items,
            "totalPages": total_pages,
            "hasNext": (page < total_pages) if total_pages else len(items) == page_size,
            "hasPrevious": page > 1,
        }
    }
```

### 5.3. Frontend Angular

**Componentes afectados:**
- Listado de alertas
- Historial de búsquedas
- Resultados de búsqueda RAG

**Interface TypeScript:**
```typescript
interface PagedResponse<T> {
  data: T[];
  pagination: {
    page: number;
    pageSize: number;
    totalItems?: number;
    totalPages?: number;
    hasNext: boolean;
    hasPrevious: boolean;
  };
  metadata?: Record<string, any>;
}

interface PaginationParams {
  page?: number;
  pageSize?: number;
  sort?: string;
  order?: 'asc' | 'desc';
}
```

---

## 6. Estrategia de Migración

### 6.1. Versionado de API

**Estrategia adoptada:** URL-based versioning con creación de API v2.

- **API v1** (actual): Mantiene estructura legacy sin cambios
- **API v2** (nueva): Implementa paginado estándar definido en este documento

Ver [VERSIONADO_API.md](VERSIONADO_API.md) para detalles completos de la estrategia de versionado.

### 6.2. Comparación v1 vs v2

**Endpoint v1 (legacy):**
```
POST /v1/query
{
  "query": "ibuprofeno",
  "retrieval_limit": 10,
  "sort_by": "relevance"
}

Response:
{
  "response": "...",
  "contexts": [...],
  "documents": [...],
  "retrieval_config": {...}
}
```

**Endpoint v2 (con paginado estándar):**
```
POST /v2/query
{
  "query": "ibuprofeno",
  "page": 1,
  "pageSize": 10,
  "sort": "relevance"
}

Response:
{
  "data": {
    "response": "...",
    "contexts": [...],
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

### 6.3. Timeline de Migración

- **2026 Q2:** Desarrollo y testing de API v2
- **2026 Q3:** Lanzamiento de v2, v1 pasa a maintenance
- **2026 Q4:** Migración gradual de clientes a v2
- **2027 Q1:** v1 marcada como deprecated
- **2027 Q2:** v1 EOL (End of Life)

### 6.4. Endpoints Prioritarios para v2

1. **Alta prioridad:** Búsqueda RAG (`/query`)
2. **Media prioridad:** Alertas, búsquedas históricas
3. **Baja prioridad:** Endpoints admin (usuarios, configuración)

---

## 7. Manejo de Errores

### 7.1. Errores comunes

**Página fuera de rango:**
```json
{
  "statusCode": 400,
  "error": "Invalid page number",
  "message": "La página solicitada (25) excede el total de páginas disponibles (8)"
}
```

**pageSize excede máximo:**
```json
{
  "statusCode": 400,
  "error": "Invalid page size",
  "message": "pageSize (150) excede el máximo permitido (100)"
}
```

**Parámetros inválidos:**
```json
{
  "statusCode": 400,
  "error": "Invalid pagination parameters",
  "message": "page debe ser >= 1, pageSize debe estar entre 1 y 100"
}
```

---

## 8. Consideraciones de Performance

### 8.1. Cache

**Estrategia de cache:**
- Key incluye: `endpoint` + `params` + `page` + `pageSize` + `sort`
- TTL sugerido: 5-15 minutos (depende de frecuencia de actualización)
- Invalidar cache al crear/modificar/eliminar items

**Ejemplo de cache key:**
```
cache:query:tenant_1:agent_2:ibuprofeno:2026-01-01:2026-05-31:page_2:size_10:sort_relevance
```

### 8.2. Optimizaciones de BD

**PostgreSQL:**
- Índices en columnas de ordenamiento (`created_at`, `updated_at`)
- Evitar `COUNT(*)` en tablas grandes (usar estimaciones con `pg_class.reltuples` o calcular async)
- Considerar cursor-based si OFFSET alto (>10000) causa performance issues

**Búsqueda vectorial:**
- LIMIT en SQL debe ser `page * pageSize` para offset correcto
- Filtrado post-SQL (BU-04) aplica después del offset

---

## 9. Testing

### 9.1. Casos de prueba obligatorios

Para cada endpoint paginado:

- ✅ Request sin parámetros (debe usar defaults)
- ✅ Request con `page=1, pageSize=10`
- ✅ Request con `page` > `totalPages` (debe retornar error o vacío)
- ✅ Request con `pageSize=1` (caso mínimo)
- ✅ Request con `pageSize=MAX` (caso máximo)
- ✅ Request con `pageSize > MAX` (debe retornar error)
- ✅ Verificar `hasNext`/`hasPrevious` en primera, última y páginas intermedias
- ✅ Verificar cálculo correcto de `totalPages`
- ✅ Verificar que `data.length <= pageSize`

---

## 10. Ejemplos Completos

### 10.1. Búsqueda RAG con paginado

**Request:**
```http
POST /api/rag/query
Content-Type: application/json

{
  "query": "ibuprofeno",
  "start_at": "2026-01-01",
  "end_at": "2026-05-31",
  "page": 1,
  "pageSize": 10,
  "sort": "relevance"
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
    },
    // ... 9 items más
  ],
  "pagination": {
    "page": 1,
    "pageSize": 10,
    "hasNext": true,
    "hasPrevious": false
  },
  "metadata": {
    "retrieval_config": {
      "document_date_filter_applied": true,
      "documents_filtered_by_date": 5
    }
  }
}
```

### 10.2. Listado de alertas con paginado

**Request:**
```http
GET /api/alertas?page=2&pageSize=20&sort=created_at&order=desc
```

**Response:**
```json
{
  "data": [
    {
      "id": 41,
      "titulo": "Alerta ibuprofeno",
      "created_at": "2026-05-15T14:30:00Z",
      "estado": "activa"
    },
    // ... 19 items más
  ],
  "pagination": {
    "page": 2,
    "pageSize": 20,
    "totalItems": 157,
    "totalPages": 8,
    "hasNext": true,
    "hasPrevious": true
  }
}
```

---

## 11. Referencias y Estándares

### 11.1. Estándares de industria

- **JSON:API** - https://jsonapi.org/format/#fetching-pagination
- **RFC 5988** - Web Linking (rel: next, prev, first, last)
- **GraphQL Cursor Connections** - https://relay.dev/graphql/connections.htm

### 11.2. Bibliotecas recomendadas

**Java (Spring):**
- Spring Data `Page<T>` y `Pageable`
- Adaptar a estructura común con mapper

**Python:**
- No usar biblioteca específica, implementar helper functions
- Considerar `fastapi-pagination` para futuras APIs FastAPI

**Angular:**
- Angular Material `MatPaginator`
- Adaptar al formato estándar

---

## 12. Decisiones Pendientes

1. **¿Incluir links de navegación en response?**
   ```json
   "links": {
     "first": "/api/alertas?page=1&pageSize=20",
     "prev": "/api/alertas?page=1&pageSize=20",
     "next": "/api/alertas?page=3&pageSize=20",
     "last": "/api/alertas?page=8&pageSize=20"
   }
   ```
   **Recomendación:** No necesario inicialmente, frontend puede construir las URLs.

2. **¿Soportar cursor-based para casos específicos?**
   **Recomendación:** No en v1, evaluar en v2 si hay casos de uso claros.

3. **¿Agregar `pageInfo` adicional (ej: `itemsInPage`))?**
   **Recomendación:** No, `data.length` es suficiente.

---

## 13. Changelog

| Versión | Fecha | Cambios |
|---------|-------|---------|
| 1.0 | 2026-05-19 | Propuesta inicial |

---

## 14. Notas sobre Asistentes de IA

Este documento ha sido diseñado para ser utilizado con cualquier asistente de IA o agente de desarrollo. Es compatible con:
- **Claude Code** (Anthropic)
- **ChatGPT Codex** (OpenAI)
- **OpenCode** (otras herramientas)
- Cualquier otro asistente de desarrollo

Los ejemplos de código, estructuras y estrategias son agnósticos a la tecnología de asistencia utilizada.

Para instrucciones específicas de cada agente, consultar:
- Claude Code: [CLAUDE.md](../CLAUDE.md)
- Todos los agentes: [AGENTS.md](../AGENTS.md)

---

**Responsable:** Equipo de Desarrollo Alert
**Aprobación pendiente:** Product Owner
**Próximos pasos:** Revisar con equipo, implementar en endpoint piloto
**Compatibilidad:** Multi-agente (Claude Code, ChatGPT Codex, OpenCode)

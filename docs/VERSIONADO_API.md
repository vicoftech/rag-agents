# Versionado de API - Proyecto Alert

**Versión:** 1.0
**Fecha:** 2026-05-19
**Estado:** Estándar aprobado

> **Nota:** Este documento es agnóstico al asistente de IA utilizado. Es compatible con Claude Code, ChatGPT Codex, OpenCode y otros agentes de desarrollo. Ver [AGENTS.md](../AGENTS.md) para más información sobre el entorno multi-agente del proyecto.

---

## 1. Resumen Ejecutivo

Este documento define la estrategia de versionado para todas las APIs del proyecto Alert. El objetivo es permitir evolución continua de las APIs mientras se mantiene compatibilidad con clientes existentes.

**Estrategia elegida:** URL-based versioning (`/v1/`, `/v2/`)

---

## 2. Estrategia de Versionado

### 2.1. Tipo de Versionado: URL-based

Todas las APIs incluyen el número de versión en la URL:

```
https://api.alert.com/v1/query
https://api.alert.com/v2/query
```

**Ventajas:**
- ✅ Explícito y visible
- ✅ Fácil de cachear (CloudFront, CDN)
- ✅ Compatible con todos los clientes HTTP
- ✅ Permite deployments separados por versión
- ✅ Estándar de la industria (GitHub, Stripe, Twitter)

**Rechazadas:**
- ❌ Header-based (`Accept: application/vnd.alert.v1+json`) - Difícil de cachear
- ❌ Query param (`?version=1`) - No semántico, problemas con cache
- ❌ Subdomain (`v1.api.alert.com`) - Complejidad de DNS/certificados

### 2.2. Formato de Versiones

**Versión Mayor (Major):** `/v1/`, `/v2/`, `/v3/`

Se incrementa cuando hay **breaking changes**:
- Cambio en estructura de request/response
- Eliminación de campos
- Cambio de tipos de datos
- Cambio de comportamiento fundamental

**No se usa versionado Minor/Patch** en la URL:
- Cambios compatibles se agregan sin nueva versión
- Se documentan en changelog interno

### 2.3. Estructura de URLs

```
Estructura:
/{version}/{recurso}/{acción}

Ejemplos:
/v1/query
/v1/alertas
/v1/alertas/123
/v2/query
/v2/busquedas/historial
```

**Sin versión = última versión estable:**
```
/query → redirige a /v1/query (transitorio)
```

**Nota:** Se recomienda siempre usar versión explícita en producción.

---

## 3. Ciclo de Vida de Versiones

### 3.1. Estados de Versión

| Estado | Descripción | Support | Deprecación |
|--------|-------------|---------|-------------|
| **Active** | Versión actual, recomendada | ✅ Full support | No |
| **Maintenance** | Versión anterior, aún soportada | ⚠️ Bug fixes only | Anunciada |
| **Deprecated** | En proceso de eliminación | ❌ No support | Fecha EOL definida |
| **Retired** | Eliminada, no disponible | ❌ No disponible | EOL alcanzado |

### 3.2. Timeline Estándar

```
Lanzamiento v2:
│
├─ Día 0: v2 lanzada (Active)
│          v1 pasa a Maintenance
│
├─ +6 meses: v1 marcada Deprecated
│            Notificación a clientes
│            Warning headers en responses
│
├─ +12 meses: v1 Retired (EOL)
│             Endpoints deshabilitados
│             Retorna 410 Gone
│
└─ Futuro: v1 código eliminado del repo
```

**Excepciones:** Versiones con bajo uso pueden tener EOL más corto (3-6 meses).

### 3.3. Anuncio de Deprecación

**Headers de respuesta para versiones deprecated:**
```http
HTTP/1.1 200 OK
Deprecation: true
Sunset: Sat, 19 May 2027 23:59:59 GMT
Link: </v2/query>; rel="successor-version"
Warning: 299 - "API v1 is deprecated. Migrate to v2 by 2027-05-19"
```

**Documentación:**
- Agregar banner en docs de API deprecated
- Email a equipos de desarrollo usando la versión
- Registro en changelog

---

## 4. Compatibilidad y Breaking Changes

### 4.1. Qué es un Breaking Change

**Requiere nueva versión Mayor:**
- ✅ Eliminar campo del response
- ✅ Cambiar tipo de dato (`string` → `number`)
- ✅ Renombrar campo
- ✅ Cambiar estructura (ej: paginado)
- ✅ Cambiar validaciones de request (más estrictas)
- ✅ Cambiar código de status HTTP
- ✅ Cambiar comportamiento de ordenamiento/filtrado

**NO requiere nueva versión (backward compatible):**
- ✅ Agregar nuevo campo al response
- ✅ Agregar nuevo parámetro opcional al request
- ✅ Agregar nuevo endpoint
- ✅ Relajar validaciones (menos estrictas)
- ✅ Agregar nuevos valores a enum existente
- ✅ Mejorar performance sin cambiar comportamiento

### 4.2. Reglas de Compatibilidad

**Clientes deben:**
- Ignorar campos desconocidos en response
- No asumir orden de campos en JSON
- Manejar nuevos códigos de error gracefully

**APIs deben:**
- Mantener campos existentes en misma versión
- No cambiar semántica de campos existentes
- Documentar todos los cambios en changelog

---

## 5. Estructura de Proyecto por Versión

### 5.1. Backend Java (Spring Boot)

```
alert-backend/
└── src/main/java/com/asap/anmatpdf/
    └── controller/
        ├── v1/
        │   ├── AlertaControllerV1.java
        │   └── BusquedaControllerV1.java
        └── v2/
            ├── AlertaControllerV2.java
            └── BusquedaControllerV2.java
```

**Rutas:**
```java
@RestController
@RequestMapping("/api/v1/alertas")
public class AlertaControllerV1 { ... }

@RestController
@RequestMapping("/api/v2/alertas")
public class AlertaControllerV2 { ... }
```

### 5.2. Lambda Python (RAG)

```
rag-agents/
└── apps/
    ├── rag_lmbd_query/           # v1 (actual)
    │   └── index.py
    ├── rag_lmbd_query_v2/        # v2 (futuro)
    │   └── index.py
    └── rag_lmbd_query_dispatcher/
        └── index.py              # Enruta a v1 o v2
```

**API Gateway routes:**
```yaml
/v1/query → rag_lmbd_query
/v2/query → rag_lmbd_query_v2
```

**Alternativa (código compartido):**
```python
# apps/rag_lmbd_query/index.py
def handler_v1(event, context):
    # Lógica v1
    return legacy_response(...)

def handler_v2(event, context):
    # Lógica v2 (usa paginado estándar)
    return paginated_response(...)

def handler(event, context):
    version = extract_version_from_path(event)
    if version == "v2":
        return handler_v2(event, context)
    return handler_v1(event, context)
```

### 5.3. Frontend Angular

```typescript
// src/app/services/api.service.ts
export class ApiService {
  private readonly API_V1 = environment.apiUrl + '/v1';
  private readonly API_V2 = environment.apiUrl + '/v2';

  // Usar v2 por defecto para nuevas features
  searchRAG(params: SearchParams): Observable<PagedResponse> {
    return this.http.post(`${this.API_V2}/query`, params);
  }

  // Mantener v1 para componentes legacy
  searchRAGLegacy(params: LegacySearchParams): Observable<LegacyResponse> {
    return this.http.post(`${this.API_V1}/query`, params);
  }
}
```

---

## 6. Estrategia de Migración

### 6.1. Plan de Migración a v2

**Fase 1: Desarrollo (2 semanas)**
- ✅ Crear nuevos endpoints v2
- ✅ Implementar paginado estándar
- ✅ Mantener v1 funcionando
- ✅ Tests para ambas versiones

**Fase 2: Testing (1 semana)**
- ✅ Validar v2 en QA
- ✅ Performance testing
- ✅ Regression testing de v1

**Fase 3: Despliegue gradual (2 semanas)**
- ✅ Día 1: v2 en QA
- ✅ Día 7: v2 en UAT
- ✅ Día 14: v2 en Prod (soft launch)

**Fase 4: Migración de clientes (3 meses)**
- ✅ Mes 1: Frontend componentes nuevos usan v2
- ✅ Mes 2: Frontend componentes legacy migran a v2
- ✅ Mes 3: Validar que v1 usage < 5%

**Fase 5: Deprecación (6 meses después)**
- ✅ Marcar v1 como deprecated
- ✅ Agregar warnings
- ✅ Comunicar fecha EOL

**Fase 6: Retiro (12 meses después)**
- ✅ Deshabilitar v1
- ✅ Monitorear errores
- ✅ Eliminar código v1

### 6.2. Guía de Migración para Desarrolladores

**Ejemplo: Migrar búsqueda RAG de v1 a v2**

**v1 (actual):**
```typescript
// Request
{
  "query": "ibuprofeno",
  "retrieval_limit": 10,
  "sort_by": "relevance"
}

// Response
{
  "response": "...",
  "contexts": [...],
  "documents": [...],
  "retrieval_config": {...}
}
```

**v2 (con paginado estándar):**
```typescript
// Request
{
  "query": "ibuprofeno",
  "page": 1,
  "pageSize": 10,
  "sort": "relevance"
}

// Response
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

**Cambios en el código:**
```typescript
// Antes (v1)
this.http.post('/v1/query', {
  query: 'ibuprofeno',
  retrieval_limit: 10
}).subscribe(response => {
  this.items = response.contexts;
});

// Después (v2)
this.http.post<PagedResponse>('/v2/query', {
  query: 'ibuprofeno',
  page: 1,
  pageSize: 10
}).subscribe(response => {
  this.items = response.data.contexts;
  this.pagination = response.pagination;
});
```

---

## 7. Documentación de APIs

### 7.1. Swagger/OpenAPI

Cada versión tiene su propio spec:

```
docs/
├── openapi-v1.yaml
└── openapi-v2.yaml
```

**Swagger UI:** `https://api.alert.com/docs/v1/` y `/docs/v2/`

### 7.2. Changelog de Versiones

**Formato:**
```markdown
# API Changelog

## v2.0.0 (2026-06-01)

### Breaking Changes
- Cambio en estructura de response de `/query` (ahora con paginado estándar)
- Renombrado: `retrieval_limit` → `pageSize`
- Renombrado: `sort_by` → `sort`

### New Features
- Paginado estándar en todos los endpoints
- Soporte para `hasNext`/`hasPrevious` en responses

### Migration Guide
Ver: docs/MIGRATION_V1_TO_V2.md

## v1.5.0 (2026-05-15)

### New Features (backward compatible)
- BU-04: Filtrado de documentos por fecha (post-SQL)
- Nuevo campo `retrieval_config.documents_filtered_by_date`

### Bug Fixes
- Fix cache key en query_dispatcher
```

---

## 8. Testing de Versiones

### 8.1. Test Matrix

Cada PR debe ejecutar tests para **todas las versiones activas**:

```yaml
# .github/workflows/api-tests.yml
strategy:
  matrix:
    api_version: [v1, v2]

steps:
  - name: Test API ${{ matrix.api_version }}
    run: npm run test:${{ matrix.api_version }}
```

### 8.2. Regression Testing

Al lanzar v2, validar que v1 **no cambia**:

```bash
# Ejecutar tests de regresión para v1
pytest tests/v1/ --baseline=v1.4.0

# Ejecutar tests de integración para v2
pytest tests/v2/ --integration
```

---

## 9. Monitoreo y Métricas

### 9.1. Métricas por Versión

Trackear en Grafana/CloudWatch:

- **Request count** por versión (v1 vs v2)
- **Error rate** por versión
- **Latency p50/p95/p99** por versión
- **Deprecated warnings** emitidos

**Alerta:** Si v1 usage < 5% del total, considerar adelantar EOL.

### 9.2. Logs

Incluir versión en todos los logs:

```json
{
  "timestamp": "2026-05-19T10:30:00Z",
  "level": "INFO",
  "api_version": "v1",
  "endpoint": "/query",
  "status": 200,
  "latency_ms": 234
}
```

---

## 10. Casos Especiales

### 10.1. Lambdas Python (Serverless)

**Opción A: Lambda por versión**
- `rag_lmbd_query` (v1)
- `rag_lmbd_query_v2` (v2)
- **Ventaja:** Aislamiento completo, rollback fácil
- **Desventaja:** Duplicación de código común

**Opción B: Lambda único con routing interno**
- Un handler detecta versión del path
- Llama a `handler_v1()` o `handler_v2()`
- **Ventaja:** Código compartido
- **Desventaja:** Acoplamiento, riesgo de romper v1 al cambiar v2

**Recomendación:** Opción A para cambios grandes (ej: paginado), Opción B para cambios pequeños.

### 10.2. API Gateway

```yaml
# API Gateway routes
/v1/query:
  integration: rag_lmbd_query

/v2/query:
  integration: rag_lmbd_query_v2

# Redirect sin versión a v1 (transitorio)
/query:
  redirect: /v1/query
  status: 301
```

---

## 11. Preguntas Frecuentes

### 11.1. ¿Puedo tener v1 y v2 en el mismo deployment?

**Sí.** Backend puede tener ambas versiones en el mismo JAR/container. Lambdas pueden ser funciones separadas o un handler con routing.

### 11.2. ¿Qué pasa si un cliente llama a una versión retirada?

**Response:**
```http
HTTP/1.1 410 Gone
Content-Type: application/json

{
  "error": "API version retired",
  "message": "API v1 was retired on 2027-05-19. Please upgrade to v2.",
  "documentation": "https://docs.alert.com/api/v2/migration"
}
```

### 11.3. ¿Puedo tener versiones intermedias (v1.1, v1.2)?

**No en la URL.** Usar changelog interno para features backward-compatible. Solo incrementar versión Mayor para breaking changes.

### 11.4. ¿Qué pasa con el frontend legacy que no puedo migrar?

**Opción 1:** Mantener v1 indefinidamente (no recomendado).
**Opción 2:** Crear adapter/proxy que convierte v1→v2 en el backend.
**Opción 3:** Priorizar migración del frontend crítico, deprecar resto.

---

## 12. Checklist para Lanzar Nueva Versión

Antes de lanzar v2:

- [ ] Documentación completa de v2 (OpenAPI spec)
- [ ] Guía de migración de v1 a v2
- [ ] Tests E2E para v2
- [ ] Regression tests para v1 (validar que no rompe)
- [ ] Performance testing de v2
- [ ] Logs incluyen campo `api_version`
- [ ] Métricas separadas por versión en Grafana
- [ ] Comunicación a equipos de desarrollo
- [ ] Fecha de deprecación de v1 definida
- [ ] Rollback plan documentado

---

## 13. Roadmap de Versiones

### Versión Actual: v1 (Active)

**Estado:** Producción desde 2025-01-01
**Features:**
- Búsqueda RAG con LLM
- Alertas generadas
- Búsquedas históricas
- Disposiciones ANMAT

### Próxima Versión: v2 (Planned - 2026 Q3)

**Breaking Changes:**
- Paginado estándar en todos los endpoints (ver [PAGINADO_ESTANDAR.md](PAGINADO_ESTANDAR.md))
- Cambio en estructura de response `/query`
- Renombrado de parámetros (`retrieval_limit` → `pageSize`)

**New Features:**
- Cursor-based pagination (opcional, para streams)
- Webhooks para alertas
- GraphQL endpoint (experimental)

**Timeline:**
- 2026-06-01: v2 lanzada (Beta)
- 2026-07-01: v2 estable (Active)
- 2026-12-01: v1 deprecated
- 2027-06-01: v1 EOL (Retired)

### Versión Futura: v3 (Considerando - 2027+)

**Posibles cambios:**
- Migración a GraphQL como default
- Autenticación OAuth2 (reemplazar Keycloak custom)
- Rate limiting más granular

---

## 14. Referencias

### 14.1. Estándares de Industria

- **Stripe API Versioning:** https://stripe.com/docs/api/versioning
- **GitHub API Versioning:** https://docs.github.com/en/rest/overview/api-versions
- **Twilio API Versioning:** https://www.twilio.com/docs/usage/api/versioning

### 14.2. RFCs y Specs

- **RFC 7231 (HTTP/1.1):** Status codes
- **RFC 5988 (Web Linking):** Link headers
- **RFC 8594 (Sunset Header):** Deprecation notices

---

## 15. Apéndices

### 15.1. Template de Commit para Cambios de Versión

```
feat(api-v2): Implementar paginado estándar en /query

Breaking changes:
- Response ahora usa estructura {data, pagination, metadata}
- Parámetro retrieval_limit renombrado a pageSize

Migration guide: docs/MIGRATION_V1_TO_V2.md

BREAKING CHANGE: Response structure changed for /query endpoint
```

**Nota sobre Co-Authored-By:** Si trabajas con un asistente de IA, puedes opcionalmente agregar:
```
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
Co-Authored-By: ChatGPT <noreply@openai.com>
Co-Authored-By: OpenCode <noreply@opencode.dev>
```

### 15.2. Template de Anuncio de Deprecación

```
Subject: API v1 Deprecation Notice - Action Required

Hi Team,

We are announcing the deprecation of API v1, effective [DATE].

Timeline:
- Today: v1 marked as deprecated
- [DATE + 6 months]: v1 will be retired (EOL)

Action Required:
1. Migrate to v2 by [EOL DATE]
2. Review migration guide: [URL]
3. Test your integration in QA environment

Support:
- Questions: #api-support channel
- Migration help: api-team@alert.com

Thank you,
Alert API Team
```

---

## 16. Documentos Relacionados

| Documento | Descripción |
|-----------|-------------|
| [PAGINADO_ESTANDAR.md](PAGINADO_ESTANDAR.md) | Especificación de paginado para API v2 |
| [ARQUITECTURA.md](ARQUITECTURA.md) | Arquitectura general del sistema |
| [proyecto.md](proyecto.md) | Estructura del proyecto |

---

## 17. Notas sobre Asistentes de IA

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

**Última actualización:** 2026-05-19
**Próxima revisión:** 2026-12-01
**Responsable:** Equipo de Arquitectura Alert
**Estado:** ✅ Aprobado para implementación
**Compatibilidad:** Multi-agente (Claude Code, ChatGPT Codex, OpenCode)

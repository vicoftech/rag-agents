# RAG Agent con Strands y Amazon Bedrock AgentCore

Agente inteligente que utiliza Strands SDK para realizar búsquedas semánticas en bases de conocimiento usando RAG (Retrieval Augmented Generation).

## 📁 Estructura

```
apps/agent/
├── agent.py              # Agente principal con Strands
├── agentcore_handler.py  # Handler para Bedrock AgentCore
├── mcp_server.py         # Servidor MCP para herramientas
├── config.py             # Configuración centralizada
├── tools/
│   ├── __init__.py
│   ├── embeddings.py     # Generación de embeddings
│   ├── lambda_client.py  # Cliente para invocar Lambdas RAG
│   ├── rag_search.py     # Tool de búsqueda en KB (knowledge_base_search)
│   └── web_search.py     # Tool de búsqueda en internet
├── tests/
│   ├── conftest.py       # Fixtures y mocks compartidos
│   ├── unit/             # Tests unitarios
│   │   ├── test_lambda_client.py
│   │   ├── test_knowledge_base_search.py
│   │   └── test_web_search.py
│   ├── integration/      # Tests de integración
│   │   ├── test_agent_flow.py
│   │   └── test_agent_edge_cases.py
│   └── manual/           # Tests con servicios reales
│       └── test_live.py
├── Dockerfile            # Imagen para despliegue
├── deploy.sh             # Script de despliegue
├── pytest.ini            # Configuración de pytest
├── mcp_client_test.py    # Cliente de prueba MCP
└── requirements.txt      # Dependencias
```

## 🚀 Instalación

```bash
cd apps/agent

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o: venv\Scripts\activate  # Windows

# Instalar dependencias
pip install -r requirements.txt
```

## ⚙️ Configuración

Configura las variables de entorno (o usa un archivo `.env`):

```bash
# AWS
export AWS_REGION=us-east-1
export AWS_ACCESS_KEY_ID_DEV=tu-access-key
export AWS_SECRET_ACCESS_KEY_DEV=tu-secret-key

# Lambdas RAG
export LAMBDA_EMBEDDINGS=rag_lmbd_embeddings
export LAMBDA_QUERY=rag_lmbd_query

# Modelos
export AGENT_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
export EMBEDDINGS_MODEL=cohere.embed-v4:0
```

## 🧪 Tests

### Estructura de Tests

| Carpeta | Descripción |
|---------|-------------|
| `tests/unit/` | Tests unitarios con mocks (sin dependencias externas) |
| `tests/integration/` | Tests de integración del flujo completo |
| `tests/manual/` | Tests con servicios reales (Lambda, Bedrock) |

### Ejecutar todos los tests

```bash
# Todos los tests
pytest

# Con verbose
pytest -v

# Con cobertura
pytest --cov=. --cov-report=html
```

### Ejecutar por carpeta

```bash
# Solo tests unitarios
pytest tests/unit/

# Solo tests de integración
pytest tests/integration/
```

### Ejecutar un archivo específico

```bash
pytest tests/unit/test_knowledge_base_search.py
pytest tests/unit/test_lambda_client.py
pytest tests/unit/test_web_search.py
pytest tests/integration/test_agent_flow.py
pytest tests/integration/test_agent_edge_cases.py
```

### Ejecutar una clase de test

```bash
# Formato: archivo::Clase
pytest tests/unit/test_knowledge_base_search.py::TestKnowledgeBaseSearch
pytest tests/unit/test_knowledge_base_search.py::TestKnowledgeBaseSearchEdgeCases
pytest tests/unit/test_lambda_client.py::TestInvokeQueryLambda
pytest tests/unit/test_lambda_client.py::TestInvokeEmbeddingsLambda
pytest tests/unit/test_web_search.py::TestWebSearch
pytest tests/unit/test_web_search.py::TestWebSearchEdgeCases
```

### Ejecutar un test individual

```bash
# Formato: archivo::Clase::test_method
pytest tests/unit/test_knowledge_base_search.py::TestKnowledgeBaseSearch::test_successful_search_returns_response
pytest tests/unit/test_lambda_client.py::TestInvokeQueryLambda::test_lambda_error_raises_runtime_error
pytest tests/unit/test_web_search.py::TestWebSearch::test_empty_results_returns_not_found_message
```

### Filtrar tests por nombre (pattern matching)

```bash
# Tests que contengan "error" en el nombre
pytest -k "error"

# Tests que contengan "empty"
pytest -k "empty"

# Tests de un archivo que contengan "document"
pytest tests/unit/test_knowledge_base_search.py -k "document"

# Combinar filtros (AND)
pytest -k "error and lambda"

# Excluir tests
pytest -k "not slow"

# OR
pytest -k "error or empty"
```

### Opciones útiles de pytest

```bash
# Verbose (más detalle)
pytest -v tests/unit/

# Mostrar prints/stdout
pytest -s tests/unit/

# Parar en el primer fallo
pytest -x tests/unit/

# Re-ejecutar solo los que fallaron
pytest --lf

# Ver los 10 tests más lentos
pytest --durations=10

# Ejecutar en paralelo (requiere pytest-xdist)
pytest -n auto
```

### Tests manuales con servicios reales

```bash
# Probar solo Knowledge Base (Lambda real)
python -m tests.manual.test_live --mode kb

# Probar solo Web Search (Bedrock real)
python -m tests.manual.test_live --mode web

# Probar el agente completo
python -m tests.manual.test_live --mode agent

# Modo interactivo
python -m tests.manual.test_live --mode interactive
```

### Resumen de tests disponibles

#### Tests Unitarios (`tests/unit/`)

| Archivo | Clase | Tests |
|---------|-------|-------|
| `test_lambda_client.py` | `TestInvokeQueryLambda` | Respuestas exitosas, errores, parsing JSON, body vacío |
| `test_lambda_client.py` | `TestInvokeEmbeddingsLambda` | Embeddings, errores, formatos |
| `test_knowledge_base_search.py` | `TestKnowledgeBaseSearch` | Búsquedas, respuestas vacías, errores, document_id |
| `test_knowledge_base_search.py` | `TestKnowledgeBaseSearchEdgeCases` | Queries largos, caracteres especiales, unicode |
| `test_web_search.py` | `TestWebSearch` | Resultados, sin resultados, max_results, errores |
| `test_web_search.py` | `TestWebSearchEdgeCases` | Queries largos, unicode, separadores |

#### Tests de Integración (`tests/integration/`)

| Archivo | Clase | Tests |
|---------|-------|-------|
| `test_agent_flow.py` | `TestAgentFullFlow` | Creación del agente, tools, contexto |
| `test_agent_flow.py` | `TestAgentWithKnowledgeBase` | Integración con KB |
| `test_agent_flow.py` | `TestAgentWithWebSearch` | Integración con web search |
| `test_agent_flow.py` | `TestAgentToolsCombination` | Combinación de tools |
| `test_agent_edge_cases.py` | `TestAgentEdgeCasesNoInformation` | Sin información disponible |
| `test_agent_edge_cases.py` | `TestAgentEdgeCasesErrors` | Timeouts, throttling, errores |
| `test_agent_edge_cases.py` | `TestAgentEdgeCasesInputValidation` | Queries vacíos, largos, inyección |
| `test_agent_edge_cases.py` | `TestAgentEdgeCasesLargeResponses` | Respuestas grandes |
| `test_agent_edge_cases.py` | `TestAgentEdgeCasesConcurrency` | Llamadas secuenciales/alternadas |

## 🚢 Despliegue en Bedrock AgentCore

### Opción 1: Script automático

```bash
./deploy.sh
```

### Opción 2: Paso a paso

```bash
# 1. Configurar el agente
agentcore configure -e agentcore_handler.py --protocol MCP

# 2. Construir imagen
agentcore build

# 3. Desplegar
agentcore launch
```

### Probar agente desplegado

```bash
# Configurar credenciales del agente desplegado
export AGENT_ARN='arn:aws:bedrock-agentcore:us-east-1:...'
export BEARER_TOKEN='tu-token'

# Probar
python mcp_client_test.py --mode agentcore
```

## 🔧 Herramientas del Agente

### `knowledge_base_search`

Busca información en la base de conocimiento empresarial usando las Lambdas RAG.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `query` | string | ✅ | Consulta del usuario |
| `tenant_id` | string | ✅ | ID del tenant/organización |
| `agent_id` | string | ✅ | ID del agente |
| `document_id` | string | ❌ | ID de documento específico |

### `web_search`

Busca información actualizada en internet.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `query` | string | ✅ | Términos de búsqueda |
| `max_results` | int | ❌ | Número de resultados (default: 5) |

### Ejemplo de uso en código

```python
from tools import knowledge_base_search, web_search

# Búsqueda en KB
kb_result = knowledge_base_search(
    query="¿Cuáles son los lineamientos de arquitectura?",
    tenant_id="asap",
    agent_id="d8c38f93-f4cd-4a85-9c31-297d14ce7009"
)

# Búsqueda web
web_result = web_search(
    query="best practices microservicios 2024",
    max_results=5
)
```

## 📝 Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                    Amazon Bedrock AgentCore                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                   Strands Agent                        │  │
│  │  ┌─────────────────┐    ┌─────────────────────────┐   │  │
│  │  │  Claude 3.5     │◄──►│  Tools:                 │   │  │
│  │  │  Sonnet Model   │    │  - knowledge_base_search│   │  │
│  │  └─────────────────┘    │  - web_search           │   │  │
│  │                         └───────────┬─────────────┘   │  │
│  └─────────────────────────────────────┼─────────────────┘  │
└────────────────────────────────────────┼────────────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
                    ▼                    ▼                    ▼
    ┌───────────────────────┐  ┌─────────────────┐  ┌─────────────────┐
    │  Lambda               │  │  Lambda         │  │  Bedrock        │
    │  rag_lmbd_query       │  │  rag_lmbd_      │  │  Web Search     │
    │  (Búsqueda + LLM)     │  │  embeddings     │  │                 │
    └───────────┬───────────┘  └─────────────────┘  └─────────────────┘
                │
                ▼
    ┌─────────────────────────────────────┐
    │  PostgreSQL + pgvector               │
    │  ┌───────────────────────────────┐  │
    │  │ tenant_X.documents            │  │
    │  │ - chunk_text                  │  │
    │  │ - embedding (vector 1536)     │  │
    │  │ - agent_id, document_id       │  │
    │  └───────────────────────────────┘  │
    └─────────────────────────────────────┘
```

## 🔗 Integración con Lambdas RAG

Este agente invoca las siguientes Lambdas:

- **`rag_lmbd_query`**: Realiza búsqueda semántica y genera respuesta con LLM
- **`rag_lmbd_embeddings`**: Genera embeddings para textos

La Lambda `rag_lmbd_query` ya procesa la información y devuelve una respuesta sintetizada por el LLM, no chunks crudos.

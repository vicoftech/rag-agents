"""
API Gateway: enqueue async RAG query (SQS) + estado / resultado en DynamoDB.
"""
from __future__ import annotations

import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "OPTIONS,POST,GET",
}

def _env_table_name() -> str:
    """Leer tabla en cada uso: en invocaciones cálidas tras cambiar env en consola/terraform."""
    return (os.environ.get("RESULT_TABLE_NAME") or "").strip()


def _env_queue_url() -> str:
    return (os.environ.get("QUEUE_URL") or "").strip()


def _effective_region() -> str:
    return (
        (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "").strip()
        or "us-east-1"
    )
SEARCH_MODE_LEXICAL = "lexical"
SEARCH_MODE_HYBRID = "hybrid"
SEARCH_MODE_ALLOWED = {SEARCH_MODE_LEXICAL, SEARCH_MODE_HYBRID}
DEFAULT_SEARCH_MODE = SEARCH_MODE_LEXICAL
API_V2_MAX_PAGE_SIZE = 50
API_V2_DEFAULT_PAGE_SIZE = 10

GSI_TENANT_CREATED = "gsi_tenant_id_created_at"
# Límite de ítems leídos del índice por página; el filtro aplica después.
_CACHE_QUERY_PAGE = 50
_CACHE_QUERY_MAX_PAGES = 20

_ddb_resource = None
_ddb_tbl = None
_ddb_table_bound_name: str | None = None
_sqs_client = None


def _ddb_table():
    global _ddb_resource, _ddb_tbl, _ddb_table_bound_name
    tbl_name = _env_table_name()
    if not tbl_name:
        raise RuntimeError("RESULT_TABLE_NAME no definido o vacío")
    region = _effective_region()
    # Recrear cliente si cambió nombre de tabla o región (post-deploy mismo contenedor).
    if (
        _ddb_tbl is None
        or tbl_name != _ddb_table_bound_name
        or _ddb_tbl.meta.client.meta.region_name != region
    ):
        _ddb_resource = boto3.resource("dynamodb", region_name=region)
        _ddb_tbl = _ddb_resource.Table(tbl_name)
        _ddb_table_bound_name = tbl_name
    return _ddb_tbl


def _sqs_client_fn():
    global _sqs_client
    if _sqs_client is None or _sqs_client.meta.region_name != _effective_region():
        _sqs_client = boto3.client("sqs", region_name=_effective_region())
    return _sqs_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ddb_json_value(obj: Any) -> Any:
    """Los ítems de DynamoDB pueden traer Decimal; JSON no los serializa."""
    if isinstance(obj, list):
        return [_ddb_json_value(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _ddb_json_value(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj


def _resp(
    status: int,
    payload: dict[str, Any],
    *,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    h = {"Content-Type": "application/json", **CORS_HEADERS}
    if extra_headers:
        h.update(extra_headers)
    return {"statusCode": status, "headers": h, "body": json.dumps(payload)}


def _method(event: dict[str, Any]) -> str:
    try:
        m = event.get("requestContext", {}).get("http", {}).get("method")
    except Exception:
        m = None
    return str(m or event.get("httpMethod") or "").upper()


def _route_key(event: dict[str, Any]) -> str:
    return str(event.get("routeKey") or "").strip()


def _normalize_search_mode(raw_mode: Any) -> str:
    mode = str(raw_mode or DEFAULT_SEARCH_MODE).strip().lower()
    if not mode:
        mode = DEFAULT_SEARCH_MODE
    if mode not in SEARCH_MODE_ALLOWED:
        allowed = ", ".join(sorted(SEARCH_MODE_ALLOWED))
        raise ValueError(f"searchMode inválido: {mode!r}. Valores permitidos: {allowed}")
    return mode


def _parse_page_params(body: dict[str, Any]) -> tuple[int, int]:
    page_raw = body.get("page")
    page_size_raw = body.get("pageSize")
    try:
        page = int(page_raw) if page_raw is not None else 1
    except (TypeError, ValueError) as e:
        raise ValueError("page debe ser un entero") from e
    try:
        page_size = int(page_size_raw) if page_size_raw is not None else API_V2_DEFAULT_PAGE_SIZE
    except (TypeError, ValueError) as e:
        raise ValueError("pageSize debe ser un entero") from e
    if page < 1:
        raise ValueError("page debe ser >= 1")
    if page_size < 1 or page_size > API_V2_MAX_PAGE_SIZE:
        raise ValueError(f"pageSize debe estar entre 1 y {API_V2_MAX_PAGE_SIZE}")
    return page, page_size


def _unversioned_query_api_version() -> str:
    """
    Versión usada por /query sin prefijo.

    Default de producto: v2. Se mantiene configurable para rollback puntual con
    UNVERSIONED_QUERY_API_VERSION=v1 sin requerir rutas nuevas.
    """
    version = str(os.getenv("UNVERSIONED_QUERY_API_VERSION", "v2")).strip().lower()
    if re.fullmatch(r"v\d+", version):
        return version
    return "v2"


def _extract_version_from_path(event: dict[str, Any]) -> str:
    explicit_version = str(event.get("api_version") or "").strip().lower()
    if re.fullmatch(r"v\d+", explicit_version):
        return explicit_version

    path = (
        event.get("requestContext", {}).get("http", {}).get("path")
        or event.get("rawPath")
        or event.get("path")
        or ""
    )
    m = re.search(r"/(v\d+)/query", path.rstrip("/"))
    if m:
        return m.group(1)
    if path.rstrip("/").endswith("/query"):
        return _unversioned_query_api_version()
    return "v1"


def _is_post_query_enqueue(event: dict[str, Any], meth: str) -> bool:
    """POST encolar async /query — compatible con APIs que omiten routeKey o usan prefijo stage."""
    if meth != "POST":
        return False
    rk = _route_key(event)
    if rk in ("POST /query", "POST /v1/query", "POST /v2/query"):
        return True
    # HTTP API a veces deja routeKey vacío o con variante; usar path terminado en /query
    raw = event.get("rawPath") or event.get("path") or ""
    path = raw.rstrip("/")
    return bool(path) and path.endswith("/query")


def _path_id(event: dict[str, Any]) -> str | None:
    pp = event.get("pathParameters") or {}
    if isinstance(pp, dict) and pp.get("id"):
        return str(pp["id"]).strip()
    raw = event.get("rawPath") or event.get("path") or ""
    m = re.search(r"/query/status/([^/]+)$", raw.rstrip("/"))
    if m:
        return m.group(1)
    m = re.search(r"/query/result/([^/]+)$", raw.rstrip("/"))
    if m:
        return m.group(1)
    return None


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    meth = _method(event)
    rk = _route_key(event)

    if meth == "OPTIONS":
        return {"statusCode": 200, "headers": {**CORS_HEADERS}, "body": ""}

    if _is_post_query_enqueue(event, meth):
        return _post_query(event)

    if meth == "GET" and ("GET /query/status/{id}" in rk or "/query/status/" in (event.get("rawPath") or "")):
        jid = _path_id(event)
        if not jid:
            return _resp(400, {"error": "Falta id en la ruta"})
        return _get_status(jid)

    if meth == "GET" and ("GET /query/result/{id}" in rk or "/query/result/" in (event.get("rawPath") or "")):
        jid = _path_id(event)
        if not jid:
            return _resp(400, {"error": "Falta id en la ruta"})
        return _get_result(jid, event)

    return _resp(404, {"error": "Ruta no soportada"})


def _window_match_filter(start_at_val: str, end_at_val: str) -> Attr:
    """Coincide ventana (start_at, fin). En Dynamo el fin se guarda en atributo ``start_end`` (GSI)."""
    sa = _attr_equal_empty_or_absent("start_at", start_at_val)
    se = _attr_equal_empty_or_absent("start_end", end_at_val)
    return sa & se


def _attr_equal_empty_or_absent(name: str, value: str) -> Attr:
    if value:
        return Attr(name).eq(value)
    return Attr(name).not_exists() | Attr(name).eq("")


def _find_cached_job_id(
    tenant_id: str,
    agent_id: str,
    query_text: str,
    start_at_val: str,
    end_at_val: str,
    retrieval_limit: int | None = 10,
    sort_by: str | None = None,
    document_name: str | None = None,
    api_version: str | None = "v1",
    search_mode: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    date_filter_field: str | None = None,
) -> str | None:
    """
    Busca un job ya completado con la misma clave lógica (sin recalcular en worker).
    Misma forma de uso que antes: POST devuelve id; el cliente usa status/result igual.

    Clave de cache incluye parámetros críticos:
    - retrieval_limit: afecta cantidad de resultados (default: 10)
    - sort_by: afecta orden de resultados
    - document_name: filtro por documento específico
    - api_version: evita formato incorrecto entre v1 y v2
    """
    tbl = _ddb_table()
    kcf = (
        Attr("agent_id").eq(agent_id)
        & Attr("query").eq(query_text)
        & Attr("status").is_in(["Ready", "Readed"])
        & Attr("result").exists()
        & _window_match_filter(start_at_val, end_at_val)
    )

    # Agregar parámetros críticos a la clave de cache
    if retrieval_limit == 10:
        # Default 10: matchear con 10 explícito o jobs antiguos sin retrieval_limit (compatibilidad)
        kcf = kcf & (
            Attr("retrieval_limit").eq(10)
            | Attr("retrieval_limit").not_exists()
            | Attr("retrieval_limit").eq(None)
        )
    elif retrieval_limit is not None:
        # Valor no-default: match exacto
        kcf = kcf & Attr("retrieval_limit").eq(retrieval_limit)
    else:
        # Fallback (no debería ocurrir con el default): matchear sin retrieval_limit
        kcf = kcf & (Attr("retrieval_limit").not_exists() | Attr("retrieval_limit").eq(None))

    if sort_by:
        kcf = kcf & Attr("sort_by").eq(sort_by)
    else:
        kcf = kcf & (Attr("sort_by").not_exists() | Attr("sort_by").eq("") | Attr("sort_by").eq(None))

    if document_name:
        kcf = kcf & Attr("document_name").eq(document_name)
    else:
        kcf = kcf & (Attr("document_name").not_exists() | Attr("document_name").eq("") | Attr("document_name").eq(None))

    if api_version:
        kcf = kcf & Attr("api_version").eq(api_version)
    else:
        kcf = kcf & (Attr("api_version").not_exists() | Attr("api_version").eq("") | Attr("api_version").eq(None))

    if search_mode == SEARCH_MODE_LEXICAL:
        kcf = kcf & Attr("search_mode").eq(SEARCH_MODE_LEXICAL)
        if page is not None:
            kcf = kcf & Attr("page").eq(int(page))
        if page_size is not None:
            kcf = kcf & Attr("page_size").eq(int(page_size))
    if search_mode == SEARCH_MODE_HYBRID:
        kcf = kcf & (
            Attr("search_mode").eq(SEARCH_MODE_HYBRID)
            | Attr("search_mode").not_exists()
            | Attr("search_mode").eq("")
            | Attr("search_mode").eq(None)
        )

    # TASK-411
    if date_filter_field:
        kcf = kcf & Attr("date_filter_field").eq(date_filter_field)
    else:
        kcf = kcf & (
            Attr("date_filter_field").eq("created_at")
            | Attr("date_filter_field").not_exists()
        )

    eks: dict[str, Any] | None = None
    for _ in range(_CACHE_QUERY_MAX_PAGES):
        kw: dict[str, Any] = {
            "IndexName": GSI_TENANT_CREATED,
            "KeyConditionExpression": Key("tenant_id").eq(tenant_id),
            "FilterExpression": kcf,
            "ScanIndexForward": False,
            "Limit": _CACHE_QUERY_PAGE,
        }
        if eks:
            kw["ExclusiveStartKey"] = eks
        try:
            page = tbl.query(**kw)
        except ClientError as e:
            print(f"[dispatcher] Query caché falló: {e}")
            return None
        items = page.get("Items") or []
        for row in items:
            sid = row.get("id")
            if not sid:
                continue
            cid = str(sid).strip()
            if not cid:
                continue
            # El Query usa GSI (solo lectura eventualmente consistente). Tras borrados o
            # ventanas cortas puede devolver un id obsoleto: validamos en la PK de la tabla.
            try:
                hit = tbl.get_item(Key={"id": cid}, ConsistentRead=True)
            except ClientError as e:
                print(f"[dispatcher] get_item cache verify falló id={cid!r}: {e}")
                continue
            if "Item" in hit:
                return cid
        eks = page.get("LastEvaluatedKey")
        if not eks:
            break
    return None


def _strip_param(body: dict[str, Any], *keys: str) -> str:
    for k in keys:
        if k not in body:
            continue
        v = body.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _required_date_window(body: dict[str, Any]) -> tuple[str, str] | None:
    """
    Ventana de fechas obligatoria para async POST /query.

    Contrato recomendado: ``start_at`` y ``end_at`` (YYYY-MM-DD o ISO).
    Compatibilidad: ``created_at_start`` / ``created_at_end``.
    """
    start_s = _strip_param(body, "start_at", "created_at_start")
    end_s = _strip_param(body, "end_at", "created_at_end")
    if not start_s or not end_s:
        return None
    return start_s, end_s


def _post_query(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    if isinstance(raw, str) and event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:
            return _resp(400, {"error": "Body base64 inválido"})
    try:
        body = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return _resp(400, {"error": "JSON inválido"})

    if not _env_table_name() or not _env_queue_url():
        return _resp(
            500,
            {"error": "Lambda sin RESULT_TABLE_NAME o QUEUE_URL configurados"},
        )

    tenant_id = body.get("tenant_id")
    agent_id = body.get("agent_id")
    query = body.get("query")
    if not tenant_id or not agent_id or not query:
        return _resp(400, {"error": "Faltan tenant_id, agent_id o query"})

    tenant_s = str(tenant_id)
    agent_s = str(agent_id)
    query_s = str(query)

    window = _required_date_window(body)
    if window is None:
        return _resp(
            400,
            {
                "error": "Faltan start_at y end_at (fecha inicio y fin de la ventana). "
                "Opcional Legacy: created_at_start y created_at_end.",
            },
        )
    start_s, end_s = window

    # Detectar versión de API desde path
    api_version = _extract_version_from_path(event)
    try:
        search_mode = _normalize_search_mode(body.get("searchMode") or body.get("search_mode"))
    except ValueError as e:
        return _resp(400, {"error": str(e)})

    # TASK-399: Extraer parámetros según versión
    if api_version == "v2":
        # v2 hybrid: fetch completo (100 contexts), paginación in-memory.
        # v2 lexical: paginación real en SQL usando page/pageSize.
        retrieval_limit = 100
        try:
            page, page_size = _parse_page_params(body)
        except ValueError as e:
            return _resp(400, {"error": str(e)})
    else:
        # v1: retrieval_limit variable (legacy)
        retrieval_limit = body.get("retrieval_limit")
        if retrieval_limit is not None:
            try:
                retrieval_limit = int(retrieval_limit)
            except (TypeError, ValueError):
                retrieval_limit = 10
        else:
            retrieval_limit = 10
        if search_mode == SEARCH_MODE_LEXICAL:
            try:
                page, page_size = _parse_page_params(body)
            except ValueError as e:
                return _resp(400, {"error": str(e)})
        else:
            page = None
            page_size = None

    # TASK-411: Extraer date_filter_field (default: created_at)
    date_filter_field = str(body.get("date_filter_field") or "created_at").strip()
    if date_filter_field not in ("created_at", "publication_date"):
        date_filter_field = "created_at"

    sort_by = (
        str(body.get("sort_by") or body.get("sort") or "").strip() or None
        if search_mode == SEARCH_MODE_HYBRID
        else None
    )
    document_name = str(body.get("document_name") or "").strip() or None

    cached_id = _find_cached_job_id(
        tenant_s,
        agent_s,
        query_s,
        start_s,
        end_s,
        retrieval_limit=retrieval_limit,
        sort_by=sort_by,
        document_name=document_name,
        api_version=api_version,
        search_mode=search_mode,
        page=page,
        page_size=page_size,
        date_filter_field=date_filter_field,
    )
    if cached_id:
        return _resp(202, {"id": cached_id})

    job_id = str(uuid.uuid4())
    created = _now_iso()

    item: dict[str, Any] = {
        "id": job_id,
        "status": "Pending",
        "created_at": created,
        "tenant_id": tenant_s,
        "agent_id": agent_s,
        "query": query_s,
        # GSI gsi_start_*: el atributo de fin en tabla sigue llamándose ``start_end`` (Terraform).
        # Valores = mismos strings que ``start_at`` / ``end_at`` del JSON.
        "start_at": start_s,
        "start_end": end_s,
        # Version de API para cache key y formato de respuesta
        "api_version": api_version,
    }

    # Guardar parámetros de búsqueda para cache key
    # retrieval_limit siempre se guarda (tiene default 10)
    item["retrieval_limit"] = retrieval_limit
    item["search_mode"] = search_mode
    item["searchMode"] = search_mode
    # TASK-411
    item["date_filter_field"] = date_filter_field

    if search_mode == SEARCH_MODE_LEXICAL and page is not None and page_size is not None:
        item["page"] = int(page)
        item["page_size"] = int(page_size)
    if sort_by:
        item["sort_by"] = sort_by
    if document_name:
        item["document_name"] = document_name

    try:
        tbl = _ddb_table()
        tbl.put_item(Item=item)
        ver = tbl.get_item(Key={"id": job_id}, ConsistentRead=True)
        if "Item" not in ver:
            try:
                ep = tbl.meta.client.meta.endpoint_url
            except Exception:
                ep = ""
            print(
                f"[dispatcher] PutItem no verificable (GetItem vacío): "
                f"table={_env_table_name()!r} region={_effective_region()!r} "
                f"id={job_id!r} endpoint={ep!r}"
            )
            return _resp(
                500,
                {
                    "error": "El job no quedó persistido en DynamoDB tras PutItem",
                    "detail": (
                        f"Ver región/cuenta/tabla. table={_env_table_name()} "
                        f"region={_effective_region()} id={job_id}"
                    ),
                },
            )
    except ClientError as e:
        return _resp(500, {"error": "No se pudo crear el job", "detail": str(e)})

    msg = dict(body)
    msg["job_id"] = job_id
    msg["date_filter_field"] = date_filter_field
    # El worker (rag_lmbd_query) filtra por created_at_start / created_at_end.
    msg["created_at_start"] = start_s
    msg["created_at_end"] = end_s
    msg["start_at"] = start_s
    msg["end_at"] = end_s
    # TASK-399: Propagar versión al worker SQS. Sin path HTTP, rag_lmbd_query
    # necesita este campo para construir la respuesta v2.
    msg["api_version"] = api_version
    msg["searchMode"] = search_mode
    msg["search_mode"] = search_mode
    # TASK-399: Para v2, pasar _page, _page_size y retrieval_limit=100 al worker
    # para paginación in-memory sobre el set completo en hybrid; en lexical esos
    # campos controlan LIMIT/OFFSET SQL.
    if api_version == "v2" or search_mode == SEARCH_MODE_LEXICAL:
        msg["retrieval_limit"] = retrieval_limit
        msg["_page"] = page
        msg["_page_size"] = page_size
    try:
        _sqs_client_fn().send_message(
            QueueUrl=_env_queue_url(),
            MessageBody=json.dumps(msg, default=str),
        )
    except ClientError as e:
        return _resp(500, {"error": "No se pudo encolar la consulta", "detail": str(e), "id": job_id})

    return _resp(202, {"id": job_id})


def _get_status(job_id: str) -> dict[str, Any]:
    try:
        r = _ddb_table().get_item(Key={"id": job_id}, ConsistentRead=True)
    except ClientError as e:
        return _resp(500, {"error": str(e)})
    item = r.get("Item")
    if not item:
        return _resp(404, {"error": "Job no encontrado"})

    status = item.get("status")
    response = {"id": job_id, "status": status}

    # Si hay error, incluir detalles del campo result
    if status == "Error":
        result = item.get("result")
        if result:
            result_dict = _ddb_json_value(result)
            if isinstance(result_dict, dict):
                # Agregar mensaje de error principal
                if "message" in result_dict:
                    response["message"] = result_dict["message"]
                # Agregar campos adicionales de error si existen
                if "error" in result_dict:
                    response["error"] = result_dict["error"]
                if "detail" in result_dict:
                    response["detail"] = result_dict["detail"]
                if "error_trace" in result_dict:
                    response["error_trace"] = result_dict["error_trace"]
            elif isinstance(result_dict, str):
                # Si result es un string directo
                response["message"] = result_dict

    return _resp(200, response)


def _paginate_v2_result(result: dict[str, Any], page: int, page_size: int) -> dict[str, Any]:
    """
    TASK-399: Pagina resultado v2 in-memory según page/pageSize solicitados.

    Args:
        result: Resultado v2 completo con data (array de 100 context_items)
        page: Número de página solicitada (1-based)
        page_size: Tamaño de página solicitado

    Returns:
        Resultado v2 paginado con data recortado y pagination actualizado
    """
    metadata = result.get("metadata") if isinstance(result, dict) else {}
    retrieval_config = metadata.get("retrieval_config", {}) if isinstance(metadata, dict) else {}
    search_mode = (
        (metadata.get("searchMode") if isinstance(metadata, dict) else None)
        or (retrieval_config.get("searchMode") if isinstance(retrieval_config, dict) else None)
        or (retrieval_config.get("search_mode") if isinstance(retrieval_config, dict) else None)
    )
    if str(search_mode or "").strip().lower() == SEARCH_MODE_LEXICAL:
        # Lexical ya viene paginado por SQL en el worker y trae totalItems/totalPages reales.
        # El dispatcher no tiene acceso a DB para recalcular otra página en GET.
        return result

    full_data = result.get("data", [])

    # Paginar data en memoria
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_data = full_data[start_idx:end_idx]

    # Calcular hasNext/hasPrevious
    total_items = len(full_data)
    has_next = end_idx < total_items
    has_previous = page > 1

    # Construir resultado paginado
    paginated = dict(result)
    paginated["data"] = page_data
    paginated["pagination"] = {
        "page": page,
        "pageSize": page_size,
        "hasNext": has_next,
        "hasPrevious": has_previous,
    }

    return paginated


def _get_result(job_id: str, event: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    TASK-399: Soporta paginación GET con ?page=N&pageSize=M para v2.
    """
    try:
        r = _ddb_table().get_item(Key={"id": job_id}, ConsistentRead=True)
    except ClientError as e:
        return _resp(500, {"error": str(e)})
    item = r.get("Item")
    if not item:
        return _resp(404, {"error": "Job no encontrado"})

    status = item.get("status")
    api_version = item.get("api_version", "v1")

    # TASK-399: Extraer query params para paginación v2
    page_from_qs = 1
    page_size_from_qs = 10
    if event and api_version == "v2":
        qp = event.get("queryStringParameters") or {}
        if isinstance(qp, dict):
            page_raw = qp.get("page")
            page_size_raw = qp.get("pageSize")
            try:
                if page_raw is not None:
                    page_from_qs = int(page_raw)
            except (TypeError, ValueError):
                pass
            try:
                if page_size_raw is not None:
                    page_size_from_qs = int(page_size_raw)
            except (TypeError, ValueError):
                pass

    if status == "Readed":
        result = _ddb_json_value(item.get("result"))
        # TASK-399: Si es v2 y vienen query params, re-paginar
        if api_version == "v2" and event:
            result = _paginate_v2_result(result, page_from_qs, page_size_from_qs)
        return _resp(200, {"id": job_id, "result": result})

    if status != "Ready":
        return _resp(
            409,
            {
                "error": "El resultado aún no está listo o falló",
                "status": status,
            },
        )

    result = item.get("result")
    now = _now_iso()
    try:
        _ddb_table().update_item(
            Key={"id": job_id},
            UpdateExpression="SET #st = :rd, updated_at = :u",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":rd": "Readed",
                ":u": now,
                ":ready": "Ready",
            },
            ConditionExpression="#st = :ready",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            r2 = _ddb_table().get_item(Key={"id": job_id}, ConsistentRead=True)
            item2 = r2.get("Item") or {}
            if item2.get("status") == "Readed":
                result2 = _ddb_json_value(item2.get("result"))
                # TASK-399: Re-paginar si es v2
                if api_version == "v2" and event:
                    result2 = _paginate_v2_result(result2, page_from_qs, page_size_from_qs)
                return _resp(200, {"id": job_id, "result": result2})
        return _resp(500, {"error": str(e)})

    result_final = _ddb_json_value(result)
    # TASK-399: Paginar v2 antes de devolver
    if api_version == "v2" and event:
        result_final = _paginate_v2_result(result_final, page_from_qs, page_size_from_qs)

    return _resp(200, {"id": job_id, "result": result_final})

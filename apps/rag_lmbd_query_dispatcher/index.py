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


def _is_post_query_enqueue(event: dict[str, Any], meth: str) -> bool:
    """POST encolar async /query — compatible con APIs que omiten routeKey o usan prefijo stage."""
    if meth != "POST":
        return False
    rk = _route_key(event)
    if rk == "POST /query":
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
        return _get_result(jid)

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
) -> str | None:
    """
    Busca un job ya completado con la misma clave lógica (sin recalcular en worker).
    Misma forma de uso que antes: POST devuelve id; el cliente usa status/result igual.

    Clave de cache incluye parámetros críticos:
    - retrieval_limit: afecta cantidad de resultados (default: 10)
    - sort_by: afecta orden de resultados
    - document_name: filtro por documento específico
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

    # Extraer parámetros de búsqueda para clave de cache
    # Default retrieval_limit = 10 si no se especifica
    retrieval_limit = body.get("retrieval_limit")
    if retrieval_limit is not None:
        try:
            retrieval_limit = int(retrieval_limit)
        except (TypeError, ValueError):
            retrieval_limit = 10  # Default en caso de error de conversión
    else:
        retrieval_limit = 10  # Default cuando no se envía

    sort_by = str(body.get("sort_by") or "").strip() or None
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
    }

    # Guardar parámetros de búsqueda para cache key
    # retrieval_limit siempre se guarda (tiene default 10)
    item["retrieval_limit"] = retrieval_limit
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
    # El worker (rag_lmbd_query) filtra por created_at_start / created_at_end.
    msg["created_at_start"] = start_s
    msg["created_at_end"] = end_s
    msg["start_at"] = start_s
    msg["end_at"] = end_s
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
    return _resp(200, {"id": job_id, "status": item.get("status")})


def _get_result(job_id: str) -> dict[str, Any]:
    try:
        r = _ddb_table().get_item(Key={"id": job_id}, ConsistentRead=True)
    except ClientError as e:
        return _resp(500, {"error": str(e)})
    item = r.get("Item")
    if not item:
        return _resp(404, {"error": "Job no encontrado"})

    status = item.get("status")

    if status == "Readed":
        return _resp(
            200,
            {"id": job_id, "result": _ddb_json_value(item.get("result"))},
        )

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
                return _resp(
                    200,
                    {"id": job_id, "result": _ddb_json_value(item2.get("result"))},
                )
        return _resp(500, {"error": str(e)})

    return _resp(200, {"id": job_id, "result": _ddb_json_value(result)})

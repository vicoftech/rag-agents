"""
API Gateway: enqueue async RAG query (SQS) + estado / resultado en DynamoDB.
"""
from __future__ import annotations

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

RESULT_TABLE = os.environ["RESULT_TABLE_NAME"]
QUEUE_URL = os.environ["QUEUE_URL"]
GSI_TENANT_CREATED = "gsi_tenant_id_created_at"
# Límite de ítems leídos del índice por página; el filtro aplica después.
_CACHE_QUERY_PAGE = 50
_CACHE_QUERY_MAX_PAGES = 20

_ddb_tbl = None
_sqs_client = None


def _ddb_table():
    global _ddb_tbl
    if _ddb_tbl is None:
        _ddb_tbl = boto3.resource("dynamodb").Table(RESULT_TABLE)
    return _ddb_tbl


def _sqs_client_fn():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs")
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

    if meth == "POST" and rk == "POST /query":
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


def _window_match_filter(start_at: str, start_end: str) -> Attr:
    """Coincide con filas antiguas sin atributo y con vacío explícito."""
    sa = _attr_equal_empty_or_absent("start_at", start_at)
    se = _attr_equal_empty_or_absent("start_end", start_end)
    return sa & se


def _attr_equal_empty_or_absent(name: str, value: str) -> Attr:
    if value:
        return Attr(name).eq(value)
    return Attr(name).not_exists() | Attr(name).eq("")


def _find_cached_job_id(
    tenant_id: str,
    agent_id: str,
    query_text: str,
    start_at: str,
    start_end: str,
) -> str | None:
    """
    Busca un job ya completado con la misma clave lógica (sin recalcular en worker).
    Misma forma de uso que antes: POST devuelve id; el cliente usa status/result igual.
    """
    tbl = _ddb_table()
    kcf = (
        Attr("agent_id").eq(agent_id)
        & Attr("query").eq(query_text)
        & Attr("status").is_in(["Ready", "Readed"])
        & Attr("result").exists()
        & _window_match_filter(start_at, start_end)
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
        if items:
            sid = items[0].get("id")
            if sid:
                return str(sid)
        eks = page.get("LastEvaluatedKey")
        if not eks:
            break
    return None


def _post_query(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    try:
        body = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return _resp(400, {"error": "JSON inválido"})

    tenant_id = body.get("tenant_id")
    agent_id = body.get("agent_id")
    query = body.get("query")
    if not tenant_id or not agent_id or not query:
        return _resp(400, {"error": "Faltan tenant_id, agent_id o query"})

    tenant_s = str(tenant_id)
    agent_s = str(agent_id)
    query_s = str(query)

    start_at = str(body.get("created_at_start") or "").strip()
    start_end = str(body.get("created_at_end") or "").strip()

    cached_id = _find_cached_job_id(tenant_s, agent_s, query_s, start_at, start_end)
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
        "start_at": start_at,
        "start_end": start_end,
    }

    try:
        _ddb_table().put_item(Item=item)
    except ClientError as e:
        return _resp(500, {"error": "No se pudo crear el job", "detail": str(e)})

    msg = dict(body)
    msg["job_id"] = job_id
    try:
        _sqs_client_fn().send_message(
            QueueUrl=QUEUE_URL,
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

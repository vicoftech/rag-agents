#!/usr/bin/env python3
"""
Invoca la Lambda rag_lmbd_query (direct invocation: el evento es el JSON del body).

Ejemplos:
  python scripts/rag_query_lambda_invoker.py --payload query.json
  python scripts/rag_query_lambda_invoker.py --payload query.json -o salida.json
  python scripts/rag_query_lambda_invoker.py --function-name rag_lmbd_query-dev --profile mi_perfil

Variables de entorno (opcionales):
  RAG_QUERY_FUNCTION_NAME  (default: rag_lmbd_query-qa)
  AWS_PROFILE              (default: asap_main)
  AWS_REGION / AWS_DEFAULT_REGION  (default: us-east-1)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict


def _default_function_name() -> str:
    return os.environ.get("RAG_QUERY_FUNCTION_NAME", "rag_lmbd_query-qa")


def _default_profile() -> str | None:
    return os.environ.get("AWS_PROFILE")


def _default_region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def _load_payload(path: str) -> Dict[str, Any]:
    if path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("El payload debe ser un objeto JSON (dict).")
    return data


def _invoke_lambda(
    *,
    function_name: str,
    profile: str | None,
    region: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        import boto3
    except ImportError as e:
        raise SystemExit(
            "Falta boto3. Instalá dependencias (ej. pip install boto3) o usá el mismo venv del proyecto."
        ) from e

    session_kw: Dict[str, Any] = {"region_name": region}
    if profile:
        session_kw["profile_name"] = profile
    client = boto3.Session(**session_kw).client("lambda")

    resp = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )

    raw = resp["Payload"].read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    out: Dict[str, Any] = {
        "StatusCode": resp.get("StatusCode"),
        "FunctionError": resp.get("FunctionError"),
        "ExecutedVersion": resp.get("ExecutedVersion"),
    }

    try:
        out["Payload"] = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        out["PayloadRaw"] = raw

    return out


def _print_json(data: Any, *, pretty: bool) -> None:
    kwargs: Dict[str, Any] = {"ensure_ascii": False}
    if pretty:
        kwargs["indent"] = 2
    text = json.dumps(data, **kwargs) + "\n"
    sys.stdout.buffer.write(text.encode("utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description="Invoca rag_lmbd_query por nombre de función.")
    p.add_argument(
        "--function-name",
        "-f",
        default=_default_function_name(),
        help="Nombre de la Lambda (default: env RAG_QUERY_FUNCTION_NAME o rag_lmbd_query-qa).",
    )
    p.add_argument(
        "--profile",
        default=_default_profile(),
        help="Perfil AWS (~/.aws/credentials). Default: env AWS_PROFILE.",
    )
    p.add_argument(
        "--region",
        "-r",
        default=_default_region(),
        help="Región AWS (default: env AWS_REGION / AWS_DEFAULT_REGION o us-east-1).",
    )
    p.add_argument(
        "--payload",
        "-p",
        required=True,
        help="Ruta a un JSON con tenant_id, agent_id, query, etc. Use '-' para leer stdin.",
    )
    p.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="Si se indica, escribe ahí la salida (UTF-8) en lugar de stdout.",
    )
    p.add_argument(
        "--unwrap-body",
        action="store_true",
        help="Si la Lambda devuelve API Gateway shape {statusCode, body}, imprime solo json.loads(body).",
    )
    p.add_argument(
        "--compact",
        action="store_true",
        help="JSON en una línea (sin indent).",
    )
    p.add_argument(
        "--include-envelope",
        action="store_true",
        help="Con --unwrap-body, escribe {statusCode, headers?, body_parsed} en lugar de solo el body.",
    )
    args = p.parse_args()

    payload = _load_payload(args.payload)
    result = _invoke_lambda(
        function_name=args.function_name,
        profile=args.profile,
        region=args.region,
        payload=payload,
    )

    if args.unwrap_body:
        inner = result.get("Payload")
        if not isinstance(inner, dict):
            raise SystemExit("Payload de Lambda no es JSON objeto; no se puede --unwrap-body.")
        status = inner.get("statusCode")
        body_raw = inner.get("body")
        if body_raw is None:
            raise SystemExit("Respuesta sin campo 'body'.")
        if isinstance(body_raw, str):
            try:
                body_parsed = json.loads(body_raw)
            except json.JSONDecodeError:
                body_parsed = body_raw
        else:
            body_parsed = body_raw
        if args.include_envelope:
            out: Dict[str, Any] = {"statusCode": status, "body": body_parsed}
            if "headers" in inner:
                out["headers"] = inner.get("headers")
        else:
            out = body_parsed
    else:
        out = result

    pretty = not args.compact
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2 if pretty else None)
            if pretty:
                f.write("\n")
    else:
        _print_json(out, pretty=pretty)

    if result.get("FunctionError"):
        return 1
    if args.unwrap_body and isinstance(result.get("Payload"), dict):
        sc = result["Payload"].get("statusCode")
        if isinstance(sc, int) and sc >= 400:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

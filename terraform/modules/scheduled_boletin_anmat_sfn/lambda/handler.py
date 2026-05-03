"""
Disparo diario de Step Functions Boletín y ANMAT desde EventBridge Scheduler.

Boletín: una ejecución SFN por cada (fecha, sección) con fechas [ayer, hoy]
en la zona configurada (criterio ventana de 2 días civiles).

ANMAT: el state machine ``rag-anmat-to-s3writer`` recibe año, página 1,
``filter_yyyymm`` (YYYYMM en la zona ``SCHEDULE_TZ``) y ``skip_existing_s3``
para no re-encolar PDFs ya presentes bajo el prefijo del agente en S3.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any

import boto3
from botocore.exceptions import ClientError
from zoneinfo import ZoneInfo

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

_sfn = None


def _client():
    global _sfn
    if _sfn is None:
        _sfn = boto3.client("stepfunctions")
    return _sfn


def _two_day_window_dates(tz_name: str) -> tuple[str, str]:
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    return yesterday.isoformat(), today.isoformat()


def _run_boletin() -> dict[str, Any]:
    arn = os.environ["BOLETIN_SFN_ARN"]
    tenant = os.environ["BOLETIN_TENANT_ID"]
    agent = os.environ["BOLETIN_AGENT_ID"]
    raw_sections = os.environ.get("BOLETIN_SECTIONS", "primera,segunda,tercera,cuarta")
    sections = [s.strip() for s in raw_sections.split(",") if s.strip()]
    tz = os.environ.get("SCHEDULE_TZ", "America/Argentina/Buenos_Aires")
    d_y, d_t = _two_day_window_dates(tz)
    dates = [d_y, d_t]

    started: list[str] = []
    errors: list[str] = []
    sfn = _client()
    for d in dates:
        for sec in sections:
            payload = {"date": d, "section": sec, "tenant_id": tenant, "agent_id": agent}
            slug = d.replace("-", "")
            name = f"dly-{slug}-{sec}-{uuid.uuid4().hex[:10]}"
            name = name[:80]
            try:
                r = sfn.start_execution(
                    stateMachineArn=arn,
                    name=name,
                    input=json.dumps(payload),
                )
                started.append(r["executionArn"])
            except ClientError as e:
                errors.append(f"{d} {sec}: {e}")

    return {
        "corpus": "boletin",
        "dates": dates,
        "sections": sections,
        "started": len(started),
        "errors": errors,
    }


def _run_anmat() -> dict[str, Any]:
    arn = os.environ["ANMAT_SFN_ARN"]
    tenant = os.environ["ANMAT_TENANT_ID"]
    agent = os.environ["ANMAT_AGENT_ID"]
    tz = os.environ.get("SCHEDULE_TZ", "America/Argentina/Buenos_Aires")
    now = datetime.now(ZoneInfo(tz))
    today = now.date()
    year_str = os.environ.get("ANMAT_YEAR", "").strip() or str(today.year)
    yyyymm = f"{today.year}{today.month:02d}"

    payload: dict[str, Any] = {
        "year": year_str,
        "page_start": 1,
        "page_end": 1,
        "tenant_id": tenant,
        "agent_id": agent,
        "pagesSinceReset": 0,
        "total_pages": None,
        "filter_yyyymm": yyyymm,
        "skip_existing_s3": True,
    }
    name = f"dly-anmat-{year_str}-{yyyymm}-p1-{uuid.uuid4().hex[:10]}"[:80]
    sfn = _client()
    try:
        r = sfn.start_execution(
            stateMachineArn=arn,
            name=name,
            input=json.dumps(payload),
        )
        arn_out = r["executionArn"]
    except ClientError as e:
        return {
            "corpus": "anmat",
            "errors": [str(e)],
            "payload": payload,
        }

    return {
        "corpus": "anmat",
        "note": (
            "ANMAT diario: año actual (o ANMAT_YEAR), sólo página 1, "
            f"filter_yyyymm={yyyymm} y skip_existing_s3=true."
        ),
        "payload": payload,
        "executionArn": arn_out,
    }


def handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    corpus = (event or {}).get("corpus") or os.environ.get("DEFAULT_CORPUS", "")
    corpus = str(corpus).strip().lower()
    if corpus == "boletin":
        out = _run_boletin()
    elif corpus == "anmat":
        out = _run_anmat()
    else:
        raise ValueError(f"corpus inválido: {corpus!r} (usar boletin|anmat en el evento)")

    LOG.info("%s", json.dumps(out, default=str))
    errs = out.get("errors") or []
    if errs:
        raise RuntimeError("; ".join(errs))
    return out

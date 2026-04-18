"""
Parseo de keys S3 para RAG (tenant, agente, document_name, fecha de partición).

Sin dependencias pesadas (PDF, boto) para poder testear en aislamiento.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, time

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
DATE8_RE = re.compile(r"^\d{8}$")
SCHEMA_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _utc_naive_midnight_from_date8(date8: str) -> datetime:
    """
    Interpreta YYYYMMDD como inicio del día en UTC (timestamp naive),
    alineado con el filtro por rango en rag_lmbd_query.
    """
    if not DATE8_RE.match(date8):
        raise ValueError(f"fecha de partición inválida (se espera YYYYMMDD): {date8!r}")
    y = int(date8[0:4])
    mo = int(date8[4:6])
    d = int(date8[6:8])
    return datetime.combine(date(y, mo, d), time.min)


def assert_valid_schema_name(name: str) -> None:
    if not name or not SCHEMA_NAME_RE.match(name):
        raise ValueError(f"Nombre de esquema tenant inválido: {name!r}")


def _schema_for_s3_prefix(prefix: str) -> str:
    """Resuelve prefijo S3 → nombre de esquema PostgreSQL (env RAG_S3_PREFIX_SCHEMA_MAP JSON)."""
    raw = os.getenv("RAG_S3_PREFIX_SCHEMA_MAP", "").strip()
    if raw:
        try:
            m = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"RAG_S3_PREFIX_SCHEMA_MAP no es JSON válido: {e}") from e
        if not isinstance(m, dict):
            raise ValueError("RAG_S3_PREFIX_SCHEMA_MAP debe ser un objeto JSON")
        mapped = m.get(prefix)
        if mapped:
            assert_valid_schema_name(mapped)
            return mapped
    if prefix.startswith("tenant_"):
        assert_valid_schema_name(prefix)
        return prefix
    raise ValueError(
        f"Key S3: prefijo {prefix!r} sin mapeo. Defina RAG_S3_PREFIX_SCHEMA_MAP "
        '(JSON, ej. {"boletin_oficial":"tenant_boletin"}) o use esquema tenant_* en S3.'
    )


def parse_s3_rag_key(key: str) -> tuple:
    """
    Formato canónico (recomendado):

        {tenant_id_o_schema}/{agent_uuid}/documents/[<fecha>/[<carpeta>/]]<archivo>

    El primer segmento puede ser el slug de API (``anmat``, ``boletin``) o ya
    ``tenant_*``; en ambos casos el esquema Postgres se normaliza como en la
    Lambda ``rag_lmbd_query`` (p. ej. ``anmat`` → ``tenant_anmat``).

    Si el primer segmento bajo ``documents/`` es ``YYYYMMDD``, ese día (UTC
    00:00 naive) se usa como ``created_at`` al insertar chunks; si no hay
    carpeta de fecha, ``created_at`` queda en manos del DEFAULT (NOW()).

    Formato legado (cargas tipo boletín; requiere env):

        {prefijo}/{YYYYMMDD}/[<carpeta>/]<archivo>

    Retorno:
        (tenant_schema, agent_id, document_name relativo para deduplicar en BD,
        created_at_partition o None).
    """
    parts = [p for p in key.split("/") if p]

    if (
        len(parts) >= 4
        and parts[2] == "documents"
        and UUID_RE.match(parts[1])
    ):
        raw_tenant = parts[0].strip()
        if raw_tenant.startswith("tenant_"):
            tenant_schema = raw_tenant
        else:
            tenant_schema = f"tenant_{raw_tenant}"
        agent_id = parts[1]
        assert_valid_schema_name(tenant_schema)
        under_documents = parts[3:]
        if not under_documents:
            raise ValueError("Key S3 inválida: falta ruta bajo documents/ (al menos el archivo)")
        basename = under_documents[-1]
        if not basename or basename.endswith("/"):
            raise ValueError("Key S3 inválida: falta nombre de archivo (último segmento)")
        document_name = "/".join(under_documents)
        partition_created_at = None
        if DATE8_RE.match(under_documents[0]):
            partition_created_at = _utc_naive_midnight_from_date8(under_documents[0])
        return tenant_schema, agent_id, document_name, partition_created_at

    if len(parts) >= 3 and DATE8_RE.match(parts[1]):
        tenant_schema = _schema_for_s3_prefix(parts[0])
        agent_id = os.getenv("RAG_S3_DEFAULT_AGENT_ID", "").strip()
        if not agent_id or not UUID_RE.match(agent_id):
            raise ValueError(
                "Key S3 en formato legado (prefijo/YYYYMMDD/...): defina la variable de entorno "
                "RAG_S3_DEFAULT_AGENT_ID con el UUID del agente Bedrock/RAG."
            )
        under = parts[2:]
        basename = under[-1]
        if not basename or basename.endswith("/"):
            raise ValueError("Key S3 inválida: falta nombre de archivo (último segmento)")
        document_name = "/".join(under)
        partition_created_at = _utc_naive_midnight_from_date8(parts[1])
        return tenant_schema, agent_id, document_name, partition_created_at

    raise ValueError(
        "Key S3 inválida: use "
        "{tenant_schema}/{agent_uuid}/documents/<archivo> "
        "o {prefijo}/{YYYYMMDD}/[<carpetas>/]<archivo> con RAG_S3_DEFAULT_AGENT_ID "
        "(y RAG_S3_PREFIX_SCHEMA_MAP si hace falta)."
    )

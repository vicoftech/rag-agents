"""
Contrato tenant_id (API / query) ↔ esquema PostgreSQL.

- Si el cliente envía el slug corto (ej. `gp`), el esquema es `tenant_gp`.
- Si ya envía el nombre completo del esquema (`tenant_gp`), se usa tal cual.
Así coincide con la primera parte del key S3 usada en ingestión.
"""
import re

SCHEMA_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def resolve_schema_name(tenant_id: str) -> str:
    if tenant_id is None or not str(tenant_id).strip():
        raise ValueError("tenant_id no puede estar vacío")
    t = str(tenant_id).strip()
    if t.startswith("tenant_"):
        schema = t
    else:
        schema = f"tenant_{t}"
    assert_valid_schema_name(schema)
    return schema


def assert_valid_schema_name(schema: str) -> None:
    if not SCHEMA_NAME_RE.match(schema):
        raise ValueError(
            f"tenant_id inválido tras normalizar: {schema!r} "
            "(use letras, números y guión bajo; máx. 63 chars)"
        )

#!/usr/bin/env python3
"""

Para cada alerta activa (Lambda rag_lmbd_obtener_alertas), ejecuta la búsqueda semántica
(Lambda rag_lmbd_query) y agrega chunks que matchearon + URIs de objeto S3.

Las invocaciones a ``rag_lmbd_query`` pueden ejecutarse en paralelo (``--parallel``, default 10 hilos).

La Lambda de query también invoca el LLM; tiene costo por alerta.

En cada invocación el script sobrescribe el umbral sólo para esa llamada.
La Lambda en API sigue usando MAX_SEMANTIC_DISTANCE del env (p. ej. 0.45) si nadie envía otro valor.

Por **default** cada invocación a ``rag_lmbd_query`` filtra chunks por ``created_at`` en un ventana de
**días civiles UTC**: hoy inclusivo hasta hoy menos (N−1), con **N = 2** (ayer + hoy). Así las corridas
son más cortas que un full-index. Para buscar todo el corpus: ``--no-created-at-filter``.

Si ``chunks_count`` es 0 y el LLM igual escribe en ``llm_response_preview``, eso **no**
es un ``matcheo`` de corpus: no hay chunk ni S3 hasta que ``tiene_fuente_documental_recuperada`` sea true.
Cada fila incluye ``explicacion_sin_contexto_recuperado`` cuando no hubo recuperación (metas de la Lambda).

**Probar una palabra clave sin alerta en BD:** ``--simulate-alert-query "Fresenius Medical Care Argentina S.A"``
con ``--corrida anmat=...`` (no invoca ``rag_lmbd_obtener_alertas``; arma ``palabras_de_busqueda`` igual que una alerta real).

Para acercarse a una **búsqueda por palabra clave**:

  - **`max_semantic_distance` más bajo** ⇒ vecinos más estrictos en espacio vectorial (0.45 es el default
    del proyecto; valores ~0.28–0.35 suelen endurecer bastante vs 0.8).
  - **`literal_keyword_overlap`** (activo por defecto en este script) ⇒ después del vector sólo pasan chunks
    cuyo texto **contiene** al menos uno de los términos extraídos de la consulta (substring, sin stemming).
    Con esto también se **desactiva el fallback** de vecinos lejanos (evita ruido tipo OCR irrelevante).

  `--no-literal-keyword-filter` vuelve al flujo sólo-semántico (con fallback posible si el umbral deja todos fuera).

**Salida JSON:** por defecto ``corridas[].resultados`` (o ``resultados``) **sólo incluye alertas con**
``chunks_count > 0`` y match documental (**no** aparecen las filas sólo con ``explicacion_sin_contexto_recuperado``).
Para auditoría incluir también las sin match: ``--include-zero-chunk-resultados``.

Con varias keywords, las muy cortas (p. ej. «beta», default ``--exact-keyword-substantive-min-len 5``) se excluyen
del filtro OR para evitar falsos positivos. Modo ``--exact-chunk-keywords-mode all_corpus`` exige que **cada**
keyword sustantiva aparezca exacta en **algún** chunk de la lista.

Para auditoría de payloads hacia Lambdas (obtener + query, incl. ``created_at_*``): ``--trace-lambda-payloads``
(revisa ``meta.lambda_invoke_trace`` en el JSON de salida).

Con salida JSON completa (sin ``--salida-solo-notificaciones``), el archivo incluye ``notificaciones`` y
``alert_creation_messages`` (objetos que el script publicaría) y ``sqs_publish_preview``: nombres de cola
por defecto y cada ``MessageBody`` como string JSON (igual que ``SendMessage``).
Con ``--trace-lambda-payloads`` y ``--output-trace PATH``, las invocaciones van sólo a ``PATH`` y se
sacan del JSON principal (evita duplicar un trazo muy grande).

Dos corpus (boletín y ANMAT) en una sola ejecución:

  python3 scripts/alerts_semantic_matches.py --profile asap_main --env prod \\
    --corrida boletin=scripts/boletin_map.json \\
    --corrida anmat=scripts/anmat_map.json \\
    --s3-bucket rag-documents-prod-913123310997 \\
    --max-semantic-distance 0.30 \\
    -o alerts_matches.json

  El script usa ``--profile asap_main`` por defecto (igual que ``deploy-lambda.sh``). Para usar
  sólo variables de entorno / role IAM sin perfil nominado: ``--profile ""``.

Mapas: scripts/boletin_map.json y scripts/anmat_map.json (agent_id UUID de ANMAT: validar).

Mapeo por fuente_de_informacion: tenant_id (slug API), agent_id (UUID),
opcional \"s3_tenant_slug\". URIs: s3://<bucket>/<s3_slug>/<agent>/documents/<document_name>.

Build imagen ECS batch (push ECR): ver ``.github/workflows/batch-alerts-semantic-docker.yml``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import quote
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# AL-02: Import para verificación de idempotencia de emails
try:
    import psycopg2
    from psycopg2.extensions import connection as PgConnection
    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False
    PgConnection = None  # type: ignore

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def mensaje_cuando_sin_chunks_recuperados(retrieval_cfg: dict[str, Any] | None) -> str:
    """
    Para salidas donde chunks_count es 0: el modelo puede igual generar texto; eso **no**
    viene de un archivo indexado. Explica la causa habitual según métricas de rag_lmbd_query.
    """
    rc = retrieval_cfg or {}
    fin = rc.get("chunks_final_after_literal")
    if isinstance(fin, int) and fin > 0:
        return (
            "Inconsistencia: la Lambda reporta chunks recuperados pero no llegaron en la respuesta; "
            "revisar parseo JSON / versión Lambda."
        )
    if "retrieval_sql_row_count" not in rc:
        return (
            "Sin métricas retrieval_sql_row_count (Lambda vieja hasta redeploy): si el modelo respondió igual, "
            "no implica chunk ni objeto S3; puede ser conocimiento general del LLM."
        )
    try:
        n_sql = int(rc["retrieval_sql_row_count"])
    except (TypeError, ValueError):
        n_sql = -1
    after_sim = rc.get("chunks_after_similarity_gate")
    try:
        after_sim_i = int(after_sim) if after_sim is not None else 0
    except (TypeError, ValueError):
        after_sim_i = 0
    lit_before = rc.get("literal_keyword_rows_before")
    lit_after = rc.get("literal_keyword_rows_after")

    if n_sql == 0:
        msg = (
            "Cero filas en la consulta SQL con embedding (¿ventana created_at sin chunks nuevos?, "
            "agent_id equivocado o sin datos cargados)."
        )
    elif lit_before is not None and lit_after == 0:
        msg = (
            f"{lit_before} chunk(s) bajo umbral de distancia pero el filtro literal (substring tokens) los eliminó."
        )
    elif after_sim_i == 0:
        msg = (
            "Hubo vecinos SQL pero ninguno bajo max_semantic_distance; con literal_keyword_overlap no se usa "
            "fallback del vecino fuera de umbral. Podés subir umbral o usar --no-literal-keyword-filter."
        )
    else:
        msg = "Tras filtros vectorial/literal la lista de contextos quedó vacía."

    return (
        msg
        + " La respuesta mostrada como llm_response_preview puede no citar corpus; sólo hay objeto S3 "
        "cuando recuperamos al menos un document_name."
    )


# Fallback sólo si la fila busqueda / destinatarios no trae remitente (SES).
DEFAULT_NOTIFICATION_FALLBACK_FROM = "wisoft.soporte@asap-consulting.net"

# Frontend Alert Management historic search ([base](https://alerts.wi-soft.net/#/search/historic-search)).
# AL-03: Configurable por ambiente vía variable de entorno HISTORIC_SEARCH_BASE_URL
HISTORIC_SEARCH_BASE_URL = (
    os.environ.get("HISTORIC_SEARCH_BASE_URL")
    or "https://alerts.wi-soft.net/#/search/historic-search"
).strip()

_DATE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _log_step(stage: str, message: str, *, level: str = "INFO") -> None:
    """
    Log line-friendly para seguimiento en vivo (tail -f).
    Siempre imprime una línea con timestamp UTC y flush inmediato.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] [{level}] [{stage}] {message}"
    print(line, file=sys.stderr, flush=True)


def normalize_destinatarios_busqueda(dest: Any) -> dict[str, str]:
    """Extrae remitentes/nombre/asunto desde ``destinatarios`` de la tabla busqueda (JSON flexible)."""
    out = {"from": "", "to": "", "nombreUsuario": "", "subject": ""}

    def _pick_email(v: Any) -> str:
        if isinstance(v, str):
            s = v.strip()
            if "@" in s:
                parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
                return parts[0] if parts else ""
            return ""
        if isinstance(v, list):
            for it in v:
                got = _pick_email(it)
                if got:
                    return got
            return ""
        if isinstance(v, dict):
            for k in ("to", "email", "mail", "destinatario", "correo"):
                got = _pick_email(v.get(k))
                if got:
                    return got
            return ""
        return ""

    def apply_mapping(m: dict[str, Any]) -> None:
        for k_dest, keys in (
            ("from", ("from", "from_email", "de")),
            ("to", ("to", "email", "mail", "destinatario")),
            ("nombreUsuario", ("nombreUsuario", "nombre_usuario", "nombre", "usuario")),
            ("subject", ("subject", "asunto", "titulo")),
        ):
            for k in keys:
                v = m.get(k)
                if v is None:
                    continue
                if k_dest == "to":
                    s = _pick_email(v)
                else:
                    s = str(v).strip()
                if s:
                    out[k_dest] = s
                    break
        # Algunos payloads guardan los datos dentro de ``cuenta``.
        if not out["to"] and isinstance(m.get("cuenta"), dict):
            out["to"] = _pick_email(m["cuenta"].get("mail"))
        if not out["to"]:
            out["to"] = _pick_email(m.get("mail"))
        if not out["to"]:
            out["to"] = _pick_email(m.get("emails"))

    if dest is None:
        return out
    if isinstance(dest, dict):
        apply_mapping(dest)
        return out
    if isinstance(dest, list):
        for item in dest:
            if isinstance(item, dict):
                apply_mapping(item)
                if out["to"]:
                    break
            elif isinstance(item, str) and "@" in item:
                out["to"] = item.strip()
                break
        return out
    if isinstance(dest, str):
        s = dest.strip()
        if not s:
            return out
        if s.startswith("{"):
            try:
                return normalize_destinatarios_busqueda(json.loads(s))
            except json.JSONDecodeError:
                pass
        if "@" in s:
            first = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
            out["to"] = first[0] if first else ""
        return out
    return out


def keywords_from_palabras_de_busqueda(raw: Any) -> list[str]:
    """Lista de keywords desde ``palabras_de_busqueda`` de la tabla busqueda (como aparece en la fila)."""
    ps = "" if raw is None else str(raw).strip()
    if not ps:
        return []
    parts = [p.strip() for p in ps.replace(";", ",").split(",") if p.strip()]
    return parts if parts else [ps]


def normalize_text_for_exact_keyword_match(s: str) -> str:
    """Unicode NFKC + casefold + espacios colapsados (comparador estable para OCR/PDF)."""
    t = unicodedata.normalize("NFKC", str(s))
    return " ".join(t.casefold().split())


def exact_keyword_in_chunk_text(chunk_text: str, keyword: str) -> bool:
    """
    True si ``keyword`` aparece en ``chunk_text`` como coincidencia “exacta”:
    igualdad del texto normalizado como subcadena y con límites de token Unicode
    (no forma parte de otra palabra alfanumérica).
    """
    needle = normalize_text_for_exact_keyword_match(keyword)
    if not needle:
        return False
    haystack = normalize_text_for_exact_keyword_match(chunk_text)
    if len(haystack) < len(needle):
        return False
    start_search = 0
    lim = len(haystack) - len(needle)
    while start_search <= lim:
        idx = haystack.find(needle, start_search)
        if idx < 0:
            return False
        left_ch = haystack[idx - 1] if idx > 0 else ""
        right_ix = idx + len(needle)
        right_ch = haystack[right_ix] if right_ix < len(haystack) else ""
        glued_left = idx > 0 and left_ch.isalnum()
        glued_right = right_ix < len(haystack) and right_ch.isalnum()
        if not glued_left and not glued_right:
            return True
        start_search = idx + 1
    return False


def keywords_for_exact_chunk_filter(*, alerta: dict[str, Any]) -> list[str]:
    kws = keywords_from_palabras_de_busqueda(alerta.get("palabras_de_busqueda"))
    if kws:
        return kws
    nb = (alerta.get("nombre_busqueda") or "").strip()
    return [nb] if nb else []


def substantive_exact_keywords(keywords: list[str], *, min_normalized_len: int) -> list[str]:
    """
    Con varias palabras clave, descarta tokens demasiado cortos (p. ej. «beta») que matchean
    en OCR por casualidad dentro del modo OR. Si todos son cortos, conserva la lista original.
    """
    raw = [str(k).strip() for k in keywords if str(k).strip()]
    if min_normalized_len <= 0 or len(raw) <= 1:
        return raw
    out: list[str] = []
    for k in raw:
        collapsed = normalize_text_for_exact_keyword_match(k).replace(" ", "")
        if len(collapsed) >= min_normalized_len:
            out.append(k)
    return out if out else raw


def historic_search_urls_for_keywords(
    fuente_codigo: str,
    keywords: list[str],
    start_at: str,
    end_at: str,
) -> list[str]:
    """
    Una URL por palabra clave: ``{BASE}/{fuente}/{keyword_encoded}/{start_at}/{end_at}``.
    Si start_at/end_at no son YYYY-MM-DD (p. ej. N/A sin filtro de fechas), devuelve cadenas vacías.
    """
    s_raw = (start_at or "").strip()
    e_raw = (end_at or "").strip()
    if not keywords:
        return []
    if not (_DATE_ISO.match(s_raw) and _DATE_ISO.match(e_raw)):
        return ["" for _ in keywords]

    base = HISTORIC_SEARCH_BASE_URL.rstrip("/")
    urls: list[str] = []
    for kw in keywords:
        kw_seg = quote((kw or "").strip(), safe="")
        urls.append(f"{base}/{fuente_codigo}/{kw_seg}/{s_raw}/{e_raw}")
    return urls


def notification_envelope_fields_from_busqueda(
    resultado: dict[str, Any],
    *,
    dest_norm: dict[str, str],
    fallback_from: str,
) -> dict[str, str]:
    nombre_alerta = (resultado.get("nombre_busqueda") or "").strip()
    mail_from = (dest_norm.get("from") or "").strip() or fallback_from.strip()
    mail_to = (dest_norm.get("to") or "").strip()
    # Fallbacks defensivos: en algunos ambientes el destinatario viene en ``cuenta.mail`` o ``mail``.
    if not mail_to:
        cuenta = resultado.get("cuenta")
        if isinstance(cuenta, dict):
            mail_to = (normalize_destinatarios_busqueda(cuenta).get("to") or "").strip()
    if not mail_to:
        mail_to = (normalize_destinatarios_busqueda({"mail": resultado.get("mail")}).get("to") or "").strip()
    nombre_usuario = (dest_norm.get("nombreUsuario") or "").strip()
    subject = (dest_norm.get("subject") or "").strip() or nombre_alerta or ""
    return {
        "from": mail_from,
        "to": mail_to,
        "subject": subject,
        "nombreUsuario": nombre_usuario,
        "nombre_alerta": nombre_alerta,
    }


def resolve_fuente_informacion(*, corrida_label: str, tenant_id_usado: str) -> str:
    lk = (corrida_label or "").strip().lower()
    if lk == "anmat":
        return "ANMAT"
    if lk in ("boletin", "boletín", "boletin_oficial"):
        return "BOLETIN_OFICIAL"
    raw = (tenant_id_usado or "").strip().lower().replace("tenant_", "")
    if raw == "anmat":
        return "ANMAT"
    if raw == "boletin":
        return "BOLETIN_OFICIAL"
    return tenant_id_usado.strip().upper() if tenant_id_usado else "DESCONOCIDO"


def busqueda_fechas_display(meta: dict[str, Any]) -> tuple[str, str]:
    if meta.get("created_at_filter") == "off":
        return ("N/A", "N/A")
    s = (meta.get("created_at_start") or "").strip()
    e = (meta.get("created_at_end") or "").strip()
    return (s or "N/A", e or "N/A")


def build_plain_alert_message(
    resultado: dict[str, Any],
    *,
    fuente_informacion: str,
    busqueda_desde: str,
    busqueda_hasta: str,
    fallback_from: str,
) -> dict[str, Any]:
    dest_raw = resultado.get("destinatarios")
    dest_norm = normalize_destinatarios_busqueda(dest_raw)
    nf = notification_envelope_fields_from_busqueda(
        resultado, dest_norm=dest_norm, fallback_from=fallback_from
    )

    kws = keywords_from_palabras_de_busqueda(resultado.get("palabras_de_busqueda"))
    if not kws:
        nb = (nf.get("nombre_alerta") or "").strip()
        kws = [nb] if nb else ["Palabras Clave"]
    # Para URL de historic search usar la frase completa original (cuando exista),
    # no el primer token parseado.
    kw_raw_for_url = (resultado.get("palabras_de_busqueda") or "").strip()
    kw_url = kw_raw_for_url if kw_raw_for_url else kws[0]

    start_at_use = (
        busqueda_desde
        if busqueda_desde and busqueda_desde != "N/A" and _DATE_ISO.match(busqueda_desde.strip())
        else ""
    )
    end_at_use = (
        busqueda_hasta
        if busqueda_hasta and busqueda_hasta != "N/A" and _DATE_ISO.match(busqueda_hasta.strip())
        else ""
    )
    urls_per_kw = historic_search_urls_for_keywords(
        fuente_informacion, [kw_url], start_at_use, end_at_use
    )
    # SES template alert_aviso usa {{ url }} (string); no usar lista ``urls``.
    primary_url = (urls_per_kw[0] if urls_per_kw else "") or ""

    body: dict[str, Any] = {
        "keywords": kws,
        "nombreUsuario": nf["nombreUsuario"],
        "nombre_alerta": nf["nombre_alerta"],
        "url": primary_url,
    }

    return {
        "body_payload": body,
        "from": nf["from"],
        "subject": nf["subject"],
        "template_name": "alert_aviso",
        "to": nf["to"],
    }


def _patch_destinatarios_for_testing(dest: Any, te: str) -> Any:
    """Normaliza ``destinatarios`` sustituyendo correos de destino por ``te``."""
    if isinstance(dest, dict):
        d2 = dict(dest)
        d2["to"] = te
        for k in ("email", "mail", "destinatario", "correo"):
            if k in d2:
                d2[k] = te
        return d2
    if isinstance(dest, list):
        out: list[dict[str, Any]] = []
        for item in dest:
            if isinstance(item, dict):
                i2 = dict(item)
                i2["to"] = te
                for k in ("email", "mail", "destinatario", "correo"):
                    if k in i2:
                        i2[k] = te
                out.append(i2)
        return out if out else [{"to": te}]
    if isinstance(dest, str):
        s = dest.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                obj = json.loads(s)
                patched = _patch_destinatarios_for_testing(obj, te)
                return json.dumps(patched, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        return json.dumps({"to": te}, ensure_ascii=False)
    return {"to": te}


def apply_testing_email_to_blob(blob: dict[str, Any], testing_email: str) -> None:
    """
    Modo prueba: sustituye ``mail``, ``cuenta.mail`` y ``destinatarios`` en cada resultado,
    y registra el override en ``meta`` (las notificaciones posteriores usan el mismo ``to``).
    """
    te = (testing_email or "").strip()
    if not te:
        return
    meta = blob.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        blob["meta"] = meta
    meta["testing_email_override"] = True
    meta["testing_email"] = te

    def patch_resultado(r: dict[str, Any]) -> None:
        if not isinstance(r, dict):
            return
        r["mail"] = te
        cuenta = r.get("cuenta")
        if isinstance(cuenta, dict):
            cuenta["mail"] = te
        if "destinatarios" in r:
            r["destinatarios"] = _patch_destinatarios_for_testing(r["destinatarios"], te)

    for c in blob.get("corridas") or []:
        for r in c.get("resultados") or []:
            patch_resultado(r)
    for r in blob.get("resultados") or []:
        patch_resultado(r)


def _es_resultado_con_match_documental(r: dict[str, Any]) -> bool:
    """True sólo si hubo chunks recuperados y sin marcador de «sin contexto»."""
    if int(r.get("chunks_count") or 0) <= 0:
        return False
    if not r.get("tiene_fuente_documental_recuperada", True):
        return False
    if r.get("explicacion_sin_contexto_recuperado"):
        return False
    return True


def compute_notificaciones(blob: dict[str, Any], fallback_from: str) -> list[dict[str, Any]]:
    meta = blob.get("meta") or {}
    desde, hasta = busqueda_fechas_display(meta)
    out: list[dict[str, Any]] = []

    corridas = blob.get("corridas")
    if isinstance(corridas, list) and corridas:
        for c in corridas:
            label = str(c.get("label") or "")
            for r in c.get("resultados") or []:
                if not isinstance(r, dict):
                    continue
                if not _es_resultado_con_match_documental(r):
                    continue
                fuente = resolve_fuente_informacion(
                    corrida_label=label, tenant_id_usado=str(r.get("tenant_id_usado") or "")
                )
                out.append(
                    {
                        "alerta_id": r.get("alerta_id"),
                        "corrida_label": label or None,
                        "chunks_count": r.get("chunks_count"),
                        "message": build_plain_alert_message(
                            r,
                            fuente_informacion=fuente,
                            busqueda_desde=desde,
                            busqueda_hasta=hasta,
                            fallback_from=fallback_from,
                        ),
                    }
                )
        return out

    for r in blob.get("resultados") or []:
        if not isinstance(r, dict):
            continue
        if not _es_resultado_con_match_documental(r):
            continue
        fuente = resolve_fuente_informacion(
            corrida_label="",
            tenant_id_usado=str(r.get("tenant_id_usado") or ""),
        )
        out.append(
            {
                "alerta_id": r.get("alerta_id"),
                "corrida_label": None,
                "chunks_count": r.get("chunks_count"),
                "message": build_plain_alert_message(
                    r,
                    fuente_informacion=fuente,
                    busqueda_desde=desde,
                    busqueda_hasta=hasta,
                    fallback_from=fallback_from,
                ),
            }
        )

    return out


# ────────────────────────────────────────────────────────────────────
# AL-02: Idempotencia de emails - Prevención de duplicados
# ────────────────────────────────────────────────────────────────────


def _connect_to_postgres() -> PgConnection | None:
    """
    Conecta a PostgreSQL usando variables de entorno o Secrets Manager.
    Retorna None si psycopg2 no está disponible o si faltan credenciales.

    Variables de entorno:
    - DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT (opcional, default 5432)
    - DB_SECRET_ARN (opcional, preferido sobre variables directas)
    """
    if not _PSYCOPG2_AVAILABLE:
        return None

    # Opción 1: Secrets Manager (preferido)
    arn = (os.environ.get("DB_SECRET_ARN") or "").strip()
    if arn:
        try:
            import json
            secrets_client = boto3.client("secretsmanager")
            resp = secrets_client.get_secret_value(SecretId=arn)
            secret = json.loads(resp.get("SecretString") or "{}")

            host = secret.get("host")
            dbname = secret.get("dbname") or secret.get("database")
            username = secret.get("username") or secret.get("user")
            password = secret.get("password")
            port = int(secret.get("port", 5432))

            if not all([host, dbname, username, password]):
                return None

            return psycopg2.connect(
                host=host,
                port=port,
                dbname=dbname,
                user=username,
                password=password,
                sslmode="require",
                connect_timeout=30,
            )
        except Exception:
            # Si falla, intentar con variables de entorno
            pass

    # Opción 2: Variables de entorno directas
    host = (os.environ.get("DB_HOST") or "").strip()
    dbname = (os.environ.get("DB_NAME") or "").strip()
    user = (os.environ.get("DB_USER") or "").strip()
    password = os.environ.get("DB_PASSWORD")
    port_s = (os.environ.get("DB_PORT") or "5432").strip()

    if not host or not dbname or not user or password is None or str(password) == "":
        return None

    try:
        port = int(port_s)
    except ValueError:
        return None

    try:
        return psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=str(password),
            sslmode=(os.environ.get("DB_SSLMODE") or "require").strip() or "require",
            connect_timeout=30,
        )
    except Exception:
        return None


def _check_email_already_sent(
    conn: PgConnection | None,
    alert_id: int | str | None,
    recipient_email: str,
    sent_date: date | None = None,
) -> bool:
    """
    Verifica si un email ya fue enviado para una alerta específica.

    Args:
        conn: Conexión a PostgreSQL (puede ser None)
        alert_id: ID de la alerta
        recipient_email: Email del destinatario
        sent_date: Fecha de envío (default: hoy)

    Returns:
        True si el email ya fue enviado, False en caso contrario
        False si no hay conexión o si ocurre algún error
    """
    if conn is None or not _PSYCOPG2_AVAILABLE:
        return False

    if not alert_id or not recipient_email:
        return False

    if sent_date is None:
        sent_date = date.today()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM alert_emails_sent
                WHERE alert_id = %s
                  AND recipient_email = %s
                  AND sent_date = %s
                LIMIT 1
                """,
                (int(alert_id), recipient_email.strip(), sent_date),
            )
            return cur.fetchone() is not None
    except Exception:
        # Si hay error (tabla no existe, etc.), no bloquear el envío
        return False


def filter_duplicate_notifications(
    notifs: list[dict[str, Any]],
    conn: PgConnection | None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Filtra notificaciones que ya fueron enviadas según la tabla alert_emails_sent.

    Args:
        notifs: Lista de notificaciones a filtrar
        conn: Conexión a PostgreSQL (puede ser None)

    Returns:
        Tupla (notificaciones_filtradas, cantidad_duplicados_detectados)
    """
    if conn is None or not _PSYCOPG2_AVAILABLE:
        # Si no hay conexión, retornar todas las notificaciones sin filtrar
        return (notifs, 0)

    filtered: list[dict[str, Any]] = []
    duplicates_count = 0
    today = date.today()

    for notif in notifs:
        alert_id = notif.get("alerta_id")
        message = notif.get("message") or {}
        recipient_email = (message.get("to") or "").strip()

        if not alert_id or not recipient_email:
            # Si falta información, incluir la notificación
            filtered.append(notif)
            continue

        already_sent = _check_email_already_sent(
            conn,
            alert_id,
            recipient_email,
            sent_date=today,
        )

        if already_sent:
            duplicates_count += 1
            _log_step(
                "DEDUP",
                f"SKIP_DUPLICATE: alert_id={alert_id} recipient={recipient_email} "
                f"(ya enviado el {today})",
                level="WARNING",
            )
        else:
            filtered.append(notif)

    return (filtered, duplicates_count)


# ────────────────────────────────────────────────────────────────────


def _publish_json_messages_to_sqs(
    messages: list[dict[str, Any]],
    *,
    queue_name: str,
    session: boto3.Session,
) -> int:
    """
    Un mensaje SQS por elemento de ``notifs`` (JSON UTF-8).
    Cola estándar (no FIFO); mensajes > 256 KiB fallarán en SendMessage.
    """
    name = (queue_name or "").strip()
    if not name:
        raise ValueError("nombre de cola SQS vacío")
    sqs = session.client("sqs")
    qurl = sqs.get_queue_url(QueueName=name)["QueueUrl"]
    sent = 0
    for item in messages:
        sqs.send_message(
            QueueUrl=qurl,
            MessageBody=json.dumps(item, ensure_ascii=False),
        )
        sent += 1
    return sent


def publish_notificaciones_to_sqs(
    notifs: list[dict[str, Any]],
    *,
    queue_name: str,
    session: boto3.Session,
) -> int:
    return _publish_json_messages_to_sqs(
        notifs,
        queue_name=queue_name,
        session=session,
    )


def compute_alert_creation_messages(blob: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Construye mensajes para la cola rag-alert-creation-*:
    - un mensaje por alerta/documento con chunk_id(s) recuperados
    - payload compatible con apps/rag_lmbd_alert_creation/handler.py
    """
    out: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    default_day = datetime.now(timezone.utc).date().isoformat()

    def _iter_results() -> list[dict[str, Any]]:
        corridas = blob.get("corridas")
        if isinstance(corridas, list) and corridas:
            rows: list[dict[str, Any]] = []
            for c in corridas:
                for r in c.get("resultados") or []:
                    if isinstance(r, dict):
                        rows.append(r)
            return rows
        return [r for r in (blob.get("resultados") or []) if isinstance(r, dict)]

    for r in _iter_results():
        if not _es_resultado_con_match_documental(r):
            continue
        busqueda_id = r.get("alerta_id")
        if busqueda_id is None:
            continue

        estado_alerta = r.get("estado_alerta")
        if estado_alerta is None:
            estado_alerta = 1

        chunks_by_doc = r.get("matched_chunk_ids_por_documento") or {}
        for dname in r.get("documents_unique") or []:
            if not dname:
                continue
            matched_ids = chunks_by_doc.get(dname) or []
            if not matched_ids:
                continue

            dispo_id = str(dname).strip()
            url = (r.get("s3_uri_por_documento") or {}).get(dname) or ""
            out.append(
                {
                    "busqueda_id": int(busqueda_id),
                    "estado_alerta": int(estado_alerta),
                    "fechayhora_ocurrencia": now_iso,
                    "disposicion": {
                        "disposicion_id": dispo_id,
                        "descripcion": (r.get("descripcion_disposicion_default") or r.get("nombre_busqueda") or dispo_id),
                        "url": url or f"s3://desconocido/{dispo_id}",
                        "nombre_pdf": r.get("nombre_pdf_disposicion_default") or dispo_id,
                        "archivo": r.get("archivo_disposicion_default"),
                        "fecha_de_aparicion": r.get("fecha_de_aparicion_default") or default_day,
                        "fecha_de_publicacion": r.get("fecha_de_publicacion_default") or default_day,
                    },
                    "matched_chunk_ids": matched_ids,
                }
            )
    return out


def utc_created_at_window_dates(*, span_days: int) -> tuple[str, str]:
    """
    Inicio y fin (YYYY-MM-DD) inclusive en días civiles UTC, terminando «hoy» UTC.
    span_days 1 ⇒ sólo hoy; 2 ⇒ ayer+hoy (default recomendado).
    """
    if span_days < 1:
        raise ValueError("span_days debe ser >= 1")
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=span_days - 1)
    return start.isoformat(), today.isoformat()


def parse_max_semantic_distance_cli(raw: str) -> float:
    """
    Distancia coseno pgvector (<=>): valores **más bajos** = chunks más parecidos al embedding de la consulta.
    Umbra **más bajos** = retriever más estricto.

    Si el valor es > 2 se divide entre 100 (ej. 35 → 0.35 cuando se escribe \"entero grande\").
    """
    v = float(str(raw).strip())
    if v > 2.0:
        v /= 100.0
    if not (0 < v <= 2.0):
        raise argparse.ArgumentTypeError(
            f"--max-semantic-distance debe normalizar a (0, 2]; obtuve {v!r}"
        )
    return v


def parse_parallel_workers(raw: str) -> int:
    """Máximo de hilos para invocaciones concurrentes a rag_lmbd_query."""
    v = int(str(raw).strip())
    if v < 1:
        raise argparse.ArgumentTypeError("--parallel debe ser un entero >= 1")
    return v


class LambdaInvokeTrace:
    """Registro thread-safe de payloads enviados a Lambda.invoke (auditoría / debug)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self.entries: list[dict[str, Any]] = []

    def record(
        self,
        function_name: str,
        payload: dict[str, Any],
        *,
        kind: str,
        alerta_id: Any = None,
    ) -> None:
        snap = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        with self._lock:
            self._seq += 1
            row: dict[str, Any] = {
                "seq": self._seq,
                "kind": kind,
                "function": function_name,
                "payload": snap,
            }
            if alerta_id is not None:
                row["alerta_id"] = alerta_id
            self.entries.append(row)


def parse_lambda_read_timeout(raw: str) -> int:
    """Segundos de espera HTTP al invocar Lambda (RequestResponse); el default de boto3 (~60) es corto vs query+LLM."""
    v = int(str(raw).strip())
    if not (30 <= v <= 900):
        raise argparse.ArgumentTypeError("--lambda-read-timeout debe estar entre 30 y 900")
    return v


def _session(profile: str, region: str) -> boto3.Session:
    kwargs: dict[str, str] = {"region_name": region}
    if profile:
        kwargs["profile_name"] = profile
    return boto3.Session(**kwargs)


def _invoke_lambda(
    client,
    *,
    name: str,
    payload: dict[str, Any],
    trace: LambdaInvokeTrace | None = None,
    trace_kind: str = "invoke",
    trace_alerta_id: Any = None,
) -> dict[str, Any]:
    if trace is not None:
        trace.record(
            name,
            payload,
            kind=trace_kind,
            alerta_id=trace_alerta_id,
        )
    invoke_kw: dict[str, Any] = {
        "FunctionName": name,
        "InvocationType": "RequestResponse",
        "Payload": json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    }
    resp = client.invoke(**invoke_kw)
    raw = resp["Payload"].read().decode("utf-8")
    outer = json.loads(raw)
    if resp.get("FunctionError"):
        err_type = outer.get("errorType") or outer.get("FunctionError") or outer
        raise RuntimeError(f"{name}: {resp.get('FunctionError')} — {err_type}")
    payload_str = outer.get("body") if isinstance(outer, dict) else None
    if isinstance(payload_str, str):
        try:
            inner = json.loads(payload_str)
        except json.JSONDecodeError:
            return outer
        sc = outer.get("statusCode")
        if isinstance(inner, dict) and inner.get("error"):
            raise RuntimeError(f"{name} status={sc}: {inner.get('error')} — {inner.get('message', '')}")
        if isinstance(sc, int) and sc >= 400:
            raise RuntimeError(f"{name} status={sc}: respuesta HTTP de error Lambda")
        return inner
    return outer


def infer_s3_tenant_slug(api_tenant: str, explicit: str | None) -> str:
    """Primer segmento de key canónico (ej. tenant_boletin vs boletin)."""
    if explicit and explicit.strip():
        return explicit.strip()
    if not api_tenant:
        raise ValueError("tenant_id vacío")
    if api_tenant.startswith("tenant_"):
        return api_tenant
    return f"tenant_{api_tenant.strip()}"


def canonical_s3_uri(
    *,
    bucket: str,
    s3_slug: str,
    agent_id: str,
    document_name: str,
) -> str:
    key = f"{s3_slug}/{agent_id}/documents/{document_name}"
    key = key.lstrip("/")
    return f"s3://{bucket}/{key}"


def normalize_search_query(palabras: Any, nombre: Any) -> str:
    pw = "" if palabras is None else str(palabras).strip()
    if pw:
        pieces = []
        current = pw.replace(";", ",")
        for comma_part in current.split(","):
            comma_part = comma_part.strip()
            if comma_part:
                pieces.append(comma_part)
        if pieces:
            return ", ".join(pieces)
        return pw.split()[0]
    nb = "" if nombre is None else str(nombre).strip()
    if not nb:
        raise ValueError("alerta sin palabras_de_busqueda ni nombre_busqueda")
    return nb


def load_fuente_map(path: str | None, inline: str | None) -> dict[str, dict[str, str]]:
    if path:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    elif inline:
        raw = json.loads(inline)
    else:
        raise ValueError("Defina --fuente-map-file o --fuente-map-inline")
    out: dict[str, dict[str, str]] = {}
    for key, cfg in raw.items():
        ks = str(key)
        out[ks] = {
            "tenant_id": cfg["tenant_id"],
            "agent_id": cfg["agent_id"],
        }
        if cfg.get("s3_tenant_slug"):
            out[ks]["s3_tenant_slug"] = cfg["s3_tenant_slug"]
        if cfg.get("s3_slug"):
            out[ks]["s3_tenant_slug"] = cfg["s3_slug"]
    return out


def resolve_fuente(map_by_fuente: dict[str, dict[str, str]], fuente_raw: Any) -> dict[str, str]:
    k = None if fuente_raw is None else str(int(fuente_raw))
    if k in map_by_fuente:
        return map_by_fuente[k]
    if "_default" in map_by_fuente:
        return map_by_fuente["_default"]
    raise KeyError(
        f"No hay mapeo para fuente_de_informacion={fuente_raw!r}. "
        f"Definilo en el JSON de --fuente-map o usa _default."
    )


def process_one_alert(
    *,
    client,
    query_fn_name: str,
    alerta: dict[str, Any],
    fuente_cfg: dict[str, str],
    bucket: str | None,
    max_semantic_distance: float,
    retrieval_limit: int | None = None,
    semantic_fallback_top_n: int | None = None,
    literal_keyword_overlap: bool = True,
    literal_keyword_min_length: int = 3,
    exact_chunk_keyword_filter: bool = True,
    exact_keyword_substantive_min_len: int = 5,
    exact_chunk_keywords_mode: str = "any",
    created_at_start: str | None = None,
    created_at_end: str | None = None,
    include_full_chunk_text: bool = False,
    invoke_trace: LambdaInvokeTrace | None = None,
) -> dict[str, Any]:
    fuente_raw = alerta.get("fuente_de_informacion")
    tenant_id = fuente_cfg["tenant_id"].strip()
    agent_id = fuente_cfg["agent_id"].strip()
    if not _UUID_RE.match(agent_id):
        raise ValueError(f"agent_id debe ser UUID: {agent_id!r}")
    agent_id_norm = str(uuid.UUID(agent_id))

    query_text = normalize_search_query(
        alerta.get("palabras_de_busqueda"),
        alerta.get("nombre_busqueda"),
    )

    q_payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "agent_id": agent_id_norm,
        "query": query_text,
        "max_semantic_distance": max_semantic_distance,
    }
    if retrieval_limit is not None:
        q_payload["retrieval_limit"] = int(retrieval_limit)
    if semantic_fallback_top_n is not None:
        q_payload["semantic_fallback_top_n"] = semantic_fallback_top_n

    q_payload["literal_keyword_overlap"] = literal_keyword_overlap
    q_payload["literal_keyword_min_length"] = literal_keyword_min_length

    if created_at_start and created_at_end:
        q_payload["created_at_start"] = created_at_start
        q_payload["created_at_end"] = created_at_end

    q_body = _invoke_lambda(
        client,
        name=query_fn_name,
        payload=q_payload,
        trace=invoke_trace,
        trace_kind="rag_lmbd_query",
        trace_alerta_id=alerta.get("id"),
    )
    contexts_lambda = q_body.get("contexts") or []

    raw_items = q_body.get("context_items")
    paired_chunks: list[tuple[dict[str, Any], str]] = []
    if isinstance(raw_items, list) and raw_items:
        for i, row in enumerate(raw_items):
            if not isinstance(row, dict):
                continue
            dn = row.get("document_name") or ""
            dist = row.get("distance")
            txt = row.get("chunk_text") or ""
            entry: dict[str, Any] = {
                "rank": i,
                "chunk_id": row.get("chunk_id"),
                "document_name": dn,
                "distance": dist,
                "chunk_text_preview": txt[:320] + ("…" if len(txt) > 320 else ""),
            }
            if include_full_chunk_text and txt:
                entry["chunk_text_full"] = txt
            paired_chunks.append((entry, txt))
    else:
        for i, txt in enumerate(contexts_lambda):
            ttxt = txt if isinstance(txt, str) else str(txt or "")
            row_dict: dict[str, Any] = {
                "rank": i,
                "chunk_id": None,
                "document_name": "",
                "distance": None,
                "chunk_text_preview": (ttxt[:320] + ("…" if len(ttxt) > 320 else "")),
            }
            if include_full_chunk_text and ttxt:
                row_dict["chunk_text_full"] = ttxt
            paired_chunks.append((row_dict, ttxt))

    n_chunks_before_exact = len(paired_chunks)
    keyword_list_exact = keywords_for_exact_chunk_filter(alerta=alerta)
    mode_lc = str(exact_chunk_keywords_mode or "any").strip().lower()
    if exact_chunk_keyword_filter and keyword_list_exact:
        kws = [str(kw).strip() for kw in keyword_list_exact if str(kw).strip()]
        if mode_lc == "all_corpus":
            ok = bool(kws) and all(
                any(exact_keyword_in_chunk_text(t, kw) for _, t in paired_chunks)
                for kw in kws
            )
            if ok:
                paired_chunks = [
                    (e, t)
                    for (e, t) in paired_chunks
                    if any(exact_keyword_in_chunk_text(t, kw) for kw in kws)
                ]
            else:
                paired_chunks = []
        else:
            paired_chunks = [
                (e, t)
                for (e, t) in paired_chunks
                if any(exact_keyword_in_chunk_text(t, kw) for kw in kws)
            ]
    n_chunks_after_exact = len(paired_chunks)

    context_entries = []
    contexts: list[str] = []
    for ni, (e, t_full) in enumerate(paired_chunks):
        e["rank"] = ni
        e["chunk_text_preview"] = t_full[:320] + ("…" if len(t_full) > 320 else "")
        if include_full_chunk_text and t_full:
            e["chunk_text_full"] = t_full
        elif not include_full_chunk_text and "chunk_text_full" in e:
            del e["chunk_text_full"]
        context_entries.append(e)
        contexts.append(t_full)

    documents = sorted({e.get("document_name") or "" for e, _ in paired_chunks})
    documents = sorted(d for d in documents if d)

    s3_slug = infer_s3_tenant_slug(tenant_id, fuente_cfg.get("s3_tenant_slug"))

    uris_by_doc: dict[str, str] = {}
    if bucket:
        for dname in documents:
            uris_by_doc[dname] = canonical_s3_uri(
                bucket=bucket,
                s3_slug=s3_slug,
                agent_id=agent_id_norm,
                document_name=dname,
            )

    chunk_ids_by_doc: dict[str, list[int]] = {}
    matched_chunk_ids: list[int] = []
    for ce in context_entries:
        dn = ce.get("document_name") or ""
        chunk_id_raw = ce.get("chunk_id")
        if chunk_id_raw is not None:
            try:
                chunk_id = int(chunk_id_raw)
            except (TypeError, ValueError):
                chunk_id = None
            if chunk_id is not None:
                matched_chunk_ids.append(chunk_id)
                if dn:
                    bucket_ids = chunk_ids_by_doc.setdefault(dn, [])
                    if chunk_id not in bucket_ids:
                        bucket_ids.append(chunk_id)
        if bucket and dn:
            ce["object_uri_canonical"] = canonical_s3_uri(
                bucket=bucket,
                s3_slug=s3_slug,
                agent_id=agent_id_norm,
                document_name=dn,
            )
        elif bucket:
            ce["object_uri_canonical"] = ""
        else:
            ce["object_uri_canonical"] = None

    rsp = q_body.get("response") or ""
    tiene_rec = len(contexts) > 0
    out: dict[str, Any] = {
        "alerta_id": alerta.get("id"),
        "nombre_busqueda": alerta.get("nombre_busqueda"),
        "palabras_de_busqueda": alerta.get("palabras_de_busqueda"),
        "estado_alerta": alerta.get("estado_alerta"),
        "descripcion_disposicion_default": alerta.get("descripcion_disposicion_default"),
        "url_disposicion_default": alerta.get("url_disposicion_default"),
        "nombre_pdf_disposicion_default": alerta.get("nombre_pdf_disposicion_default"),
        "archivo_disposicion_default": alerta.get("archivo_disposicion_default"),
        "fecha_de_aparicion_default": alerta.get("fecha_de_aparicion_default"),
        "fecha_de_publicacion_default": alerta.get("fecha_de_publicacion_default"),
        "destinatarios": alerta.get("destinatarios"),
        "cuenta": alerta.get("cuenta"),
        "mail": alerta.get("mail"),
        "fuente_de_informacion": fuente_raw,
        "tenant_id_usado": tenant_id,
        "agent_id_usado": agent_id_norm,
        "query_text_usada": query_text,
        "context_items": context_entries,
        "matched_chunk_ids": matched_chunk_ids,
        "matched_chunk_ids_por_documento": chunk_ids_by_doc,
        "llm_response_preview": rsp[:320] + ("…" if len(rsp) > 320 else ""),
        "chunks_count": len(contexts),
        "documents_unique": documents,
        "s3_uri_por_documento": uris_by_doc,
        "retrieval_config": q_body.get("retrieval_config"),
        "tiene_fuente_documental_recuperada": tiene_rec,
    }
    if exact_chunk_keyword_filter and keyword_list_exact:
        out["exact_keyword_chunk_filter"] = {
            "keywords": keyword_list_exact,
            "keywords_mode": mode_lc,
            "substantive_min_normalized_len": int(exact_keyword_substantive_min_len),
            "chunks_before": n_chunks_before_exact,
            "chunks_after": n_chunks_after_exact,
        }
    if not tiene_rec:
        if (
            exact_chunk_keyword_filter
            and keyword_list_exact
            and n_chunks_before_exact > 0
            and n_chunks_after_exact == 0
        ):
            ks_display = ", ".join(
                str(k).strip() for k in keyword_list_exact if str(k).strip()
            )
            out["explicacion_sin_contexto_recuperado"] = (
                "La consulta recuperó chunks por embedding pero ninguno contiene coincidencia exacta "
                f"de las palabras clave ({ks_display}) en el texto del chunk."
            )
        else:
            out["explicacion_sin_contexto_recuperado"] = mensaje_cuando_sin_chunks_recuperados(
                q_body.get("retrieval_config")
            )
    return out


def _run_query_workers(
    *,
    client,
    alertas: list,
    fm: dict[str, dict[str, str]],
    query_name: str,
    bucket: str | None,
    max_semantic_distance: float,
    retrieval_limit: int | None,
    semantic_fallback_top_n: int | None,
    literal_keyword_overlap: bool,
    literal_keyword_min_length: int,
    exact_chunk_keyword_filter: bool,
    exact_keyword_substantive_min_len: int,
    exact_chunk_keywords_mode: str,
    parallel: int,
    created_at_start: str | None,
    created_at_end: str | None,
    include_full_chunk_text: bool,
    invoke_trace: LambdaInvokeTrace | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total = len(alertas)
    _log_step(
        "QUERY",
        f"Inicio procesamiento de {total} alerta(s) (parallel={max(1, parallel)}).",
    )

    def _job(a: dict[str, Any]):
        fid = str(a.get("id"))
        try:
            fc = resolve_fuente(fm, a.get("fuente_de_informacion"))
            return (
                fid,
                process_one_alert(
                    client=client,
                    query_fn_name=query_name,
                    alerta=a,
                    fuente_cfg=fc,
                    bucket=bucket,
                    max_semantic_distance=max_semantic_distance,
                    retrieval_limit=retrieval_limit,
                    semantic_fallback_top_n=semantic_fallback_top_n,
                    literal_keyword_overlap=literal_keyword_overlap,
                    literal_keyword_min_length=literal_keyword_min_length,
                    exact_chunk_keyword_filter=exact_chunk_keyword_filter,
                    exact_keyword_substantive_min_len=exact_keyword_substantive_min_len,
                    exact_chunk_keywords_mode=exact_chunk_keywords_mode,
                    created_at_start=created_at_start,
                    created_at_end=created_at_end,
                    include_full_chunk_text=include_full_chunk_text,
                    invoke_trace=invoke_trace,
                ),
            )
        except Exception as e:
            return (fid, {"error": str(e), "alerta": {k: a.get(k) for k in ("id", "nombre_busqueda")}})

    if parallel <= 1:
        for idx, a in enumerate(alertas, start=1):
            fid, res = _job(a)
            if "error" in res:
                errors.append({"alerta_id": fid, **res})
                _log_step(
                    "QUERY",
                    f"{idx}/{total} alerta_id={fid} ERROR: {res.get('error')}",
                    level="ERROR",
                )
            else:
                results.append(res)
                _log_step(
                    "QUERY",
                    f"{idx}/{total} alerta_id={fid} ok (chunks={res.get('chunks_count', 0)}).",
                )
    else:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = {ex.submit(_job, a): a for a in alertas}
            done = 0
            for fut in as_completed(futs):
                fid, res = fut.result()
                done += 1
                if "error" in res:
                    errors.append({"alerta_id": fid, **res})
                    _log_step(
                        "QUERY",
                        f"{done}/{total} alerta_id={fid} ERROR: {res.get('error')}",
                        level="ERROR",
                    )
                else:
                    results.append(res)
                    _log_step(
                        "QUERY",
                        f"{done}/{total} alerta_id={fid} ok (chunks={res.get('chunks_count', 0)}).",
                    )

    _log_step("QUERY", f"Fin procesamiento: ok={len(results)} error={len(errors)}.")
    return results, errors


def omit_resultados_sin_coincidencia_documental(
    blob: dict[str, Any], *, include_zero_chunk: bool
) -> dict[str, Any]:
    """
    Deja en ``resultados`` / ``corridas[].resultados`` sólo filas con chunks reales
    (misma regla que ``notificaciones``). Con ``include_zero_chunk=True`` no altera.
    """
    if include_zero_chunk:
        return blob
    if isinstance(blob.get("corridas"), list):
        for c in blob["corridas"]:
            if not isinstance(c, dict):
                continue
            summ = c.get("summary")
            if not isinstance(summ, dict):
                summ = {}
                c["summary"] = summ
            full = [r for r in (c.get("resultados") or []) if isinstance(r, dict)]
            filt = [r for r in full if _es_resultado_con_match_documental(r)]
            summ["resultados_totales_procesados"] = len(full)
            summ["resultados_con_coincidencia_documental"] = len(filt)
            c["resultados"] = filt
    elif isinstance(blob.get("resultados"), list):
        full = [r for r in blob["resultados"] if isinstance(r, dict)]
        summ = blob.get("summary")
        if not isinstance(summ, dict):
            summ = {}
            blob["summary"] = summ
        filt = [r for r in full if _es_resultado_con_match_documental(r)]
        summ["resultados_totales_procesados"] = len(full)
        summ["resultados_con_coincidencia_documental"] = len(filt)
        blob["resultados"] = filt
    return blob


def run(args: argparse.Namespace) -> dict[str, Any]:
    suf = "-" + args.env
    obtener_name = getattr(args, "obtener_function", "").strip()
    query_name = getattr(args, "query_function", "").strip()
    if not obtener_name:
        obtener_name = f"rag_lmbd_obtener_alertas{suf}"
    if not query_name:
        query_name = f"rag_lmbd_query{suf}"

    sim_q = (getattr(args, "simulate_alert_query", "") or "").strip()
    if not getattr(args, "allow_weekend_run", False) and not sim_q:
        tz_art = "America/Argentina/Buenos_Aires"
        now_art = datetime.now(ZoneInfo(tz_art))
        if now_art.weekday() >= 5:
            dias_es = (
                "lunes",
                "martes",
                "miércoles",
                "jueves",
                "viernes",
                "sábado",
                "domingo",
            )
            dia = dias_es[now_art.weekday()]
            skip_msg = (
                f"SKIP: ejecución en día no laborable ({now_art.strftime('%Y-%m-%d')}, {dia})"
            )
            _log_step("RUN", skip_msg)
            _log_step("MAIN", skip_msg)
            stub_meta: dict[str, Any] = {
                "obtener_alertas_lambda": obtener_name,
                "query_lambda": query_name,
                "aws_profile": args.profile or None,
                "aws_region": args.region,
                "skipped_non_business_day": True,
                "skip_timezone": tz_art,
                "skip_local_date": now_art.strftime("%Y-%m-%d"),
                "skip_local_weekday": dia,
            }
            return {
                "meta": stub_meta,
                "corridas": [],
                "summary": {"total_alertas_filtradas": 0, "matches_ok": 0, "matches_error": 0},
                "resultados": [],
                "errors": [],
            }

    _log_step(
        "RUN",
        f"Inicio env={args.env} region={args.region} obtener={obtener_name} query={query_name}",
    )
    sess = _session(args.profile, args.region)
    read_to = int(getattr(args, "lambda_read_timeout"))
    client = sess.client(
        "lambda",
        config=Config(
            read_timeout=read_to,
            connect_timeout=30,
            retries={"mode": "standard", "max_attempts": 5},
        ),
    )

    invoke_trace: LambdaInvokeTrace | None = None
    if getattr(args, "trace_lambda_payloads", False):
        invoke_trace = LambdaInvokeTrace()

    if sim_q:
        sim_id = int(getattr(args, "simulate_alerta_id", 900001))
        sim_fuente = int(getattr(args, "simulate_fuente_de_informacion", 0))
        sim_nombre = (getattr(args, "simulate_nombre_busqueda", "") or "").strip() or "(simulado)"
        alertas = [
            {
                "id": sim_id,
                # Solo simulación: destinatario fijo para pruebas de envío.
                "destinatarios": {"to": "viglesias@asap-consulting.net"},
                "fuente_de_informacion": sim_fuente,
                "nombre_busqueda": sim_nombre,
                "palabras_de_busqueda": sim_q,
            }
        ]
        _log_step("RUN", f"Modo simulación activo (alerta_id={sim_id}).")
    else:
        obtener_payload: dict[str, Any] = {}
        if args.obtener_payload:
            obtener_payload = json.loads(args.obtener_payload)
        elif (getattr(args, "ids", "") or "").strip():
            id_list = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
            if len(id_list) == 1:
                # Evento directo: la Lambda lee id/alerta_id desde body JSON.
                obtener_payload = {"body": json.dumps({"id": id_list[0]})}
        _log_step("RUN", f"Invocando Lambda obtener_alertas={obtener_name}.")
        obtener_body = _invoke_lambda(
            client,
            name=obtener_name,
            payload=obtener_payload,
            trace=invoke_trace,
            trace_kind="rag_lmbd_obtener_alertas",
            trace_alerta_id=None,
        )
        alertas = obtener_body.get("alertas")
        if not isinstance(alertas, list):
            raise RuntimeError(
                f"Respuesta inesperada de {obtener_name}: esperaba .alertas; "
                f"claves={list(obtener_body.keys())}"
            )
        _log_step("RUN", f"obtener_alertas devolvió {len(alertas)} alerta(s).")

    if args.ids:
        ids = {int(x) for x in args.ids.split(",")}
        alertas = [a for a in alertas if a.get("id") in ids]
        _log_step("RUN", f"Filtro --ids aplicado: quedan {len(alertas)} alerta(s).")

    max_sd: float = args.max_semantic_distance
    retrieval_limit: int | None = args.retrieval_limit
    fb_n: int | None = args.semantic_fallback_top_n
    literal_kw = getattr(args, "literal_keyword_overlap", True)
    literal_kw_len = int(getattr(args, "literal_keyword_min_length", 3))
    exact_kw_filter = not getattr(args, "no_exact_chunk_keyword_filter", False)
    exact_sub_len = int(getattr(args, "exact_keyword_substantive_min_len", 5))
    exact_kw_mode = str(getattr(args, "exact_chunk_keywords_mode", "any"))

    base_meta: dict[str, Any] = {
        "obtener_alertas_lambda": obtener_name,
        "query_lambda": query_name,
        "aws_profile": args.profile or None,
        "aws_region": args.region,
        "max_semantic_distance": max_sd,
        "retrieval_limit": retrieval_limit,
        "literal_keyword_overlap": literal_kw,
        "literal_keyword_min_length": literal_kw_len,
        "exact_chunk_keyword_filter": exact_kw_filter,
        "exact_keyword_substantive_min_len": exact_sub_len,
        "exact_chunk_keywords_mode": exact_kw_mode,
        "json_incluye_alertas_sin_match": bool(getattr(args, "include_zero_chunk_resultados", False)),
        "query_parallel_workers": int(getattr(args, "parallel", 10)),
        "lambda_invoke_read_timeout_seconds": read_to,
    }
    if sim_q:
        base_meta["obtener_alertas_skipped"] = True
        base_meta["simulated_alert_query"] = sim_q
        base_meta["simulated_alerta_id"] = int(getattr(args, "simulate_alerta_id", 900001))
    if fb_n is not None:
        base_meta["semantic_fallback_top_n"] = fb_n

    ca_start_str: str | None = None
    ca_end_str: str | None = None
    explicit = getattr(args, "created_at_explicit", None)
    if not args.no_created_at_filter:
        if isinstance(explicit, tuple) and len(explicit) == 2:
            ca_start_str, ca_end_str = explicit[0], explicit[1]
            base_meta["created_at_explicit_range"] = True
            base_meta["created_at_start"] = ca_start_str
            base_meta["created_at_end"] = ca_end_str
            base_meta["created_at_boundary_note"] = (
                "La Lambda usa sólo día civil UTC: el primer instante efectivo es 00:00:00Z de "
                f"{ca_start_str} (pedir corte intra-día p.ej. 04:50:04 todavía no está en SQL)."
            )
        else:
            ca_start_str, ca_end_str = utc_created_at_window_dates(span_days=args.created_at_span_days)
            base_meta["created_at_span_days"] = args.created_at_span_days
            base_meta["created_at_start"] = ca_start_str
            base_meta["created_at_end"] = ca_end_str
    else:
        base_meta["created_at_filter"] = "off"
    _log_step(
        "RUN",
        f"Ventana created_at={base_meta.get('created_at_start', 'off')}..{base_meta.get('created_at_end', 'off')}",
    )

    if args.corridas_list:
        corridas_out: list[dict[str, Any]] = []
        for label, path in args.corridas_list:
            _log_step("RUN", f"Corrida '{label}' usando map={path}")
            fm = load_fuente_map(path, None)
            results, errors = _run_query_workers(
                client=client,
                alertas=alertas,
                fm=fm,
                query_name=query_name,
                bucket=args.s3_bucket or None,
                max_semantic_distance=max_sd,
                retrieval_limit=retrieval_limit,
                semantic_fallback_top_n=fb_n,
                literal_keyword_overlap=literal_kw,
                literal_keyword_min_length=literal_kw_len,
                exact_chunk_keyword_filter=exact_kw_filter,
                exact_keyword_substantive_min_len=exact_sub_len,
                exact_chunk_keywords_mode=exact_kw_mode,
                parallel=args.parallel,
                created_at_start=ca_start_str,
                created_at_end=ca_end_str,
                include_full_chunk_text=args.include_full_chunk_text,
                invoke_trace=invoke_trace,
            )
            corridas_out.append(
                {
                    "label": label,
                    "map_file": path,
                    "summary": {
                        "total_alertas_filtradas": len(alertas),
                        "matches_ok": len(results),
                        "matches_error": len(errors),
                    },
                    "resultados": results,
                    "errors": errors,
                }
            )
            _log_step("RUN", f"Corrida '{label}' finalizada: ok={len(results)} error={len(errors)}.")
        blob_out: dict[str, Any] = {"meta": base_meta, "corridas": corridas_out}
        if invoke_trace is not None:
            base_meta["lambda_invoke_trace"] = list(invoke_trace.entries)
        return omit_resultados_sin_coincidencia_documental(
            blob_out, include_zero_chunk=bool(args.include_zero_chunk_resultados)
        )

    fm = load_fuente_map(args.fuente_map_file, args.fuente_map_inline)
    _log_step("RUN", "Procesando corrida única.")
    results, errors = _run_query_workers(
        client=client,
        alertas=alertas,
        fm=fm,
        query_name=query_name,
        bucket=args.s3_bucket or None,
        max_semantic_distance=max_sd,
        retrieval_limit=retrieval_limit,
        semantic_fallback_top_n=fb_n,
        literal_keyword_overlap=literal_kw,
        literal_keyword_min_length=literal_kw_len,
        exact_chunk_keyword_filter=exact_kw_filter,
        exact_keyword_substantive_min_len=exact_sub_len,
        exact_chunk_keywords_mode=exact_kw_mode,
        parallel=args.parallel,
        created_at_start=ca_start_str,
        created_at_end=ca_end_str,
        include_full_chunk_text=args.include_full_chunk_text,
        invoke_trace=invoke_trace,
    )
    summary = {
        "total_alertas_filtradas": len(alertas),
        "matches_ok": len(results),
        "matches_error": len(errors),
    }
    _log_step("RUN", f"Fin corrida única: ok={len(results)} error={len(errors)}.")
    blob_out = {"meta": base_meta, "summary": summary, "resultados": results, "errors": errors}
    if invoke_trace is not None:
        base_meta["lambda_invoke_trace"] = list(invoke_trace.entries)
    return omit_resultados_sin_coincidencia_documental(
        blob_out, include_zero_chunk=bool(args.include_zero_chunk_resultados)
    )


def _pop_lambda_invoke_trace(blob: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Extrae y quita ``meta.lambda_invoke_trace`` del blob (sidecar)."""
    meta = blob.get("meta")
    if not isinstance(meta, dict):
        return None
    raw = meta.pop("lambda_invoke_trace", None)
    if raw is None:
        return None
    return raw if isinstance(raw, list) else None


def main(argv: list[str]) -> int:
    _log_step("MAIN", f"Comando: {' '.join(argv)}")
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplo rápido (prod):\n"
            "  python3 scripts/alerts_semantic_matches.py --profile asap_main --env prod \\\n"
            "    --corrida boletin=scripts/boletin_map.json \\\n"
            "    --corrida anmat=scripts/anmat_map.json \\\n"
            "    --max-semantic-distance 0.30 \\\n"
            "    --s3-bucket rag-documents-prod-913123310997 \\\n"
            "    -o alerts_matches.json"
        ),
    )
    p.add_argument(
        "--profile",
        default="asap_main",
        metavar="NAME",
        help=(
            "Perfil AWS CLI (~/.aws/credentials); default asap_main (igual deploy-lambda.sh). "
            'Cadena vacía: omitir profile_name (usa AWS_PROFILE / role / cadena default). Ej: --profile ""'
        ),
    )
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--env", choices=["prod", "qa", "dev"], required=True)
    p.add_argument(
        "--allow-weekend-run",
        action="store_true",
        help=(
            "Ejecutar aunque sea sábado o domingo en America/Argentina/Buenos_Aires. "
            "Sin este flag, el batch no invoca Lambdas ni publica colas (AL-01). "
            "No aplica si --simulate-alert-query está definido."
        ),
    )
    p.add_argument(
        "--trace-lambda-payloads",
        action="store_true",
        help=(
            "Incluir en meta.lambda_invoke_trace la lista ordenada por seq de cada payload enviado a "
            "rag_lmbd_obtener_alertas y rag_lmbd_query (incluye created_at_start/end cuando aplique)."
        ),
    )

    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument(
        "--fuente-map-inline",
        help='JSON objeto: {\"0\":{\"tenant_id\":\"...\",\"agent_id\":\"uuid\"}, \"1\":{...}} '
        '+ opcional s3_tenant_slug; clave especial _default',
    )
    g.add_argument(
        "--fuente-map-file",
        help="Mismo formato que --fuente-map-inline pero en archivo UTF-8",
    )
    p.add_argument(
        "--corrida",
        action="append",
        metavar="LABEL=PATH",
        help="Ejecutar contra este map JSON (repitable). Ej: --corrida boletin=scripts/boletin_map.json",
    )
    p.add_argument(
        "--max-semantic-distance",
        type=parse_max_semantic_distance_cli,
        default=parse_max_semantic_distance_cli("0.32"),
        help=(
            "Umbral coseno (0,2] por invocación; valores MÁS BAJOS ⇒ retriever más estricto "
            "(más cercano a descartar similitud laxa). Entero >2 se divide entre 100 (ej. 32→0.32). "
            "Default 0.32."
        ),
    )
    p.add_argument(
        "--retrieval-limit",
        type=int,
        default=50,
        help=(
            "Cantidad de chunks candidatos que pide a rag_lmbd_query antes de filtros (1..500). "
            "Default 50."
        ),
    )
    p.add_argument(
        "--no-literal-keyword-filter",
        action="store_true",
        help="No aplicar substring de tokens sobre los chunks recuperados ni desactivar fallback vectorial.",
    )
    p.add_argument(
        "--no-exact-chunk-keyword-filter",
        action="store_true",
        help=(
            "Desactiva el filtro POST-Lambda en este script: sólo conserva chunks donde el texto incluye "
            "coincidencia exacta (tokens UTF-8) de al menos una palabra clave de la alerta."
        ),
    )
    p.add_argument(
        "--exact-keyword-substantive-min-len",
        type=int,
        default=5,
        metavar="N",
        help=(
            "Con 2 o más palabras clave, excluye del filtro exacto las keywords con menos de N caracteres "
            "tras NFKC+casefold y sin espacios (ej. «beta», «IV»). Con una sola keyword no aplica filtro por "
            "longitud. 0 lo desactiva. Default 5."
        ),
    )
    p.add_argument(
        "--exact-chunk-keywords-mode",
        choices=("any", "all_corpus"),
        default="any",
        help=(
            "any: cada chunk puede matchear con cualquiera de las keywords (OR). "
            "all_corpus: después del OR cada keyword debe aparecer exacta en algún chunk de la lista (AND)."
        ),
    )
    p.add_argument(
        "--include-zero-chunk-resultados",
        action="store_true",
        help=(
            "Incluye en el JSON todas las alertas aun sin chunks recuperados (con "
            "explicaciones «sin matching»). Por defecto se omiten y sólo quedan filas con match documental."
        ),
    )
    p.add_argument(
        "--literal-keyword-min-length",
        type=int,
        default=3,
        help="Tokens de la consulta con al menos esta longitud (para el filtro literal). Default 3.",
    )
    p.add_argument(
        "--semantic-fallback-top-n",
        type=int,
        default=-1,
        help="Opcional: semantic_fallback_top_n en el payload Lambda. -1 = no enviar (usa env de la función).",
    )
    p.add_argument(
        "--no-created-at-filter",
        action="store_true",
        help="No filtrar por created_at (Lee todo el índice por agente/tenant; más lento/caros los embeds/query).",
    )
    p.add_argument(
        "--created-at-span-days",
        type=int,
        default=2,
        help=(
            "Si no hay --created-at-start/--created-at-end: N días civiles UTC inclusivos terminando "
            "hoy (default 2 = ayer + hoy UTC)."
        ),
    )
    p.add_argument(
        "--created-at-start",
        default="",
        metavar="YYYY-MM-DD",
        help=(
            "Filtro created_at desde este día inclusivo (UTC civil). Sin --created-at-end, hasta hoy UTC. "
            "Anula el cómputo por --created-at-span-days."
        ),
    )
    p.add_argument(
        "--created-at-end",
        default="",
        metavar="YYYY-MM-DD",
        help="Fin inclusivo UTC (requiere --created-at-start). Omitir ese flag usa solo hoy como fin.",
    )
    p.add_argument(
        "--include-full-chunk-text",
        action="store_true",
        help="En context_items agregar chunk_text_full además del preview (sólo cuando hay recuperación).",
    )

    p.add_argument("--s3-bucket", default="", help="Bucket documentos para armar URIs s3:// (opcional)")
    p.add_argument("--obtener-function", default="", help="Override nombre Lambda obtener_alertas")
    p.add_argument("--query-function", default="", help="Override nombre Lambda query")
    p.add_argument(
        "--simulate-alert-query",
        default="",
        metavar="TEXTO",
        help=(
            "No invoca rag_lmbd_obtener_alertas. Simula una alerta con este texto en "
            "palabras_de_busqueda (misma ruta que una alerta real hacia rag_lmbd_query). "
            "Usá con --corrida para tenant/agent_id."
        ),
    )
    p.add_argument(
        "--simulate-alerta-id",
        type=int,
        default=900001,
        help="id de la alerta simulada en el JSON de salida (default 900001).",
    )
    p.add_argument(
        "--simulate-fuente-de-informacion",
        type=int,
        default=0,
        help="fuente_de_informacion de la fila simulada (default 0, suele mapear a _default en el JSON de corrida).",
    )
    p.add_argument(
        "--simulate-nombre-busqueda",
        default="",
        help="nombre_busqueda simulado; si vacío se usa «(simulado)».",
    )
    p.add_argument(
        "--obtener-payload",
        default="",
        help="JSON opcional pasado como evento directo al obtener_alertas (default {}",
    )
    p.add_argument(
        "--ids",
        default="",
        help="Lista de IDs de alerta coma-separados (filtro después de obtener lista)",
    )
    p.add_argument(
        "--parallel",
        type=parse_parallel_workers,
        default=10,
        metavar="N",
        help=(
            "Máximo de hilos concurrentes para invocar rag_lmbd_query (ThreadPoolExecutor). "
            "1 = secuencial. Default 10; reducir si hay throttling o límites de cuenta."
        ),
    )
    p.add_argument(
        "--lambda-read-timeout",
        type=parse_lambda_read_timeout,
        default=420,
        metavar="SEC",
        help=(
            "Timeout HTTP (solo lectura) del cliente boto3 para Lambda.invoke; debe superar la demora típica de "
            "rag_lmbd_query (embed+híbrido+LLM). Default 420s; hasta 900 (tope función Lambda)."
        ),
    )
    p.add_argument("-o", "--output", default="", help="Escribir JSON aquí")
    p.add_argument(
        "--output-trace",
        default="",
        metavar="PATH.json",
        help=(
            "Segundo archivo: sólo {\"lambda_invoke_trace\": [...]}. Requiere --trace-lambda-payloads. "
            "Quita esa clave de meta en el JSON principal (-o o stdout)."
        ),
    )
    p.add_argument(
        "--salida-solo-notificaciones",
        action="store_true",
        help=(
            "Con -o, escribir sólo un array JSON (notificaciones con chunks_count>0, sin wrapper meta/corridas). "
            "Sin este flag, el array va en la clave top-level notificaciones junto con sqs_publish_preview. "
            "En modo solo-notificaciones no se incluye la vista previa de colas."
        ),
    )
    p.add_argument(
        "--notification-template",
        default="",
        metavar="PATH.json",
        help=(
            "JSON opcional: normalmente {\"from\":\"...\"}; remitente SES si la fila busqueda "
            "no define ``from`` en destinatarios. to/subject/nombreUsuario/keywords vienen del item busqueda."
        ),
    )
    p.add_argument(
        "--publish-email-queue",
        action="store_true",
        help=(
            "Tras escribir -o/--output, enviar cada notificación (chunks_count>0) como un mensaje JSON "
            "a la cola SQS (--email-sqs-queue)."
        ),
    )
    p.add_argument(
        "--no-email-queue-send",
        action="store_true",
        help=(
            "Fuerza modo prueba sin envío a SQS, incluso si se pasa --publish-email-queue "
            "(genera archivo JSON pero no publica mensajes)."
        ),
    )
    p.add_argument(
        "--testing-email",
        default="",
        metavar="EMAIL",
        help=(
            "Modo prueba: reemplaza todos los destinatarios en cada resultado (mail, cuenta, destinatarios) "
            "por este correo; las notificaciones y la cola SQS usan sólo este ``to``. "
            "Se guarda en meta.testing_email_override / meta.testing_email."
        ),
    )
    p.add_argument(
        "--email-sqs-queue",
        default="email-sender-record-email-processor-prod",
        metavar="QUEUE_NAME",
        help="Nombre de la cola SQS (solo con --publish-email-queue).",
    )
    p.add_argument(
        "--publish-alert-creation-queue",
        action="store_true",
        help=(
            "Publica mensajes para rag_lmbd_alert_creation en SQS con busqueda_id/disposicion/matched_chunk_ids."
        ),
    )
    p.add_argument(
        "--alert-creation-sqs-queue",
        default="",
        metavar="QUEUE_NAME",
        help="Nombre cola SQS de alert creation (default: rag-alert-creation-<env>).",
    )
    args = p.parse_args(argv)

    corrida_specs: list[tuple[str, str]] = []
    if args.corrida:
        for spec in args.corrida:
            if "=" not in spec:
                p.error(f"--corrida inválido (use LABEL=ruta.json): {spec!r}")
            lab, _, path = spec.partition("=")
            lab, path = lab.strip(), path.strip()
            if not lab or not path:
                p.error(f"--corrida inválido: {spec!r}")
            corrida_specs.append((lab, path))
        if args.fuente_map_file or args.fuente_map_inline:
            p.error("No mezclar --corrida con --fuente-map-file / --fuente-map-inline.")
    elif not args.fuente_map_file and not args.fuente_map_inline:
        p.error(
            "Indicá --corrida LABEL=scripts/....json (una o más) "
            "o bien --fuente-map-file / --fuente-map-inline."
        )

    args.corridas_list = corrida_specs
    args.semantic_fallback_top_n = (
        None if args.semantic_fallback_top_n < 0 else args.semantic_fallback_top_n
    )
    args.literal_keyword_overlap = not args.no_literal_keyword_filter
    if not (2 <= args.literal_keyword_min_length <= 64):
        p.error("--literal-keyword-min-length debe estar entre 2 y 64")
    if not (1 <= args.retrieval_limit <= 500):
        p.error("--retrieval-limit debe estar entre 1 y 500")
    if args.created_at_span_days < 1:
        p.error("--created-at-span-days debe ser >= 1")

    ek = getattr(args, "exact_keyword_substantive_min_len", 5)
    if ek < 0 or ek > 256:
        p.error("--exact-keyword-substantive-min-len debe estar entre 0 y 256.")

    cs = args.created_at_start.strip()
    ce = args.created_at_end.strip()
    setattr(args, "created_at_explicit", None)
    if cs or ce:
        if args.no_created_at_filter:
            p.error("No uses --created-at-start / --created-at-end junto con --no-created-at-filter.")
        if ce and not cs:
            p.error("--created-at-end requiere --created-at-start.")
        try:
            d_s = date.fromisoformat(cs)
            if ce:
                d_e = date.fromisoformat(ce)
            else:
                d_e = datetime.now(timezone.utc).date()
        except ValueError:
            p.error("--created-at-start / --created-at-end deben ser YYYY-MM-DD válidos.")
        if d_e < d_s:
            p.error("created-at-end debe ser >= created-at-start.")
        args.created_at_explicit = (d_s.isoformat(), d_e.isoformat())

    if (args.simulate_alert_query or "").strip() and (args.obtener_payload or "").strip():
        p.error("No mezclar --simulate-alert-query con --obtener-payload (obtener no se llama en modo simulación).")
    if args.publish_email_queue and not str(args.output or "").strip():
        p.error("--publish-email-queue requiere -o/--output.")
    if args.publish_alert_creation_queue and not str(args.output or "").strip():
        p.error("--publish-alert-creation-queue requiere -o/--output.")

    trace_out = (getattr(args, "output_trace", "") or "").strip()
    if trace_out and not getattr(args, "trace_lambda_payloads", False):
        p.error("--output-trace requiere --trace-lambda-payloads.")

    te_arg = (getattr(args, "testing_email", "") or "").strip()
    if te_arg and "@" not in te_arg:
        p.error("--testing-email debe ser un correo que contenga «@».")

    try:
        _log_step("MAIN", "Ejecutando run().")
        out = run(args)
    except ClientError as e:
        _log_step("MAIN", f"AWS ClientError: {e}", level="ERROR")
        return 2
    except Exception as e:
        _log_step("MAIN", f"Error: {e}", level="ERROR")
        return 1

    fb_from = DEFAULT_NOTIFICATION_FALLBACK_FROM
    nt_path = (getattr(args, "notification_template", "") or "").strip()
    if nt_path:
        pth = Path(nt_path).expanduser()
        if not pth.is_file():
            print(f"Error: notification-template no es archivo: {pth}", file=sys.stderr)
            return 2
        with open(pth, encoding="utf-8") as tf:
            extra = json.load(tf)
        if not isinstance(extra, dict):
            print("Error: notification-template debe ser un objeto JSON.", file=sys.stderr)
            return 2
        if extra.get("from"):
            fb_from = str(extra["from"]).strip() or fb_from

    if te_arg:
        apply_testing_email_to_blob(out, te_arg)
        _log_step("MAIN", f"Modo testing-email activo: destinatarios → {te_arg!r}")

    notifs = compute_notificaciones(out, fb_from)
    alert_creation_msgs = compute_alert_creation_messages(out)
    _log_step("MAIN", f"Notificaciones generadas (chunks_count>0): {len(notifs)}")
    _log_step("MAIN", f"Mensajes alert_creation generados: {len(alert_creation_msgs)}")
    email_qn = (args.email_sqs_queue or "").strip() or "email-sender-record-email-processor-prod"
    alert_qn = (args.alert_creation_sqs_queue or "").strip() or f"rag-alert-creation-{args.env}"
    sqs_publish_preview: dict[str, Any] = {
        "email_queue_name": email_qn,
        "alert_creation_queue_name": alert_qn,
        "email_send_message_body_json": [
            json.dumps(n, ensure_ascii=False) for n in notifs
        ],
        "alert_creation_send_message_body_json": [
            json.dumps(m, ensure_ascii=False) for m in alert_creation_msgs
        ],
        "nota": (
            "Cada string es el MessageBody de SQS SendMessage (mismo json.dumps que al publicar). "
            "notificaciones y alert_creation_messages repiten el contenido como objetos."
        ),
    }
    trace_path = (getattr(args, "output_trace", "") or "").strip()
    if trace_path:
        popped = _pop_lambda_invoke_trace(out)
        trace_blob = {"lambda_invoke_trace": list(popped) if popped else []}
        _log_step("MAIN", f"Escribiendo trazas Lambda en {trace_path}")
        with open(trace_path, "w", encoding="utf-8") as tf:
            tf.write(json.dumps(trace_blob, indent=2, ensure_ascii=False))
    if getattr(args, "salida_solo_notificaciones", False):
        text = json.dumps(notifs, indent=2, ensure_ascii=False)
    else:
        out["notificaciones"] = notifs
        out["alert_creation_messages"] = alert_creation_msgs
        out["sqs_publish_preview"] = sqs_publish_preview
        text = json.dumps(out, indent=2, ensure_ascii=False)

    if args.output:
        _log_step("MAIN", f"Escribiendo salida JSON en {args.output}")
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(args.output)
        do_publish_queue = bool(args.publish_email_queue and not args.no_email_queue_send)
        if do_publish_queue:
            try:
                # AL-02: Conectar a PostgreSQL para verificar duplicados
                pg_conn = _connect_to_postgres()
                if pg_conn is None:
                    _log_step(
                        "DEDUP",
                        "PostgreSQL no disponible - enviando notificaciones sin verificar duplicados",
                        level="WARNING",
                    )
                else:
                    _log_step("DEDUP", "Verificando duplicados en alert_emails_sent...")

                # AL-02: Filtrar notificaciones duplicadas
                notifs_filtered, duplicates_count = filter_duplicate_notifications(notifs, pg_conn)

                if duplicates_count > 0:
                    _log_step(
                        "DEDUP",
                        f"Duplicados detectados: {duplicates_count} notificaciones omitidas",
                        level="WARNING",
                    )

                # Cerrar conexión
                if pg_conn is not None:
                    try:
                        pg_conn.close()
                    except Exception:
                        pass

                qn = (args.email_sqs_queue or "").strip() or "email-sender-record-email-processor-prod"
                _log_step("MAIN", f"Publicando notificaciones en SQS queue={qn}")
                n_sent = publish_notificaciones_to_sqs(
                    notifs_filtered,  # AL-02: Usar notificaciones filtradas
                    queue_name=qn,
                    session=_session(args.profile, args.region),
                )
                _log_step(
                    "MAIN",
                    f"SQS publicados: {n_sent} mensaje(s) → cola «{qn}» "
                    f"(originales: {len(notifs)}, duplicados: {duplicates_count})",
                )
            except ClientError as e:
                _log_step("MAIN", f"AWS ClientError (SQS): {e}", level="ERROR")
                return 4
        elif args.publish_email_queue and args.no_email_queue_send:
            _log_step("MAIN", "Modo prueba activo: se omite publicación a SQS (--no-email-queue-send).")

        if bool(args.publish_alert_creation_queue and not args.no_email_queue_send):
            try:
                qn_alert = (args.alert_creation_sqs_queue or "").strip() or f"rag-alert-creation-{args.env}"
                _log_step("MAIN", f"Publicando alert_creation en SQS queue={qn_alert}")
                n_alert = _publish_json_messages_to_sqs(
                    alert_creation_msgs,
                    queue_name=qn_alert,
                    session=_session(args.profile, args.region),
                )
                _log_step("MAIN", f"SQS alert_creation publicados: {n_alert} mensaje(s) → cola «{qn_alert}»")
            except ClientError as e:
                _log_step("MAIN", f"AWS ClientError (SQS alert_creation): {e}", level="ERROR")
                return 5
    else:
        print(text)
    def _has_any_errors(blob: dict[str, Any]) -> bool:
        if blob.get("errors"):
            return True
        for c in blob.get("corridas", []):
            if c.get("errors"):
                return True
        return False

    code = 0 if not _has_any_errors(out) else 3
    _log_step("MAIN", f"Fin ejecución exit_code={code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

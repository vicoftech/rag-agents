import base64
import json
import os
import boto3
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

# AWS Session (boto3 cliente S3). En Lambda el runtime define ACCESS_KEY/SECRET y
# SESSION_TOKEN para el rol; no pasar solo id+secret sin session token (S3: InvalidAccessKeyId).
session_args = {'region_name': os.getenv('AWS_REGION', 'us-east-1')}
if (
    os.getenv('AWS_ACCESS_KEY_ID')
    and os.getenv('AWS_SECRET_ACCESS_KEY')
    and not os.getenv('AWS_SESSION_TOKEN')
):
    session_args.update(
        {
            'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
            'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY'),
        }
    )

# Environment variables
BOLETIN_BASE_URL = os.getenv('BOLETIN_BASE_URL', 'https://www.boletinoficial.gob.ar')
DEFAULT_SECTION = os.getenv('DEFAULT_SECTION', 'primera')
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))
BOLETIN_TZ = os.getenv('BOLETIN_TZ', 'America/Argentina/Buenos_Aires')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', '').strip()
S3_STAGING_PREFIX = os.getenv('S3_STAGING_PREFIX', 'staging/bolinks-ingest').strip().strip('/')

# Boletín Oficial: sólo secciones I, II y III (primera, segunda, tercera). No hay cuarta en este flujo.
SECTIONS_IN_ORDER = ("primera", "segunda", "tercera")
VALID_SECTIONS = frozenset(SECTIONS_IN_ORDER)


def resolve_sections(section_param) -> list[str]:
    """Normaliza ``section`` a una lista de secciones válidas (sólo I–III / primera–tercera)."""
    if section_param is None:
        return [DEFAULT_SECTION]
    if section_param == "all":
        return list(SECTIONS_IN_ORDER)
    if isinstance(section_param, list):
        if not section_param:
            raise ValueError("Lista de secciones vacía.")
        invalid = set(section_param) - VALID_SECTIONS
        if invalid:
            raise ValueError(
                f"Secciones inválidas: {sorted(invalid)}. Válidas: {sorted(VALID_SECTIONS)}"
            )
        return [str(s) for s in section_param]
    if isinstance(section_param, str):
        if section_param not in VALID_SECTIONS:
            raise ValueError(
                f"Sección inválida: {section_param!r}. Válidas: {sorted(VALID_SECTIONS)} o 'all'"
            )
        return [section_param]
    raise ValueError(f"Tipo inválido para section: {type(section_param).__name__}")


def _received_params_for_output(body: dict) -> dict:
    """Eco de la invocación para s3writer cuando la SFN sólo pasa ``bolinks_output``."""
    return {
        "date": body.get("date"),
        "section": body.get("section"),
        "tenant_id": body.get("tenant_id"),
        "agent_id": body.get("agent_id"),
    }


def _today_yyyymmdd_boletin_tz() -> str:
    """Hoy en YYYYMMDD según BOLETIN_TZ (CD-01 / AL-01)."""
    return datetime.now(ZoneInfo(BOLETIN_TZ)).strftime("%Y%m%d")


def resolve_date_default_today(date_raw) -> tuple[str | None, str | None]:
    """Usa HOY (zona BOLETIN_TZ) como default si no se pasa fecha."""
    if date_raw is None or (isinstance(date_raw, str) and not str(date_raw).strip()):
        return _today_yyyymmdd_boletin_tz(), None
    return normalize_date_to_yyyymmdd(str(date_raw).strip())


def normalize_date_to_yyyymmdd(date_str: str | None) -> tuple[str | None, str | None]:
    """
    Devuelve (YYYYMMDD, None) o (None, mensaje de error).
    Acepta YYYYMMDD o YYYY-MM-DD (como envía la Step Function / el invoker).
    """
    if not date_str:
        yesterday = datetime.now() - timedelta(days=1)
        return yesterday.strftime("%Y%m%d"), None
    s = str(date_str).strip()
    if len(s) == 8 and s.isdigit():
        return s, None
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            return datetime.strptime(s, "%Y-%m-%d").strftime("%Y%m%d"), None
        except ValueError:
            return None, f"Fecha inválida: {date_str!r}"
    return None, (
        f"Formato de fecha no soportado: {date_str!r}. "
        "Usá YYYYMMDD o YYYY-MM-DD."
    )


# Headers para simular un navegador real
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-AR,es;q=0.8,en-US;q=0.5,en;q=0.3',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

def _extract_pdf_base64_from_download_response(response: requests.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        print(
            f"download_section: respuesta no JSON (status={response.status_code}): "
            f"{response.text[:500]!r}"
        )
        return None
    if not isinstance(data, dict):
        return None
    b64 = data.get("pdfBase64") or data.get("pdf_base64")
    if b64:
        return str(b64)
    return None


def _put_pdf_staging_s3(target_date: str, seccion: str, pdf_bytes: bytes) -> str | None:
    """Evita pasar PDF por JSON de Step Functions (límite de tamaño)."""
    if not S3_BUCKET_NAME:
        print(
            "S3_BUCKET_NAME no configurado en bolinks: "
            "definir en Terraform para fechas históricas (staging S3)."
        )
        return None
    key = f"{S3_STAGING_PREFIX}/{target_date}/{seccion}.pdf"
    try:
        boto3.client("s3", **session_args).put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
            ServerSideEncryption="AES256",
        )
        return f"s3://{S3_BUCKET_NAME}/{key}"
    except Exception as e:
        print(f"Error subiendo PDF histórico a staging S3 {key!r}: {e}")
        return None


def _edition_pdf_via_cdn_html(
    html: str, seccion: str, target_date: str, session: requests.Session
) -> list[dict]:
    """Edición del día: enlace CDN en HTML (CD-01)."""
    soup = BeautifulSoup(html, "html.parser")
    edition_re = re.compile(
        r"https://s3\.arsat\.com\.ar/cdn-bo-001/pdf-del-dia/"
        + re.escape(seccion)
        + r"\.pdf",
        re.IGNORECASE,
    )
    pdf_url: str | None = None
    m = edition_re.search(html)
    if m:
        pdf_url = m.group(0)
    else:
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "pdf-del-dia" not in href.lower():
                continue
            if f"/{seccion}.pdf" not in href.lower() and not href.lower().endswith(
                f"{seccion}.pdf"
            ):
                continue
            if href.startswith("http"):
                pdf_url = href
            else:
                pdf_url = f"{BOLETIN_BASE_URL.rstrip('/')}/{href.lstrip('/')}"
            break

    if not pdf_url:
        print(
            f"No se encontró enlace CDN pdf-del-dia para sección {seccion!r} (modo hoy)."
        )
        return []

    out: list[dict] = []
    try:
        response = session.head(
            pdf_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                ),
            },
            timeout=10,
            allow_redirects=True,
        )
        content_type = response.headers.get("content-type", "").lower()
        if "application/pdf" in content_type:
            out.append(
                {
                    "url": pdf_url,
                    "section": seccion,
                    "date": target_date,
                    "source": "boletin_edition_cdn",
                }
            )
            print(f"Added edition PDF (CDN): {pdf_url}")
        else:
            print(
                f"Skipping edition link (not PDF Content-Type): {pdf_url} "
                f"(Content-Type: {content_type})"
            )
    except requests.RequestException as e:
        print(f"Error checking edition PDF link {pdf_url}: {e}")

    return out


def _edition_pdf_via_post(
    session: requests.Session, seccion: str, target_date: str
) -> list[dict]:
    """Fecha histórica: POST /pdf/download_section → JSON + Base64 (CD-01)."""
    base = BOLETIN_BASE_URL.rstrip("/")
    post_url = f"{base}/pdf/download_section"
    referer = f"{base}/seccion/{seccion}"
    r = session.post(
        post_url,
        data={"nombreSeccion": seccion},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
        },
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code != 200:
        print(f"download_section: HTTP {r.status_code} para {seccion!r}")
        return []

    b64 = _extract_pdf_base64_from_download_response(r)
    if not b64:
        print(f"download_section: sin pdfBase64 para {seccion!r} fecha {target_date}")
        return []

    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception as e:
        print(f"download_section: Base64 inválido: {e}")
        return []

    if not raw.startswith(b"%PDF"):
        print(
            "download_section: contenido decodificado no parece PDF "
            f"(primeros bytes: {raw[:12]!r})"
        )
        return []

    s3_url = _put_pdf_staging_s3(target_date, seccion, raw)
    if not s3_url:
        return []

    return [
        {
            "url": s3_url,
            "section": seccion,
            "date": target_date,
            "source": "boletin_edition_post",
        }
    ]


def get_pdf_links(target_date: str, seccion: str = "primera"):
    """
    PDF de **edición completa** por sección y fecha (YYYYMMDD).

    - **Hoy** (calendario BOLETIN_TZ): enlace CDN `pdf-del-dia` en HTML de `/seccion/...`.
    - **Histórico**: `POST /pdf/download_section` con sesión ya fijada por
      `GET /edicion/actualizar/{DD-MM-YYYY}`; el PDF se sube a staging en S3 y se
      devuelve una URL `s3://...` para s3writer (evita payload enorme en la SFN).
    """
    if len(target_date) == 8:
        formatted_date = f"{target_date[6:8]}-{target_date[4:6]}-{target_date[:4]}"
    else:
        print("La fecha debe estar en formato YYYYMMDD (ej. 20260317)")
        return []

    print(
        f"Obteniendo boletín (PDF edición completa) para la fecha: {formatted_date}, "
        f"sección {seccion}..."
    )

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
        }
    )

    update_url = f"{BOLETIN_BASE_URL.rstrip('/')}/edicion/actualizar/{formatted_date}"
    res = session.get(update_url, timeout=REQUEST_TIMEOUT)

    if res.status_code != 200:
        print("Error al actualizar la fecha en el servidor.")
        return []

    res_seccion = session.get(
        f"{BOLETIN_BASE_URL.rstrip('/')}/seccion/{seccion}",
        timeout=REQUEST_TIMEOUT,
    )
    if res_seccion.status_code != 200:
        print(f"Error al obtener la sección {seccion}: HTTP {res_seccion.status_code}")
        return []

    html = res_seccion.text
    is_today = target_date == _today_yyyymmdd_boletin_tz()

    if is_today:
        found = _edition_pdf_via_cdn_html(html, seccion, target_date, session)
    else:
        found = _edition_pdf_via_post(session, seccion, target_date)

    print(f"Found {len(found)} edition PDF(s) for section '{seccion}'")
    return found

def handler(event, context):
    """Lambda handler: extrae enlaces PDF del Boletín Oficial por fecha y sección(es)."""
    CORS_HEADERS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "OPTIONS,POST,GET",
    }

    http_method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod")

    if http_method == "OPTIONS":
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json", **CORS_HEADERS},
            "body": "",
        }

    try:
        if http_method:
            body = json.loads(event.get("body") or "{}")
        else:
            body = event

        try:
            sections = resolve_sections(body.get("section"))
        except ValueError as e:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"success": False, "message": str(e)}),
            }

        date_str, date_err = resolve_date_default_today(body.get("date"))
        if date_err:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps(
                    {
                        "success": False,
                        "message": date_err,
                        "pdf_links": {},
                    }
                ),
            }

        try:
            date_obj = datetime.strptime(date_str, "%Y%m%d")
        except ValueError as e:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps(
                    {
                        "success": False,
                        "message": f"Fecha inválida: {date_str}",
                        "pdf_links": {},
                        "error": str(e),
                    }
                ),
            }

        if date_obj.weekday() in (5, 6):
            print(
                f"Date {date_str} is weekend ({date_obj.strftime('%A')}), "
                "returning empty PDF links"
            )
            result = {
                "success": True,
                "message": (
                    f"No hay boletín (fin de semana): {date_str} "
                    f"({date_obj.strftime('%A')})"
                ),
                "date": date_str,
                "day_of_week": date_obj.strftime("%A"),
                "is_weekend": True,
                "sections_processed": [],
                "sections_failed": {},
                "pdf_links": {},
                "totals": {"total": 0},
                "timestamp": datetime.now().isoformat(),
                "received_params": _received_params_for_output(body),
            }
        else:
            print(
                f"Date {date_str} is weekday ({date_obj.strftime('%A')}), "
                f"extracting PDF links for sections: {sections}"
            )
            pdf_links: dict[str, list] = {}
            sections_failed: dict[str, str] = {}

            for section in sections:
                try:
                    pdf_links[section] = get_pdf_links(date_str, section)
                except Exception as e:
                    sections_failed[section] = str(e)
                    print(f"ERROR procesando sección {section!r}: {e}")

            totals = {s: len(links) for s, links in pdf_links.items()}
            totals["total"] = sum(v for k, v in totals.items() if k != "total")

            all_ok = len(sections_failed) == 0
            result = {
                "success": all_ok,
                "message": (
                    f"Procesadas {len(pdf_links)} secciones, {totals['total']} PDFs encontrados"
                ),
                "date": date_str,
                "day_of_week": date_obj.strftime("%A"),
                "is_weekend": False,
                "sections_processed": list(pdf_links.keys()),
                "sections_failed": sections_failed,
                "pdf_links": pdf_links,
                "totals": totals,
                "timestamp": datetime.now().isoformat(),
                "received_params": _received_params_for_output(body),
            }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json", **CORS_HEADERS},
            "body": json.dumps(result),
        }

    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json", **CORS_HEADERS},
            "body": json.dumps({"error": "Invalid JSON in request body"}),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json", **CORS_HEADERS},
            "body": json.dumps({"error": f"Internal server error: {str(e)}"}),
        }


if __name__ == "__main__":
    import sys

    # Ejemplos locales; el ZIP de prod se actualiza vía deploy-lambdas (paths apps/rag_lmbd_*).
    if len(sys.argv) > 1 and sys.argv[1] == "all":
        print(handler({"date": "20260408", "section": "all"}, None))
    else:
        print(handler({"date": "20260408", "section": "primera"}, None))

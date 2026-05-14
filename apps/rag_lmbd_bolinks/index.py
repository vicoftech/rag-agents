import json
import os
import boto3
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

# AWS Session
session_args = {'region_name': os.getenv('AWS_REGION', 'us-east-1')}
if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
    session_args.update({
        'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
        'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY')
    })

# Environment variables
BOLETIN_BASE_URL = os.getenv('BOLETIN_BASE_URL', 'https://www.boletinoficial.gob.ar')
DEFAULT_SECTION = os.getenv('DEFAULT_SECTION', 'primera')
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))

VALID_SECTIONS = frozenset({"primera", "segunda", "tercera"})


def resolve_sections(section_param) -> list[str]:
    """Normaliza el parámetro section a una lista de secciones válidas."""
    if section_param is None:
        return [DEFAULT_SECTION]
    if section_param == "all":
        return sorted(VALID_SECTIONS)
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


def resolve_date_default_today(date_raw) -> tuple[str | None, str | None]:
    """Usa HOY como default si no se pasa fecha (no modifica normalize_date_to_yyyymmdd)."""
    if date_raw is None or (isinstance(date_raw, str) and not str(date_raw).strip()):
        return datetime.now().strftime("%Y%m%d"), None
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

def get_pdf_links(target_date: str, seccion: str = 'primera'):
    """
    Devuelve el/los PDF(s) de **edición completa** de la sección para la fecha dada
    (un solo archivo agregado por sección en CDN Arsat), no los PDFs por aviso.

    Flujo: sesión con fecha → GET /seccion/{seccion} → enlace pdf-del-dia/{seccion}.pdf
    en el HTML. Los avisos individuales viven en /pdf/aviso/... y no se listan aquí.

    Formato de parametro fecha: YYYYMMDD
    """
    if len(target_date) == 8:
        formatted_date = f"{target_date[6:8]}-{target_date[4:6]}-{target_date[:4]}"
    else:
        print("La fecha debe estar en formato YYYYMMDD (ej. 20260317)")
        return []

    print(f"Obteniendo boletín (PDF edición completa) para la fecha: {formatted_date}, sección {seccion}...")

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })

    update_url = f'{BOLETIN_BASE_URL.rstrip("/")}/edicion/actualizar/{formatted_date}'
    res = session.get(update_url, timeout=REQUEST_TIMEOUT)

    if res.status_code != 200:
        print("Error al actualizar la fecha en el servidor.")
        return []

    res_seccion = session.get(
        f'{BOLETIN_BASE_URL.rstrip("/")}/seccion/{seccion}',
        timeout=REQUEST_TIMEOUT,
    )
    if res_seccion.status_code != 200:
        print(f"Error al obtener la sección {seccion}: HTTP {res_seccion.status_code}")
        return []

    html = res_seccion.text
    soup = BeautifulSoup(html, 'html.parser')

    # PDF único de la sección (edición del día): CDN Boletín en página de sección
    edition_re = re.compile(
        r'https://s3\.arsat\.com\.ar/cdn-bo-001/pdf-del-dia/'
        + re.escape(seccion)
        + r'\.pdf',
        re.IGNORECASE,
    )
    pdf_url: str | None = None
    m = edition_re.search(html)
    if m:
        pdf_url = m.group(0)
    else:
        for link in soup.find_all('a', href=True):
            href = link['href']
            if 'pdf-del-dia' not in href.lower():
                continue
            if f'/{seccion}.pdf' not in href.lower() and not href.lower().endswith(f'{seccion}.pdf'):
                continue
            if href.startswith('http'):
                pdf_url = href
            else:
                pdf_url = f"{BOLETIN_BASE_URL.rstrip('/')}/{href.lstrip('/')}"
            break

    if not pdf_url:
        print(f"No se encontró enlace a PDF de edición completa (pdf-del-dia) para sección {seccion!r}.")
        return []

    pdf_links_dict: list[dict] = []
    try:
        response = requests.head(
            pdf_url,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36'
                ),
            },
            timeout=10,
            allow_redirects=True,
        )
        content_type = response.headers.get('content-type', '').lower()
        if 'application/pdf' in content_type:
            pdf_links_dict.append(
                {'url': pdf_url, 'section': seccion, 'date': target_date}
            )
            print(f"Added edition PDF: {pdf_url}")
        else:
            print(
                f"Skipping edition link (not PDF Content-Type): {pdf_url} "
                f"(Content-Type: {content_type})"
            )
    except requests.RequestException as e:
        print(f"Error checking edition PDF link {pdf_url}: {e}")

    print(f"Found {len(pdf_links_dict)} edition PDF link(s) for section '{seccion}'")
    return pdf_links_dict

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

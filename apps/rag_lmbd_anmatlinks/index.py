import json
import os
import socket
import time
from datetime import datetime
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from lib.lambda_chromium import try_sparticuz_launch_config

# URL base del BuscaDispo (sin barra final); override si ANMAT cambia el host
DEFAULT_ANMAT_ORIGIN = "https://buscadispo.anmat.gob.ar"


def _anmat_origin() -> str:
    return os.environ.get("ANMAT_BASE_URL", DEFAULT_ANMAT_ORIGIN).rstrip("/")


def _format_ip_for_chromium_map(ip: str) -> str:
    """
    IPv6 en --host-resolver-rules debe ir entre corchetes; si no, los ':' rompen el parser
    y Chromium ignora el MAP → vuelve DNS propio → ERR_NAME_NOT_RESOLVED intermitente.
    """
    if ":" in ip:
        return f"[{ip}]"
    return ip


def _resolve_ip_for_host(hostname: str) -> str | None:
    """
    Resuelve una IP usable para --host-resolver-rules. Reintenta porque en Lambda
    el resolver del runtime a veces devuelve timeout / lista vacía de forma intermitente
    (mismo orden de magnitud que "DNS secundario" o caché fría).
    """
    max_tries = int(os.environ.get("ANMAT_DNS_MAX_ATTEMPTS", "8"))
    base_delay = float(os.environ.get("ANMAT_DNS_RETRY_DELAY_SEC", "0.35"))

    def _try_family(family: int) -> str | None:
        infos = socket.getaddrinfo(hostname, 443, family, socket.SOCK_STREAM)
        if not infos:
            return None
        return infos[0][4][0]

    ipv4_only = os.environ.get("ANMAT_RESOLVER_IPV4_ONLY", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    families: list[tuple[int, str]] = [(socket.AF_INET, "A")]
    if not ipv4_only:
        families.append((socket.AF_INET6, "AAAA"))

    last_err: OSError | None = None
    for attempt in range(max_tries):
        for family, label in families:
            try:
                ip = _try_family(family)
                if ip:
                    if attempt > 0:
                        print(
                            f"DNS {label} para {hostname}: {ip} "
                            f"(intento {attempt + 1}/{max_tries})"
                        )
                    return ip
            except OSError as e:
                last_err = e
                print(
                    f"DNS ({label}) {hostname} intento {attempt + 1}/{max_tries}: {e}"
                )
        if attempt < max_tries - 1:
            time.sleep(base_delay * (1.35**attempt))
    if last_err:
        print(f"DNS agotado para {hostname}: último error {last_err}")
    return None


def _resolve_ip_for_host_v6_only(hostname: str) -> str | None:
    """Sólo AAAA, para fallback cuando ANMAT_RESOLVER_IPV4_ONLY y no hay registro A."""
    max_tries = int(os.environ.get("ANMAT_DNS_MAX_ATTEMPTS", "8"))
    base_delay = float(os.environ.get("ANMAT_DNS_RETRY_DELAY_SEC", "0.35"))
    last_err: OSError | None = None
    for attempt in range(max_tries):
        try:
            infos = socket.getaddrinfo(
                hostname, 443, socket.AF_INET6, socket.SOCK_STREAM
            )
            if infos:
                ip = infos[0][4][0]
                print(f"DNS AAAA (fallback) para {hostname}: {ip}")
                return ip
        except OSError as e:
            last_err = e
            print(
                f"DNS (AAAA fallback) {hostname} intento {attempt + 1}/{max_tries}: {e}"
            )
        if attempt < max_tries - 1:
            time.sleep(base_delay * (1.35**attempt))
    if last_err:
        print(f"DNS AAAA fallback agotado para {hostname}: {last_err}")
    return None


def _chromium_host_resolver_rule(hostname: str) -> str | None:
    """
    Fuerza MAP host->IP para Chromium. Sin esta regla, Chromium hace DNS propio
    y en Lambda suele coincidir con fallos intermitentes (ERR_NAME_NOT_RESOLVED).
    """
    forced = os.environ.get("ANMAT_FORCED_RESOLVER_IP", "").strip()
    if forced:
        mapped = _format_ip_for_chromium_map(forced)
        rule = f"MAP {hostname} {mapped}"
        print(f"Chromium host-resolver-rules: {rule} (ANMAT_FORCED_RESOLVER_IP)")
        return rule

    ip = _resolve_ip_for_host(hostname)
    if not ip:
        ipv4_only = os.environ.get("ANMAT_RESOLVER_IPV4_ONLY", "true").lower() in (
            "1",
            "true",
            "yes",
        )
        if ipv4_only:
            # Reintento sólo AAAA con literal bien formado (sitios sólo-IPv6)
            ip = _resolve_ip_for_host_v6_only(hostname)
    if not ip:
        print(
            f"ADVERTENCIA: no se pudo resolver {hostname}; Chromium usará DNS interno "
            "(mayor riesgo de ERR_NAME_NOT_RESOLVED)."
        )
        return None
    mapped = _format_ip_for_chromium_map(ip)
    rule = f"MAP {hostname} {mapped}"
    print(f"Chromium host-resolver-rules: {rule}")
    return rule


def _merge_resolver_arg(chromium_args: list, origin: str) -> list:
    host = urlparse(origin).hostname
    if not host:
        return chromium_args
    rule = _chromium_host_resolver_rule(host)
    if not rule:
        return chromium_args
    out = list(chromium_args)
    out.append(f"--host-resolver-rules={rule}")
    return out


def extraer_fecha_url(url, year, meses):
    """
    Extrae la fecha en formato YYYYMMDD de una URL de ANMAT.
    
    Args:
        url (str): URL del PDF
        year (str): Año de búsqueda como fallback
        meses (dict): Diccionario de meses en español a números
        
    Returns:
        str: Fecha en formato YYYYMMDD
    """
    # Formato URL: .../BuscaDispoPDF/2026/marzo/...
    parts = url.split('/')
    fecha_aviso = f"{year}0101"  # Default fallback
    
    try:
        # Buscar el año (4 dígitos) y el mes en el path
        for i, part in enumerate(parts):
            if part.isdigit() and len(part) == 4 and part.startswith('20'):
                year_from_url = part
                # El mes debería estar después del año
                if i + 1 < len(parts):
                    month_name = parts[i + 1].lower()
                    if month_name in meses:
                        month_num = meses[month_name]
                        fecha_aviso = f"{year_from_url}{month_num}01"
                        break
    except Exception as e:
        print(f"Error extrayendo fecha de URL: {e}")
        fecha_aviso = f"{year}0101"  # Fallback al año de búsqueda
    
    return fecha_aviso


def _pagination_ceiling(total_pages_cap, total_pages_approx):
    """Tope de páginas: parámetro explícito gana sobre el cálculo desde el sitio."""
    if isinstance(total_pages_cap, int) and total_pages_cap > 0:
        return total_pages_cap
    if isinstance(total_pages_approx, int):
        return total_pages_approx
    return None


def scrape_anmat(year, page_start=1, page_end=None, total_pages_cap=None):
    """
    Extrae PDFs de ANMAT para un año específico.
    
    Args:
        year (int): Año a buscar
        page_start (int): Página de inicio (default: 1)
        page_end (int): Página final (None para sin límite)
        total_pages_cap (int|None): Tope máximo de páginas (p. ej. desde Step Function).
            Si se informa, acota has_more y evita seguir más allá aunque el sitio calcule otro total.
    """
    print(f"Iniciando scraping para el año {year}...")
    
    # Mapeo de meses en español a números
    meses = {
        'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
        'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
        'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
    }
    
    exec_path, sparticuz_args = try_sparticuz_launch_config()
    if (not exec_path or not sparticuz_args) and os.environ.get(
        "AWS_EXECUTION_ENV", ""
    ).startswith("AWS_Lambda_"):
        raise RuntimeError(
            "Sparticuz Chromium no encontrado bajo /opt (falta chromium.br). "
            "Revisá la capa Lambda y CHROMIUM_PACK_PATH."
        )

    local_fallback_args = [
        "--disable-features=AsyncDns",
        "--dns-prefetch-disable",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--single-process",
    ]

    with sync_playwright() as p:
        launch_kw = {}
        origin = _anmat_origin()
        if exec_path and sparticuz_args:
            # Sparticuz chrome-headless-shell: args ya incluyen --headless=shell
            launch_kw["executable_path"] = exec_path
            launch_kw["args"] = _merge_resolver_arg(sparticuz_args, origin)
            launch_kw["headless"] = False
        else:
            launch_kw["headless"] = True
            launch_kw["args"] = _merge_resolver_arg(local_fallback_args, origin)

        browser = p.chromium.launch(**launch_kw)
        context = browser.new_context()
        page = context.new_page()

        wait_until = os.environ.get("PLAYWRIGHT_GOTO_WAIT_UNTIL", "domcontentloaded")
        goto_timeout_ms = int(os.environ.get("PLAYWRIGHT_GOTO_TIMEOUT_MS", "120000"))

        # 1. Navegamos a la página
        print("Cargando sitio web...")
        entry_url = f"{origin}/"
        for attempt in range(3):
            try:
                page.goto(
                    entry_url,
                    wait_until=wait_until,
                    timeout=goto_timeout_ms,
                )
                break
            except Exception as e:
                if attempt < 2 and "ERR_NAME_NOT_RESOLVED" in str(e):
                    wait_s = 2**attempt
                    print(
                        f"Reintento {attempt + 1} tras ERR_NAME_NOT_RESOLVED "
                        f"(espera {wait_s}s)..."
                    )
                    time.sleep(wait_s)
                else:
                    raise
        
        # 2. Llenamos el año en el input correspondiente
        page.fill("id=ctl00_MainContent_txtAnioDispo", str(year), timeout=60000)
        
        # 3. Hacemos click en el botón de búsqueda
        print(f"Buscando disposiciones del año {year}...")
        with page.expect_navigation(wait_until="load"):
            page.click("id=ctl00_MainContent_btnBusqueda")
        
        try:
            resultados_texto = page.locator("id=ctl00_MainContent_lblCantFiltrado").inner_text(timeout=5000)
            print(f"Estado: {resultados_texto}")
            
            # Intentar extraer el número del texto "Se encontraron X registros"
            import re
            match = re.search(r'\d+', resultados_texto)
            total_records = int(match.group()) if match else 0
            
            # Calculamos las páginas totales aproximadas (la grilla muestra 100 registros por página)
            total_pages_approx = (total_records // 100) + (1 if total_records % 100 > 0 else 0)
            print(f"El sitio informa un total aproximado de {total_pages_approx} páginas a procesar.")
            
        except Exception:
            print("No se encontró mensaje de cantidad de registros.")
            total_pages_approx = "Desconocido"
            total_records = 0
            
        # Determinar límite de páginas
        if page_end is not None:
            max_paginas = page_end
            print(f"Procesando desde página {page_start} hasta {page_end}")
        else:
            max_paginas = None  # Sin límite, procesar hasta la última página disponible
            print("Procesando hasta la última página disponible")

        if isinstance(total_pages_cap, int) and total_pages_cap > 0:
            if max_paginas is not None:
                max_paginas = min(max_paginas, total_pages_cap)
            print(f"Tope explícito total_pages (parámetro): {total_pages_cap}")
        
        pdf_links = set()
        pdf_links_dict = []
        page_num = page_start
        has_more = True

        if isinstance(total_pages_cap, int) and total_pages_cap > 0 and page_start > total_pages_cap:
            print(
                f"page_start ({page_start}) supera total_pages ({total_pages_cap}); "
                "no hay páginas que procesar."
            )
            browser.close()
            return [], total_pages_approx, total_records, False
        
        # Navegar a la página de inicio si no es la primera
        if page_num > 1:
            print(f"Navegando a página de inicio: {page_num}")
            # Navegar a la página específica haciendo clic en los números de página
            for target_page in range(2, page_num + 1):
                try:
                    next_link = page.locator(f"tr.paginacion a:has-text('{target_page}'), td a:text-is('{target_page}')").first
                    if next_link.count() > 0:
                        with page.expect_navigation(wait_until="load", timeout=60000):
                            next_link.click()
                        print(f"Navegado a página {target_page}")
                    else:
                        # Si no encuentra el número directo, intentar con "..."
                        dots_link = page.locator("td a:text-is('...')").first
                        if dots_link.count() > 0:
                            with page.expect_navigation(wait_until="load", timeout=60000):
                                dots_link.click()
                            print(f"Usando '...' para avanzar hacia página {target_page}")
                except Exception as e:
                    print(f"Error navegando a página {target_page}: {e}")
                    break
        
        while True:
            if max_paginas is not None and page_num > max_paginas:
                print(f"Límite de {max_paginas} páginas alcanzado. Deteniendo scraping.")
                ceiling = _pagination_ceiling(total_pages_cap, total_pages_approx)
                has_more = ceiling is not None and max_paginas < ceiling
                break

            if (
                isinstance(total_pages_cap, int)
                and total_pages_cap > 0
                and page_num > total_pages_cap
            ):
                has_more = False
                break
                
            print(f"Procesando página {page_num}...")
            # Extraemos los links de la tabla actual
            rows = page.locator("a[id*='lnkPDF']").all()
            
            for row in rows:
                href = row.get_attribute("href")
                if href:
                    # Limpiar y formatear la URL
                    clean_href = href.replace("\\", "/")
                    
                    # Asegurar que sea una URL completa
                    if clean_href.startswith("//"):
                        full_url = "https:" + clean_href
                    elif clean_href.startswith("/"):
                        full_url = origin + clean_href
                    elif clean_href.startswith("http"):
                        full_url = clean_href
                    else:
                        full_url = f"{origin}/" + clean_href
                    
                    pdf_links.add(full_url)
                    
                    # Extraer fecha de la URL usando la función auxiliar
                    fecha_aviso = extraer_fecha_url(full_url, year, meses)
                    pdf_links_dict.append({"url": full_url, "date": fecha_aviso, "section": "default"})

            ceiling = _pagination_ceiling(total_pages_cap, total_pages_approx)
            if ceiling is not None and page_num >= ceiling:
                has_more = False
                break
                    
            # Buscamos el elemento span dentro del bloque de paginación que nos dice la pagina actual
            next_page_str = str(page_num + 1)
            
            # Buscamos un enlace con el texto exacto de la siguiente pagina
            next_link = page.locator(f"tr.paginacion a:has-text(' {next_page_str} '), td a:text-is('{next_page_str}')")
            
            if next_link.count() > 0:
                with page.expect_navigation(wait_until="load", timeout=60000):
                    next_link.first.click()
                page_num += 1
            else:
                # A veces el paginador requiere clickear en "..."
                dots_link = page.locator("td a:text-is('...')").last
                if dots_link.count() > 0:
                    with page.expect_navigation(wait_until="load", timeout=60000):
                        dots_link.click()
                    page_num += 1 
                else:
                    # No hay ni mas números ni puntos suspensivos avanzando
                    # Fin real de paginación: no quedan más páginas para este año.
                    has_more = False
                    break
                
        browser.close()
        
    return pdf_links_dict, total_pages_approx, total_records, has_more


def _parse_event_body(event: dict) -> dict:
    """Body de API Gateway (string JSON) o invocación directa con dict."""
    raw = event.get("body")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        return json.loads(raw)
    return {}


def _pick_param(event: dict, body: dict, key: str, default=None):
    """Misma precedencia que year: queryStringParameters → raíz del evento → body."""
    qsp = event.get("queryStringParameters") or {}
    if qsp.get(key) is not None:
        return qsp[key]
    if key in event:
        return event[key]
    return body.get(key, default)


def handler(event, context):
    try:
        body = _parse_event_body(event)

        if event.get("queryStringParameters") and "year" in event["queryStringParameters"]:
            year = event["queryStringParameters"]["year"]
        elif "year" in event:
            year = event["year"]
        elif body.get("year"):
            year = body["year"]
        else:
            year = None

        if not year:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": 'Parámetro "year" es requerido.'}),
            }

        ps = _pick_param(event, body, "page_start", 1)
        pe = _pick_param(event, body, "page_end", None)
        page_start = int(ps) if ps not in (None, "") else 1
        page_end = None if pe in (None, "") else int(pe)

        ptp = _pick_param(event, body, "total_pages", None)
        if ptp in (None, ""):
            total_pages_cap = None
        else:
            try:
                total_pages_cap = int(ptp)
            except (TypeError, ValueError):
                total_pages_cap = None
        if total_pages_cap is not None and total_pages_cap <= 0:
            total_pages_cap = None
        
        # Scraper: un reintento completo si Playwright sigue sin resolver (suele alinearse con
        # resolución intermitente en el mismo invocación, no solo "DNS secundario").
        try:
            links, total_pages, total_records, has_more = scrape_anmat(
                year, page_start, page_end, total_pages_cap
            )
        except Exception as first:
            if "ERR_NAME_NOT_RESOLVED" not in str(first):
                raise
            print("Reintento del scrape tras ERR_NAME_NOT_RESOLVED (espera 3s)...")
            time.sleep(3)
            links, total_pages, total_records, has_more = scrape_anmat(
                year, page_start, page_end, total_pages_cap
            )

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json'
            },
            'body': json.dumps({
                'success': True,
                'timestamp': datetime.now().isoformat(),
                'received_params': {
                    'year': year,
                    'date': f"{year}0101",  # Formato YYYYMMDD (1/1/year)
                    'section': 'default',
                    'page_start': page_start,
                    'page_end': page_end,
                    'total_pages': total_pages_cap,
                },
                'total_records': total_records,
                'total_pages_approx': total_pages,
                'pdfs_collected': len(links),
                'pdf_links': links,
                'has_more': has_more
            })
        }
    except Exception as e:
        print(f"Error procesando: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            })
        }

if __name__ == "__main__":
    # Evento de prueba simulado como si el año viniera en el "queryStringParameters" o "body"
    evento_de_prueba = {
        "year": "2025",  # Puedes cambiar este año
        "page_start": 59,  # Página de inicio
        "page_end": 59  # Página final (None para sin límite)
    }
    
    # Contexto ficticio que exige la estructura Lambda (aunque no lo usemos en el código)
    contexto_de_prueba = {}
    
    print("Iniciando prueba local simulando el evento Lambda...")
    
    # Invocamos la función igual a como Amazon AWS la ejecutaría
    respuesta = handler(evento_de_prueba, contexto_de_prueba)
    
    print("\n--- RESPUESTA DE LA LAMBDA ---")
    print("STATUS CODE:", respuesta.get('statusCode'))
    
    # Imprimimos el body de manera más estética
    if respuesta.get('body'):
        body_parseado = json.loads(respuesta['body'])
        print(json.dumps(body_parseado, indent=4, ensure_ascii=False))
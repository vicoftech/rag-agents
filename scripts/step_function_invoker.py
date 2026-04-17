#!/usr/bin/env python3
"""
Script para invocar Step Function de AWS para procesar años y páginas de ANMAT
"""

import boto3
import json
import time
from datetime import datetime
import sys
import argparse

# Configuración
AWS_REGION = "us-east-1"
AWS_PROFILE = "asap_main"
STEP_FUNCTION_ARN = "arn:aws:states:us-east-1:913123310997:stateMachine:rag-anmat-to-s3writer-qa"

# Rango de años (descendente)
START_YEAR = 2010
END_YEAR = 2010
AGENT_ID = "7c9aa113-ecf2-4449-a955-d91c76e7ee27"
TENANT_ID = "anmat"
MAX_RETRIES_PER_PAGE = 3
# Tope de páginas para el año en curso (None = usar solo lo que calcule el sitio / el scraper)
TOTAL_PAGES = None
MAX_PARALLEL_PAGES = 5

def create_step_function_client():
    """Crear cliente de Step Functions"""
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    return session.client('stepfunctions')

def invoke_step_function(
    sfn_client, year, page_start, page_end, pages_since_reset=0, total_pages=None
):
    """Invocar Step Function con parámetros específicos"""
    
    payload = {
        "year": str(year),
        "page_start": page_start,
        "page_end": page_end,
        "agent_id": AGENT_ID,
        "tenant_id": TENANT_ID,
        "pagesSinceReset": pages_since_reset,
        "total_pages": total_pages,
    }
    
    try:
        response = sfn_client.start_execution(
            stateMachineArn=STEP_FUNCTION_ARN,
            name=f"anmat-{year}-page-{page_start}-{page_end}-{int(time.time())}",
            input=json.dumps(payload)
        )
        
        execution_arn = response['executionArn']
        print(f"✅ Iniciada ejecución para año {year}, páginas {page_start}-{page_end}")
        print(f"   ARN: {execution_arn}")
        
        return execution_arn
        
    except Exception as e:
        print(f"❌ Error invocando Step Function para año {year}: {str(e)}")
        return None

def wait_for_completion(sfn_client, execution_arn, timeout=300):
    """Esperar a que complete la ejecución"""
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            response = sfn_client.describe_execution(
                executionArn=execution_arn
            )
            
            status = response['status']
            
            if status == 'SUCCEEDED':
                print(f"✅ Ejecución completada exitosamente")
                return True
            elif status in ['FAILED', 'TIMED_OUT', 'ABORTED']:
                print(f"❌ Ejecución falló con status: {status}")
                return False
            elif status == 'RUNNING':
                print(f"⏳ Ejecutando... ({int(time.time() - start_time)}s)")
                time.sleep(10)
            else:
                print(f"⚠️ Status desconocido: {status}")
                time.sleep(10)
                
        except Exception as e:
            print(f"❌ Error verificando estado: {str(e)}")
            time.sleep(10)
    
    print(f"⏰ Timeout esperando ejecución")
    return False

def _extract_has_more_from_execution(sfn_client, execution_arn):
    """
    Extrae `has_more` desde la salida del estado RunAnmatlinks.
    En este workflow el output final suele ser el resultado del Map/SQS, no el body
    de la Lambda de scrapeo, por eso hay que leer el historial de eventos.
    """
    response = sfn_client.get_execution_history(
        executionArn=execution_arn,
        maxResults=1000,
        reverseOrder=True,
    )

    for event in response.get("events", []):
        details = event.get("stateEnteredEventDetails")
        if details and details.get("name") == "BuildCtxForFanOut":
            raw_input = details.get("input")
            if not raw_input:
                break
            parsed_input = json.loads(raw_input)
            # BuildCtxForFanOut recibe todo el contexto, incluyendo anmatResponse.
            # El flag real de paginación vive en anmatResponse.data.has_more.
            return (
                parsed_input.get("anmatResponse", {})
                .get("data", {})
                .get("has_more", False)
            )

    raise RuntimeError("No se pudo extraer has_more desde el historial de ejecución")

def process_year(sfn_client, year, start_page=1, total_pages=None):
    """Procesar todas las páginas de un año hasta has_more=false"""
    
    print(f"\n📅 Procesando año {year}")
    print("=" * 50)
    
    page_start = start_page
    page_end = start_page
    has_more = True
    pages_since_reset = 0
    
    while has_more:
        page_processed = False
        execution_arn = None

        for attempt in range(1, MAX_RETRIES_PER_PAGE + 1):
            if attempt > 1:
                wait_seconds = min(30, attempt * 5)
                print(
                    f"🔁 Reintentando año {year}, página {page_start} "
                    f"(intento {attempt}/{MAX_RETRIES_PER_PAGE}) en {wait_seconds}s..."
                )
                time.sleep(wait_seconds)

            # Invocar para el rango de páginas actual
            execution_arn = invoke_step_function(
                sfn_client,
                year,
                page_start,
                page_end,
                pages_since_reset=pages_since_reset,
                total_pages=total_pages,
            )

            if not execution_arn:
                print(
                    f"⚠️ No se pudo iniciar ejecución para año {year}, "
                    f"páginas {page_start}-{page_end}"
                )
                continue

            # Esperar a que complete
            success = wait_for_completion(sfn_client, execution_arn)
            if success:
                # Mantener el contador local alineado al contrato del reset Lambda:
                # if pages_since < 3 -> +1, else -> 0 (se fuerza cold start).
                if pages_since_reset < 3:
                    pages_since_reset += 1
                else:
                    pages_since_reset = 0
                page_processed = True
                break

            print(
                f"⚠️ Falló ejecución para año {year}, páginas {page_start}-{page_end} "
                f"(intento {attempt}/{MAX_RETRIES_PER_PAGE})"
            )

        if not page_processed:
            print(
                f"❌ Agotados los reintentos para año {year}, "
                f"páginas {page_start}-{page_end}"
            )
            return False
        
        # Obtener resultado para verificar has_more
        try:
            has_more = _extract_has_more_from_execution(sfn_client, execution_arn)
            if has_more:
                # Incrementar para el siguiente lote
                page_start = page_end + 1
                page_end = page_start
                print(f"📄 Continuando con página {page_start} (has_more=true)")
            else:
                print(f"🏁 Completado año {year} (has_more=false)")
        except Exception as e:
            print(f"⚠️ Error obteniendo resultado: {str(e)}")
            # Ante duda, cortar para evitar reprocesar siempre la misma página.
            has_more = False
        
        # Pequeña pausa entre ejecuciones
        time.sleep(2)
    
    return True


def process_year_parallel(sfn_client, year, start_page=1, total_pages=0, max_parallel=None):
    """
    Variante que no depende de has_more, pensada para cuando conocemos total_pages.
    Lanza hasta `max_parallel` ejecuciones de Step Functions en paralelo, una por página.
    """
    if total_pages is None or total_pages <= 0:
        print("⚠️ total_pages no informado o inválido; usando flujo secuencial con has_more.")
        return process_year(sfn_client, year, start_page=start_page, total_pages=None)

    if max_parallel is None or max_parallel <= 0:
        max_parallel = MAX_PARALLEL_PAGES

    print(f"\n📅 Procesando año {year} en modo paralelo (hasta {max_parallel} páginas simultáneas)")
    print("=" * 50)

    next_page = start_page
    last_page = total_pages
    pages_since_reset = 0
    active = []  # [{page, arn, attempt}]
    failed_pages = []

    def _launch_page(page_num, attempt, pages_since_reset_local):
        print(f"🚀 Lanzando ejecución para año {year}, página {page_num} (intento {attempt})")
        execution_arn = invoke_step_function(
            sfn_client,
            year,
            page_num,
            page_num,
            pages_since_reset=pages_since_reset_local,
            total_pages=total_pages,
        )
        return execution_arn

    while next_page <= last_page or active:
        # Rellenar el "pool" de ejecuciones activas hasta max_parallel
        while next_page <= last_page and len(active) < max_parallel:
            execution_arn = _launch_page(next_page, attempt=1, pages_since_reset_local=pages_since_reset)
            if not execution_arn:
                print(f"⚠️ No se pudo iniciar ejecución para año {year}, página {next_page}")
                failed_pages.append(next_page)
                next_page += 1
                continue

            # Mantener el contador para el reset Lambda (aproximado, por página lanzada)
            if pages_since_reset < 3:
                pages_since_reset += 1
            else:
                pages_since_reset = 0

            active.append(
                {
                    "page": next_page,
                    "arn": execution_arn,
                    "attempt": 1,
                }
            )
            next_page += 1

        if not active:
            # No hay más páginas por lanzar ni ejecuciones activas
            break

        # Esperar un poco antes de chequear estados
        time.sleep(10)

        still_active = []
        for job in active:
            page = job["page"]
            arn = job["arn"]
            attempt = job["attempt"]

            try:
                resp = sfn_client.describe_execution(executionArn=arn)
                status = resp["status"]
            except Exception as e:
                print(f"⚠️ Error verificando estado de año {year}, página {page}: {e}")
                status = "UNKNOWN"

            if status == "RUNNING":
                still_active.append(job)
            elif status == "SUCCEEDED":
                print(f"✅ Año {year}, página {page} completada")
            elif status in ["FAILED", "TIMED_OUT", "ABORTED", "UNKNOWN"]:
                if attempt < MAX_RETRIES_PER_PAGE:
                    next_attempt = attempt + 1
                    wait_seconds = min(30, next_attempt * 5)
                    print(
                        f"🔁 Reintentando año {year}, página {page} "
                        f"(intento {next_attempt}/{MAX_RETRIES_PER_PAGE}) en {wait_seconds}s..."
                    )
                    time.sleep(wait_seconds)
                    new_arn = _launch_page(page, attempt=next_attempt, pages_since_reset_local=pages_since_reset)
                    if new_arn:
                        still_active.append(
                            {
                                "page": page,
                                "arn": new_arn,
                                "attempt": next_attempt,
                            }
                        )
                        # Actualizar contador de reset de forma aproximada
                        if pages_since_reset < 3:
                            pages_since_reset += 1
                        else:
                            pages_since_reset = 0
                    else:
                        print(f"❌ No se pudo relanzar ejecución para año {year}, página {page}")
                        failed_pages.append(page)
                else:
                    print(
                        f"❌ Agotados los reintentos para año {year}, página {page} "
                        f"(status final: {status})"
                    )
                    failed_pages.append(page)
            else:
                print(f"⚠️ Status desconocido ({status}) para año {year}, página {page}")

        active = still_active

    if failed_pages:
        print(f"❌ Páginas con fallo definitivo en año {year}: {sorted(set(failed_pages))}")
        return False

    print(f"🏁 Completado año {year} en modo paralelo")
    return True


def parse_args():
    """Parsear argumentos CLI"""
    parser = argparse.ArgumentParser(
        description="Invocador de Step Functions para procesamiento ANMAT"
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Página inicial desde la cual comenzar (default: 1)",
    )
    parser.add_argument(
        "--total-pages",
        type=int,
        default=None,
        help="Cantidad máxima de páginas a procesar para el año (opcional; acota has_more)",
    )
    return parser.parse_args()

def main():
    """Función principal"""
    args = parse_args()
    if args.start_page < 1:
        print("❌ --start-page debe ser mayor o igual a 1")
        sys.exit(1)

    print("🚀 Iniciando procesamiento de ANMAT via Step Functions")
    print(f"📍 Región: {AWS_REGION}")
    print(f"👤 Perfil: {AWS_PROFILE}")
    print(f"📊 Rango de años: {START_YEAR} a {END_YEAR}")
    print(f"📄 Página inicial: {args.start_page}")
    effective_total = args.total_pages if args.total_pages is not None else TOTAL_PAGES
    print(f"📑 Tope total_pages (param): {effective_total}")
    if effective_total:
        print(f"🔄 Procesando hasta {MAX_PARALLEL_PAGES} ejecuciones en paralelo")
    else:
        print(f"🔄 Procesando una ejecución a la vez (usa has_more)")
    print("=" * 60)
    
    # Crear cliente de Step Functions
    sfn_client = create_step_function_client()
    
    if not sfn_client:
        print("❌ No se pudo crear cliente de Step Functions")
        sys.exit(1)
    
    # Procesar años en orden descendente
    successful_years = []
    failed_years = []
    
    for year in range(START_YEAR, END_YEAR - 1, -1):
        print(f"\n🎯 Iniciando procesamiento del año {year}")
        if effective_total:
            success = process_year_parallel(
                sfn_client,
                year,
                start_page=args.start_page,
                total_pages=effective_total,
                max_parallel=MAX_PARALLEL_PAGES,
            )
        else:
            success = process_year(
                sfn_client,
                year,
                start_page=args.start_page,
                total_pages=None,
            )
        
        if success:
            successful_years.append(year)
            print(f"✅ Año {year} completado exitosamente")
        else:
            failed_years.append(year)
            print(f"❌ Falló procesamiento del año {year}")
        
        # Pausa entre años
        time.sleep(5)
    
    # Resumen final
    print("\n" + "=" * 60)
    print("📊 RESUMEN FINAL")
    print("=" * 60)
    print(f"✅ Años exitosos: {len(successful_years)}")
    print(f"   {successful_years}")
    print(f"❌ Años fallidos: {len(failed_years)}")
    print(f"   {failed_years}")
    print(f"🏁 Procesamiento completado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()

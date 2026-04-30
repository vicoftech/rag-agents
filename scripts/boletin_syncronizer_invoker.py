#!/usr/bin/env python3
"""
Invoca la Step Function de Boletín por fecha (descendente) y secciones.
Soporta paralelizar días (--parallel-days) y, opcionalmente, secciones (--parallel-sections).

Rango de fechas:
  - Por día: --start-date / --end-date (YYYY-MM-DD), recorrido descendente.
  - Por años calendario completos (1 ene → 31 dic de cada año): --start-year / --end-year
    (p. ej. 2026 y 2016 = años 2016 a 2026, todos los días de cada uno).

Por defecto: producción (cuenta 913, profile asap_main). Usá --env qa para el state machine -qa.
"""

import argparse
import json
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import boto3

# Configuración por defecto
AWS_REGION = "us-east-1"
AWS_PROFILE = "asap_main"
# Cuenta 913: prod gestionado en Terraform: Alerts-BoletinOficialSyncronizer-prod (JSONata, Lambdas -prod)
STEP_FUNCTION_ARN_PROD = (
    "arn:aws:states:us-east-1:913123310997:stateMachine:Alerts-BoletinOficialSyncronizer-prod"
)
STEP_FUNCTION_ARN_QA = (
    "arn:aws:states:us-east-1:913123310997:stateMachine:Alerts-BoletinOficialSyncronizer-qa"
)
STEP_FUNCTION_ARN = STEP_FUNCTION_ARN_PROD

TENANT_ID = "boletin"
# Agente RAG "boletin" en prod (ajustar --agent-id para QA u otros)
AGENT_ID = "05032266-f6e1-48cb-9248-bc116652c7c7"

START_DATE = datetime(2026, 4, 21)
END_DATE = datetime(2025, 4, 1)

SECTIONS = ["primera", "segunda", "tercera", "cuarta"]
MAX_PARALLEL_DAYS = 10

_print_lock = threading.Lock()


def log_progress(msg: str) -> None:
    """Siempre visible (timestamp): sirve para ver que no está colgado."""
    ts = datetime.now().strftime("%H:%M:%S")
    with _print_lock:
        print(f"[{ts}] {msg}", flush=True)


def _log(msg: str, quiet: bool = False) -> None:
    if quiet:
        return
    with _print_lock:
        print(msg, flush=True)


def create_step_function_client(profile_name: str, region_name: str):
    session = boto3.Session(profile_name=profile_name, region_name=region_name)
    return session.client("stepfunctions")


def validate_aws_identity(profile_name: str, region_name: str) -> bool:
    try:
        session = boto3.Session(profile_name=profile_name, region_name=region_name)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        print(f"Identidad AWS válida. Account: {identity.get('Account')}")
        print(f"Caller ARN: {identity.get('Arn')}")
        return True
    except Exception as e:
        print(f"ERROR validando credenciales AWS: {e}")
        return False


def _execution_name(date_str: str, section: str) -> str:
    """Nombre único (límite AWS 80 chars)."""
    slug = date_str.replace("-", "")
    suffix = uuid.uuid4().hex[:12]
    name = f"anmat-{slug}-{section}-{suffix}"
    return name[:80]


def invoke_step_function(
    sfn_client,
    date_str: str,
    section: str,
    tenant_id: str,
    agent_id: str,
    quiet: bool = False,
) -> str | None:
    payload = {
        "date": date_str,
        "section": section,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
    }
    name = _execution_name(date_str, section)
    try:
        response = sfn_client.start_execution(
            stateMachineArn=STEP_FUNCTION_ARN,
            name=name,
            input=json.dumps(payload),
        )
        arn = response["executionArn"]
        log_progress(
            f"SFN START {date_str} {section} "
            f"(thread={threading.current_thread().name})"
        )
        _log(f"  {section.upper()}: {date_str} -> started", quiet)
        _log(f"     {arn}", quiet)
        return arn
    except Exception as e:
        log_progress(f"SFN START ERROR {date_str} {section}: {e}")
        _log(f"  {section.upper()}: ERROR start_execution {e}", quiet)
        return None


def wait_for_completion(
    sfn_client,
    execution_arn: str,
    timeout: int = 900,
    quiet: bool = False,
    *,
    wait_label: str = "",
    progress_interval_sec: float = 15.0,
) -> bool:
    """Espera a la ejecución. Emite log_progress cada progress_interval aunque quiet=True."""
    start = time.time()
    last_progress = 0.0
    label = wait_label or execution_arn.split(":")[-1][:48]
    while time.time() - start < timeout:
        try:
            response = sfn_client.describe_execution(executionArn=execution_arn)
            status = response["status"]
            if status == "SUCCEEDED":
                log_progress(f"SFN OK {label} ({int(time.time() - start)}s)")
                _log("     -> SUCCEEDED", quiet)
                return True
            if status in ("FAILED", "TIMED_OUT", "ABORTED"):
                log_progress(f"SFN {status} {label} ({int(time.time() - start)}s)")
                _log(f"     -> {status}", quiet)
                return False
            now = time.time()
            elapsed = int(now - start)
            if now - last_progress >= progress_interval_sec:
                log_progress(
                    f"SFN esperando… {label} RUNNING {elapsed}s "
                    f"(timeout {timeout}s, thread={threading.current_thread().name})"
                )
                last_progress = now
            time.sleep(5 if quiet else 10)
        except Exception as e:
            log_progress(f"SFN describe_execution error {label}: {e}")
            _log(f"     describe_execution error: {e}", quiet)
            time.sleep(10)
    log_progress(f"SFN TIMEOUT {label} tras {timeout}s")
    _log("     -> TIMEOUT", quiet)
    return False


def process_date_sequential_sections(
    profile: str,
    region: str,
    day: datetime,
    tenant_id: str,
    agent_id: str,
    wait_timeout: int,
    quiet: bool,
    sf_progress_interval: float = 15.0,
) -> tuple[str, bool, list[str], list[str]]:
    """Un día: secciones en serie. Cliente SFN propio al hilo."""
    sfn = create_step_function_client(profile, region)
    date_str = day.strftime("%Y-%m-%d")
    log_progress(
        f"Día {date_str}: inicio worker (secciones en serie, "
        f"thread={threading.current_thread().name})"
    )
    _log(f"\n{'='*60}\nFecha: {date_str}\n{'='*60}", quiet)

    ok_sec: list[str] = []
    bad_sec: list[str] = []

    for section in SECTIONS:
        _log(f"  {section.upper()}:", quiet)
        arn = invoke_step_function(sfn, date_str, section, tenant_id, agent_id, quiet)
        if not arn:
            bad_sec.append(section)
            continue
        if wait_for_completion(
            sfn,
            arn,
            timeout=wait_timeout,
            quiet=quiet,
            wait_label=f"{date_str} {section}",
            progress_interval_sec=sf_progress_interval,
        ):
            ok_sec.append(section)
        else:
            bad_sec.append(section)
        time.sleep(0 if quiet else 1)

    _log(f"  Resumen {date_str}: ok={ok_sec} fail={bad_sec}", quiet)
    log_progress(f"Día {date_str}: fin worker serie (ok={len(ok_sec)} fail={len(bad_sec)})")
    success = len(ok_sec) > 0
    return date_str, success, ok_sec, bad_sec


def _run_one_section(
    profile: str,
    region: str,
    date_str: str,
    section: str,
    tenant_id: str,
    agent_id: str,
    wait_timeout: int,
    quiet: bool,
    sf_progress_interval: float = 15.0,
) -> tuple[str, bool]:
    sfn = create_step_function_client(profile, region)
    arn = invoke_step_function(sfn, date_str, section, tenant_id, agent_id, quiet)
    if not arn:
        return section, False
    ok = wait_for_completion(
        sfn,
        arn,
        timeout=wait_timeout,
        quiet=quiet,
        wait_label=f"{date_str} {section}",
        progress_interval_sec=sf_progress_interval,
    )
    return section, ok


def process_date_parallel_sections(
    profile: str,
    region: str,
    day: datetime,
    tenant_id: str,
    agent_id: str,
    wait_timeout: int,
    quiet: bool,
    sf_progress_interval: float = 15.0,
) -> tuple[str, bool, list[str], list[str]]:
    """Un día: las 4 secciones en paralelo (hasta 4 SFN a la vez por día)."""
    date_str = day.strftime("%Y-%m-%d")
    log_progress(
        f"Día {date_str}: inicio worker (secciones en paralelo, "
        f"thread={threading.current_thread().name})"
    )
    _log(f"\n{'='*60}\nFecha: {date_str} (secciones en paralelo)\n{'='*60}", quiet)

    ok_sec: list[str] = []
    bad_sec: list[str] = []

    with ThreadPoolExecutor(max_workers=len(SECTIONS)) as pool:
        futures = {
            pool.submit(
                _run_one_section,
                profile,
                region,
                date_str,
                sec,
                tenant_id,
                agent_id,
                wait_timeout,
                quiet,
                sf_progress_interval,
            ): sec
            for sec in SECTIONS
        }
        for fut in as_completed(futures):
            section, ok = fut.result()
            if ok:
                ok_sec.append(section)
            else:
                bad_sec.append(section)

    ok_sec.sort(key=lambda s: SECTIONS.index(s) if s in SECTIONS else 99)
    bad_sec.sort(key=lambda s: SECTIONS.index(s) if s in SECTIONS else 99)
    _log(f"  Resumen {date_str}: ok={ok_sec} fail={bad_sec}", quiet)
    log_progress(f"Día {date_str}: fin worker paralelo (ok={len(ok_sec)} fail={len(bad_sec)})")
    success = len(ok_sec) > 0
    return date_str, success, ok_sec, bad_sec


def iter_days_descending(start: datetime, end: datetime):
    d = start
    while d >= end:
        yield d
        d -= timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(
        description="Invoca Step Functions de boletín por fecha y sección."
    )
    parser.add_argument("--profile", default=AWS_PROFILE)
    parser.add_argument("--region", default=AWS_REGION)
    parser.add_argument(
        "--env",
        choices=("qa", "prod"),
        default="prod",
        help="State Machine: prod=Alerts-BoletinOficialSyncronizer, qa=...-qa (default: prod).",
    )
    parser.add_argument(
        "--sfn-arn",
        default=None,
        metavar="ARN",
        help="Override: ARN de la Step Function (tiene prioridad sobre --env).",
    )
    parser.add_argument("--tenant-id", default=TENANT_ID)
    parser.add_argument("--agent-id", default=AGENT_ID)
    parser.add_argument(
        "--parallel-days",
        type=int,
        default=10,
        metavar="N",
        help="Cantidad de días a procesar en paralelo (default: 10, máx: 10).",
    )
    parser.add_argument(
        "--parallel-sections",
        action="store_true",
        help="Dentro de cada día, lanzar las 4 secciones en paralelo (más SFN concurrentes).",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=900,
        help="Timeout en segundos por ejecución de sección (default: 900).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log detallado (por defecto en modo paralelo se reduce ruido).",
    )
    parser.add_argument(
        "--sf-progress-interval",
        type=float,
        default=15.0,
        metavar="SEC",
        help="Cada cuántos segundos loguear avance mientras una SFN está RUNNING (default: 15).",
    )
    parser.add_argument(
        "--pool-heartbeat",
        type=float,
        default=45.0,
        metavar="SEC",
        help="Con varios días en paralelo, cada cuántos segundos loguear estado del pool (default: 45; 0=desactivar).",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Primer día a procesar (más reciente; se va hacia atrás). "
            f"Default: {START_DATE.strftime('%Y-%m-%d')}."
        ),
    )
    parser.add_argument(
        "--end-date",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Último día del rango (más antiguo). "
            f"Default: {END_DATE.strftime('%Y-%m-%d')}. "
            "Si usás --start-year/--end-year, este flag se ignora."
        ),
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        metavar="YYYY",
        help="Año más reciente: incluir todo ese año (1 ene – 31 dic). Requiere --end-year.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        metavar="YYYY",
        help="Año más antiguo: incluir todo ese año (1 ene – 31 dic). Requiere --start-year.",
    )
    args = parser.parse_args()

    def _parse_ymd(s: str) -> datetime:
        y, m, d = (int(p) for p in s.strip().split("-", 2))
        return datetime(y, m, d)

    by_calendar_years = args.start_year is not None or args.end_year is not None
    if by_calendar_years:
        if args.start_year is None or args.end_year is None:
            print(
                "ERROR: con modo años usá --start-year y --end-year a la vez "
                "(año reciente y año antiguo, p. ej. 2026 y 2016).",
                file=sys.stderr,
            )
            sys.exit(1)
        if args.start_year < args.end_year:
            print(
                f"ERROR: --start-year ({args.start_year}) debe ser >= --end-year ({args.end_year}) "
                "(se procesa del año reciente hacia el antiguo).",
                file=sys.stderr,
            )
            sys.exit(1)
        if args.start_date or args.end_date:
            print(
                "[WARN] Modo --start-year/--end-year: se ignoran --start-date y --end-date.",
                file=sys.stderr,
            )
        # Un día de full-year range por año: 31-12 (inicio) … 1-1 (cierre) en orden descendente.
        start_date = datetime(args.start_year, 12, 31)
        end_date = datetime(args.end_year, 1, 1)
    else:
        start_date = START_DATE
        end_date = END_DATE
        if args.start_date:
            start_date = _parse_ymd(args.start_date)
        if args.end_date:
            end_date = _parse_ymd(args.end_date)
    if start_date < end_date:
        print(
            f"ERROR: inicio del rango ({start_date.date()}) debe ser >= fin ({end_date.date()}) "
            "(el recorrido de días es descendente).",
            file=sys.stderr,
        )
        sys.exit(1)

    global STEP_FUNCTION_ARN
    if args.sfn_arn and str(args.sfn_arn).strip():
        STEP_FUNCTION_ARN = str(args.sfn_arn).strip()
    elif args.env == "qa":
        STEP_FUNCTION_ARN = STEP_FUNCTION_ARN_QA
    else:
        STEP_FUNCTION_ARN = STEP_FUNCTION_ARN_PROD

    requested_parallel_days = max(1, args.parallel_days)
    parallel_days = min(requested_parallel_days, MAX_PARALLEL_DAYS)
    if requested_parallel_days > MAX_PARALLEL_DAYS:
        print(
            f"[WARN] --parallel-days={requested_parallel_days} excede el máximo "
            f"permitido ({MAX_PARALLEL_DAYS}); se usará {parallel_days}."
        )
    quiet = parallel_days > 1 and not args.verbose

    print("Invocando Step Functions (Boletín)")
    print(f"Región: {args.region} | Perfil: {args.profile} | entorno: {args.env}")
    print(f"State machine: {STEP_FUNCTION_ARN}")
    if by_calendar_years:
        n_years = args.start_year - args.end_year + 1
        print(
            f"Modo años calendario completos: {args.end_year}–{args.start_year} "
            f"({n_years} años, en cada uno del 01-01 al 31-12, días en orden descendente.)"
        )
    print(
        f"Rango de días: {start_date.strftime('%Y-%m-%d')} (más reciente) "
        f"→ {end_date.strftime('%Y-%m-%d')} (más antiguo)"
    )
    print(f"Secciones: {', '.join(SECTIONS)}")
    print(f"Tenant: {args.tenant_id} | Agent: {args.agent_id}")
    print(
        f"Paralelismo: {parallel_days} día(s)"
        + (" + secciones en paralelo" if args.parallel_sections else "")
    )
    print(f"Timeout/sección: {args.wait_timeout}s")
    print(
        f"Avance SFN: cada {args.sf_progress_interval}s | "
        f"Heartbeat pool: cada {args.pool_heartbeat}s"
    )
    print("=" * 60)

    if not validate_aws_identity(args.profile, args.region):
        print("ERROR: credenciales inválidas o expiradas.")
        sys.exit(1)

    days = list(iter_days_descending(start_date, end_date))
    if not days:
        print("No hay fechas en el rango.")
        return

    total_days = len(days)
    log_progress(f"Inicio: {total_days} días en cola (parallel_days={parallel_days})")

    successful_dates: list[str] = []
    failed_dates: list[str] = []
    results_lock = threading.Lock()
    days_done = [0]

    def process_one_day(day: datetime) -> None:
        ds = day.strftime("%Y-%m-%d")
        try:
            if args.parallel_sections:
                ds, ok, _, _ = process_date_parallel_sections(
                    args.profile,
                    args.region,
                    day,
                    args.tenant_id,
                    args.agent_id,
                    args.wait_timeout,
                    quiet,
                    args.sf_progress_interval,
                )
            else:
                ds, ok, _, _ = process_date_sequential_sections(
                    args.profile,
                    args.region,
                    day,
                    args.tenant_id,
                    args.agent_id,
                    args.wait_timeout,
                    quiet,
                    args.sf_progress_interval,
                )
        except Exception as e:
            with results_lock:
                failed_dates.append(ds)
            log_progress(f">>> Día {ds}: ERROR {e}")
            return

        with results_lock:
            if ok:
                successful_dates.append(ds)
            else:
                failed_dates.append(ds)
        log_progress(f">>> Día {ds}: {'OK' if ok else 'FALLIDO'}")

    if parallel_days == 1:
        for day in days:
            process_one_day(day)
            days_done[0] += 1
            log_progress(f"Progreso global: {days_done[0]}/{total_days} días procesados")
    else:
        hb_stop = threading.Event()
        pool_t0 = time.time()

        def pool_heartbeat() -> None:
            interval = max(5.0, float(args.pool_heartbeat))
            while not hb_stop.is_set():
                if hb_stop.wait(timeout=interval):
                    break
                log_progress(
                    f"Pool sigue activo: {days_done[0]}/{total_days} días cerrados | "
                    f"{int(time.time() - pool_t0)}s desde inicio del pool | "
                    f"max_workers={parallel_days}"
                )

        hb_thread = None
        if float(args.pool_heartbeat) > 0:
            hb_thread = threading.Thread(target=pool_heartbeat, daemon=True)
            hb_thread.start()

        try:
            with ThreadPoolExecutor(max_workers=parallel_days) as pool:
                future_to_day = {pool.submit(process_one_day, d): d for d in days}
                for fut in as_completed(future_to_day):
                    fut.result()
                    days_done[0] += 1
                    log_progress(
                        f"Pool: día completado ({days_done[0]}/{total_days} días cerrados)"
                    )
        finally:
            hb_stop.set()

    successful_dates.sort(reverse=True)
    failed_dates.sort(reverse=True)

    print("\n" + "=" * 60)
    print("RESUMEN FINAL")
    print("=" * 60)
    print(f"Fechas exitosas: {len(successful_dates)}")
    print(f"Fechas fallidas: {len(failed_dates)}")
    print(f"Total: {len(successful_dates) + len(failed_dates)}")
    print(f"Completado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if failed_dates:
        print("\nFechas fallidas (máx. 15):")
        for d in failed_dates[:15]:
            print(f"  - {d}")
        if len(failed_dates) > 15:
            print(f"  ... y {len(failed_dates) - 15} más")


if __name__ == "__main__":
    main()

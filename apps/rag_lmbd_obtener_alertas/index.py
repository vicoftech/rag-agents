import json
import logging
import os
from datetime import datetime
from typing import Any

import boto3
import psycopg2
from botocore.exceptions import ClientError
from psycopg2.extras import RealDictCursor

# Configurar logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

_secrets_client_cache: Any = None
_db_secret_cached: dict[str, Any] | None = None
_db_secret_arn_used: str = ""

def _secrets_client():
    global _secrets_client_cache
    if _secrets_client_cache is None:
        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "us-east-1"
        )
        _secrets_client_cache = boto3.client(
            "secretsmanager", region_name=region.strip() or "us-east-1"
        )
    return _secrets_client_cache


def _get_db_secret_from_arn() -> dict[str, Any]:
    """
    Credenciales vía Secrets Manager (``DB_SECRET_ARN`` o ``DB_SECRET_ID``).
    Las variables DB_HOST_* / DB_PASSWORD_* / etc. siguen teniendo prioridad si están definidas y no vacías;
    el secreto sólo completa huecos (p. ej. ``DB_PASSWORD_PROD`` vacío + password en el JSON del secreto).
    """
    global _db_secret_cached, _db_secret_arn_used
    # Terraform/histórico: DB_SECRET_ID; otras lambdas: DB_SECRET_ARN — ambos válidos.
    arn = (
        os.environ.get("DB_SECRET_ARN") or os.environ.get("DB_SECRET_ID") or ""
    ).strip()
    if not arn:
        _db_secret_cached = {}
        _db_secret_arn_used = ""
        return {}
    if arn != _db_secret_arn_used:
        _db_secret_cached = None
        _db_secret_arn_used = arn
    if _db_secret_cached is not None:
        return _db_secret_cached
    try:
        resp = _secrets_client().get_secret_value(SecretId=arn)
        raw = resp.get("SecretString") or "{}"
        _db_secret_cached = json.loads(raw)
        return _db_secret_cached
    except (ClientError, json.JSONDecodeError, TypeError) as e:
        logger.error(f"No se pudo leer secreto RDS (DB_SECRET_ARN / DB_SECRET_ID): {e}")
        _db_secret_cached = {}
        return {}


def _env_nonempty(key: str) -> str | None:
    v = os.environ.get(key)
    if v is None or str(v).strip() == "":
        return None
    return str(v).strip()


def _nz(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def get_db_schema():
    """
    Obtener schema de BD según ambiente (fallback: public)
    """
    environment = os.environ.get('ENVIRONMENT', 'dev').upper()
    schema = os.environ.get(f'DB_SCHEMA_{environment}', 'public')
    # Evitar inyección al interpolar identificador de schema.
    if not schema.replace('_', '').isalnum():
        raise ValueError(f"DB schema inválido: {schema}")
    return schema

def _merge_pg_config(
    *,
    keys: tuple[str, str, str, str, str],
    secret: dict[str, Any],
    port_default: int = 5432,
) -> dict[str, Any]:
    host_k, port_k, user_k, password_k, database_k = keys
    raw_port = _env_nonempty(port_k)
    if raw_port is not None:
        try:
            port_i = int(raw_port)
        except ValueError as e:
            raise ValueError(f"{port_k} inválido: {raw_port!r}") from e
    else:
        sp = secret.get("port")
        try:
            port_i = int(sp) if sp is not None and str(sp).strip() != "" else port_default
        except (TypeError, ValueError):
            port_i = port_default

    host = _env_nonempty(host_k) or _nz(secret.get("host"))
    user = (
        _env_nonempty(user_k)
        or _nz(secret.get("username"))
        or _nz(secret.get("user"))
    )

    pwd_env = os.environ.get(password_k)
    if pwd_env is not None and str(pwd_env) != "":
        password = str(pwd_env)
    else:
        spw = secret.get("password")
        password = str(spw) if spw not in (None, "") else None

    database = (
        _env_nonempty(database_k)
        or _nz(secret.get("dbname"))
        or _nz(secret.get("database"))
    )

    return {
        "host": host,
        "port": port_i,
        "user": user,
        "password": password,
        "database": database,
        "sslmode": "require",
    }


def get_db_config():
    """
    Configuración de BD por ENVIRONMENT.
    Preferencia: variables DB_*_{env}; si falta algo, se usa JSON de Secrets Manager cuando
    ``DB_SECRET_ARN`` o ``DB_SECRET_ID`` apunta al secreto (mismo ARN que en consola).

    Importante para operadores: ``aws lambda update-function-configuration --environment``
    sustituye el mapa entero de variables; conviene fusión desde la consola/CLI incluyendo
    todas las claves necesarias (contraseña en plaintext opcional si el secreto trae ``password``).
    """
    environment = os.environ.get("ENVIRONMENT", "dev").strip().lower()

    secret = _get_db_secret_from_arn()

    if environment == "prod":
        cfg = _merge_pg_config(
            keys=(
                "DB_HOST_PROD",
                "DB_PORT_PROD",
                "DB_USER_PROD",
                "DB_PASSWORD_PROD",
                "DB_NAME_PROD",
            ),
            secret=secret,
        )
    elif environment == "qa":
        cfg = _merge_pg_config(
            keys=(
                "DB_HOST_QA",
                "DB_PORT_QA",
                "DB_USER_QA",
                "DB_PASSWORD_QA",
                "DB_NAME_QA",
            ),
            secret=secret,
        )
    else:
        host = _env_nonempty("DB_HOST_DEV") or _nz(secret.get("host")) or "localhost"
        raw_port = _env_nonempty("DB_PORT_DEV")
        if raw_port:
            port_i = int(raw_port)
        else:
            sp = secret.get("port")
            try:
                port_i = (
                    int(sp)
                    if sp is not None and str(sp).strip() != ""
                    else int(os.environ.get("DB_PORT_DEV", "5432"))
                )
            except (TypeError, ValueError):
                port_i = 5432
        user = (
            _env_nonempty("DB_USER_DEV")
            or _nz(secret.get("username"))
            or _nz(secret.get("user"))
            or "postgres"
        )
        pwd_env = os.environ.get("DB_PASSWORD_DEV")
        if pwd_env not in (None, ""):
            password = pwd_env
        else:
            spw = secret.get("password")
            password = str(spw) if spw not in (None, "") else ""

        db = (
            _env_nonempty("DB_NAME_DEV")
            or _nz(secret.get("dbname"))
            or _nz(secret.get("database"))
            or "alertas_db"
        )
        cfg = {
            "host": host,
            "port": port_i,
            "user": user,
            "password": password,
            "database": db,
            "sslmode": "require",
        }

    missing = [
        label
        for label, ok in (
            ("host", bool(cfg.get("host"))),
            ("user", bool(cfg.get("user"))),
            ("password", cfg.get("password") not in (None, "")),
            ("database", bool(cfg.get("database"))),
        )
        if not ok
    ]
    if missing:
        raise ValueError(
            "Faltan datos de conexión a PostgreSQL (%s): "
            "definí DB_*_%s y/o DB_SECRET_ARN/DB_SECRET_ID coherente con ENVIRONMENT=%r "
            "(revisá que un update-configuration no haya borrado env vars)."
            % (", ".join(missing), environment.upper(), os.environ.get("ENVIRONMENT"))
        )

    return cfg

def get_db_connection():
    """
    Crear conexión a la base de datos PostgreSQL
    """
    try:
        config = get_db_config()
        logger.info(f"Conectando a PostgreSQL: {config['host']}:{config['port']}/{config['database']}")
        
        connection = psycopg2.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config['database'],
            sslmode=config['sslmode'],
            connect_timeout=30
        )
        
        logger.info("Conexión a PostgreSQL establecida exitosamente")
        return connection
        
    except Exception as e:
        logger.error(f"Error conectando a PostgreSQL: {str(e)}")
        raise e

def execute_query(connection, query, params=None):
    """
    Ejecutar consulta SQL con parámetros
    """
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            result = cursor.fetchall()
            logger.info(f"Consulta ejecutada exitosamente. Registros: {len(result)}")
            return result
            
    except Exception as e:
        logger.error(f"Error ejecutando consulta: {str(e)}")
        logger.error(f"Query: {query}")
        raise e

def table_columns(connection, table_name: str) -> set[str]:
    """Devuelve columnas existentes para schema.table (minúsculas)."""
    sql = """
        SELECT lower(column_name) AS c
        FROM information_schema.columns
        WHERE table_schema = split_part(%s, '.', 1)
          AND table_name = split_part(%s, '.', 2)
    """
    rows = execute_query(connection, sql, [table_name, table_name])
    return {str(r["c"]) for r in rows}

def resolve_alertas_table(connection):
    """
    Descubrir nombre de tabla (schema.table) de alertas.
    Basado en DDL actual: public.busqueda; admite otros esquemas si existiera la migración.
    """
    preferred_schema = get_db_schema()
    candidates = [
        f"{preferred_schema}.busqueda",
        "public.busqueda",
        "busqueda",
    ]
    try:
        with connection.cursor() as cursor:
            for candidate in candidates:
                cursor.execute("SELECT to_regclass(%s)", [candidate])
                regclass = cursor.fetchone()[0]
                if regclass:
                    logger.info(f"Tabla de alertas detectada: {candidate}")
                    return candidate

            # Fallback: introspección cuando to_regclass no ve la tabla (search_path distinto, etc.).
            cursor.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_type = 'BASE TABLE'
                  AND table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND lower(table_name) IN ('busqueda', 'alertas', 'busquedas')
                ORDER BY
                  CASE WHEN table_schema = %s THEN 0 ELSE 1 END,
                  CASE WHEN lower(table_name) = 'busqueda' THEN 0 ELSE 1 END,
                  table_schema, table_name
                LIMIT 1
                """,
                [preferred_schema],
            )
            row = cursor.fetchone()
            if row:
                schema, table = row[0], row[1]
                fq = f'"{schema}"."{table}"'
                logger.info(f"Tabla de alertas (information_schema): {fq}")
                return fq
    except Exception as e:
        logger.error(f"Error resolviendo tabla de alertas: {str(e)}")
        raise e

    raise RuntimeError(
        'No existe ninguna tabla activable (busqueda/alertas) en esta base; '
        "aplique el DDL alerts-ddl.sql o defina DB_SCHEMA_<ENV>"
    )

def get_alertas(connection):
    """
    Obtener alertas de la base de datos con filtros opcionales
    """
    try:
        # Query base
        table_name = resolve_alertas_table(connection)
        cols = table_columns(connection, table_name)
        optional_exprs = [
            ("estado_alerta", "estado_alerta"),
            ("descripcion_disposicion_default", "descripcion_disposicion_default"),
            ("url_disposicion_default", "url_disposicion_default"),
            ("nombre_pdf_disposicion_default", "nombre_pdf_disposicion_default"),
            ("archivo_disposicion_default", "archivo_disposicion_default"),
            ("fecha_de_aparicion_default", "fecha_de_aparicion_default"),
            ("fecha_de_publicacion_default", "fecha_de_publicacion_default"),
        ]
        selected = [
            "id",
            "destinatarios",
            "fuente_de_informacion",
            "nombre_busqueda",
            "palabras_de_busqueda",
        ]
        for col, alias in optional_exprs:
            if col in cols:
                selected.append(f"{col} AS {alias}")
            else:
                selected.append(f"NULL::text AS {alias}")
        query = f"""
        SELECT
            {", ".join(selected)}
        FROM {table_name}
        WHERE activo=true
        AND eliminado=false
        """
        
        params = []
                        
        logger.info(f"Ejecutando consulta de alertas con {len(params)} parámetros")
        return execute_query(connection, query, params)
        
    except Exception as e:
        logger.error(f"Error en get_alertas: {str(e)}")
        raise e

def get_alerta_by_id(connection, alerta_id):
    """
    Obtener una alerta específica por ID
    """
    try:
        table_name = resolve_alertas_table(connection)
        cols = table_columns(connection, table_name)
        optional_exprs = [
            ("estado_alerta", "estado_alerta"),
            ("descripcion_disposicion_default", "descripcion_disposicion_default"),
            ("url_disposicion_default", "url_disposicion_default"),
            ("nombre_pdf_disposicion_default", "nombre_pdf_disposicion_default"),
            ("archivo_disposicion_default", "archivo_disposicion_default"),
            ("fecha_de_aparicion_default", "fecha_de_aparicion_default"),
            ("fecha_de_publicacion_default", "fecha_de_publicacion_default"),
        ]
        selected = [
            "id",
            "destinatarios",
            "fuente_de_informacion",
            "nombre_busqueda",
            "palabras_de_busqueda",
        ]
        for col, alias in optional_exprs:
            if col in cols:
                selected.append(f"{col} AS {alias}")
            else:
                selected.append(f"NULL::text AS {alias}")
        query = f"""
        SELECT
            {", ".join(selected)}
        FROM {table_name}
        WHERE id = %s
        AND activo=true
        AND eliminado=false
        """
        
        result = execute_query(connection, query, [alerta_id])
        return result[0] if result else None
        
    except Exception as e:
        logger.error(f"Error en get_alerta_by_id: {str(e)}")
        raise e

def get_alertas_count(connection, fecha_desde=None, fecha_hasta=None):
    """
    Obtener conteo total de alertas
    """
    try:
        table_name = resolve_alertas_table(connection)
        query = f"SELECT COUNT(*) as total FROM {table_name} WHERE activo=true AND eliminado=false"
        params = []
        
        result = execute_query(connection, query, params)
        return result[0]['total'] if result else 0
        
    except Exception as e:
        logger.error(f"Error en get_alertas_count: {str(e)}")
        raise e

def format_alertas_response(alertas, total_count=None):
    """
    Formatear alertas para respuesta JSON
    """
    formatted_alertas = []
    
    for alerta in alertas:
        formatted_alerta = {
            'id': alerta['id'],
            'destinatarios': alerta['destinatarios'],
            'fuente_de_informacion': alerta['fuente_de_informacion'],
            'nombre_busqueda': alerta['nombre_busqueda'],
            'palabras_de_busqueda': alerta['palabras_de_busqueda'],
            # Campos opcionales para armar payload de alert_creation si existen en BD.
            'estado_alerta': alerta.get('estado_alerta'),
            'descripcion_disposicion_default': alerta.get('descripcion_disposicion_default'),
            'url_disposicion_default': alerta.get('url_disposicion_default'),
            'nombre_pdf_disposicion_default': alerta.get('nombre_pdf_disposicion_default'),
            'archivo_disposicion_default': alerta.get('archivo_disposicion_default'),
            'fecha_de_aparicion_default': alerta.get('fecha_de_aparicion_default'),
            'fecha_de_publicacion_default': alerta.get('fecha_de_publicacion_default'),
        }
        formatted_alertas.append(formatted_alerta)
    
    return {
        'alertas': formatted_alertas,
        'total_count': total_count or len(formatted_alertas),
        'timestamp': datetime.now().isoformat()
    }

def handler(event, context):
    """
    Handler principal de la Lambda
    """
    connection = None
    
    try:
        logger.info("Iniciando handler de rag_lmbd_obtener_alertas")
        
        # Extraer parámetros del evento (query string, path params o body JSON).
        query_params = event.get('queryStringParameters') or {}
        path_params = event.get('pathParameters') or {}
        body_params = {}
        body_raw = event.get('body')
        if isinstance(body_raw, str) and body_raw.strip():
            try:
                body_params = json.loads(body_raw)
            except json.JSONDecodeError:
                body_params = {}
        elif isinstance(body_raw, dict):
            body_params = body_raw

        alerta_id = (
            query_params.get('alerta_id')
            or query_params.get('id')
            or path_params.get('alerta_id')
            or path_params.get('id')
            or body_params.get('alerta_id')
            or body_params.get('id')
        )
                
        # Conectar a base de datos
        connection = get_db_connection()
        
        if alerta_id:
            # Obtener alerta específica
            alerta = get_alerta_by_id(connection, alerta_id)
            result = format_alertas_response([alerta] if alerta else [], 1)
            
        else:
            # Obtener lista de alertas
            alertas = get_alertas(connection)
            total_count = get_alertas_count(connection)
            result = format_alertas_response(alertas, total_count)
        
        # Cerrar conexión
        connection.close()
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS'
            },
            'body': json.dumps(result, ensure_ascii=False)
        }
        
    except Exception as e:
        logger.error(f"Error en handler: {str(e)}")
        
        # Cerrar conexión si existe
        if connection:
            connection.close()
        
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS'
            },
            'body': json.dumps({
                'error': 'Error interno del servidor',
                'message': str(e),
                'timestamp': datetime.now().isoformat()
            }, ensure_ascii=False)
        }

if __name__ == "__main__":
    # Evento de prueba local
    evento_de_prueba = {
        'queryStringParameters': {
        }
    }
    
    contexto_de_prueba = {}
    
    print("Iniciando prueba local de rag_lmbd_obtener_alertas...")
    
    respuesta = handler(evento_de_prueba, contexto_de_prueba)
    
    print("\n--- RESPUESTA DE LA LAMBDA ---")
    print("STATUS CODE:", respuesta.get('statusCode'))
    
    if respuesta.get('body'):
        body_parseado = json.loads(respuesta['body'])
        print(json.dumps(body_parseado, indent=4, ensure_ascii=False))

import json
import os
import boto3
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

# Configurar logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_db_schema():
    """
    Obtener schema de BD según ambiente (fallback: public)
    """
    environment = os.environ.get('ENVIRONMENT', 'dev').upper()
    schema = os.environ.get(f'DB_SCHEMA_{environment}', 'tenant_boletin')
    # Evitar inyección al interpolar identificador de schema.
    if not schema.replace('_', '').isalnum():
        raise ValueError(f"DB schema inválido: {schema}")
    return schema

def get_db_config():
    """
    Obtener configuración de base de datos según el ambiente
    """
    environment = os.environ.get('ENVIRONMENT', 'dev')
    
    if environment == 'prod':
        return {
            'host': os.environ.get('DB_HOST_PROD'),
            'port': int(os.environ.get('DB_PORT_PROD', 5432)),
            'user': os.environ.get('DB_USER_PROD'),
            'password': os.environ.get('DB_PASSWORD_PROD'),
            'database': os.environ.get('DB_NAME_PROD'),
            'sslmode': 'require'
        }
    elif environment == 'qa':
        return {
            'host': os.environ.get('DB_HOST_QA'),
            'port': int(os.environ.get('DB_PORT_QA', 5432)),
            'user': os.environ.get('DB_USER_QA'),
            'password': os.environ.get('DB_PASSWORD_QA'),
            'database': os.environ.get('DB_NAME_QA'),
            'sslmode': 'require'
        }
    else:  # dev
        return {
            'host': os.environ.get('DB_HOST_DEV', 'localhost'),
            'port': int(os.environ.get('DB_PORT_DEV', 5432)),
            'user': os.environ.get('DB_USER_DEV', 'postgres'),
            'password': os.environ.get('DB_PASSWORD_DEV', ''),
            'database': os.environ.get('DB_NAME_DEV', 'alertas_db'),
            'sslmode': 'require'
        }

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

def resolve_alertas_table(connection):
    """
    Descubrir nombre de tabla (schema.table) para alertas/busquedas.
    """
    preferred_schema = get_db_schema()
    candidates = [
        f"{preferred_schema}.busqueda",
        f"{preferred_schema}.alertas",
        f"{preferred_schema}.busquedas",
        "tenant_boletin.busqueda",
        "tenant_boletin.alertas",
        "tenant_anmat.busqueda",
        "tenant_anmat.alertas",
        "public.busqueda",
        "public.alertas",
    ]
    try:
        with connection.cursor() as cursor:
            for candidate in candidates:
                cursor.execute("SELECT to_regclass(%s)", [candidate])
                regclass = cursor.fetchone()[0]
                if regclass:
                    logger.info(f"Tabla de alertas detectada: {candidate}")
                    return candidate
    except Exception as e:
        logger.error(f"Error resolviendo tabla de alertas: {str(e)}")
        raise e

    raise RuntimeError(
        "No se encontró tabla de alertas (busqueda/alertas) en los esquemas esperados"
    )

def get_alertas(connection):
    """
    Obtener alertas de la base de datos con filtros opcionales
    """
    try:
        # Query base
        table_name = resolve_alertas_table(connection)
        query = f"""
        SELECT 
            id,
            destinatarios,
            fuente_de_informacion,
            nombre_busqueda,
            palabras_de_busqueda
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
        query = f"""
        SELECT 
            id,
            destinatarios,
            fuente_de_informacion,
            nombre_busqueda,
            palabras_de_busqueda
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
            'palabras_de_busqueda': alerta['palabras_de_busqueda']
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

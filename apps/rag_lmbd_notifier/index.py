import json
import os
import re
from datetime import UTC, datetime
from typing import Any, Dict, Optional

import boto3

# No usar credenciales hardcodeadas. En AWS Lambda se usa el rol de ejecución.
DEFAULT_REGION = os.getenv("AWS_REGION", "us-east-1")
DEFAULT_ENVIRONMENT = os.getenv("ENVIRONMENT", "PRODUCCIÓN")
SNS_SUBJECT_MAX_LENGTH = 100
MAX_FIELD_LENGTH = 1200
MAX_MESSAGE_LENGTH = 12_000

_sns_client = None


def get_sns_client():
    """Devuelve cliente SNS lazy para simplificar tests locales y evitar side effects."""
    global _sns_client
    if _sns_client is None:
        _sns_client = boto3.client("sns", region_name=DEFAULT_REGION)
    return _sns_client


def utc_now_text() -> str:
    """Timestamp UTC estable para notificaciones."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def as_text(value: Any, default: str = "N/A", max_length: int = MAX_FIELD_LENGTH) -> str:
    """Convierte valores arbitrarios a texto plano seguro y truncado."""
    if value is None:
        return default

    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)

    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text).strip()
    if not text:
        return default
    if len(text) > max_length:
        return f"{text[:max_length]}... [truncado]"
    return text


def clean_subject(value: str) -> str:
    """SNS requiere subject corto, sin saltos de línea/control chars."""
    subject = re.sub(r"\s+", " ", as_text(value, "ALERTA SISTEMA ALERT", 500)).strip()
    if len(subject) > SNS_SUBJECT_MAX_LENGTH:
        subject = subject[: SNS_SUBJECT_MAX_LENGTH - 3].rstrip() + "..."
    return subject


def first_present(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", []):
            return value
    return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_component_name(execution_data: Dict[str, Any]) -> str:
    return as_text(
        first_present(
            execution_data,
            "component_name",
            "component",
            "site_id",
            "source",
            default="Sistema Alert",
        ),
        "Sistema Alert",
    )


def get_process_name(execution_data: Dict[str, Any]) -> str:
    return as_text(
        first_present(
            execution_data,
            "process_name",
            "lambda_name",
            "function_name",
            "state_machine_name",
            "failed_step",
            default="Proceso no especificado",
        ),
        "Proceso no especificado",
    )


def get_environment(execution_data: Dict[str, Any]) -> str:
    return as_text(first_present(execution_data, "environment", "ambiente", default=DEFAULT_ENVIRONMENT), DEFAULT_ENVIRONMENT)


def get_error_message(execution_data: Dict[str, Any]) -> str:
    # Step Functions suele entregar Error/Cause en estructuras anidadas.
    task_error = execution_data.get("taskError") or execution_data.get("task_error") or {}
    if isinstance(task_error, dict):
        nested = first_present(task_error, "Cause", "cause", "Error", "error")
        if nested:
            return as_text(nested)

    return as_text(
        first_present(
            execution_data,
            "error_message",
            "message",
            "error",
            "cause",
            "Cause",
            default="Sin detalle de error informado",
        ),
        "Sin detalle de error informado",
    )


def generate_cloudwatch_link(execution_data: Dict[str, Any]) -> str:
    explicit_link = first_present(execution_data, "cloudwatch_link", "logs_link")
    if explicit_link:
        return as_text(explicit_link, max_length=2000)

    log_group = first_present(execution_data, "log_group", "logGroup")
    if not log_group:
        process_name = get_process_name(execution_data)
        if process_name and process_name != "Proceso no especificado":
            log_group = f"/aws/lambda/{process_name}"

    if not log_group:
        return "N/A"

    encoded_log_group = as_text(log_group, max_length=500).replace("/", "$252F")
    return (
        f"https://{DEFAULT_REGION}.console.aws.amazon.com/cloudwatch/home"
        f"?region={DEFAULT_REGION}#logsV2:log-groups/log-group/{encoded_log_group}"
    )


def build_action_hint(notification_type: str, execution_data: Dict[str, Any]) -> str:
    if execution_data.get("is_test"):
        return "Verificar recepción del correo en todos los destinatarios configurados."

    if notification_type == "failure":
        return (
            "1. Revisar CloudWatch Logs del proceso indicado.\n"
            "2. Verificar si hay incidentes en dependencias externas o AWS.\n"
            "3. Reintentar manualmente solo si el error fue transitorio y el proceso es idempotente."
        )

    if notification_type == "partial_success":
        return (
            "1. Revisar elementos fallidos en logs/datos del proceso.\n"
            "2. Reprocesar solo los elementos pendientes si aplica."
        )

    return "No se requiere acción inmediata. Registrar evidencia si era una prueba controlada."


def build_base_fields(execution_data: Dict[str, Any]) -> Dict[str, str]:
    success = bool(execution_data.get("success", False))
    failed_count = safe_int(execution_data.get("failed_count"), 0)

    if success and failed_count == 0:
        notification_type = "success"
        severity = "INFO"
        default_incident_type = "SUCCESS"
    elif success and failed_count > 0:
        notification_type = "partial_success"
        severity = "WARNING"
        default_incident_type = "PARTIAL_SUCCESS"
    else:
        notification_type = "failure"
        severity = "CRITICAL"
        default_incident_type = "ERROR"

    if execution_data.get("is_test"):
        severity = "TEST"
        default_incident_type = "TEST_NOTIFICATION"

    return {
        "notification_type": notification_type,
        "severity": severity,
        "environment": get_environment(execution_data),
        "component_name": get_component_name(execution_data),
        "process_name": get_process_name(execution_data),
        "incident_type": as_text(first_present(execution_data, "error_type", "incident_type", default=default_incident_type)),
        "message": get_error_message(execution_data),
        "failed_step": as_text(first_present(execution_data, "failed_step", "step", default="N/A")),
        "timestamp_utc": as_text(first_present(execution_data, "timestamp_utc", "timestamp", "date", default=utc_now_text())),
        "execution_id": as_text(first_present(execution_data, "execution_id", "execution_arn", "executionArn", default="N/A"), max_length=2000),
        "reference": as_text(first_present(execution_data, "alarm_name", "alarmName", "reference", default="N/A"), max_length=1000),
        "cloudwatch_link": generate_cloudwatch_link(execution_data),
    }


def create_plain_text_notification(execution_data: Dict[str, Any]) -> Dict[str, str]:
    fields = build_base_fields(execution_data)
    status_label = fields["notification_type"].upper()
    test_prefix = "TEST - " if execution_data.get("is_test") else ""

    subject = clean_subject(
        f"{test_prefix}ALERTA ALERT {fields['environment']} - {status_label} - "
        f"{fields['component_name']}"
    )

    message = f"""
ALERTA SISTEMA ALERT - {fields['environment']}

Severidad: {fields['severity']}
Estado: {status_label}
Componente: {fields['component_name']}
Proceso: {fields['process_name']}
Tipo de incidente: {fields['incident_type']}
Mensaje: {fields['message']}
Paso fallido: {fields['failed_step']}
Fecha/hora detección UTC: {fields['timestamp_utc']}
Execution ID: {fields['execution_id']}
Referencia AWS: {fields['reference']}
CloudWatch: {fields['cloudwatch_link']}

Métricas/resumen:
- Fecha proceso: {as_text(execution_data.get('date'))}
- Total encontrados: {as_text(execution_data.get('total_found', 0))}
- Procesados: {as_text(execution_data.get('processed_count', 0))}
- Fallidos: {as_text(execution_data.get('failed_count', 0))}

Acción sugerida:
{build_action_hint(fields['notification_type'], execution_data)}

Mensaje automático del Sistema de Monitoreo Alert. No responder este correo.
""".strip()

    if len(message) > MAX_MESSAGE_LENGTH:
        message = f"{message[:MAX_MESSAGE_LENGTH]}\n... [mensaje truncado]"

    return {
        "subject": subject,
        "message": message,
        "status": fields["notification_type"],
        "priority": fields["severity"].lower(),
    }


def create_success_notification(execution_data: Dict[str, Any]) -> Dict[str, str]:
    """Compatibilidad con invocaciones/tests existentes."""
    return create_plain_text_notification({**execution_data, "success": True, "failed_count": 0})


def create_failure_notification(execution_data: Dict[str, Any]) -> Dict[str, str]:
    """Compatibilidad con invocaciones/tests existentes."""
    return create_plain_text_notification({**execution_data, "success": False})


def create_partial_success_notification(execution_data: Dict[str, Any]) -> Dict[str, str]:
    """Compatibilidad con invocaciones/tests existentes."""
    data = {**execution_data, "success": True}
    if not data.get("failed_count"):
        data["failed_count"] = 1
    return create_plain_text_notification(data)


def publish_notification(notification: Dict[str, str]) -> Dict[str, Any]:
    """Publica notificación de texto puro a SNS."""
    topic_arn = os.getenv("SNS_TOPIC_ARN")
    if not topic_arn:
        return {
            "success": False,
            "error": "SNS_TOPIC_ARN is not configured",
        }

    try:
        response = get_sns_client().publish(
            TopicArn=topic_arn,
            Message=notification["message"],
            Subject=notification["subject"],
        )
        message_id = response.get("MessageId")
        print(f"Successfully published monitoring notification to SNS: {message_id}")
        return {
            "success": True,
            "message_id": message_id,
        }
    except Exception as exc:  # No imprimir payloads ni secretos.
        print(f"Error publishing monitoring notification to SNS: {type(exc).__name__}: {exc}")
        return {
            "success": False,
            "error": f"Error publishing notification to SNS: {type(exc).__name__}",
        }


def process_execution_result(execution_data: Dict[str, Any]) -> Dict[str, Any]:
    """Procesa el resultado de ejecución y publica una notificación."""
    try:
        notification = create_plain_text_notification(execution_data)
        publish_result = publish_notification(notification)

        return {
            "success": publish_result["success"],
            "notification_type": notification["status"],
            "subject": notification["subject"],
            "message_id": publish_result.get("message_id"),
            "error": publish_result.get("error"),
            "execution_summary": {
                "component_name": get_component_name(execution_data),
                "process_name": get_process_name(execution_data),
                "date": execution_data.get("date"),
                "success": bool(execution_data.get("success", False)),
                "processed_count": execution_data.get("processed_count", 0),
                "total_found": execution_data.get("total_found", 0),
                "failed_count": execution_data.get("failed_count", 0),
            },
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Error processing execution result: {type(exc).__name__}",
        }


def parse_event(event: Dict[str, Any]) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Extrae método HTTP y execution_data desde evento HTTP o invocación directa."""
    http_method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod")

    if http_method:
        body = json.loads(event.get("body") or "{}")
        return http_method, body.get("execution_data")

    return None, event.get("execution_data")


def response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "OPTIONS,POST,GET",
    }
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **cors_headers},
        "body": json.dumps(body, ensure_ascii=False),
    }


def handler(event, context):
    """Lambda handler para enviar notificaciones operativas vía SNS."""
    event = event or {}

    try:
        http_method, execution_data = parse_event(event)

        if http_method == "OPTIONS":
            return response(200, {})

        if not isinstance(execution_data, dict) or not execution_data:
            return response(400, {"error": "Missing required parameter: execution_data"})

        result = process_execution_result(execution_data)
        return response(200 if result.get("success") else 500, result)

    except json.JSONDecodeError:
        return response(400, {"error": "Invalid JSON in request body"})
    except Exception as exc:
        return response(500, {"error": f"Internal server error: {type(exc).__name__}"})


if __name__ == "__main__":
    sample_event = {
        "execution_data": {
            "success": False,
            "component_name": "TEST - Sistema de Monitoreo",
            "process_name": "alert-monitoring-local",
            "environment": "PRODUCCIÓN",
            "error_type": "TEST_NOTIFICATION",
            "error_message": "Mensaje local de prueba. Configurar SNS_TOPIC_ARN para publicar en SNS.",
            "failed_step": "local-test",
            "execution_id": "local",
            "is_test": True,
        }
    }
    print(json.dumps(handler(sample_event, {}), indent=2, ensure_ascii=False))

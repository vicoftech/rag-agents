import json

import index


class FakeSnsClient:
    def __init__(self):
        self.calls = []

    def publish(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "msg-123"}


def test_create_failure_notification_plain_text():
    notification = index.create_failure_notification(
        {
            "component_name": "Boletín Oficial Sync",
            "process_name": "rag_lmbd_bolinks-prod",
            "environment": "PRODUCCIÓN",
            "error_type": "FETCH_ERROR",
            "error_message": "Connection timeout",
            "failed_step": "bolinks",
            "execution_id": "arn:aws:states:us-east-1:123:execution:test",
        }
    )

    assert notification["status"] == "failure"
    assert "ALERTA ALERT PRODUCCIÓN" in notification["subject"]
    assert "ALERTA SISTEMA ALERT - PRODUCCIÓN" in notification["message"]
    assert "Componente: Boletín Oficial Sync" in notification["message"]
    assert "Tipo de incidente: FETCH_ERROR" in notification["message"]
    assert "<html" not in notification["message"].lower()


def test_publish_notification_uses_plain_sns_message(monkeypatch):
    fake_client = FakeSnsClient()
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:test-topic")
    monkeypatch.setattr(index, "get_sns_client", lambda: fake_client)

    result = index.publish_notification({"subject": "Test", "message": "Texto puro"})

    assert result == {"success": True, "message_id": "msg-123"}
    assert fake_client.calls[0]["Message"] == "Texto puro"
    assert fake_client.calls[0]["Subject"] == "Test"
    assert "MessageStructure" not in fake_client.calls[0]


def test_handler_returns_500_when_sns_topic_missing(monkeypatch):
    monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)

    result = index.handler(
        {
            "execution_data": {
                "success": False,
                "component_name": "TEST",
                "error_type": "TEST_NOTIFICATION",
                "is_test": True,
            }
        },
        {},
    )

    assert result["statusCode"] == 500
    body = json.loads(result["body"])
    assert body["success"] is False
    assert body["error"] == "SNS_TOPIC_ARN is not configured"
    assert "execution_data" not in body


def test_handler_http_event_success(monkeypatch):
    fake_client = FakeSnsClient()
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:test-topic")
    monkeypatch.setattr(index, "get_sns_client", lambda: fake_client)

    result = index.handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "body": json.dumps(
                {
                    "execution_data": {
                        "success": False,
                        "component_name": "TEST - Sistema de Monitoreo",
                        "process_name": "alert-monitoring-test",
                        "environment": "PRODUCCIÓN",
                        "error_type": "TEST_NOTIFICATION",
                        "error_message": "Mensaje de prueba",
                        "is_test": True,
                    }
                }
            ),
        },
        {},
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["success"] is True
    assert body["message_id"] == "msg-123"
    assert fake_client.calls[0]["Message"].startswith("ALERTA SISTEMA ALERT")

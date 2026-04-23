"""
S3 (ObjectCreated) -> SQS. Cada mensaje es JSON con {"Records": [<evento s3:ObjectCreated:*>]}.
rag_lmbd_embeddings-async consume la cola y desenrolla a ese mismo formato.
"""
import json
import os
import logging

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

_sqs = None


def _get_sqs():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _sqs


def _queue_url() -> str:
    u = os.environ.get("EMBEDDINGS_INGEST_QUEUE_URL", "").strip()
    if not u:
        raise RuntimeError("Falta EMBEDDINGS_INGEST_QUEUE_URL")
    return u


def handler(event, context):
    url = _queue_url()
    sqs = _get_sqs()
    n = 0
    for rec in event.get("Records", []):
        if rec.get("eventSource") != "aws:s3":
            continue
        out = {
            "Records": [
                {
                    "eventVersion": rec.get("eventVersion", "2.1"),
                    "eventSource": "aws:s3",
                    "awsRegion": rec.get("awsRegion", os.environ.get("AWS_REGION", "us-east-1")),
                    "eventTime": rec.get("eventTime", ""),
                    "eventName": rec.get("eventName", "ObjectCreated:Put"),
                    "userIdentity": rec.get("userIdentity", {"principalId": "s3"}),
                    "requestParameters": rec.get("requestParameters", {}),
                    "responseElements": rec.get("responseElements", {}),
                    "s3": rec.get("s3", {}),
                }
            ]
        }
        sqs.send_message(QueueUrl=url, MessageBody=json.dumps(out))
        n += 1
    log.info("encolada %s notificacion(es) S3", n)
    return {"statusCode": 200, "body": json.dumps({"enqueued": n})}

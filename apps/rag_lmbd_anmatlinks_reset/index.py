import os
import time
import boto3


LAMBDA_REGION = os.environ.get("AWS_REGION", "us-east-1")
TARGET_FUNCTION_NAME = os.environ["TARGET_FUNCTION_NAME"]

lambda_client = boto3.client("lambda", region_name=LAMBDA_REGION)


def handler(event, context):
    pages_since = int(event.get("pagesSinceReset", 0) or 0)
    max_pages = int(event.get("maxPagesBeforeReset", 3) or 3)

    if pages_since < max_pages:
        event["pagesSinceReset"] = pages_since + 1
        return event

    cfg = lambda_client.get_function_configuration(FunctionName=TARGET_FUNCTION_NAME)
    env = (cfg.get("Environment") or {}).get("Variables") or {}
    env["FORCE_COLDSTART_TOKEN"] = str(int(time.time()))

    lambda_client.update_function_configuration(
        FunctionName=TARGET_FUNCTION_NAME,
        Environment={"Variables": env},
    )

    event["pagesSinceReset"] = 0
    return event


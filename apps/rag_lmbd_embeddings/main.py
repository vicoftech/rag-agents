import os
import boto3
from lib.logger import setup_logger


# AWS Session Setup (for local testing)
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID_DEV', "")
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY_DEV', "")

session_args = {"region_name": AWS_REGION}

if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    session_args.update({
        "aws_access_key_id": AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": AWS_SECRET_ACCESS_KEY
    })

endpoint_url = f"https://s3.{AWS_REGION}.amazonaws.com"
s3 = boto3.client('s3', endpoint_url=endpoint_url, **session_args)
# Logger
logger = setup_logger(__name__)


def handler(event, context): 
    try:
        logger.info(f"Event received:  {event}")

    except Exception as e:
        logger.error(f"Failed to insert status: {str(e)}")

    return {
        "statusCode": 200,
        "body": f"Lambda executed successfully"
    }

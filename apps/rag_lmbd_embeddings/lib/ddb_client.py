# lib/dynamodb_client.py
import boto3
from botocore.exceptions import ClientError
from lib.logger import setup_logger
from boto3.dynamodb.conditions import Key, Attr
from datetime import datetime, timezone
from enum import Enum, auto
from decimal import Decimal
import uuid
import time

logger = setup_logger(__name__)

def parse_decimal(value):
        if isinstance(value, str):
            # Quitar separador de miles y reemplazar coma por punto
            value = value.replace('.', '').replace(',', '.')
        return Decimal(str(value)) 

class DocumentStatus(Enum):
    RECEIVED = "RECEIVED"
    OCR_IN_PROGRESS = "OCR_IN_PROGRESS "
    OCR_DONE = "OCR_DONE"
    OCR_FAILED = "OCR_FAILED"
    TEXT_EXTRACTION_IN_PROGRESS = "TEXT_EXTRACTION_IN_PROGRESS"
    TEXT_EXTRACTION_DONE = "TEXT_EXTRACTION_DONE"
    TEXT_EXTRACTION_FAILED = "TEXT_EXTRACTION_FAILED"
    BEDROCK_IN_PROGRESS = "BEDROCK_IN_PROGRESS"
    BEDROCK_DONE = "BEDROCK_DONE"
    BEDROCK_FAILS = "BEDROCK_FAILS"
    VALIDATION_IN_PROGRESS = "VALIDATION_IN_PROGRESS"
    VALIDATION_DONE = "VALIDATION_DONE"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    PROCESS_COMPLETED = "PROCESS_COMPLETED"
    PROCESS_FAILED = "PROCESS_FAILED"
    PROCESS_PARTIALLY_COMPLETED = "PROCESS_PARTIALLY_COMPLETED"

class DynamoDBClient:
    def __init__(self, table_name, dynamodb):
        self.dynamodb = dynamodb
        self.table = self.dynamodb.Table(table_name)


    def put_item(self, item):
        try:
            response = self.table.put_item(Item=item)
            logger.info(f"Item inserted into {self.table.name}: {item}")
            return response
        except ClientError as e:
            logger.error(f"Error inserting item: {e}")
            raise

    def get_item(self, key):
        try:
            response = self.table.get_item(Key=key)
            item = response.get("Item")
            logger.info(f"Item retrieved: {item}")
            return item
        except ClientError as e:
            logger.error(f"Error retrieving item: {e}")
            raise

    def get_item_by_fields(self, **filters):
        """
        Busca un ítem usando múltiples campos como filtro (ej: lang='es', document_type='invoice')
        """
        try:
          
            # Construye FilterExpression con los campos pasados
            filter_expression = None
            for field, value in filters.items():
                condition = Attr(field).eq(value)
                filter_expression = condition if filter_expression is None else filter_expression & condition

            logger.info(f"Searching for item with filters: {filters}")

            response = self.table.scan(FilterExpression=filter_expression)
            items = response.get("Items", [])

            if not items:
                logger.warning("No items found with given filters")
                return None

            logger.info(f"{len(items)} item(s) found")
            return items[0] if len(items) == 1 else items

        except ClientError as e:
            logger.error(f"Error retrieving item(s): {e}")
            raise


    def update_item(self, key, update_expression, expression_attrs):
        try:
            response = self.table.update_item(
                Key=key,
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_attrs,
                ReturnValues="UPDATED_NEW"
            )
            logger.info(f"Item updated: {response.get('Attributes')}")
            return response
        except ClientError as e:
            logger.error(f"Error updating item: {e}")
            raise


    def query_items_with_filters(self, partition_key, partition_value, filters=None):
        try:
            key_condition = Key(partition_key).eq(partition_value)

            filter_expression = None
            expression_values = {":pk": partition_value}
            expression_names = {f"#{partition_key}": partition_key}

            if filters:
                for i, (k, v) in enumerate(filters.items()):
                    placeholder = f":val{i}"
                    name = f"#field{i}"
                    expression_values[placeholder] = v
                    expression_names[name] = k
                    condition = Attr(k).eq(v)
                    filter_expression = condition if not filter_expression else filter_expression & condition

            query_kwargs = {
                "KeyConditionExpression": key_condition,
                "ExpressionAttributeValues": expression_values,
                "ExpressionAttributeNames": expression_names
            }

            if filter_expression:
                query_kwargs["FilterExpression"] = filter_expression

            response = self.table.query(**query_kwargs)
            return response.get("Items", [])
        except ClientError as e:
            logger.error(f"Error querying items with filters: {e}")
            raise

    def get_extracted_text(self, **filters):
        """
        Retrieves OCR text with priority:
        - if ocr_amount != 0, return ocr_extracted_text
        - else, if aws_extract_text exists and is not empty, return it
        - else raise Exception
        """
        try:
            # Build filter expression
            filter_expression = None
            for field, value in filters.items():
                condition = Attr(field).eq(value)
                filter_expression = condition if filter_expression is None else filter_expression & condition

            logger.info(f"Searching item with filters: {filters}")

            response = self.table.scan(FilterExpression=filter_expression)
            items = response.get("Items", [])

            if not items:
                raise Exception("No items found with given filters")

            item = items[0]  # Assuming unique result

            ocr_amount = item.get("ocr_ammount", 0)
            ocr_text = item.get("ocr_extracted_text", "")
            aws_text = item.get("aws_extract_text")

            if ocr_amount and parse_decimal(ocr_amount) != 0:
                return ocr_text

            if aws_text is not None and str(aws_text).strip():
                return aws_text

            raise Exception("No valid extracted text found (aws_extract_text is empty or null)")

        except ClientError as e:
            logger.error(f"DynamoDB error: {e}")
            raise
        except Exception as e:
            logger.error(f"Error processing item: {e}")
            raise



    def upsert_document_status(self, document_id, status, extra_fields=None):
        """
        Inserta o actualiza el estado actual del documento con timestamps inteligentes:
        - Si el estado es 'RECEIVED', se agrega 'start_at'.
        - Si el estado es uno de los de finalización, se agrega 'end_at'.
        - En todos los casos se actualiza 'updated_at'.
        """
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "document_id": document_id,
            "status": status,
            "updated_at": now
        }

        # Estados especiales para lógica de timestamps
        if status == DocumentStatus.RECEIVED.value:
            item["start_at"] = now
        elif status in {DocumentStatus.PROCESS_COMPLETED.value,DocumentStatus.PROCESS_FAILED.value, DocumentStatus.PROCESS_PARTIALLY_COMPLETED.value}:
            item["end_at"] = now

        if extra_fields:
            item.update(extra_fields)

        return self.put_item(item)


    def insert_status_transition(self, document_id, status, transition_at=None, extra_fields=None):
        """
        Inserta un nuevo registro en la tabla de historial de estados.
        """
        transition_at = transition_at or datetime.now(timezone.utc).isoformat()

        item = {
            "document_id": document_id,
            "transition_at": transition_at,
            "status": status
        }

        if extra_fields:
            item.update(extra_fields)

        return self.put_item(item)
    
    @staticmethod
    def prpepare_notification(title,message,type):
        notification = {
            "id": {"S": uuid.uuid4().hex[:6]},
            "title":{"S": title},
            "message": {"S":message},
            "time": {"N":str(int(time.time()))},
            "read": {"N":"0"},
            "type": {"S":type}
        }
        return notification
    

    @staticmethod
    def record_status_change(document_id, status, status_table, history_table, notification_table, ddb_client, notification, extra_fields=None):
        """
        Atomically records a status change in both:
        - Current status table (status_table), merging extra_fields if present
        - History table (history_table), storing current transition with metadata

        All tables must be in the same region/account. Requires low-level boto3 DynamoDB client.

        :param document_id: ID of the document
        :param status: New status
        :param status_table: boto3 Table object for the current status
        :param history_table: boto3 Table object for the status history
        :param ddb_client: boto3.client("dynamodb")
        :param extra_fields: Optional dict with metadata (e.g., actor, error info)
        """
        now = datetime.now(timezone.utc).isoformat()

        # Start with basic item
        status_item = {
            "document_id": {"S": document_id},
            "status": {"S": status},
            "updated_at": {"S": now}
        }

        # Fetch current item to preserve existing extra fields
        try:
            current = ddb_client.get_item(
                TableName=status_table.name,
                Key={"document_id": {"S": document_id}}
            ).get("Item", {})
        except ClientError as e:
            logger.warning(f"Could not fetch current item for merge: {e}")
            current = {}

        if status == DocumentStatus.RECEIVED.value:
            status_item["start_at"] = {"S": now}
        elif status in {
            DocumentStatus.PROCESS_COMPLETED.value,
            DocumentStatus.PROCESS_FAILED.value,
            DocumentStatus.PROCESS_PARTIALLY_COMPLETED.value
        }:
            status_item["end_at"] = {"S": now}
            if current and "start_at" in current:
                start_at_str = current["start_at"]['S']
                start_at_dt = datetime.fromisoformat(start_at_str.replace("Z", "+00:00"))
                end_at_dt = datetime.fromisoformat(now)
                duration_seconds = int((end_at_dt - start_at_dt).total_seconds())
                status_item["duration"] = {"N": str(duration_seconds)}



        # Merge existing extra fields (excluding known fields) + new ones
        known_keys = {"document_id", "status", "updated_at","start_at"}
        merged_fields = {}

        # Existing fields to preserve
        for k, v in current.items():
            if k not in known_keys:
                merged_fields[k] = v

        # New fields to override/add
        if extra_fields:
            for k, v in extra_fields.items():
                merged_fields[k] = {"S": str(v)}

        # Add merged fields to status_item
        status_item.update(merged_fields)

        # Build history item (no need to merge here)
        history_item = {
            "document_id": {"S": document_id},
            "transition_at": {"S": now},
            "status": {"S": status}
        }

        if extra_fields:
            for k, v in extra_fields.items():
                history_item[k] = {"S": str(v)}

        if notification:
            try:
                ddb_client.transact_write_items(
                    TransactItems=[
                        {
                            "Put": {
                                "TableName": status_table.name,
                                "Item": status_item
                            }
                        },
                        {
                            "Put": {
                                "TableName": history_table.name,
                                "Item": history_item
                            }
                        },
                        {
                            "Put": {
                                "TableName": notification_table.name,
                                "Item": notification
                            }
                        }
                    ]
                )
                logger.info(f"Transaction succeeded: status '{status}' recorded for document '{document_id}'")
            except ClientError as e:
                logger.error(f"Transaction failed for document '{document_id}': {e}")
                raise
        else: 
            try:
                ddb_client.transact_write_items(
                    TransactItems=[
                        {
                            "Put": {
                                "TableName": status_table.name,
                                "Item": status_item
                            }
                        },
                        {
                            "Put": {
                                "TableName": history_table.name,
                                "Item": history_item
                            }
                        }
                    ]
                )
                logger.info(f"Transaction succeeded: status '{status}' recorded for document '{document_id}'")
            except ClientError as e:
                logger.error(f"Transaction failed for document '{document_id}': {e}")
                raise


'''        
🧪 Ejemplo de uso

status_table = dynamodb.Table("DocumentProcessingStatus")
history_table = dynamodb.Table("DocumentStatusHistory")

DynamoDBClient.record_status_change(
    document_id="doc-301",
    status="PROCESS_COMPLETED",
    status_table=status_table,
    history_table=history_table,
    ddb_client=ddb_client,
    extra_fields={"actor": "lambda-ocr", "summary": "All pages processed"}
)
''' 
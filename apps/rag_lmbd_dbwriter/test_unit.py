import unittest
import json
import os
import sys
from unittest.mock import patch, MagicMock
from decimal import Decimal

# Add parent directory to path to import lambda functions
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from index import handler, generate_partition_key, generate_sort_key, create_document_item, create_site_item, process_s3writer_output
import index as dbw_index

class TestRAGDBWriter(unittest.TestCase):
    """Unit tests for rag_lmbd_dbwriter Lambda function"""
    
    def setUp(self):
        """Set up test fixtures"""
        self._dt_patcher = patch.object(dbw_index, 'DYNAMODB_TABLE', 'rag-documents-dev')
        self._dt_patcher.start()
        self.addCleanup(self._dt_patcher.stop)
        self.test_s3writer_output = {
            "success": True,
            "site_id": "boletinoficial_gob_ar",
            "date": "2026-03-06",
            "processed_count": 2,
            "failed_count": 0,
            "total_found": 2,
            "uploaded_files": [
                {
                    "original_url": "https://www.boletinoficial.gob.ar/documentos/boletin-2026-03-06.pdf",
                    "s3_key": "boletinoficial_gob_ar/2026-03-06/Boletín_Completo.pdf",
                    "s3_uri": "s3://rag-documents-dev/boletinoficial_gob_ar/2026-03-06/Boletín_Completo.pdf",
                    "filename": "Boletín_Completo.pdf",
                    "size": 1048576,
                    "metadata": {
                        "title": "Boletín Completo",
                        "date": "06/03/2026",
                        "section": "primera"
                    }
                },
                {
                    "original_url": "https://www.boletinoficial.gob.ar/edicion/segunda/20260306.pdf",
                    "s3_key": "boletinoficial_gob_ar/2026-03-06/Segunda_Sección.pdf",
                    "s3_uri": "s3://rag-documents-dev/boletinoficial_gob_ar/2026-03-06/Segunda_Sección.pdf",
                    "filename": "Segunda_Sección.pdf",
                    "size": 524288,
                    "metadata": {
                        "title": "Segunda Sección",
                        "date": "06/03/2026",
                        "section": "segunda"
                    }
                }
            ],
            "s3_bucket": "rag-documents-dev"
        }
    
    def test_generate_partition_key(self):
        """Test partition key generation"""
        pk = generate_partition_key("boletinoficial_gob_ar", "2026-03-06")
        self.assertEqual(pk, "boletinoficial_gob_ar#2026-03-06")
        
        pk2 = generate_partition_key("example_com", "2026-03-06")
        self.assertEqual(pk2, "example_com#2026-03-06")
    
    def test_generate_sort_key(self):
        """Test sort key generation"""
        sk = generate_sort_key("test_file.pdf")
        self.assertEqual(sk, "test_file.pdf")
        
        sk2 = generate_sort_key("Boletín_Completo.pdf")
        self.assertEqual(sk2, "Boletín_Completo.pdf")
    
    def test_create_document_item(self):
        """Test document item creation for DynamoDB"""
        file_info = self.test_s3writer_output["uploaded_files"][0]
        item = create_document_item(self.test_s3writer_output, file_info)
        
        self.assertEqual(item['PK'], "boletinoficial_gob_ar#20260306")
        self.assertEqual(item['SK'], "Boletín_Completo.pdf")
        self.assertEqual(item['entity_type'], "document")
        self.assertEqual(item['site_id'], "boletinoficial_gob_ar")
        self.assertEqual(item['date'], "20260306")
        self.assertEqual(item['filename'], "Boletín_Completo.pdf")
        self.assertEqual(item['original_url'], file_info['original_url'])
        self.assertEqual(item['s3_key'], file_info['s3_key'])
        self.assertEqual(item['s3_uri'], file_info['s3_uri'])
        self.assertEqual(item['file_size'], 1048576)
        self.assertEqual(item['file_metadata'], file_info['metadata'])
        self.assertEqual(item['processing_status'], "completed")
        self.assertEqual(item['source'], "rag_lmbd_s3writer")
        self.assertIn('created_at', item)
        self.assertIn('updated_at', item)
        
        # Check numeric conversion to Decimal
        self.assertIsInstance(item['file_size'], Decimal)
    
    def test_create_site_item(self):
        """Test site item creation for DynamoDB"""
        item = create_site_item(self.test_s3writer_output)
        
        self.assertEqual(item['PK'], "boletinoficial_gob_ar#2026-03-06")
        self.assertEqual(item['SK'], "site#info")
        self.assertEqual(item['entity_type'], "site")
        self.assertEqual(item['site_id'], "boletinoficial_gob_ar")
        self.assertEqual(item['date'], "2026-03-06")
        self.assertEqual(item['processed_count'], 2)
        self.assertEqual(item['failed_count'], 0)
        self.assertEqual(item['total_found'], 2)
        self.assertEqual(item['s3_bucket'], "rag-documents-dev")
        self.assertEqual(item['processing_status'], "completed")
        self.assertEqual(item['source'], "rag_lmbd_s3writer")
        self.assertIn('created_at', item)
        self.assertIn('updated_at', item)
        
        # Check numeric conversion to Decimal
        self.assertIsInstance(item['processed_count'], Decimal)
        self.assertIsInstance(item['failed_count'], Decimal)
        self.assertIsInstance(item['total_found'], Decimal)
    
    @patch('index.batch_upsert_items')
    def test_process_s3writer_output_success(self, mock_batch):
        """Test successful processing of s3writer output"""
        mock_batch.return_value = {
            'success': True,
            'processed_count': 3  # 1 site + 2 documents
        }
        
        result = process_s3writer_output(self.test_s3writer_output)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['site_id'], 'boletinoficial_gob_ar')
        self.assertEqual(result['date'], '2026-03-06')
        self.assertEqual(result['processed_count'], 3)
        self.assertEqual(result['documents_count'], 2)
        self.assertTrue(result['site_item_created'])
        self.assertEqual(result['dynamodb_table'], 'rag-documents-dev')
        
        # Verify batch_upsert_items was called
        mock_batch.assert_called_once()
        args = mock_batch.call_args[0]
        self.assertEqual(args[0], 'rag-documents-dev')  # table name
        self.assertEqual(len(args[1]), 3)  # 3 items (1 site + 2 documents)
    
    @patch('index.batch_upsert_items')
    def test_process_s3writer_output_batch_failure(self, mock_batch):
        """Test processing when batch upsert fails"""
        mock_batch.return_value = {
            'success': False,
            'error': 'DynamoDB error',
            'processed_count': 0
        }
        
        result = process_s3writer_output(self.test_s3writer_output)
        
        self.assertFalse(result['success'])
        self.assertEqual(result.get('error'), 'DynamoDB error')
    
    def test_process_s3writer_output_s3writer_failure(self):
        """Test processing when s3writer output indicates failure"""
        failed_s3writer_output = {
            "success": False,
            "error": "S3 upload failed"
        }
        
        result = process_s3writer_output(failed_s3writer_output)
        
        self.assertFalse(result['success'])
        self.assertIn('S3Writer output indicates failure', result['error'])
    
    def test_process_s3writer_output_no_files(self):
        """Test processing with no uploaded files"""
        empty_s3writer_output = {
            "success": True,
            "site_id": "example_com",
            "date": "2026-03-06",
            "processed_count": 0,
            "uploaded_files": []
        }
        
        result = process_s3writer_output(empty_s3writer_output)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['processed_count'], 0)
        self.assertEqual(result['message'], 'No files uploaded to process')
        self.assertEqual(result['documents_count'], 0)
    
    @patch('index.process_s3writer_output')
    def test_handler_http_event_success(self, mock_process):
        """Test handler with HTTP event (API Gateway)"""
        mock_process.return_value = {
            'success': True,
            'site_id': 'boletinoficial_gob_ar',
            'processed_count': 3
        }
        
        event = {
            "requestContext": {
                "http": {
                    "method": "POST"
                }
            },
            "body": json.dumps({
                "s3writer_output": self.test_s3writer_output
            })
        }
        
        result = handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        body = json.loads(result['body'])
        self.assertTrue(body['success'])
        self.assertEqual(body['site_id'], 'boletinoficial_gob_ar')
        mock_process.assert_called_once_with(self.test_s3writer_output)
    
    @patch('index.process_s3writer_output')
    def test_handler_direct_event_success(self, mock_process):
        """Test handler with direct Lambda invocation"""
        mock_process.return_value = {
            'success': True,
            'site_id': 'boletinoficial_gob_ar',
            'processed_count': 3
        }
        
        event = {
            "s3writer_output": self.test_s3writer_output
        }
        
        result = handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        body = json.loads(result['body'])
        self.assertTrue(body['success'])
        mock_process.assert_called_once_with(self.test_s3writer_output)
    
    def test_handler_missing_s3writer_output(self):
        """Test handler with missing s3writer_output parameter"""
        event = {
            "requestContext": {
                "http": {
                    "method": "POST"
                }
            },
            "body": json.dumps({})
        }
        
        result = handler(event, None)
        
        self.assertEqual(result['statusCode'], 400)
        body = json.loads(result['body'])
        self.assertIn('Missing required parameter: s3writer_output', body['error'])
    
    def test_handler_invalid_json(self):
        """Test handler with invalid JSON"""
        event = {
            "requestContext": {
                "http": {
                    "method": "POST"
                }
            },
            "body": "invalid json"
        }
        
        result = handler(event, None)
        
        self.assertEqual(result['statusCode'], 400)
        body = json.loads(result['body'])
        self.assertIn('Invalid JSON', body['error'])

if __name__ == '__main__':
    unittest.main()

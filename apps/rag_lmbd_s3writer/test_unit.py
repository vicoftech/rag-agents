import unittest
import json
import os
import sys
from unittest.mock import patch, MagicMock, mock_open

# Add parent directory to path to import lambda functions
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from index import handler, generate_site_id, extract_date_from_context, download_pdf, upload_to_s3, process_parser_output

class TestRAGS3Writer(unittest.TestCase):
    """Unit tests for rag_lmbd_s3writer Lambda function"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_parser_output = {
            "success": True,
            "url": "https://www.boletinoficial.gob.ar/seccion/primera",
            "page_title": "BOLETIN OFICIAL REPUBLICA ARGENTINA",
            "page_date": "06/03/2026",
            "pdf_links": [
                {
                    "url": "https://www.boletinoficial.gob.ar/documentos/boletin-2026-03-06.pdf",
                    "text": "Boletín Completo",
                    "title": "Boletín Completo",
                    "date": "06/03/2026",
                    "section": "primera"
                },
                {
                    "url": "https://www.boletinoficial.gob.ar/edicion/segunda/20260306.pdf",
                    "text": "Segunda Sección",
                    "title": "Segunda Sección",
                    "date": "06/03/2026",
                    "section": "segunda"
                }
            ],
            "pdf_links_count": 2,
            "total_links_found": 15
        }
        
        self.test_pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"
    
    def test_generate_site_id(self):
        """Test site ID generation from URL"""
        url1 = "https://www.boletinoficial.gob.ar/seccion/primera"
        site_id1 = generate_site_id(url1)
        self.assertEqual(site_id1, "boletinoficial_gob_ar")
        
        url2 = "http://example.com/path"
        site_id2 = generate_site_id(url2)
        self.assertEqual(site_id2, "example_com")
        
        url3 = "https://sub.domain.co.uk/path"
        site_id3 = generate_site_id(url3)
        self.assertEqual(site_id3, "sub_domain_co_uk")
    
    def test_extract_date_from_context(self):
        """Test date extraction from parser context"""
        context = {
            "page_date": "06/03/2026"
        }
        date = extract_date_from_context(context)
        self.assertEqual(date, "2026-03-06")
        
        # Test with date in PDF links
        context_no_page_date = {
            "pdf_links": [
                {"url": "https://example.com/2026-03-06.pdf"},
                {"url": "https://example.com/documento.pdf"}
            ]
        }
        date2 = extract_date_from_context(context_no_page_date)
        self.assertEqual(date2, "2026-03-06")
        
        # Test with no date (should return current date)
        context_no_date = {}
        date3 = extract_date_from_context(context_no_date)
        self.assertIsNotNone(date3)
        self.assertRegex(date3, r'\d{4}-\d{2}-\d{2}')
    
    @patch('index.requests.get')
    def test_download_pdf_success(self, mock_get):
        """Test successful PDF download"""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.headers = {'content-length': '1024'}
        mock_response.iter_content.return_value = [self.test_pdf_content]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        result = download_pdf("https://example.com/test.pdf")
        
        self.assertEqual(result, self.test_pdf_content)
        mock_get.assert_called_once()
    
    @patch('index.requests.get')
    def test_download_pdf_invalid_pdf(self, mock_get):
        """Test download of invalid PDF (non-PDF content)"""
        # Mock response with non-PDF content
        mock_response = MagicMock()
        mock_response.headers = {'content-length': '1024'}
        mock_response.iter_content.return_value = [b"Not a PDF file"]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        result = download_pdf("https://example.com/notpdf.pdf")
        
        self.assertIsNone(result)
    
    @patch('index.requests.get')
    def test_download_pdf_file_too_large(self, mock_get):
        """Test download of file exceeding size limit"""
        # Mock response with large file
        mock_response = MagicMock()
        mock_response.headers = {'content-length': str(60 * 1024 * 1024)}  # 60MB
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        result = download_pdf("https://example.com/large.pdf")
        
        self.assertIsNone(result)
    
    @patch('index.requests.get')
    def test_download_pdf_request_exception(self, mock_get):
        """Test download with request exception"""
        mock_get.side_effect = Exception("Connection error")
        
        result = download_pdf("https://example.com/test.pdf")
        
        self.assertIsNone(result)
    
    @patch('index.s3_client')
    def test_upload_to_s3_success(self, mock_s3):
        """Test successful S3 upload"""
        mock_s3.put_object.return_value = {}
        
        result = upload_to_s3(self.test_pdf_content, "test-bucket", "test-key.pdf")
        
        self.assertTrue(result)
        mock_s3.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="test-key.pdf",
            Body=self.test_pdf_content,
            ContentType='application/pdf',
            ServerSideEncryption='AES256'
        )
    
    @patch('index.s3_client')
    def test_upload_to_s3_failure(self, mock_s3):
        """Test S3 upload failure"""
        mock_s3.put_object.side_effect = Exception("S3 error")
        
        result = upload_to_s3(self.test_pdf_content, "test-bucket", "test-key.pdf")
        
        self.assertFalse(result)
    
    @patch('index.process_parser_output')
    def test_process_s3writer_output_success(self, mock_process):
        """Test successful processing of parser output"""
        # Mock successful downloads and uploads
        mock_process.return_value = {
            'success': True,
            'site_id': 'boletinoficial_gob_ar',
            'processed_count': 2
        }
        
        result = process_parser_output(self.test_parser_output)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['site_id'], 'boletinoficial_gob_ar')
        self.assertEqual(result['date'], '2026-03-06')
        self.assertEqual(result['processed_count'], 2)
        self.assertEqual(result['failed_count'], 0)
        self.assertEqual(result['total_found'], 2)
        self.assertEqual(len(result['uploaded_files']), 2)
        
        # Check uploaded files structure
        first_file = result['uploaded_files'][0]
        self.assertEqual(first_file['filename'], 'Boletín_Completo.pdf')
        self.assertIn('s3_key', first_file)
        self.assertIn('s3_uri', first_file)
        self.assertEqual(first_file['size'], len(self.test_pdf_content))
        
        # Verify download was called for each PDF
        self.assertEqual(mock_download.call_count, 2)
        # Verify upload was called for each PDF
        self.assertEqual(mock_upload.call_count, 2)
    
    @patch('index.process_parser_output')
    def test_process_s3writer_output_partial_failure(self, mock_process):
        """Test processing with some download failures"""
        # Mock one successful, one failed download
        mock_process.return_value = {
            'success': True,
            'processed_count': 1,
            'failed_count': 1,
            'uploaded_files': [self.test_parser_output["uploaded_files"][0]]
        }
        
        result = process_parser_output(self.test_parser_output)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['processed_count'], 1)
        self.assertEqual(result['failed_count'], 1)
        self.assertEqual(len(result['uploaded_files']), 1)
    
    def test_process_s3writer_output_parser_failure(self):
        """Test processing when parser output indicates failure"""
        failed_parser_output = {
            "success": False,
            "error": "Parser failed to extract PDFs"
        }
        
        result = process_parser_output(failed_parser_output)
        
        self.assertFalse(result['success'])
        self.assertIn('Parser output indicates failure', result['error'])
    
    def test_process_s3writer_output_no_pdfs(self):
        """Test processing with no PDF links found"""
        empty_parser_output = {
            "success": True,
            "url": "https://example.com",
            "pdf_links": [],
            "pdf_links_count": 0
        }
        
        result = process_s3writer_output(empty_parser_output)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['processed_count'], 0)
        self.assertEqual(result['message'], 'No PDF links found to process')
        self.assertEqual(len(result['uploaded_files']), 0)
    
    @patch('index.process_parser_output')
    def test_handler_http_event_success(self, mock_process):
        """Test handler with HTTP event (API Gateway)"""
        mock_process.return_value = {
            'success': True,
            'site_id': 'boletinoficial_gob_ar',
            'processed_count': 2
        }
        
        event = {
            "requestContext": {
                "http": {
                    "method": "POST"
                }
            },
            "body": json.dumps({
                "parser_output": self.test_parser_output
            })
        }
        
        result = handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        body = json.loads(result['body'])
        self.assertTrue(body['success'])
        self.assertEqual(body['site_id'], 'boletinoficial_gob_ar')
        mock_process.assert_called_once_with(self.test_parser_output)
    
    @patch('index.process_parser_output')
    def test_handler_direct_event_success(self, mock_process):
        """Test handler with direct Lambda invocation"""
        mock_process.return_value = {
            'success': True,
            'site_id': 'boletinoficial_gob_ar',
            'processed_count': 2
        }
        
        event = {
            "parser_output": self.test_parser_output
        }
        
        result = handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        body = json.loads(result['body'])
        self.assertTrue(body['success'])
        mock_process.assert_called_once_with(self.test_parser_output)
    
    def test_handler_missing_parser_output(self):
        """Test handler with missing parser_output parameter"""
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
        self.assertIn('Missing required parameter: parser_output', body['error'])
    
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

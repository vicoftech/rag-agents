import unittest
import json
import os
import sys
from unittest.mock import patch, MagicMock

# Add parent directory to path to import lambda functions
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from index import handler, fetch_boletin_by_url

class TestRAGFetcher(unittest.TestCase):
    """Unit tests for rag_lmbd_fetcher Lambda function"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_url = "https://www.boletinoficial.gob.ar/seccion/primera"
        self.test_html = """
        <html>
        <head><title>Boletín Oficial de la República Argentina</title></head>
        <body>
            <h1>Primera Sección - 06/03/2026</h1>
            <div class="content">
                <a href="/documentos/boletin-2026-03-06.pdf">Boletín Completo</a>
                <a href="https://www.boletinoficial.gob.ar/edicion/primera/20260306.pdf">Edición Primera</a>
            </div>
        </body>
        </html>
        """
    
    @patch('index.requests.get')
    def test_fetch_boletin_by_url_success(self, mock_get):
        """Test successful HTML fetching"""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.text = self.test_html
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        result = fetch_boletin_by_url(self.test_url)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['url'], self.test_url)
        self.assertIn('Boletín Oficial de la República Argentina', result['page_title'])
        self.assertIn('06/03/2026', result['page_date'])
        self.assertIn('raw_html', result)
        mock_get.assert_called_once_with(
            self.test_url, 
            headers=unittest.mock.ANY, 
            timeout=unittest.mock.ANY
        )
    
    @patch('index.requests.get')
    def test_fetch_boletin_by_url_request_exception(self, mock_get):
        """Test handling of request exceptions"""
        mock_get.side_effect = Exception("Connection error")
        
        result = fetch_boletin_by_url(self.test_url)
        
        self.assertFalse(result['success'])
        self.assertIn('Error fetching content', result['error'])
        self.assertEqual(result['url'], self.test_url)
    
    def test_handler_http_event_success(self):
        """Test handler with HTTP event (API Gateway)"""
        event = {
            "requestContext": {
                "http": {
                    "method": "POST"
                }
            },
            "body": json.dumps({
                "url": self.test_url
            })
        }
        
        with patch('index.fetch_boletin_by_url') as mock_fetch:
            mock_fetch.return_value = {
                'success': True,
                'url': self.test_url,
                'page_title': 'Test Title',
                'page_date': '06/03/2026',
                'raw_html': self.test_html
            }
            
            result = handler(event, None)
            
            self.assertEqual(result['statusCode'], 200)
            body = json.loads(result['body'])
            self.assertTrue(body['success'])
            self.assertEqual(body['url'], self.test_url)
    
    def test_handler_direct_event_success(self):
        """Test handler with direct Lambda invocation"""
        event = {
            "url": self.test_url
        }
        
        with patch('index.fetch_boletin_by_url') as mock_fetch:
            mock_fetch.return_value = {
                'success': True,
                'url': self.test_url,
                'page_title': 'Test Title',
                'page_date': '06/03/2026',
                'raw_html': self.test_html
            }
            
            result = handler(event, None)
            
            self.assertEqual(result['statusCode'], 200)
            body = json.loads(result['body'])
            self.assertTrue(body['success'])
            self.assertEqual(body['url'], self.test_url)
    
    def test_handler_options_request(self):
        """Test OPTIONS request for CORS"""
        event = {
            "requestContext": {
                "http": {
                    "method": "OPTIONS"
                }
            }
        }
        
        result = handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        self.assertIn('Access-Control-Allow-Origin', result['headers'])
        self.assertEqual(result['body'], "")
    
    def test_handler_missing_url_parameter(self):
        """Test handler with missing URL parameter"""
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
        self.assertIn('Missing required parameter', body['error'])
    
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

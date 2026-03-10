import unittest
import json
import os
import sys
from unittest.mock import patch, MagicMock

# Add parent directory to path to import lambda functions
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from index import handler, parse_html_content, extract_pdf_links

class TestRAGParser(unittest.TestCase):
    """Unit tests for rag_lmbd_parser Lambda function"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_html = """
        <html>
        <head><title>Boletín Oficial de la República Argentina</title></head>
        <body>
            <h1>Primera Sección - 06/03/2026</h1>
            <div class="content">
                <a href="/documentos/boletin-2026-03-06.pdf">Boletín Completo</a>
                <a href="https://www.boletinoficial.gob.ar/edicion/primera/20260306.pdf">Edición Primera</a>
                <a href="/secciones/segunda/20260306.pdf">Segunda Sección</a>
                <a href="/otros/documento.pdf">Otro Documento</a>
                <a href="/pagina.html">Página HTML (no PDF)</a>
                <a href="/download.php?file=resolucion-123.pdf">Resolución 123</a>
            </div>
        </body>
        </html>
        """
        self.base_url = "https://www.boletinoficial.gob.ar"
    
    def test_extract_pdf_links_success(self):
        """Test successful PDF link extraction"""
        result = extract_pdf_links(self.test_html, self.base_url)
        
        self.assertTrue(result['success'])
        self.assertEqual(len(result['pdf_links']), 5)
        
        # Check first PDF link
        first_pdf = result['pdf_links'][0]
        self.assertEqual(first_pdf['url'], 'https://www.boletinoficial.gob.ar/documentos/boletin-2026-03-06.pdf')
        self.assertEqual(first_pdf['text'], 'Boletín Completo')
        self.assertEqual(first_pdf['title'], 'Boletín Completo')
        self.assertEqual(first_pdf.get('section'), 'primera')
        
        # Check absolute URL handling
        absolute_pdf = next((pdf for pdf in result['pdf_links'] if 'edicion/primera' in pdf['url']), None)
        self.assertIsNotNone(absolute_pdf)
        self.assertTrue(absolute_pdf['url'].startswith('https://'))
    
    def test_extract_pdf_links_no_pdfs(self):
        """Test HTML with no PDF links"""
        html_no_pdfs = """
        <html>
        <body>
            <a href="/pagina.html">Página HTML</a>
            <a href="/otro.txt">Archivo de texto</a>
        </body>
        </html>
        """
        
        result = extract_pdf_links(html_no_pdfs, self.base_url)
        
        self.assertTrue(result['success'])
        self.assertEqual(len(result['pdf_links']), 0)
    
    def test_extract_pdf_links_empty_html(self):
        """Test with empty HTML"""
        result = extract_pdf_links("", self.base_url)
        
        self.assertTrue(result['success'])
        self.assertEqual(len(result['pdf_links']), 0)
    
    def test_extract_pdf_links_invalid_html(self):
        """Test with invalid HTML"""
        result = extract_pdf_links("<invalid html", self.base_url)
        
        self.assertTrue(result['success'])  # Should not crash
        self.assertEqual(len(result['pdf_links']), 0)
    
    def test_parse_html_content_success(self):
        """Test successful HTML parsing"""
        result = parse_html_content(self.test_html, self.base_url)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['page_title'], 'Boletín Oficial de la República Argentina')
        self.assertEqual(result['page_date'], '06/03/2026')
        self.assertEqual(result.get('section'), 'primera')
        self.assertEqual(result['pdf_links_count'], 5)
        self.assertGreater(result['total_links_found'], 5)
    
    def test_parse_html_content_with_base_url(self):
        """Test HTML parsing with base URL"""
        result = parse_html_content(self.test_html, self.base_url)
        
        self.assertTrue(result['success'])
        # Check that relative URLs are converted to absolute
        pdf_links = result['pdf_links']
        absolute_urls = [pdf.get('url') for pdf in pdf_links if isinstance(pdf, dict) and pdf.get('url', '').startswith('https://')]
        self.assertGreater(len(absolute_urls), 0)
    
    def test_handler_http_event_success(self):
        """Test handler with HTTP event (API Gateway)"""
        event = {
            "requestContext": {
                "http": {
                    "method": "POST"
                }
            },
            "body": json.dumps({
                "raw_html": self.test_html,
                "url": self.base_url
            })
        }
        
        result = handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        body = json.loads(result['body'])
        self.assertTrue(body['success'])
        self.assertEqual(body['page_title'], 'Boletín Oficial de la República Argentina')
        self.assertEqual(body.get('pdf_links_count'), 5)
    
    def test_handler_direct_event_success(self):
        """Test handler with direct Lambda invocation"""
        event = {
            "raw_html": self.test_html,
            "url": self.base_url
        }
        
        result = handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        body = json.loads(result['body'])
        self.assertTrue(body['success'])
        self.assertEqual(body['page_title'], 'Boletín Oficial de la República Argentina')
    
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
    
    def test_handler_missing_raw_html_parameter(self):
        """Test handler with missing raw_html parameter"""
        event = {
            "requestContext": {
                "http": {
                    "method": "POST"
                }
            },
            "body": json.dumps({
                "url": self.base_url
            })
        }
        
        result = handler(event, None)
        
        self.assertEqual(result['statusCode'], 400)
        body = json.loads(result['body'])
        self.assertIn('Missing required parameter: raw_html', body['error'])
    
    def test_handler_large_html_content(self):
        """Test handler with HTML content exceeding size limit"""
        # Create HTML larger than 5MB
        large_html = "<html>" + "x" * (5 * 1024 * 1024 + 1) + "</html>"
        
        event = {
            "requestContext": {
                "http": {
                    "method": "POST"
                }
            },
            "body": json.dumps({
                "raw_html": large_html,
                "url": self.base_url
            })
        }
        
        result = handler(event, None)
        
        self.assertEqual(result['statusCode'], 413)
        body = json.loads(result['body'])
        self.assertIn('HTML content too large', body['error'])
    
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

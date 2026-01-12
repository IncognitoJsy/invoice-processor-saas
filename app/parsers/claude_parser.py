"""Claude API-based invoice parser using vision - handles consolidated invoices"""
import anthropic
import os
import base64
import json
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

class ClaudeInvoiceParser:
    """Universal invoice parser using Claude's vision capabilities"""
    
    def __init__(self):
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        
        self.client = anthropic.Anthropic(
            api_key=api_key,
            max_retries=2
        )
        self.logger = logging.getLogger(__name__)
    
    def parse(self, pdf_path: str) -> Dict:
        """Parse invoice using Claude API - handles consolidated invoices"""
        try:
            self.logger.info(f"Claude parsing: {pdf_path}")
            
            # Read PDF file as binary and encode to base64
            with open(pdf_path, 'rb') as f:
                pdf_data = base64.standard_b64encode(f.read()).decode('utf-8')
            
            # Call Claude API with PDF document
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8192,  # Increased for consolidated invoices
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_data
                            }
                        },
                        {
                            "type": "text",
                            "text": self._get_extraction_prompt()
                        }
                    ]
                }]
            )
            
            # Parse response
            response_text = message.content[0].text
            self.logger.info(f"Claude response received: {len(response_text)} chars")
            
            return self._parse_response(response_text, pdf_path)
            
        except Exception as e:
            self.logger.error(f"Claude parsing error: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': f'Claude API error: {str(e)}'
            }
    
    def _get_extraction_prompt(self) -> str:
        """Get the prompt for invoice extraction"""
        return """You are an expert at extracting data from electrical supplier invoices (YESSS, CEF, Wholesale Electrics, etc).

CRITICAL: This PDF may contain MULTIPLE invoices (consolidated invoice). Each invoice has its own job reference and should be treated separately.

Extract all invoices and return ONLY valid JSON with no markdown formatting, no code blocks, no explanation:

{
    "invoices": [
        {
            "supplier": "name of supplier (e.g. YESSS Electrical, CEF, Wholesale Electrics)",
            "job_reference": "customer reference or job number (e.g. TLC, LA MAISON DE ST JEAN, DAVID HAZZARD)",
            "invoice_number": "invoice number if present",
            "total_net_amount": 2788.74,
            "items": [
                {
                    "part_number": "exact part number from invoice (e.g. JFG320U, WMSSU83, 221-415)",
                    "description": "complete item description, including all details even if multi-line",
                    "quantity": 2.0,
                    "original_unit_price": 1541.12,
                    "discount": "45",
                    "total_amount": 1695.23
                }
            ]
        }
    ]
}

CRITICAL RULES FOR CONSOLIDATED INVOICES:
1. **DETECT MULTIPLE ORDERS**: Look for job reference changes (e.g., "TLC" then "LA MAISON DE ST JEAN")
2. **SEPARATE EACH ORDER**: Create a separate entry in "invoices" array for each job reference
3. **GROUP ITEMS CORRECTLY**: Each invoice object should only contain items for that specific job reference
4. **CALCULATE TOTALS PER INVOICE**: total_net_amount should be the sum of all items for that specific job
5. **IGNORE BLANK PAGES**: Skip empty pages between invoices

STANDARD RULES:
6. Extract EVERY SINGLE item from the invoice - do not skip any
7. Part numbers must be EXACT as shown on invoice
8. Descriptions must be COMPLETE - include all text even if it spans multiple lines
9. Prices must be NUMERIC ONLY (no £, $, or currency symbols)
10. Discount is the percentage as a STRING (e.g. "45" not "45%" or 45)
11. original_unit_price is the price BEFORE discount is applied
12. total_amount is the final line total AFTER discount
13. If quantity is not explicitly shown, it's usually 1
14. Be very careful with decimal points - 1,541.12 means one thousand five hundred forty-one pounds

EXAMPLE: If you see three different job references (TLC, LA MAISON, DAVID), create THREE separate invoice objects in the array.

Double-check your work - missing items or wrong grouping costs real money!"""
    
    def _parse_response(self, text: str, pdf_path: str) -> Dict:
        """Parse Claude's JSON response - handles both single and consolidated invoices"""
        try:
            # Clean up response - remove markdown code blocks if present
            text = text.strip()
            if text.startswith('```'):
                lines = text.split('\n')
                text = '\n'.join(lines[1:-1])
            
            # Parse JSON
            data = json.loads(text)
            
            # Check if this is consolidated format (multiple invoices)
            if 'invoices' in data and isinstance(data['invoices'], list):
                self.logger.info(f"Detected consolidated invoice with {len(data['invoices'])} orders")
                return self._process_consolidated_invoices(data['invoices'], pdf_path)
            
            # Legacy single invoice format
            elif 'items' in data:
                self.logger.info("Detected single invoice format")
                return self._process_single_invoice(data)
            
            else:
                return {'success': False, 'error': 'No items or invoices found in response'}
            
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parse error: {str(e)}")
            self.logger.error(f"Response text: {text[:500]}")
            return {
                'success': False,
                'error': f'Failed to parse JSON response: {str(e)}'
            }
        except Exception as e:
            self.logger.error(f"Response parsing error: {str(e)}")
            return {
                'success': False,
                'error': f'Failed to process response: {str(e)}'
            }
    
    def _process_consolidated_invoices(self, invoices: List[Dict], pdf_path: str) -> Dict:
        """Process consolidated invoices - returns multiple invoice results"""
        results = []
        
        for idx, invoice_data in enumerate(invoices):
            try:
                items = self._transform_items(invoice_data.get('items', []))
                
                if not items:
                    continue
                
                results.append({
                    'success': True,
                    'items': items,
                    'job_reference': invoice_data.get('job_reference'),
                    'supplier': invoice_data.get('supplier', 'Unknown'),
                    'invoice_number': invoice_data.get('invoice_number'),
                    'method': 'claude_api',
                    'consolidated': True,
                    'order_number': idx + 1,
                    'total_orders': len(invoices)
                })
                
            except Exception as e:
                self.logger.error(f"Error processing invoice {idx + 1}: {str(e)}")
                continue
        
        if not results:
            return {'success': False, 'error': 'No valid invoices processed from consolidated PDF'}
        
        # Return as multiple invoices
        return {
            'success': True,
            'consolidated': True,
            'invoices': results,
            'method': 'claude_api'
        }
    
    def _process_single_invoice(self, data: Dict) -> Dict:
        """Process single invoice format (legacy/fallback)"""
        items = self._transform_items(data.get('items', []))
        
        if not items:
            return {'success': False, 'error': 'No items found'}
        
        return {
            'success': True,
            'items': items,
            'job_reference': data.get('job_reference'),
            'supplier': data.get('supplier', 'Unknown'),
            'method': 'claude_api',
            'consolidated': False
        }
    
    def _transform_items(self, items: List[Dict]) -> List[Dict]:
        """Transform items to our internal format with pricing"""
        transformed = []
        
        for item in items:
            try:
                # Calculate cost per item
                quantity = float(item['quantity'])
                total_amount = float(item['total_amount'])
                cost_per_item = round(total_amount / quantity, 2) if quantity > 0 else 0
                
                # Get discount
                discount = str(item.get('discount', '0')).replace('%', '')
                discount_val = float(discount) if discount else 0
                
                # Apply pricing logic based on discount
                if discount_val == 0:
                    markup = 0.20
                elif 1 <= discount_val <= 30:
                    markup = 0.40
                elif 30 < discount_val <= 70:
                    markup = 0.50
                else:
                    markup = 0.70
                
                selling_price = round(cost_per_item * (1 + markup), 2)
                profit_per_item = round(selling_price - cost_per_item, 2)
                
                transformed.append({
                    'part_number': item['part_number'],
                    'description': item['description'],
                    'quantity': quantity,
                    'original_unit_price': float(item.get('original_unit_price', 0)),
                    'discount': discount,
                    'cost_per_item': cost_per_item,
                    'total_amount': total_amount,
                    'selling_price': selling_price,
                    'markup_percent': int(markup * 100),
                    'profit_per_item': profit_per_item
                })
            except Exception as e:
                self.logger.error(f"Error processing item: {str(e)}")
                continue
        
        return transformed

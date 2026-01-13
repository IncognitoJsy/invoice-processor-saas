"""Claude API-based invoice parser using vision - handles consolidated invoices"""
import anthropic
import os
import base64
import json
import logging
import re
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

CRITICAL: This PDF may also contain CREDIT NOTES mixed with invoices. You MUST identify each document type.

Extract all invoices and return ONLY valid JSON with no markdown formatting, no code blocks, no explanation:

{
    "invoices": [
        {
            "document_type": "invoice" or "credit_note",
            "supplier": "name of supplier (e.g. YESSS Electrical, CEF, Wholesale Electrics)",
            "invoice_number": "EXACT invoice number as shown on document - THIS IS CRITICAL",
            "job_reference": "customer reference or job number (e.g. TLC, LA MAISON DE ST JEAN, DAVID HAZZARD)",
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

INVOICE NUMBER EXTRACTION - VERY IMPORTANT:
1. **CEF**: Invoice number is in TOP RIGHT, starts with "JER" (e.g., JER753997, JER765610)
2. **YESSS**: Invoice number is directly under "INVOICE NUMBER" text, starts with "093" (e.g., 0931234567)
3. **Wholesale Electrics**: Invoice number is below "INVOICE NUMBER" text, starts with "IN" (e.g., IN123456)
4. Extract the EXACT invoice number - do not modify or abbreviate it

DOCUMENT TYPE DETECTION:
5. **INVOICE**: Normal purchase document - process normally
6. **CREDIT NOTE**: Has "CREDIT" or "CREDIT NOTE" prominently displayed, negative amounts, or reference to returned goods
7. Mark document_type as "credit_note" if it's a credit - we will skip these

CRITICAL RULES FOR CONSOLIDATED INVOICES:
8. **DETECT MULTIPLE ORDERS**: Look for job reference changes (e.g., "TLC" then "LA MAISON DE ST JEAN")
9. **SEPARATE EACH ORDER**: Create a separate entry in "invoices" array for each job reference
10. **GROUP ITEMS CORRECTLY**: Each invoice object should only contain items for that specific job reference
11. **CALCULATE TOTALS PER INVOICE**: total_net_amount should be the sum of all items for that specific job
12. **IGNORE BLANK PAGES**: Skip empty pages between invoices

STANDARD RULES:
13. Extract EVERY SINGLE item from the invoice - do not skip any
14. Part numbers must be EXACT as shown on invoice
15. Descriptions must be COMPLETE - include all text even if it spans multiple lines
16. Prices must be NUMERIC ONLY (no £, $, or currency symbols)
17. Discount is the percentage as a STRING (e.g. "45" not "45%" or 45)
18. original_unit_price is the price BEFORE discount is applied
19. total_amount is the final line total AFTER discount
20. If quantity is not explicitly shown, it's usually 1
21. Be very careful with decimal points - 1,541.12 means one thousand five hundred forty-one pounds

EXAMPLE: If you see three different job references (TLC, LA MAISON, DAVID), create THREE separate invoice objects in the array.

Double-check your work - missing items, wrong invoice numbers, or wrong grouping costs real money!"""
    
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
                self.logger.info(f"Detected consolidated invoice with {len(data['invoices'])} documents")
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
        """Process consolidated invoices - returns multiple invoice results, skips credit notes"""
        results = []
        skipped_credits = 0
        
        for idx, invoice_data in enumerate(invoices):
            try:
                # Check if this is a credit note - skip it
                doc_type = invoice_data.get('document_type', 'invoice').lower()
                if doc_type == 'credit_note' or 'credit' in doc_type:
                    self.logger.info(f"Skipping credit note: {invoice_data.get('invoice_number', 'unknown')}")
                    skipped_credits += 1
                    continue
                
                items = self._transform_items(invoice_data.get('items', []))
                
                if not items:
                    continue
                
                # Validate and clean invoice number
                invoice_number = self._clean_invoice_number(
                    invoice_data.get('invoice_number'),
                    invoice_data.get('supplier', '')
                )
                
                results.append({
                    'success': True,
                    'items': items,
                    'job_reference': invoice_data.get('job_reference'),
                    'supplier': invoice_data.get('supplier', 'Unknown'),
                    'invoice_number': invoice_number,
                    'document_type': 'invoice',
                    'method': 'claude_api',
                    'consolidated': True,
                    'order_number': idx + 1,
                    'total_orders': len(invoices)
                })
                
            except Exception as e:
                self.logger.error(f"Error processing invoice {idx + 1}: {str(e)}")
                continue
        
        if skipped_credits > 0:
            self.logger.info(f"Skipped {skipped_credits} credit note(s)")
        
        if not results:
            if skipped_credits > 0:
                return {'success': False, 'error': f'All {skipped_credits} documents were credit notes - nothing to process'}
            return {'success': False, 'error': 'No valid invoices processed from consolidated PDF'}
        
        # Return as multiple invoices
        return {
            'success': True,
            'consolidated': True,
            'invoices': results,
            'skipped_credits': skipped_credits,
            'method': 'claude_api'
        }
    
    def _process_single_invoice(self, data: Dict) -> Dict:
        """Process single invoice format (legacy/fallback)"""
        # Check if this is a credit note
        doc_type = data.get('document_type', 'invoice').lower()
        if doc_type == 'credit_note' or 'credit' in doc_type:
            return {
                'success': False, 
                'error': 'Document is a credit note - skipping',
                'is_credit_note': True
            }
        
        items = self._transform_items(data.get('items', []))
        
        if not items:
            return {'success': False, 'error': 'No items found'}
        
        # Validate and clean invoice number
        invoice_number = self._clean_invoice_number(
            data.get('invoice_number'),
            data.get('supplier', '')
        )
        
        return {
            'success': True,
            'items': items,
            'job_reference': data.get('job_reference'),
            'supplier': data.get('supplier', 'Unknown'),
            'invoice_number': invoice_number,
            'document_type': 'invoice',
            'method': 'claude_api',
            'consolidated': False
        }
    
    def _clean_invoice_number(self, invoice_number: str, supplier: str) -> str:
        """Clean and validate invoice number based on supplier patterns"""
        if not invoice_number:
            return None
        
        # Remove any whitespace
        invoice_number = str(invoice_number).strip()
        
        supplier_lower = supplier.lower() if supplier else ''
        
        # Validate pattern based on supplier
        if 'cef' in supplier_lower:
            # CEF: Should start with JER
            if not invoice_number.upper().startswith('JER'):
                # Try to extract JER number from the string
                match = re.search(r'(JER\d+)', invoice_number, re.IGNORECASE)
                if match:
                    invoice_number = match.group(1).upper()
            else:
                invoice_number = invoice_number.upper()
                
        elif 'yesss' in supplier_lower:
            # YESSS: Should start with 093
            if not invoice_number.startswith('093'):
                # Try to extract 093 number
                match = re.search(r'(093\d+)', invoice_number)
                if match:
                    invoice_number = match.group(1)
                    
        elif 'wholesale' in supplier_lower:
            # Wholesale: Should start with IN
            if not invoice_number.upper().startswith('IN'):
                # Try to extract IN number
                match = re.search(r'(IN\d+)', invoice_number, re.IGNORECASE)
                if match:
                    invoice_number = match.group(1).upper()
            else:
                invoice_number = invoice_number.upper()
        
        return invoice_number
    
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

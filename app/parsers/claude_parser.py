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
    
    def parse(self, pdf_path: str, expected_document_type: str = 'invoice', user_markup_settings: Dict = None) -> Dict:
        """
        Parse invoice using Claude API - handles consolidated invoices
        
        Args:
            pdf_path: Path to PDF file
            expected_document_type: 'invoice' or 'quote' - what the user selected
            user_markup_settings: Dict with 'is_admin' and 'default_markup' keys
        """
        try:
            self.logger.info(f"Claude parsing: {pdf_path}")
            self.logger.info(f"Expected document type: {expected_document_type}")
            self.logger.info(f"User markup settings: {user_markup_settings}")
            
            # Store markup settings for use in transform
            self.user_markup_settings = user_markup_settings or {'is_admin': False, 'default_markup': 50.0}
            
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
            
            return self._parse_response(response_text, pdf_path, expected_document_type)
            
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
        return """You are an expert at extracting data from electrical supplier invoices and quotations (YESSS, CEF, Wholesale Electrics, etc).

CRITICAL: First, identify what TYPE of document this is by looking for keywords:
- QUOTATION, QUOTE, ESTIMATE, PROFORMA = This is a QUOTE
- INVOICE, TAX INVOICE, BILL = This is an INVOICE  
- CREDIT, CREDIT NOTE = This is a CREDIT NOTE

CRITICAL: This PDF may contain MULTIPLE invoices/quotes (consolidated). Each has its own job reference and should be treated separately.

Extract all documents and return ONLY valid JSON with no markdown formatting, no code blocks, no explanation:

{
    "detected_document_type": "invoice" or "quote" or "credit_note",
    "invoices": [
        {
            "document_type": "invoice" or "quote" or "credit_note",
            "supplier": "name of supplier (e.g. YESSS Electrical, CEF, Wholesale Electrics)",
            "invoice_number": "EXACT invoice/quote number as shown on document - THIS IS CRITICAL",
            "job_reference": "customer reference or job number (e.g. TLC, LA MAISON DE ST JEAN, DAVID HAZZARD, SARAH HOLT)",
            "total_net_amount": 2788.74,
            "items": [
                {
                    "part_number": "exact part number from document (e.g. JFG320U, WMSSU83, 221-415, HV3PROAAUB075T2)",
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

DOCUMENT TYPE DETECTION - VERY IMPORTANT:
1. **QUOTE/QUOTATION**: Look for "QUOTATION", "QUOTE", "ESTIMATE", "PROFORMA" prominently displayed at top
2. **INVOICE**: Look for "INVOICE", "TAX INVOICE", "BILL" prominently displayed
3. **CREDIT NOTE**: Has "CREDIT" or "CREDIT NOTE" prominently displayed, negative amounts
4. Set "detected_document_type" to the OVERALL type of the PDF (what's shown at the top)
5. Set each document's "document_type" accordingly

INVOICE/QUOTE NUMBER EXTRACTION - VERY IMPORTANT:
6. **CEF**: Number is in TOP RIGHT, starts with "JER" (e.g., JER753997, JER765610)
7. **YESSS Invoices**: Number is under "INVOICE NUMBER", starts with "093" (e.g., 0931234567)
8. **YESSS Quotes**: Number is under "DOCUMENT NUMBER", format like "093QO69883"
9. **Wholesale Electrics**: Number is below "INVOICE NUMBER", starts with "IN" (e.g., IN123456)
10. Extract the EXACT number - do not modify or abbreviate it

CRITICAL RULES FOR CONSOLIDATED DOCUMENTS:
11. **DETECT MULTIPLE ORDERS**: Look for job reference changes
12. **SEPARATE EACH ORDER**: Create a separate entry in "invoices" array for each job reference
13. **GROUP ITEMS CORRECTLY**: Each entry should only contain items for that specific job reference
14. **CALCULATE TOTALS PER DOCUMENT**: total_net_amount should be the sum of all items for that specific job

CRITICAL PRICING RULES FOR WHOLESALE ELECTRICS:
15. For Wholesale Electrics invoices, the "Amount" column shows price BEFORE discount
16. The discount percentage is shown separately (e.g. "51.00%", "77.50%", "90.00%")
17. Extract total_amount as the BEFORE-discount amount from the Amount column
18. Extract discount as just the number (e.g. "51" not "51%")
19. The actual cost will be calculated by applying: total_amount * (1 - discount/100)

STANDARD RULES:
20. Extract EVERY SINGLE item from the document - do not skip any
21. Part numbers must be EXACT as shown on document
22. Descriptions must be COMPLETE - include all text even if it spans multiple lines
23. Prices must be NUMERIC ONLY (no £, $, or currency symbols)
24. Discount is the percentage as a STRING (e.g. "45" not "45%" or 45)
25. original_unit_price is the price BEFORE discount is applied
26. total_amount is the line total shown in the Amount column
27. If quantity is not explicitly shown, it's usually 1
28. Be very careful with decimal points - 1,541.12 means one thousand five hundred forty-one pounds

Double-check your work - missing items, wrong document type, or wrong grouping costs real money!"""
    
    def _parse_response(self, text: str, pdf_path: str, expected_document_type: str = 'invoice') -> Dict:
        """Parse Claude's JSON response - handles both single and consolidated invoices"""
        try:
            # Clean up response - remove markdown code blocks if present
            text = text.strip()
            if text.startswith('```'):
                lines = text.split('\n')
                text = '\n'.join(lines[1:-1])
            
            # Parse JSON
            data = json.loads(text)
            
            # Check detected document type vs expected
            detected_type = data.get('detected_document_type', 'invoice').lower()
            
            # Normalize detected type
            if detected_type in ['quote', 'quotation', 'estimate', 'proforma']:
                detected_type = 'quote'
            elif detected_type in ['invoice', 'tax invoice', 'bill']:
                detected_type = 'invoice'
            elif detected_type in ['credit', 'credit_note', 'credit note']:
                detected_type = 'credit_note'
            
            self.logger.info(f"Detected document type: {detected_type}, Expected: {expected_document_type}")
            
            # Validate document type matches what user selected
            if detected_type == 'credit_note':
                return {
                    'success': False,
                    'error': 'This document is a Credit Note and cannot be processed.',
                    'is_credit_note': True,
                    'detected_document_type': detected_type
                }
            
            if detected_type != expected_document_type:
                # Mismatch - return error with helpful message
                if detected_type == 'quote' and expected_document_type == 'invoice':
                    return {
                        'success': False,
                        'error': 'This appears to be a QUOTATION, not an Invoice. Please select "Supplier Quote" and upload again.',
                        'document_type_mismatch': True,
                        'detected_document_type': detected_type,
                        'expected_document_type': expected_document_type
                    }
                elif detected_type == 'invoice' and expected_document_type == 'quote':
                    return {
                        'success': False,
                        'error': 'This appears to be an INVOICE, not a Quote. Please select "Supplier Invoice" and upload again.',
                        'document_type_mismatch': True,
                        'detected_document_type': detected_type,
                        'expected_document_type': expected_document_type
                    }
            
            # Check if this is consolidated format (multiple invoices)
            if 'invoices' in data and isinstance(data['invoices'], list):
                self.logger.info(f"Detected consolidated document with {len(data['invoices'])} entries")
                return self._process_consolidated_invoices(data['invoices'], pdf_path, expected_document_type)
            
            # Legacy single invoice format
            elif 'items' in data:
                self.logger.info("Detected single document format")
                return self._process_single_invoice(data, expected_document_type)
            
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
    
    def _process_consolidated_invoices(self, invoices: List[Dict], pdf_path: str, expected_document_type: str = 'invoice') -> Dict:
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
                
                # Get supplier to determine pricing logic
                supplier = invoice_data.get('supplier', 'Unknown')
                items = self._transform_items(invoice_data.get('items', []), supplier)
                
                if not items:
                    continue
                
                # Validate and clean invoice number
                invoice_number = self._clean_invoice_number(
                    invoice_data.get('invoice_number'),
                    supplier
                )
                
                results.append({
                    'success': True,
                    'items': items,
                    'job_reference': invoice_data.get('job_reference'),
                    'supplier': supplier,
                    'invoice_number': invoice_number,
                    'document_type': expected_document_type,
                    'method': 'claude_api',
                    'consolidated': True,
                    'order_number': idx + 1,
                    'total_orders': len(invoices)
                })
                
            except Exception as e:
                self.logger.error(f"Error processing document {idx + 1}: {str(e)}")
                continue
        
        if skipped_credits > 0:
            self.logger.info(f"Skipped {skipped_credits} credit note(s)")
        
        if not results:
            if skipped_credits > 0:
                return {'success': False, 'error': f'All {skipped_credits} documents were credit notes - nothing to process'}
            return {'success': False, 'error': 'No valid documents processed from consolidated PDF'}
        
        # Return as multiple invoices
        return {
            'success': True,
            'consolidated': True,
            'invoices': results,
            'skipped_credits': skipped_credits,
            'method': 'claude_api',
            'document_type': expected_document_type
        }
    
    def _process_single_invoice(self, data: Dict, expected_document_type: str = 'invoice') -> Dict:
        """Process single invoice format (legacy/fallback)"""
        # Check if this is a credit note
        doc_type = data.get('document_type', 'invoice').lower()
        if doc_type == 'credit_note' or 'credit' in doc_type:
            return {
                'success': False, 
                'error': 'Document is a credit note - skipping',
                'is_credit_note': True
            }
        
        # Get supplier to determine pricing logic
        supplier = data.get('supplier', 'Unknown')
        items = self._transform_items(data.get('items', []), supplier)
        
        if not items:
            return {'success': False, 'error': 'No items found'}
        
        # Validate and clean invoice number
        invoice_number = self._clean_invoice_number(
            data.get('invoice_number'),
            supplier
        )
        
        return {
            'success': True,
            'items': items,
            'job_reference': data.get('job_reference'),
            'supplier': supplier,
            'invoice_number': invoice_number,
            'document_type': expected_document_type,
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
                match = re.search(r'(093\w+)', invoice_number)
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
    
    def _get_admin_tiered_markup(self, discount_val: float) -> float:
        """Get markup for admin user based on discount tiers"""
        if discount_val == 0:
            return 0.20  # 20% markup
        elif 1 <= discount_val <= 30:
            return 0.40  # 40% markup
        elif 30 < discount_val <= 70:
            return 0.50  # 50% markup
        else:
            return 0.70  # 70% markup
    
    def _transform_items(self, items: List[Dict], supplier: str = 'Unknown') -> List[Dict]:
        """Transform items to our internal format with pricing
        
        Admin users: Use tiered markup based on discount percentage
        Regular users: Use their flat default_markup setting
        """
        transformed = []
        supplier_lower = supplier.lower() if supplier else ''
        
        # Get user markup settings
        is_admin = self.user_markup_settings.get('is_admin', False)
        user_default_markup = self.user_markup_settings.get('default_markup', 50.0) / 100  # Convert to decimal
        
        self.logger.info(f"Transform items: is_admin={is_admin}, user_markup={user_default_markup*100}%")
        
        for item in items:
            try:
                quantity = float(item['quantity'])
                total_amount = float(item['total_amount'])  # This is BEFORE discount for Wholesale
                
                # Get discount percentage
                discount = str(item.get('discount', '0')).replace('%', '')
                discount_val = float(discount) if discount else 0
                
                # Apply discount to get actual cost
                # For Wholesale Electrics, total_amount is BEFORE discount
                if discount_val > 0:
                    discounted_total = total_amount * (1 - discount_val / 100)
                else:
                    discounted_total = total_amount
                
                cost_per_item = round(discounted_total / quantity, 2) if quantity > 0 else 0
                
                # Determine markup based on user type
                if is_admin:
                    # Admin uses tiered markup based on discount
                    markup = self._get_admin_tiered_markup(discount_val)
                else:
                    # Regular users use their flat markup setting
                    markup = user_default_markup
                
                selling_price = round(cost_per_item * (1 + markup), 2)
                profit_per_item = round(selling_price - cost_per_item, 2)
                
                transformed.append({
                    'part_number': item['part_number'],
                    'description': item['description'],
                    'quantity': quantity,
                    'original_unit_price': float(item.get('original_unit_price', 0)),
                    'discount': discount,
                    'cost_per_item': cost_per_item,
                    'total_amount': discounted_total,  # Store the DISCOUNTED total
                    'selling_price': selling_price,
                    'markup_percent': int(markup * 100),
                    'profit_per_item': profit_per_item
                })
            except Exception as e:
                self.logger.error(f"Error processing item: {str(e)}")
                continue
        
        return transformed

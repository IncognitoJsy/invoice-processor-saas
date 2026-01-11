"""Claude API-based invoice parser using vision"""
import anthropic
import os
"""Claude API-based invoice parser using vision"""
import anthropic
import os
import base64
import json
import logging
from typing import Dict, List
from pdf2image import convert_from_path
import io

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
        """Parse invoice using Claude API with vision"""
        try:
            self.logger.info(f"Claude parsing: {pdf_path}")
            
            # Convert PDF to images (first 2 pages)
            images = convert_from_path(pdf_path, first_page=1, last_page=2, dpi=200)
            
            if not images:
                return {'success': False, 'error': 'Could not convert PDF to images'}
            
            # Encode images to base64
            image_data = []
            for img in images[:2]:  # Max 2 pages
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='PNG')
                img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode()
                image_data.append(img_base64)
            
            # Call Claude API
            message_content = []
            
            # Add images
            for img_base64 in image_data:
                message_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_base64
                    }
                })
            
            # Add text prompt
            message_content.append({
                "type": "text",
                "text": self._get_extraction_prompt()
            })
            
            # Make API call
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": message_content
                }]
            )
            
            # Parse response
            response_text = message.content[0].text
            self.logger.info(f"Claude response received: {len(response_text)} chars")
            
            return self._parse_response(response_text)
            
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

Extract ALL items from this invoice and return ONLY valid JSON with no markdown formatting, no code blocks, no explanation:

{
    "supplier": "name of supplier (e.g. YESSS Electrical, CEF, Wholesale Electrics)",
    "job_reference": "customer reference or job number if present, otherwise null",
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

CRITICAL RULES:
1. Extract EVERY SINGLE item from the invoice - do not skip any
2. Part numbers must be EXACT as shown on invoice
3. Descriptions must be COMPLETE - include all text even if it spans multiple lines
4. Prices must be NUMERIC ONLY (no £, $, or currency symbols)
5. Discount is the percentage as a STRING (e.g. "45" not "45%" or 45)
6. original_unit_price is the price BEFORE discount is applied
7. total_amount is the final line total AFTER discount
8. If quantity is not explicitly shown, it's usually 1
9. Be very careful with decimal points - 1,541.12 means one thousand five hundred forty-one pounds
10. For consolidated invoices with multiple orders, extract ALL items from ALL orders

Double-check your work - missing items or wrong prices costs real money!"""
    
    def _parse_response(self, text: str) -> Dict:
        """Parse Claude's JSON response and transform to our format"""
        try:
            # Clean up response - remove markdown code blocks if present
            text = text.strip()
            if text.startswith('```'):
                # Remove ```json and ``` markers
                lines = text.split('\n')
                text = '\n'.join(lines[1:-1])
            
            # Parse JSON
            data = json.loads(text)
            
            # Validate required fields
            if 'items' not in data:
                return {'success': False, 'error': 'No items found in response'}
            
            # Transform items to our format
            items = []
            for item in data.get('items', []):
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
                    
                    items.append({
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
            
            return {
                'success': True,
                'items': items,
                'job_reference': data.get('job_reference'),
                'supplier': data.get('supplier', 'Unknown'),
                'method': 'claude_api'
            }
            
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
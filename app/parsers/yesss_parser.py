"""YESSS Electrical invoice parser - FIXED VERSION"""
import re
import logging
from typing import Dict, List, Optional
from app.parsers.base_parser import BaseInvoiceParser
import pdfplumber

logger = logging.getLogger(__name__)

class YesssInvoiceParser(BaseInvoiceParser):
    """Parser for YESSS Electrical invoices"""

    def __init__(self):
        super().__init__()
        self.supplier_name = 'YESSS'

    def detect(self, filepath: str) -> bool:
        """Detect if this is a YESSS invoice"""
        try:
            with pdfplumber.open(filepath) as pdf:
                first_page_text = pdf.pages[0].extract_text() or ''
                return 'YESSS ELECTRICAL' in first_page_text.upper()
        except:
            return False

    def extract_job_reference(self, text: str) -> Optional[str]:
        """Extract job reference from YESSS invoice"""
        patterns = [
            r'YOUR ORDER REFERENCE[:\s]+([A-Z0-9\s\-/]+?)(?:\s+DATE|\s+INVOICE|\n)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                job_ref = match.group(1).strip()
                job_ref = re.sub(r'\s+', ' ', job_ref)
                if job_ref and len(job_ref) > 2:
                    return job_ref
        return None

    def parse(self, filepath: str) -> Dict:
        """Parse YESSS invoice using table extraction"""
        try:
            with pdfplumber.open(filepath) as pdf:
                page = pdf.pages[0]
                text = page.extract_text()
                
                job_reference = self.extract_job_reference(text)
                
                tables = page.extract_tables()
                items = []
                
                if tables:
                    main_table = tables[0] if tables else None
                    
                    if main_table and len(main_table) > 1:
                        for row in main_table[1:]:
                            if not row or len(row) < 4:
                                continue
                            
                            try:
                                qty_str = str(row[0] or '').strip()
                                part_no = str(row[1] or '').strip()
                                desc = str(row[2] or '').strip()
                                price_str = str(row[3] or '').strip()
                                discount_str = str(row[6] or '0').strip() if len(row) > 6 else '0'
                                amount_str = str(row[7] or '0').strip() if len(row) > 7 else '0'
                                
                                if not qty_str or not part_no:
                                    continue
                                
                                quantity = float(qty_str)
                                original_price = float(price_str)
                                
                                discount_pct = 0
                                if discount_str.isdigit() and len(discount_str) <= 3:
                                    discount_pct = float(discount_str)
                                
                                amount_clean = amount_str.replace('R', '').strip()
                                total_amount = float(amount_clean)
                                
                                price_per = original_price * (1 - discount_pct / 100) if discount_pct > 0 else original_price
                                cost_per_item = total_amount / quantity if quantity > 0 else price_per
                                
                                item = {
                                    'part_number': part_no,
                                    'description': desc,
                                    'quantity': quantity,
                                    'price_per': price_per,
                                    'discount': f'{discount_pct}%',
                                    'total_amount': total_amount,
                                    'cost_per_item': cost_per_item,
                                    'original_price': original_price,
                                }
                                
                                items.append(item)
                                
                            except Exception as e:
                                logger.error(f"Error parsing row: {e}")
                                continue
                
                total = sum(item['total_amount'] for item in items)
                
                return {
                    'supplier': self.supplier_name,
                    'items': items,
                    'invoice_number': None,
                    'invoice_date': None,
                    'job_reference': job_reference,
                    'total': total
                }
                
        except Exception as e:
            logger.error(f"Error parsing YESSS invoice: {e}")
            return {
                'supplier': self.supplier_name,
                'items': [],
                'job_reference': None,
                'total': 0
            }

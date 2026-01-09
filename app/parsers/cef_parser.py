"""CEF invoice parser with rotation handling"""
import re
import logging
from typing import Dict, List, Optional
from app.parsers.base_parser import BaseInvoiceParser
import pdfplumber
from PIL import Image
import io

logger = logging.getLogger(__name__)

class CEFInvoiceParser(BaseInvoiceParser):
    """Parser for CEF invoices (handles 90-degree rotation)"""

    def __init__(self):
        super().__init__()
        self.supplier_name = 'CEF'

    def detect(self, filepath: str) -> bool:
        """Detect if this is a CEF invoice"""
        try:
            with pdfplumber.open(filepath) as pdf:
                # Try normal orientation first
                first_page_text = pdf.pages[0].extract_text() or ''
                if 'C.E.F.' in first_page_text or 'CEF' in first_page_text or 'City Electrical' in first_page_text:
                    return True
                
                # Try rotated (CEF invoices are often sideways)
                # Check page dimensions - if width > height, likely rotated
                page = pdf.pages[0]
                if page.width > page.height:
                    logger.info("CEF invoice appears to be rotated")
                    return True
                    
                return False
        except Exception as e:
            logger.error(f"Error detecting CEF: {e}")
            return False

    def calculate_markup(self, discount_percent):
        """Calculate markup based on discount received"""
        if discount_percent == 0:
            return 0.20
        elif 1 <= discount_percent <= 30:
            return 0.40
        elif 30 < discount_percent <= 70:
            return 0.50
        else:
            return 0.70

    def extract_job_reference(self, text):
        """Extract job reference from CEF invoice"""
        import re
        # CEF format: "Your Order Number: XXXXX"
        patterns = [
            r'Your Order Number[:\s]+([A-Z0-9][A-Z0-9\s\-]+?)(?:\n|\s+Page|$)',
            r'Order Number[:\s]+([A-Z0-9][A-Z0-9\s\-]+?)(?:\n|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                job_ref = match.group(1).strip()
                job_ref = ' '.join(job_ref.split())
                if job_ref and len(job_ref) > 1:
                    return job_ref
        return None

    def parse(self, filepath: str) -> Dict:
        """Parse CEF invoice with rotation handling"""
        items = []
        try:
            with pdfplumber.open(filepath) as pdf:
                page = pdf.pages[0]
                
                # Check if page is rotated (landscape)
                if page.width > page.height:
                    logger.info(f"Rotating CEF invoice (width={page.width}, height={page.height})")
                    # Rotate page 270 degrees (counter-clockwise) to correct 90-degree clockwise rotation
                    page = page.rotate(270)
                
                text = page.extract_text() or ''
                logger.info(f"Extracted text length: {len(text)}")
                
                # Extract job reference
                job_reference = self.extract_job_reference(text)
                logger.info(f"Job reference: {job_reference}")
                
                # Extract table
                tables = page.extract_tables()
                logger.info(f"Found {len(tables)} tables")
                
                if tables:
                    for table_idx, table in enumerate(tables):
                        logger.info(f"Table {table_idx}: {len(table)} rows")
                        if not table or len(table) < 2:
                            continue
                        
                        # Log first few rows to debug
                        for i in range(min(3, len(table))):
                            logger.info(f"  Row {i}: {table[i]}")
                        
                        # Find header row
                        header_row = None
                        for i, row in enumerate(table):
                            row_text = ' '.join([str(cell or '') for cell in row]).lower()
                            logger.info(f"Checking row {i} for headers: {row_text[:100]}")
                            if 'item' in row_text or 'description' in row_text or 'qty' in row_text:
                                header_row = i
                                logger.info(f"Found header row at {i}")
                                break
                        
                        if header_row is None:
                            logger.info("No header row found")
                            continue
                        
                        # Process data rows
                        for row in table[header_row + 1:]:
                            if not row or len(row) < 4:
                                continue
                            
                            try:
                                # CEF format: Qty | Item | Description | Price Per | Discount | £ | Goods v
                                qty_str = str(row[0] or '').strip()
                                part_no = str(row[1] or '').strip()
                                desc = str(row[2] or '').strip()
                                price_str = str(row[3] or '').strip()
                                discount_str = str(row[4] or '0').strip() if len(row) > 4 else '0'
                                total_str = str(row[5] or '0').strip() if len(row) > 5 else '0'
                                
                                # Skip if not valid
                                if not qty_str or not part_no or qty_str.lower() in ['qty', 'quantity']:
                                    continue
                                
                                # Parse values
                                quantity = float(qty_str)
                                
                                # Parse price (remove "each" or other text)
                                price_clean = price_str.split()[0] if price_str else '0'
                                original_price = float(price_clean)
                                
                                # Parse discount (remove % sign)
                                discount_pct = 0
                                if discount_str and discount_str.replace('%', '').replace('.', '').isdigit():
                                    discount_pct = float(discount_str.replace('%', ''))
                                
                                # Parse total
                                total_clean = total_str.replace('£', '').strip()
                                total_amount = float(total_clean) if total_clean else 0
                                
                                # Calculate cost per item
                                cost_per_item = total_amount / quantity if quantity > 0 else original_price
                                
                                # Calculate selling price with markup
                                markup = self.calculate_markup(discount_pct)
                                selling_price = round(cost_per_item * (1 + markup), 2)
                                profit_per_item = round(selling_price - cost_per_item, 2)
                                
                                # Calculate original unit price
                                if discount_pct > 0:
                                    original_unit_price = round(cost_per_item / (1 - discount_pct / 100), 2)
                                else:
                                    original_unit_price = cost_per_item
                                
                                item = {
                                    'part_number': part_no,
                                    'description': desc,
                                    'quantity': quantity,
                                    'price_per': original_price,
                                    'discount': f'{discount_pct}%' if discount_pct > 0 else '0%',
                                    'total_amount': total_amount,
                                    'cost_per_item': round(cost_per_item, 2),
                                    'original_price': original_price,
                                    'original_unit_price': original_unit_price,
                                    'selling_price': selling_price,
                                    'profit_per_item': profit_per_item,
                                    'markup_percent': int(markup * 100)
                                }
                                
                                items.append(item)
                                logger.info(f"Parsed CEF item: {part_no}")
                                
                            except Exception as e:
                                logger.error(f"Error parsing CEF row: {e}")
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
            logger.error(f"Error parsing CEF invoice: {e}", exc_info=True)
            return {
                'supplier': self.supplier_name,
                'items': [],
                'job_reference': None,
                'total': 0
            }

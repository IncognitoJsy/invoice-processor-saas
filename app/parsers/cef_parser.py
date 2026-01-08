"""CEF invoice parser"""
import re
import logging
from typing import Dict, List, Optional
from app.parsers.base_parser import BaseInvoiceParser
import pdfplumber

logger = logging.getLogger(__name__)

class CEFInvoiceParser(BaseInvoiceParser):
    """Parser for CEF invoices"""

    def __init__(self):
        super().__init__()
        self.supplier_name = 'CEF'

    def detect(self, filepath: str) -> bool:
        """Detect if this is a CEF invoice"""
        import pdfplumber
        try:
            with pdfplumber.open(filepath) as pdf:
                first_page_text = pdf.pages[0].extract_text() or ''
                return 'c.e.f.' in first_page_text.lower() or 'city electrical' in first_page_text.lower()
        except:
            return False
    def parse(self, pdf_path: str) -> Dict:
        """Parse CEF invoice"""
        items = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if not ("C.E.F." in text or "CEF" in text):
                        continue
                    tables = page.extract_tables()
                    for table in tables:
                        header_idx = -1
                        for i, row in enumerate(table):
                            if row and 'Qty' in str(row) and 'Item' in str(row):
                                header_idx = i
                                break
                        if header_idx == -1:
                            continue
                        for row in table[header_idx + 1:]:
                            if not row or 'Goods Total' in str(row):
                                continue
                            try:
                                qty = float(str(row[0]).strip())
                                part_no = str(row[1]).strip()
                                desc = str(row[2]).strip()
                                price = 0.0
                                if len(row) > 3 and row[3]:
                                    price = float(str(row[3]).replace('£', '').strip())
                                discount = '0'
                                if len(row) > 4 and row[4] and '%' in str(row[4]):
                                    discount = str(row[4]).replace('%', '').strip()
                                total = 0.0
                                if len(row) > 5 and row[5]:
                                    total = float(str(row[5]).replace('£', '').strip())
                                cost_per_item = total / qty if qty > 0 else price
                                items.append({
                                    'part_number': part_no,
                                    'description': desc,
                                    'quantity': qty,
                                    'price_per': price,
                                    'discount': discount,
                                    'total_amount': total,
                                    'cost_per_item': round(cost_per_item, 2)
                                })
                            except (ValueError, IndexError) as e:
                                continue
            return {
                'supplier': 'CEF',
                'items': items,
                'invoice_number': None,
                'invoice_date': None,
                'total': sum(item.get('total_amount', 0) for item in items)
            }
        except Exception as e:
            logger.error(f"Error processing PDF: {str(e)}")
            return {'supplier': 'CEF', 'items': []}

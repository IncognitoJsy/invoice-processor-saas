"""Wholesale Electrics parser"""
import logging
from app.parsers.base_parser import BaseInvoiceParser

logger = logging.getLogger(__name__)

class WholesaleInvoiceParser(BaseInvoiceParser):
    """Parse Wholesale invoices"""
    
    def __init__(self):
        super().__init__()
        self.supplier_name = 'WHOLESALE'
    
    def detect(self, text: str) -> bool:
        return 'WHOLESALE' in text.upper()
    
    def parse(self, pdf_path: str):
        return {'supplier': 'WHOLESALE', 'items': []}

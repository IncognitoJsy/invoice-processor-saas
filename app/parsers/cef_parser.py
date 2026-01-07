"""CEF invoice parser"""
import logging
from app.parsers.base_parser import BaseInvoiceParser

logger = logging.getLogger(__name__)

class CEFInvoiceParser(BaseInvoiceParser):
    """Parse CEF invoices"""
    
    def __init__(self):
        super().__init__()
        self.supplier_name = 'CEF'
    
    def detect(self, text: str) -> bool:
        return 'CEF' in text.upper()
    
    def parse(self, pdf_path: str):
        return {'supplier': 'CEF', 'items': []}

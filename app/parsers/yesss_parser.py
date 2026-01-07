"""YESSS invoice parser"""
import logging
from app.parsers.base_parser import BaseInvoiceParser

logger = logging.getLogger(__name__)

class YesssInvoiceParser(BaseInvoiceParser):
    """Parse YESSS invoices"""
    
    def __init__(self):
        super().__init__()
        self.supplier_name = 'YESSS'
    
    def detect(self, text: str) -> bool:
        return 'YESSS' in text.upper()
    
    def parse(self, pdf_path: str):
        return {'supplier': 'YESSS', 'items': []}

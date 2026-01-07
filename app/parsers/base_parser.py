"""Base parser class"""
from abc import ABC, abstractmethod

class BaseInvoiceParser(ABC):
    """Abstract base class for parsers"""
    
    def __init__(self):
        self.supplier_name = None
    
    @abstractmethod
    def parse(self, pdf_path: str):
        """Parse invoice PDF"""
        pass
    
    @abstractmethod
    def detect(self, text: str) -> bool:
        """Detect if this parser can handle the invoice"""
        pass

"""Main invoice processing orchestration"""
import logging

logger = logging.getLogger(__name__)

class InvoiceProcessor:
    """Orchestrate invoice processing"""
    
    def __init__(self, gmail_service, quickbooks_service, job_extractor, desc_cleaner):
        self.gmail = gmail_service
        self.quickbooks = quickbooks_service
        self.job_extractor = job_extractor
        self.desc_cleaner = desc_cleaner
    
    def process_invoice(self, invoice_id: int):
        """Process a single invoice"""
        logger.info(f"Processing invoice {invoice_id}")
        return {'success': True, 'invoice_id': invoice_id}

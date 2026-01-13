"""Invoice duplicate detection service"""
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class DuplicateDetectionService:
    """Detect and prevent duplicate invoice entries"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def check_duplicate(self, user_id: int, supplier_name: str, invoice_number: str) -> Tuple[bool, Optional[Dict]]:
        """
        Check if an invoice already exists in the database
        
        Returns:
            (is_duplicate, existing_invoice_dict or None)
        """
        if not invoice_number:
            # Can't check duplicates without invoice number
            return False, None
        
        from app.models.invoice import Invoice
        
        # Normalize for comparison
        invoice_number_clean = invoice_number.strip().upper()
        
        # Look for existing invoice with same number and supplier
        existing = Invoice.query.filter(
            Invoice.user_id == user_id,
            Invoice.invoice_number.ilike(f"%{invoice_number_clean}%")
        ).first()
        
        if existing:
            # Also verify supplier matches (case insensitive)
            if supplier_name and existing.supplier_name:
                existing_supplier = existing.supplier_name.lower()
                new_supplier = supplier_name.lower()
                
                # Check if suppliers match (partial match for variations)
                supplier_match = (
                    'cef' in existing_supplier and 'cef' in new_supplier or
                    'yesss' in existing_supplier and 'yesss' in new_supplier or
                    'wholesale' in existing_supplier and 'wholesale' in new_supplier or
                    existing_supplier == new_supplier
                )
                
                if supplier_match:
                    self.logger.warning(f"Duplicate detected: Invoice {invoice_number} from {supplier_name}")
                    return True, {
                        'id': existing.id,
                        'invoice_number': existing.invoice_number,
                        'supplier_name': existing.supplier_name,
                        'job_reference': existing.job_reference,
                        'total_cost': float(existing.total_cost) if existing.total_cost else 0,
                        'created_at': existing.created_at.isoformat() if existing.created_at else None
                    }
        
        return False, None
    
    def check_duplicates_batch(self, user_id: int, invoices: List[Dict]) -> List[Dict]:
        """
        Check multiple invoices for duplicates
        
        Returns list of invoices with duplicate status added
        """
        results = []
        
        for invoice in invoices:
            supplier = invoice.get('supplier', '')
            inv_number = invoice.get('invoice_number', '')
            
            is_dup, existing = self.check_duplicate(user_id, supplier, inv_number)
            
            invoice_result = {
                **invoice,
                'is_duplicate': is_dup,
                'existing_invoice': existing
            }
            
            results.append(invoice_result)
        
        return results
    
    def check_similar_invoice(self, user_id: int, supplier_name: str, total_amount: float, 
                               job_reference: str = None, days_back: int = 7) -> Tuple[bool, Optional[Dict]]:
        """
        Check for similar invoices (same supplier, similar amount) within recent days
        This catches potential duplicates even when invoice numbers differ
        
        Returns:
            (is_similar, similar_invoice_dict or None)
        """
        from app.models.invoice import Invoice
        
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        # Query for similar invoices
        query = Invoice.query.filter(
            Invoice.user_id == user_id,
            Invoice.created_at >= cutoff_date
        )
        
        # Filter by supplier (partial match)
        if supplier_name:
            supplier_lower = supplier_name.lower()
            if 'cef' in supplier_lower:
                query = query.filter(Invoice.supplier_name.ilike('%CEF%'))
            elif 'yesss' in supplier_lower:
                query = query.filter(Invoice.supplier_name.ilike('%YESSS%'))
            elif 'wholesale' in supplier_lower:
                query = query.filter(Invoice.supplier_name.ilike('%Wholesale%'))
        
        # Filter by job reference if provided
        if job_reference:
            query = query.filter(Invoice.job_reference.ilike(f'%{job_reference}%'))
        
        similar_invoices = query.all()
        
        # Check for amount similarity (within £1)
        for inv in similar_invoices:
            inv_total = float(inv.total_cost) if inv.total_cost else 0
            if abs(inv_total - total_amount) <= 1.00:
                self.logger.warning(f"Similar invoice detected: {inv.invoice_number} with total £{inv_total:.2f}")
                return True, {
                    'id': inv.id,
                    'invoice_number': inv.invoice_number,
                    'supplier_name': inv.supplier_name,
                    'job_reference': inv.job_reference,
                    'total_cost': inv_total,
                    'created_at': inv.created_at.isoformat() if inv.created_at else None
                }
        
        return False, None


# Singleton instance
_duplicate_service = None

def get_duplicate_service() -> DuplicateDetectionService:
    """Get or create the duplicate detection service"""
    global _duplicate_service
    if _duplicate_service is None:
        _duplicate_service = DuplicateDetectionService()
    return _duplicate_service

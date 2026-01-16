"""Master invoice parser service - handles consolidated invoices with duplicate detection"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

class InvoiceParserService:
    """Master parser - handles both single and consolidated invoices"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        from app.parsers.yesss_parser import YesssInvoiceParser
        from app.parsers.cef_parser import CEFInvoiceParser
        from app.parsers.wholesale_parser import WholesaleInvoiceParser
        from app.parsers.claude_parser import ClaudeInvoiceParser
        
        self.custom_parsers = [
            YesssInvoiceParser(),
            CEFInvoiceParser(),
            WholesaleInvoiceParser()
        ]
        
        try:
            self.claude_parser = ClaudeInvoiceParser()
            self.claude_available = True
        except ValueError as e:
            self.logger.warning(f"Claude parser not available: {str(e)}")
            self.claude_available = False
    
    def parse(self, pdf_path: str, use_claude: bool = True, user_id: int = None, document_type: str = 'invoice', user_markup_settings: Dict = None) -> List[Dict]:
        """
        Parse invoice - returns LIST of invoices (for consolidated support)
        Single invoice returns list with 1 item
        Consolidated returns list with multiple items
        
        Args:
            pdf_path: Path to PDF file
            use_claude: Whether to use Claude API
            user_id: If provided, checks for duplicate invoices
            document_type: 'invoice' or 'quote' - validates PDF matches this type
            user_markup_settings: Dict with 'is_admin' and 'default_markup' keys
        """
        
        # Default markup settings if not provided
        if user_markup_settings is None:
            user_markup_settings = {'is_admin': False, 'default_markup': 50.0}
        
        print("\n" + "="*80)
        self.logger.info(f"=== MASTER PARSER STARTED ===")
        self.logger.info(f"File: {pdf_path}")
        self.logger.info(f"Use Claude: {use_claude}")
        self.logger.info(f"Document Type: {document_type}")
        self.logger.info(f"User Markup Settings: admin={user_markup_settings.get('is_admin')}, markup={user_markup_settings.get('default_markup')}%")
        print("="*80 + "\n")
        
        # Try custom parsers first (only for invoices, not quotes)
        custom_result = {'success': False}
        if document_type == 'invoice':
            custom_result = self._try_custom_parsers(pdf_path, user_markup_settings)
        
        # If Claude not requested, return custom result as list
        if not use_claude or not self.claude_available:
            print("\n⚠️  Claude not used\n")
            if custom_result.get('success'):
                results = [custom_result]
            else:
                results = [{'success': False, 'error': custom_result.get('error', 'Parser not available')}]
            
            # Check for duplicates if user_id provided
            if user_id:
                results = self._check_duplicates(results, user_id)
            return results
        
        # Try Claude parser with document type validation and user markup settings
        print(f"\n🤖 CLAUDE PARSER: Running (expecting {document_type})...")
        claude_result = self.claude_parser.parse(pdf_path, expected_document_type=document_type, user_markup_settings=user_markup_settings)
        
        # Check for document type mismatch error
        if claude_result.get('document_type_mismatch'):
            print(f"\n❌ DOCUMENT TYPE MISMATCH!")
            print(f"   Expected: {claude_result.get('expected_document_type')}")
            print(f"   Detected: {claude_result.get('detected_document_type')}")
            return [claude_result]  # Return error to frontend
        
        # Check for credit note
        if claude_result.get('is_credit_note'):
            print(f"\n❌ CREDIT NOTE DETECTED - Skipping")
            return [claude_result]
        
        # Check if consolidated
        if claude_result.get('consolidated'):
            print(f"✅ Detected CONSOLIDATED {document_type} with {len(claude_result.get('invoices', []))} orders")
            if claude_result.get('skipped_credits', 0) > 0:
                print(f"⚠️  Skipped {claude_result['skipped_credits']} credit note(s)")
            results = self._handle_consolidated(claude_result, custom_result, pdf_path, document_type)
        else:
            # Single invoice - do normal comparison
            print(f"📄 Single {document_type} detected")
            compared = self._compare_single(custom_result, claude_result, document_type)
            results = [compared]  # Wrap in list
        
        # Check for duplicates if user_id provided (only for invoices)
        if user_id and document_type == 'invoice':
            results = self._check_duplicates(results, user_id)
        
        return results
    
    def _check_duplicates(self, invoices: List[Dict], user_id: int) -> List[Dict]:
        """Check all parsed invoices for duplicates"""
        from app.services.duplicate_detection import get_duplicate_service
        
        dup_service = get_duplicate_service()
        
        for invoice in invoices:
            if not invoice.get('success'):
                continue
            
            supplier = invoice.get('supplier', '')
            inv_number = invoice.get('invoice_number')
            
            if inv_number:
                is_dup, existing = dup_service.check_duplicate(user_id, supplier, inv_number)
                invoice['is_duplicate'] = is_dup
                invoice['existing_invoice'] = existing
                
                if is_dup:
                    print(f"\n⚠️  DUPLICATE DETECTED: Invoice {inv_number} already exists!")
                    print(f"   Existing invoice ID: {existing.get('id')}")
                    print(f"   Created: {existing.get('created_at')}\n")
            else:
                # No invoice number - check for similar invoices
                total = sum(item.get('total_amount', 0) for item in invoice.get('items', []))
                job_ref = invoice.get('job_reference')
                
                is_similar, similar = dup_service.check_similar_invoice(
                    user_id, supplier, total, job_ref
                )
                
                if is_similar:
                    invoice['is_potential_duplicate'] = True
                    invoice['similar_invoice'] = similar
                    print(f"\n⚠️  POTENTIAL DUPLICATE: Similar invoice found!")
                    print(f"   Similar invoice: {similar.get('invoice_number')}")
                    print(f"   Total: £{similar.get('total_cost'):.2f}\n")
        
        return invoices
    
    def _handle_consolidated(self, claude_result: Dict, custom_result: Dict, pdf_path: str, document_type: str = 'invoice') -> List[Dict]:
        """Handle consolidated invoice with multiple job references"""
        invoices = claude_result.get('invoices', [])
        
        if not invoices:
            return [{'success': False, 'error': f'No {document_type}s in consolidated result'}]
        
        results = []
        for idx, invoice in enumerate(invoices):
            print(f"\n📋 Processing Order {idx + 1}/{len(invoices)}")
            print(f"   Job Reference: {invoice.get('job_reference')}")
            print(f"   {document_type.title()} Number: {invoice.get('invoice_number')}")
            print(f"   Items: {len(invoice.get('items', []))}")
            
            # Add consolidated metadata
            invoice['consolidated'] = True
            invoice['order_number'] = idx + 1
            invoice['total_orders'] = len(invoices)
            invoice['confidence'] = 'medium'  # Consolidated documents get medium confidence
            invoice['success'] = True
            invoice['document_type'] = document_type
            
            results.append(invoice)
        
        print(f"\n✅ Processed {len(results)} {document_type}s from consolidated PDF\n")
        return results
    
    def _compare_single(self, custom_result: Dict, claude_result: Dict, document_type: str = 'invoice') -> Dict:
        """Compare single invoice results"""
        
        # Check if Claude returned a credit note error
        if claude_result.get('is_credit_note'):
            print("\n⚠️  Document is a CREDIT NOTE - skipping\n")
            return {'success': False, 'error': 'Document is a credit note', 'is_credit_note': True}
        
        # Check for document type mismatch
        if claude_result.get('document_type_mismatch'):
            return claude_result
        
        if not custom_result.get('success') and claude_result.get('success'):
            print(f"\n✅ Only Claude succeeded\n")
            return {**claude_result, 'method': 'claude_only', 'confidence': 'medium', 'document_type': document_type}
        
        if custom_result.get('success') and not claude_result.get('success'):
            print("\n✅ Only custom parser succeeded\n")
            return {**custom_result, 'method': 'custom_only', 'confidence': 'medium', 'document_type': document_type}
        
        if not custom_result.get('success') and not claude_result.get('success'):
            print("\n❌ Both parsers FAILED\n")
            return {'success': False, 'error': claude_result.get('error', 'Both parsers failed')}
        
        # Both succeeded - compare
        comparison = self._compare_results(custom_result, claude_result)
        
        if comparison['match']:
            print(f"\n✅ HIGH CONFIDENCE - Both parsers agree!\n")
            return {
                'success': True,
                'confidence': 'high',
                'method': 'both_agreed',
                'items': claude_result['items'],
                'job_reference': claude_result.get('job_reference'),
                'supplier': claude_result.get('supplier'),
                'invoice_number': claude_result.get('invoice_number'),
                'document_type': document_type,
                'comparison': comparison
            }
        else:
            print("\n⚠️  Parsers disagree - NEEDS REVIEW\n")
            return {
                'success': True,
                'confidence': 'low',
                'needs_review': True,
                'method': 'disagreement',
                'items': claude_result['items'],
                'job_reference': claude_result.get('job_reference'),
                'supplier': claude_result.get('supplier'),
                'invoice_number': claude_result.get('invoice_number'),
                'document_type': document_type,
                'comparison': comparison
            }
    
    def _try_custom_parsers(self, pdf_path: str, user_markup_settings: Dict = None) -> Dict:
        """Try all custom parsers"""
        for parser in self.custom_parsers:
            try:
                if parser.detect(pdf_path):
                    # Pass user markup settings if parser supports it
                    if hasattr(parser, 'parse') and user_markup_settings:
                        result = parser.parse(pdf_path, user_markup_settings=user_markup_settings)
                    else:
                        result = parser.parse(pdf_path)
                    if result.get('success'):
                        return {**result, 'method': f'custom_{parser.__class__.__name__}'}
            except Exception as e:
                self.logger.error(f"Custom parser error: {str(e)}")
                continue
        
        return {'success': False, 'error': 'No custom parser could handle this invoice'}
    
    def _compare_results(self, result1: Dict, result2: Dict) -> Dict:
        """Compare two parsing results"""
        differences = []
        
        items1 = result1.get('items', [])
        items2 = result2.get('items', [])
        
        total1 = sum(item.get('total_amount', 0) for item in items1)
        total2 = sum(item.get('total_amount', 0) for item in items2)
        
        if abs(total1 - total2) > 1.00:
            differences.append(f'Total: £{total1:.2f} vs £{total2:.2f}')
        
        match = (len(differences) == 0 or abs(total1 - total2) <= 1.00)
        
        return {
            'match': match,
            'differences': differences,
            'custom_total': total1,
            'claude_total': total2
        }

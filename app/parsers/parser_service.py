"""Master invoice parser service - handles consolidated invoices"""
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
    
    def parse(self, pdf_path: str, use_claude: bool = True) -> List[Dict]:
        """
        Parse invoice - returns LIST of invoices (for consolidated support)
        Single invoice returns list with 1 item
        Consolidated returns list with multiple items
        """
        
        print("\n" + "="*80)
        self.logger.info(f"=== MASTER PARSER STARTED ===")
        self.logger.info(f"File: {pdf_path}")
        self.logger.info(f"Use Claude: {use_claude}")
        print("="*80 + "\n")
        
        # Try custom parsers first
        custom_result = self._try_custom_parsers(pdf_path)
        
        # If Claude not requested, return custom result as list
        if not use_claude or not self.claude_available:
            print("\n⚠️  Claude not used\n")
            if custom_result.get('success'):
                return [custom_result]  # Wrap in list
            return [{'success': False, 'error': custom_result.get('error')}]
        
        # Try Claude parser
        print(f"\n🤖 CLAUDE PARSER: Running...")
        claude_result = self.claude_parser.parse(pdf_path)
        
        # Check if consolidated
        if claude_result.get('consolidated'):
            print(f"✅ Detected CONSOLIDATED invoice with {len(claude_result.get('invoices', []))} orders")
            return self._handle_consolidated(claude_result, custom_result, pdf_path)
        
        # Single invoice - do normal comparison
        print(f"📄 Single invoice detected")
        compared = self._compare_single(custom_result, claude_result)
        return [compared]  # Wrap in list
    
    def _handle_consolidated(self, claude_result: Dict, custom_result: Dict, pdf_path: str) -> List[Dict]:
        """Handle consolidated invoice with multiple job references"""
        invoices = claude_result.get('invoices', [])
        
        if not invoices:
            return [{'success': False, 'error': 'No invoices in consolidated result'}]
        
        results = []
        for idx, invoice in enumerate(invoices):
            print(f"\n📋 Processing Order {idx + 1}/{len(invoices)}")
            print(f"   Job Reference: {invoice.get('job_reference')}")
            print(f"   Items: {len(invoice.get('items', []))}")
            
            # Add consolidated metadata
            invoice['consolidated'] = True
            invoice['order_number'] = idx + 1
            invoice['total_orders'] = len(invoices)
            invoice['confidence'] = 'medium'  # Consolidated invoices get medium confidence
            invoice['success'] = True
            
            results.append(invoice)
        
        print(f"\n✅ Processed {len(results)} invoices from consolidated PDF\n")
        return results
    
    def _compare_single(self, custom_result: Dict, claude_result: Dict) -> Dict:
        """Compare single invoice results"""
        
        if not custom_result.get('success') and claude_result.get('success'):
            print("\n✅ Only Claude succeeded\n")
            return {**claude_result, 'method': 'claude_only', 'confidence': 'medium'}
        
        if custom_result.get('success') and not claude_result.get('success'):
            print("\n✅ Only custom parser succeeded\n")
            return {**custom_result, 'method': 'custom_only', 'confidence': 'medium'}
        
        if not custom_result.get('success') and not claude_result.get('success'):
            print("\n❌ Both parsers FAILED\n")
            return {'success': False, 'error': 'Both parsers failed'}
        
        # Both succeeded - compare
        comparison = self._compare_results(custom_result, claude_result)
        
        if comparison['match']:
            print("\n✅ HIGH CONFIDENCE - Both parsers agree!\n")
            return {
                'success': True,
                'confidence': 'high',
                'method': 'both_agreed',
                'items': claude_result['items'],
                'job_reference': claude_result.get('job_reference'),
                'supplier': claude_result.get('supplier'),
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
                'comparison': comparison
            }
    
    def _try_custom_parsers(self, pdf_path: str) -> Dict:
        """Try all custom parsers"""
        for parser in self.custom_parsers:
            try:
                if parser.detect(pdf_path):
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

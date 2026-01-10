"""Master invoice parser service that uses multiple parsers and compares results"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class InvoiceParserService:
    """
    Master parser that uses both custom parsers and Claude API,
    then compares results for maximum accuracy
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Import parsers
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
    
    def parse(self, pdf_path: str, use_claude: bool = True) -> Dict:
        """Parse invoice using multiple methods and compare results"""
        
        print("\n" + "="*80)
        self.logger.info(f"=== MASTER PARSER STARTED ===")
        self.logger.info(f"File: {pdf_path}")
        self.logger.info(f"Use Claude: {use_claude}")
        print("="*80 + "\n")
        
        # Try custom parsers
        custom_result = self._try_custom_parsers(pdf_path)
        print(f"📝 CUSTOM PARSER: Success={custom_result.get('success')}")
        if custom_result.get('success'):
            print(f"   Method: {custom_result.get('method')}")
            print(f"   Items: {len(custom_result.get('items', []))}")
        else:
            print(f"   Error: {custom_result.get('error')}")
        
        # If Claude not requested or not available, return custom result
        if not use_claude or not self.claude_available:
            print("\n⚠️  Claude not used - returning custom result only\n")
            return custom_result
        
        # Try Claude parser
        print(f"\n🤖 CLAUDE PARSER: Running...")
        claude_result = self.claude_parser.parse(pdf_path)
        print(f"   Success={claude_result.get('success')}")
        if claude_result.get('success'):
            print(f"   Items: {len(claude_result.get('items', []))}")
        else:
            print(f"   Error: {claude_result.get('error')}")
        
        # If one failed, return the successful one
        if not custom_result.get('success') and claude_result.get('success'):
            print("\n✅ Only Claude succeeded\n")
            return {**claude_result, 'method': 'claude_only', 'confidence': 'medium'}
        
        if custom_result.get('success') and not claude_result.get('success'):
            print("\n✅ Only custom parser succeeded\n")
            return {**custom_result, 'method': 'custom_only', 'confidence': 'medium'}
        
        if not custom_result.get('success') and not claude_result.get('success'):
            print("\n❌ Both parsers FAILED\n")
            return {'success': False, 'error': 'Both parsers failed'}
        
        # Both succeeded - compare results
        comparison = self._compare_results(custom_result, claude_result)
        print(f"\n🔍 COMPARISON:")
        print(f"   Match: {comparison['match']}")
        print(f"   Custom total: £{comparison['custom_total']:.2f}")
        print(f"   Claude total: £{comparison['claude_total']:.2f}")
        if comparison['differences']:
            print(f"   Differences: {comparison['differences']}")
        
        if comparison['match']:
            print("\n✅ HIGH CONFIDENCE - Both parsers agree!\n")
            return {
                'success': True,
                'confidence': 'high',
                'method': 'both_agreed',
                'items': claude_result['items'],
                'job_reference': claude_result.get('job_reference'),
                'supplier': claude_result.get('supplier'),
                'comparison': {
                    'agreed': True,
                    'custom_item_count': len(custom_result.get('items', [])),
                    'claude_item_count': len(claude_result.get('items', []))
                }
            }
        else:
            print("\n⚠️  LOW CONFIDENCE - Parsers disagree - NEEDS REVIEW\n")
            return {
                'success': True,
                'confidence': 'low',
                'needs_review': True,
                'method': 'disagreement',
                'items': claude_result['items'],
                'job_reference': claude_result.get('job_reference'),
                'supplier': claude_result.get('supplier'),
                'comparison': {
                    'agreed': False,
                    'differences': comparison['differences'],
                    'custom_item_count': len(custom_result.get('items', [])),
                    'claude_item_count': len(claude_result.get('items', [])),
                    'custom_total': comparison['custom_total'],
                    'claude_total': comparison['claude_total']
                }
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
        
        count1 = len(items1)
        count2 = len(items2)
        
        if count1 != count2:
            differences.append(f'Item count: {count1} vs {count2}')
        
        total1 = sum(item.get('total_amount', 0) for item in items1)
        total2 = sum(item.get('total_amount', 0) for item in items2)
        
        if abs(total1 - total2) > 1.00:
            differences.append(f'Total: £{total1:.2f} vs £{total2:.2f}')
        
        parts1 = {item['part_number'] for item in items1}
        parts2 = {item['part_number'] for item in items2}
        
        missing_in_1 = parts2 - parts1
        missing_in_2 = parts1 - parts2
        
        if missing_in_1:
            differences.append(f'Custom missing: {list(missing_in_1)[:5]}')
        if missing_in_2:
            differences.append(f'Claude missing: {list(missing_in_2)[:5]}')
        
        match = (len(differences) == 0 or (abs(total1 - total2) <= 1.00 and count1 == count2))
        
        return {
            'match': match,
            'differences': differences,
            'custom_total': total1,
            'claude_total': total2
        }

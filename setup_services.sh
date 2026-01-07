#!/bin/bash

set -e

echo "🔧 Creating service layer files..."
echo ""

# ============================================
# Job Reference Extractor (Your Fix)
# ============================================
echo "📝 Creating job_reference_extractor.py..."
cat > app/services/job_reference_extractor.py << 'EOF'
"""Enhanced job reference extraction with multiple strategies"""
import re
import logging
from typing import Optional
from PyPDF2 import PdfReader

logger = logging.getLogger(__name__)

class JobReferenceExtractor:
    """Extract job references from invoices using multiple strategies"""
    
    def __init__(self):
        self.extraction_strategies = [
            self._extract_from_labeled_field,
            self._extract_from_table_structure,
            self._extract_from_context_patterns,
            self._extract_from_subject_line,
        ]
    
    def extract(self, pdf_path: str, supplier: str, email_subject: str = None) -> Optional[str]:
        """
        Extract job reference using multiple strategies
        
        Args:
            pdf_path: Path to PDF file
            supplier: Supplier identifier (YESSS, WHOLESALE, CEF)
            email_subject: Optional email subject line
            
        Returns:
            Extracted job reference or None
        """
        try:
            text = self._extract_pdf_text(pdf_path)
            
            for strategy in self.extraction_strategies:
                reference = strategy(text, supplier, email_subject)
                if reference and self._is_valid_reference(reference):
                    logger.info(f"Extracted reference '{reference}' using {strategy.__name__}")
                    return reference
            
            logger.warning(f"Could not extract job reference from {pdf_path}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting job reference: {str(e)}")
            return None
    
    def _extract_pdf_text(self, pdf_path: str, max_pages: int = 3) -> str:
        """Extract text from first few pages of PDF"""
        reader = PdfReader(pdf_path)
        text = ""
        
        for i, page in enumerate(reader.pages[:max_pages]):
            page_text = page.extract_text()
            if page_text:
                text += f"\n--- PAGE {i+1} ---\n{page_text}"
        
        return text
    
    def _extract_from_labeled_field(
        self, text: str, supplier: str, email_subject: str = None
    ) -> Optional[str]:
        """Strategy 1: Look for labeled fields like 'YOUR ORDER REF:', 'JOB REF:', etc."""
        
        patterns = {
            'YESSS': [
                r'YOUR\s+ORDER\s+REFERENCE[:\s]+([A-Za-z0-9\s\-/\.]+?)(?:\s*\n|\s*DATE|\s*DUE)',
                r'ORDER\s+REFERENCE[:\s]+([A-Za-z0-9\s\-/\.]+?)(?:\s*\n|\s*DATE)',
            ],
            'WHOLESALE': [
                r'YOUR\s+ORDER\s+REF[:\s]+([A-Za-z0-9\s\-/\.]+?)(?:\s*Item|\s*Taken|\s*\n)',
                r'ORDER\s+REF[:\s]+([A-Za-z0-9\s\-/\.]+?)(?:\s*\n|\s*DATE)',
            ],
            'CEF': [
                r'YOUR\s+ORDER\s+NUMBER[:\s]+([A-Za-z0-9\s\-/\.]+?)(?:\s*\n|$)',
                r'ORDER\s+NUMBER[:\s]+([A-Za-z0-9\s\-/\.]+?)(?:\s*\n|$)',
            ]
        }
        
        supplier_patterns = patterns.get(supplier, [])
        for pattern in supplier_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                ref = self._clean_reference(match.group(1))
                if ref:
                    return ref
        
        return None
    
    def _extract_from_table_structure(
        self, text: str, supplier: str, email_subject: str = None
    ) -> Optional[str]:
        """Strategy 2: Extract from table-like structures"""
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            if re.search(r'YOUR\s+ORDER|ORDER\s+REF|JOB\s+REF', line, re.IGNORECASE):
                for j in range(1, min(5, len(lines) - i)):
                    next_line = lines[i + j].strip()
                    if not next_line or any(word in next_line.upper() for word in ['DATE', 'INVOICE', 'DUE']):
                        continue
                    ref = self._clean_reference(next_line)
                    if ref and len(ref) >= 3:
                        return ref
        
        return None
    
    def _extract_from_context_patterns(
        self, text: str, supplier: str, email_subject: str = None
    ) -> Optional[str]:
        """Strategy 3: Use context clues to find likely references"""
        lines = text.split('\n')
        
        for line in lines:
            if any(word in line.upper() for word in ['INVOICE', 'DATE', 'TOTAL', 'AMOUNT']):
                continue
            
            potential_refs = re.findall(r'\b([A-Za-z]+[A-Za-z0-9\-/\s]{2,30})\b', line)
            for ref in potential_refs:
                ref = self._clean_reference(ref)
                if ref and self._looks_like_reference(ref):
                    return ref
        
        return None
    
    def _extract_from_subject_line(
        self, text: str, supplier: str, email_subject: str = None
    ) -> Optional[str]:
        """Strategy 4: Extract from email subject line if provided"""
        if not email_subject:
            return None
        
        patterns = [
            r'(?:Job|Project|Site|PO)[:|\s]+([A-Za-z0-9\s\-/\.]+)',
            r'for\s+([A-Za-z][A-Za-z0-9\s\-/\.]{2,30})',
            r'RE[:|\s]+([A-Za-z0-9\s\-/\.]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, email_subject, re.IGNORECASE)
            if match:
                ref = self._clean_reference(match.group(1))
                if ref:
                    return ref
        
        return None
    
    def _clean_reference(self, ref: str) -> Optional[str]:
        """Clean up extracted reference"""
        if not ref:
            return None
        
        ref = re.sub(r'^(REF|REFERENCE|JOB|PROJECT|SITE|PO|ORDER)[:\s]+', '', ref, flags=re.IGNORECASE)
        ref = re.sub(r'\s+(DATE|INVOICE|DUE|TOTAL).*$', '', ref, flags=re.IGNORECASE)
        ref = ref.rstrip('.:,-')
        ref = ' '.join(ref.split())
        ref = ref.title()
        
        return ref if ref else None
    
    def _looks_like_reference(self, ref: str) -> bool:
        """Check if string looks like a plausible reference"""
        if not re.search(r'[A-Za-z]', ref):
            return False
        if not re.search(r'[0-9]', ref) and len(ref) <= 4:
            return False
        if ref.replace(' ', '').replace('-', '').replace('/', '').isdigit():
            return False
        
        false_positives = ['INVOICE', 'DATE', 'TOTAL', 'AMOUNT', 'PRICE', 'DELIVERY', 'PAGE']
        if ref.upper() in false_positives:
            return False
        
        return True
    
    def _is_valid_reference(self, ref: str) -> bool:
        """Validate reference meets minimum quality standards"""
        if not ref or len(ref) < 2 or len(ref) > 100:
            return False
        if not re.search(r'[A-Za-z0-9]', ref):
            return False
        return True
EOF

echo "✅ job_reference_extractor.py created"

echo ""
echo "🎉 Service files created!"
echo ""
echo "✅ Job Reference Extractor (with improved extraction)"
echo ""

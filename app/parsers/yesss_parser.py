"""YESSS Electrical invoice parser"""
import re
import logging
from typing import Dict, List, Optional
from app.parsers.base_parser import BaseInvoiceParser
import pdfplumber

logger = logging.getLogger(__name__)

class YesssInvoiceParser(BaseInvoiceParser):
    """Parser for YESSS Electrical invoices"""

    def __init__(self):
        super().__init__()
        self.supplier_name = 'YESSS'

    def detect(self, filepath: str) -> bool:
        """Detect if this is a YESSS invoice"""
        import pdfplumber
        try:
            with pdfplumber.open(filepath) as pdf:
                first_page_text = pdf.pages[0].extract_text() or ''
                return 'YESSS ELECTRICAL' in first_page_text.upper() or 'yesss.co.uk' in first_page_text.lower()
        except:
            return False


    def extract_job_reference(self, text: str) -> str:
        """Extract job reference from YESSS invoice"""
        import re
        lines = text.split('\n')
        
        # Find the line with YOUR ORDER REFERENCE header
        for i, line in enumerate(lines):
            if "YOUR ORDER REFERENCE" in line and "DATE" in line:
                # The reference is on the next data row (skip table headers)
                for j in range(i+1, min(i+5, len(lines))):
                    next_line = lines[j].strip()
                    
                    # Skip empty lines
                    if not next_line:
                        continue
                    
                    # Skip table headers like "Qty. Part No. Description"
                    if "Qty." in next_line or "Part No" in next_line or "Description" in next_line:
                        continue
                    
                    # Skip pure date lines or invoice number lines
                    if next_line.replace('/', '').replace('-', '').replace('.', '').isdigit():
                        continue
                    
                    # Extract reference - it's the part before any date
                    # Format is like: "093IN1054492 ROSE COTTAGE 21/11/2024"
                    words = next_line.split()
                    if len(words) >= 2:
                        # First word is usually account/invoice number, skip it
                        # Find words that are letters (the job reference)
                        ref_words = []
                        for word in words:  # Check all words
                            # Stop at dates
                            if '/' in word or len(word) > 15:
                                break
                            # Only take words with letters (not invoice numbers)
                            if any(c.isalpha() for c in word) and not word[0].isdigit():
                                ref_words.append(word)
                        
                        if ref_words:
                            return ' '.join(ref_words)
        
        return None

        return None

    def is_start_of_new_item(self, line: str) -> bool:
        """Check if this line starts a new item"""
        parts = line.split()
        if not parts:
            return False
        try:
            float(parts[0])
            if len(parts) > 1:
                part_num = parts[1]
                if 'JE' in part_num:
                    return False
                return any(c.isdigit() or c == '-' for c in part_num) or len(part_num) > 3
            return False
        except ValueError:
            return False

    def extract_item_from_line(self, line: str, surrounding_lines: List[str], current_line_idx: int) -> Optional[Dict]:
        """Extract item details from a line"""
        try:
            parts = line.split()
            if not parts or len(parts) < 2:
                return None

            try:
                qty = float(parts[0])
            except ValueError:
                return None

            part_no = parts[1]
            if 'JE' in part_no:
                return None
            if not (any(c.isdigit() or c == '-' for c in part_no) or len(part_no) > 3):
                return None

            total_amount = None
            discount = None
            price_per = None
            original_price = None

            each_index = -1
            for i, part in enumerate(parts):
                if part in ['EACH', 'EA', 'M']:
                    each_index = i
                    break

            start_search = 2
            for i in range(start_search, len(parts)):
                if i < each_index or each_index == -1:
                    try:
                        candidate = float(parts[i].rstrip('R'))
                        if candidate > 0 and candidate < 10000:
                            original_price = candidate
                            break
                    except ValueError:
                        continue

            for i, part in enumerate(parts):
                if part in ['EACH', 'EA', 'M']:
                    for j in range(i-1, -1, -1):
                        try:
                            candidate = float(parts[j].rstrip('R'))
                            price_per = candidate
                            break
                        except ValueError:
                            continue
                    # Look for discount: only 1-2 digit numbers after EACH, before amount
                    for j in range(i+1, min(i+4, len(parts))):
                        if parts[j].isdigit() and len(parts[j]) <= 2:
                            discount = parts[j]
                            break
                        elif parts[j].replace('.', '').isdigit() and len(parts[j]) <= 3:
                            discount = parts[j]
                            break
                elif part.endswith('R') and part[:-1].replace('.', '').replace(' ', '').isdigit():
                    total_amount = float(part[:-1])

            if total_amount is None and price_per is not None and discount is not None and qty:
                discount_value = float(discount) / 100
                total_amount = round(price_per * qty * (1 - discount_value), 2)

            elif total_amount is None and price_per is not None and qty:
                total_amount = round(price_per * qty, 2)

            if qty and part_no and (total_amount or price_per):
                desc_start = line.index(part_no) + len(part_no)
                price_text = str(original_price) if original_price is not None else None

                if price_text:
                    desc_end = line.find(price_text, desc_start)
                    if desc_end == -1:
                        desc_end = line.find('EACH', desc_start) if 'EACH' in line else line.find('EA', desc_start)
                    if desc_end == -1:
                        desc_end = len(line)
                else:
                    desc_end = len(line)

                main_desc = line[desc_start:desc_end].strip()
                main_desc = ' '.join(main_desc.split())

                desc_lines = [main_desc]
                next_line_idx = current_line_idx + 1
                continuation_limit = 3

                for i in range(continuation_limit):
                    if next_line_idx < len(surrounding_lines):
                        next_line = surrounding_lines[next_line_idx].strip()
                        if self.is_start_of_new_item(next_line):
                            break
                        if (any(next_line.split() and next_line.split()[0].replace('.', '').isdigit() for part in next_line.split()) or
                            'EACH' in next_line or 'EA' in next_line or ' R' in next_line.split()):
                            break
                        if next_line and not next_line.startswith("Page ") and not next_line.startswith("YESSS"):
                            desc_lines.append(next_line)
                        next_line_idx += 1
                    else:
                        break

                description = ' '.join(desc_lines).strip()
                description = ' '.join(description.split())
                description = description.rstrip('.')

                if len(description) < 3:
                    description = f"Item {part_no}"

                if part_no.endswith(' R'):
                    part_no = part_no[:-2]

                if total_amount is not None and qty > 0:
                    cost_per_item = total_amount / qty
                elif price_per is not None:
                    cost_per_item = price_per
                else:
                    cost_per_item = 0

                return {
                    'part_number': part_no,
                    'description': description,
                    'quantity': qty,
                    'price_per': price_per or 0,
                    'discount': discount or '0',
                    'total_amount': total_amount or 0,
                    'cost_per_item': round(cost_per_item, 2),
                    'original_price': original_price or price_per or 0
                }

        except Exception as e:
            logger.error(f"Error extracting item: {str(e)}")
        return None

    def parse(self, pdf_path: str) -> Dict:
        """Parse YESSS invoice"""
        items = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    words = page.extract_words(keep_blank_chars=True)
                    current_y = None
                    current_line = []
                    lines = []

                    for word in words:
                        if current_y is None:
                            current_y = word['top']
                        if abs(word['top'] - current_y) < 5:
                            current_line.append(word['text'])
                        else:
                            if current_line:
                                lines.append(' '.join(current_line))
                            current_line = [word['text']]
                            current_y = word['top']

                    if current_line:
                        lines.append(' '.join(current_line))

                    for i, line in enumerate(lines):
                        if not line or not any(c.isdigit() for c in line.split()[0] if line.split()):
                            continue
                        if line.split() and line.split()[0].replace('.', '').isdigit():
                            item = self.extract_item_from_line(line, lines, i)
                            if item:
                                items.append(item)

            # Extract full text for job reference
                text = pdf.pages[0].extract_text()
                job_reference = self.extract_job_reference(text)
                
            return {
                'supplier': 'YESSS',
                'items': items,
                'invoice_number': None,
                'invoice_date': None,
                'job_reference': job_reference,
                'total': sum(item.get('total_amount', 0) for item in items)
            }
        except Exception as e:
            logger.error(f"Error processing PDF: {str(e)}")
            return {'supplier': 'YESSS', 'items': []}

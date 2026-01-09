"""CEF invoice parser with coordinate-based extraction for rotated PDFs"""
import re
import logging
from typing import Dict, List, Optional
from app.parsers.base_parser import BaseInvoiceParser
import pdfplumber

logger = logging.getLogger(__name__)

class CEFInvoiceParser(BaseInvoiceParser):
    """Parser for CEF invoices (handles 90-degree rotation)"""

    def __init__(self):
        super().__init__()
        self.supplier_name = 'CEF'

    def detect(self, filepath: str) -> bool:
        """Detect if this is a CEF invoice"""
        try:
            with pdfplumber.open(filepath) as pdf:
                page = pdf.pages[0]
                
                # Try to extract text from both orientations
                text = page.extract_text() or ''
                
                # Check for CEF indicators
                if 'C.E.F.' in text or 'CEF' in text or 'City Electrical' in text.upper():
                    return True
                
                # Check if likely rotated (width > height)
                if page.width > page.height:
                    logger.info("CEF: Page appears rotated")
                    return True
                    
                return False
        except Exception as e:
            logger.error(f"Error detecting CEF: {e}")
            return False

    def calculate_markup(self, discount_percent):
        """Calculate markup based on discount received"""
        if discount_percent == 0:
            return 0.20
        elif 1 <= discount_percent <= 30:
            return 0.40
        elif 30 < discount_percent <= 70:
            return 0.50
        else:
            return 0.70

    def extract_job_reference(self, text):
        """Extract job reference from CEF invoice"""
        # Look for "Your Order Number" in the reconstructed text
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if 'Your Order Number' in line or 'Order Number' in line:
                # Job ref might be on same line or next few lines
                for j in range(i, min(i+3, len(lines))):
                    # Look for alphanumeric pattern that's not a date
                    words = lines[j].split()
                    for word in words:
                        if len(word) > 2 and any(c.isalpha() for c in word) and '/' not in word:
                            if word not in ['Your', 'Order', 'Number', 'Page', 'Account']:
                                return word
        return None

    def parse(self, filepath: str) -> Dict:
        """Parse CEF invoice using coordinate-based extraction"""
        items = []
        try:
            with pdfplumber.open(filepath) as pdf:
                page = pdf.pages[0]
                
                # Rotate if landscape
                if page.width > page.height:
                    logger.info(f"Rotating CEF page")
                    page = page.rotate(270)
                
                # Extract words with coordinates
                words = page.extract_words()
                logger.info(f"Extracted {len(words)} words")
                
                # Reconstruct lines based on y-coordinate
                lines_dict = {}
                for word in words:
                    y = round(word['top'], 1)  # Round to group nearby words
                    if y not in lines_dict:
                        lines_dict[y] = []
                    lines_dict[y].append(word)
                
                # Sort words in each line by x-coordinate
                for y in lines_dict:
                    lines_dict[y].sort(key=lambda w: w['x0'])
                
                # Convert to text lines
                sorted_ys = sorted(lines_dict.keys())
                text_lines = []
                for y in sorted_ys:
                    line_text = ' '.join([w['text'] for w in lines_dict[y]])
                    text_lines.append(line_text)
                
                logger.info(f"Reconstructed {len(text_lines)} lines")
                
                # Log first 20 lines for debugging
                for i in range(min(20, len(text_lines))):
                    logger.info(f"Reconstructed line {i}: {text_lines[i][:100]}")
                
                # Join all lines for job reference extraction
                full_text = '\n'.join(text_lines)
                job_reference = self.extract_job_reference(full_text)
                logger.info(f"Job reference: {job_reference}")
                
                # Parse items from reconstructed lines
                for line in text_lines:
                    parts = line.split()
                    if not parts:
                        continue
                    
                    try:
                        # Look for lines starting with quantity
                        qty = float(parts[0])
                        if qty > 0 and len(parts) > 3:
                            part_no = parts[1]
                            
                            # Find description and numeric values
                            desc_parts = []
                            prices = []
                            discount_pct = 0
                            
                            for i, part in enumerate(parts[2:], start=2):
                                # Check if numeric
                                try:
                                    val = float(part)
                                    prices.append(val)
                                except:
                                    if '%' in part:
                                        try:
                                            discount_pct = float(part.replace('%', ''))
                                        except:
                                            pass
                                    elif part not in ['each', 'J']:
                                        if not prices:  # Only add to description if we haven't hit prices yet
                                            desc_parts.append(part)
                            
                            # Need at least original price and total
                            if len(prices) >= 2 and desc_parts:
                                description = ' '.join(desc_parts)
                                original_price = prices[0]
                                total_amount = prices[-1]
                                
                                # Calculate cost per item
                                cost_per_item = total_amount / qty if qty > 0 else original_price
                                
                                # Calculate selling price
                                markup = self.calculate_markup(discount_pct)
                                selling_price = round(cost_per_item * (1 + markup), 2)
                                profit_per_item = round(selling_price - cost_per_item, 2)
                                
                                # Original unit price
                                if discount_pct > 0:
                                    original_unit_price = round(cost_per_item / (1 - discount_pct / 100), 2)
                                else:
                                    original_unit_price = cost_per_item
                                
                                item = {
                                    'part_number': part_no,
                                    'description': description,
                                    'quantity': qty,
                                    'price_per': original_price,
                                    'discount': f'{discount_pct}%',
                                    'total_amount': total_amount,
                                    'cost_per_item': round(cost_per_item, 2),
                                    'original_price': original_price,
                                    'original_unit_price': original_unit_price,
                                    'selling_price': selling_price,
                                    'profit_per_item': profit_per_item,
                                    'markup_percent': int(markup * 100)
                                }
                                
                                items.append(item)
                                logger.info(f"Parsed CEF item: {part_no} - {description[:30]}")
                    
                    except (ValueError, IndexError) as e:
                        continue
                
                total = sum(item['total_amount'] for item in items)
                
                return {
                    'supplier': self.supplier_name,
                    'items': items,
                    'invoice_number': None,
                    'invoice_date': None,
                    'job_reference': job_reference,
                    'total': total
                }
                
        except Exception as e:
            logger.error(f"Error parsing CEF invoice: {e}", exc_info=True)
            return {
                'supplier': self.supplier_name,
                'items': [],
                'job_reference': None,
                'total': 0
            }

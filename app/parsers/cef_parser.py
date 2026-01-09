import re
import pdfplumber
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class CEFInvoiceParser:
    """Parser for CEF invoices with support for 90-degree rotated PDFs"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def detect(self, pdf_path: str) -> bool:
        """Detect if this is a CEF invoice"""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                first_page_text = pdf.pages[0].extract_text() if len(pdf.pages) > 0 else ""
                return "C.E.F." in first_page_text or "CEF" in first_page_text
        except Exception as e:
            self.logger.error(f"Error detecting CEF invoice: {str(e)}")
            return False

    def parse(self, pdf_path: str) -> Dict:
        """Main parse method called by upload handler"""
        try:
            items = self.extract_pdf_data(pdf_path)
            job_ref = self.extract_job_reference(pdf_path)
            
            return {
                'success': True,
                'items': items,
                'job_reference': job_ref,
                'supplier': 'CEF'
            }
        except Exception as e:
            self.logger.error(f"Error in parse: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'items': []
            }

    def calculate_new_prices(self, item: Dict) -> Dict:
        """Calculate new prices based on discount rules"""
        cost_per_item = item['cost_per_item']
        discount = float(item.get('discount', 0))
        new_purchase_price = cost_per_item
        if discount == 0:
            markup = 0.20
        elif 1 <= discount <= 30:
            markup = 0.40
        elif 30 < discount <= 70:
            markup = 0.50
        else:
            markup = 0.70
        new_sales_price = round(cost_per_item * (1 + markup), 2)
        return {'new_purchase_price': new_purchase_price, 'new_sales_price': new_sales_price}

    def extract_pdf_data(self, pdf_path: str) -> List[Dict]:
        """Extract data from CEF invoice PDF (handles rotated PDFs)"""
        items = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                first_page_text = pdf.pages[0].extract_text() if len(pdf.pages) > 0 else ""
                if not ("C.E.F." in first_page_text or "CEF" in first_page_text):
                    self.logger.info("Not a CEF invoice")
                    return []
                self.logger.info("CEF invoice detected, processing...")
                
                for page in pdf.pages:
                    page_items = self._extract_table_columns(page)
                    
                    if not page_items:
                        width = page.width
                        height = page.height
                        is_rotated = width > height
                        self.logger.info(f"Page dimensions: {width}x{height}, rotated: {is_rotated}")
                        
                        if is_rotated:
                            page_items = self._extract_rotated_page(page)
                        else:
                            page_items = self._extract_normal_page(page)
                    
                    items.extend(page_items)
                    
        except Exception as e:
            self.logger.error(f"Error extracting PDF data: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
        
        self.logger.info(f"Extracted {len(items)} items total")
        return items

    def _extract_table_columns(self, page) -> List[Dict]:
        """Extract items from table where each item is in a column (rotated PDF format)"""
        items = []
        
        try:
            tables = page.extract_tables()
            if not tables:
                return []
            
            table = tables[0]
            if not table or len(table) == 0:
                return []
            
            row = table[0]
            self.logger.info(f"Table has {len(row)} columns")
            
            for col_idx, cell in enumerate(row):
                if not cell or not cell.strip():
                    continue
                
                if 'Qty' in cell and 'Item' in cell:
                    continue
                
                item = self._parse_column_cell(cell)
                if item:
                    items.append(item)
                    self.logger.info(f"Extracted from column {col_idx}: {item['part_number']} - Qty: {item['quantity']}, Discount: {item['discount']}%, Total: £{item['total_amount']}")
            
        except Exception as e:
            self.logger.error(f"Error in _extract_table_columns: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
        
        return items

    def _parse_column_cell(self, cell_text: str) -> Dict:
        """Parse a table cell that contains a complete item"""
        try:
            lines = [line.strip() for line in cell_text.split('\n') if line.strip()]
            
            if len(lines) < 3:
                return None
            
            try:
                quantity = float(lines[0])
            except ValueError:
                return None
            
            part_number_lines = []
            description_lines = []
            price_per = 0.0
            discount = '0'
            total_amount = 0.0
            
            found_price = False
            price_line_idx = -1
            found_part_number = False
            
            for i, line in enumerate(lines[1:], start=1):
                if 'each' in line.lower():
                    parts = line.split('each')
                    try:
                        price_per = float(parts[0].strip())
                    except:
                        pass
                    found_price = True
                    price_line_idx = i
                    break
                
                elif not found_price:
                    # Part number logic: collect consecutive ALL CAPS lines at the start
                    # Once we hit a non-caps line, part number is complete
                    if not found_part_number and re.match(r'^[A-Z0-9\-]+$', line):
                        part_number_lines.append(line)
                    else:
                        # Once we hit a non-caps line, mark part number as complete
                        if not found_part_number and part_number_lines:
                            found_part_number = True
                        
                        # Check if this is a decimal number (price)
                        if line.replace('.', '').isdigit() and '.' in line:
                            try:
                                price_per = float(line)
                                found_price = True
                                price_line_idx = i
                                break
                            except:
                                description_lines.append(line)
                        else:
                            description_lines.append(line)
            
            # Look for discount and total after price
            if price_line_idx > 0:
                remaining_lines = lines[price_line_idx + 1:]
                for j, remaining_line in enumerate(remaining_lines):
                    if '%' in remaining_line:
                        discount = remaining_line.replace('%', '').strip()
                    elif 'J' in remaining_line:
                        try:
                            total_amount = float(remaining_line.replace('J', '').strip())
                        except:
                            if j > 0:
                                prev_line = remaining_lines[j - 1]
                                try:
                                    total_amount = float(prev_line)
                                except:
                                    pass
            
            part_number = ' '.join(part_number_lines) if part_number_lines else ''
            
            if not part_number and len(lines) > 1:
                part_number = lines[1]
            
            description = ' '.join(description_lines)
            
            # Calculate cost per item
            cost_per_item = 0.0
            if total_amount > 0 and quantity > 0:
                cost_per_item = round(total_amount / quantity, 2)
            elif price_per > 0:
                discount_val = float(discount) / 100 if discount else 0
                cost_per_item = round(price_per * (1 - discount_val), 2)
            
            if not part_number or cost_per_item == 0:
                return None
            
            return {
                'quantity': quantity,
                'part_number': part_number,
                'description': description,
                'price_per': price_per,
                'discount': discount,
                'total_amount': total_amount,
                'cost_per_item': cost_per_item
            }
            
        except Exception as e:
            self.logger.error(f"Error parsing column cell: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None

    def _extract_rotated_page(self, page) -> List[Dict]:
        """Extract items from a 90-degree rotated page using coordinate-based approach"""
        items = []
        try:
            words = page.extract_words(keep_blank_chars=True, x_tolerance=3, y_tolerance=3)
            if not words:
                self.logger.warning("No words extracted from page")
                return []
            self.logger.info(f"Extracted {len(words)} words from rotated page")
            from collections import defaultdict
            columns = defaultdict(list)
            for word in words:
                x_bucket = round(word['x0'] / 50) * 50
                columns[x_bucket].append(word)
            sorted_columns = sorted(columns.items())
            self.logger.info(f"Organized into {len(sorted_columns)} columns")
            qty_column_idx = -1
            for idx, (x_pos, col_words) in enumerate(sorted_columns):
                numeric_count = sum(1 for w in col_words if w['text'].replace('.', '').isdigit())
                if numeric_count >= 3:
                    qty_column_idx = idx
                    self.logger.info(f"Found quantity column at index {idx} (X={x_pos})")
                    break
            if qty_column_idx == -1:
                self.logger.warning("Could not identify quantity column")
                return []
            qty_column = sorted_columns[qty_column_idx][1]
            qty_column = sorted(qty_column, key=lambda w: w['top'])
            for qty_word in qty_column:
                try:
                    qty_text = qty_word['text'].strip()
                    if not qty_text.replace('.', '').isdigit():
                        continue
                    quantity = float(qty_text)
                    if quantity <= 0 or quantity > 1000:
                        continue
                    qty_y = qty_word['top']
                    tolerance = 15
                    item = {'quantity': quantity, 'part_number': '', 'description': '', 'price_per': 0.0, 'discount': '0', 'total_amount': 0.0, 'cost_per_item': 0.0}
                    row_words = []
                    for x_pos, col_words in sorted_columns:
                        for word in col_words:
                            if abs(word['top'] - qty_y) < tolerance:
                                row_words.append(word)
                    row_words = sorted(row_words, key=lambda w: w['x0'])
                    part_num_candidates = [w['text'] for w in row_words if w != qty_word]
                    if part_num_candidates:
                        for candidate in part_num_candidates:
                            if any(c.isalpha() for c in candidate) and any(c.isdigit() for c in candidate):
                                item['part_number'] = candidate
                                break
                    desc_words = []
                    for word in row_words:
                        text = word['text']
                        if (text not in [str(quantity), item['part_number']] and not text.replace('.', '').replace('%', '').isdigit() and text not in ['each', 'J', '£']):
                            desc_words.append(text)
                    item['description'] = ' '.join(desc_words[:10])
                    for word in row_words:
                        text = word['text']
                        if '%' in text:
                            try:
                                item['discount'] = text.replace('%', '').strip()
                            except:
                                pass
                        if re.match(r'^\d+\.\d{2}$', text):
                            price = float(text)
                            if item['price_per'] == 0.0:
                                item['price_per'] = price
                            else:
                                item['total_amount'] = price
                    if item['total_amount'] > 0 and quantity > 0:
                        item['cost_per_item'] = round(item['total_amount'] / quantity, 2)
                    elif item['price_per'] > 0:
                        discount_val = float(item['discount']) / 100 if item['discount'] else 0
                        item['cost_per_item'] = round(item['price_per'] * (1 - discount_val), 2)
                    if item['part_number'] and item['cost_per_item'] > 0:
                        items.append(item)
                        self.logger.info(f"Extracted: {item['part_number']} - {item['description'][:30]}...")
                except Exception as e:
                    self.logger.error(f"Error processing quantity {qty_text}: {str(e)}")
                    continue
        except Exception as e:
            self.logger.error(f"Error in _extract_rotated_page: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
        return items

    def _extract_normal_page(self, page) -> List[Dict]:
        """Extract items from normal (non-rotated) page using table extraction"""
        items = []
        try:
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                header_idx = -1
                for i, row in enumerate(table):
                    if row and any('Qty' in str(cell) for cell in row):
                        header_idx = i
                        break
                if header_idx == -1:
                    continue
                for row in table[header_idx + 1:]:
                    if not row or not row[0]:
                        continue
                    try:
                        item = {'quantity': float(row[0]), 'part_number': str(row[1]) if len(row) > 1 else '', 'description': str(row[2]) if len(row) > 2 else '', 'price_per': float(row[3]) if len(row) > 3 and row[3] else 0.0, 'discount': str(row[4]) if len(row) > 4 and row[4] else '0', 'total_amount': float(row[5]) if len(row) > 5 and row[5] else 0.0, 'cost_per_item': 0.0}
                        if item['total_amount'] > 0 and item['quantity'] > 0:
                            item['cost_per_item'] = round(item['total_amount'] / item['quantity'], 2)
                        if item['part_number']:
                            items.append(item)
                    except:
                        continue
        except Exception as e:
            self.logger.error(f"Error in _extract_normal_page: {str(e)}")
        return items

    def extract_job_reference(self, pdf_path: str) -> str:
        """Extract job reference from CEF invoice"""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                text = pdf.pages[0].extract_text() if len(pdf.pages) > 0 else ""
                patterns = [r'Your\s+Ref[:\s]+([A-Z0-9\s\-/]+?)(?:\n|$)', r'Order\s+Ref[:\s]+([A-Z0-9\s\-/]+?)(?:\n|$)', r'Job[:\s]+([A-Z0-9\s\-/]+?)(?:\n|$)']
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return match.group(1).strip()
                return None
        except Exception as e:
            self.logger.error(f"Error extracting job reference: {str(e)}")
            return None

    def process_pdf(self, pdf_path: str):
        """Process PDF and return results for QuickBooks integration"""
        try:
            self.logger.info(f"Processing CEF PDF: {pdf_path}")
            items = self.extract_pdf_data(pdf_path)
            results = []
            for item in items:
                new_prices = self.calculate_new_prices(item)
                results.append({'Part Number': item['part_number'], 'Description': item['description'], 'Quantity': item['quantity'], 'Unit Price': item.get('price_per', 0), 'Discount': item.get('discount', '0'), 'Total Amount': item.get('total_amount', 0), 'Cost Per Item': item.get('cost_per_item', 0), 'New Sales Price': new_prices['new_sales_price']})
            return results
        except Exception as e:
            self.logger.error(f"Error processing PDF: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []

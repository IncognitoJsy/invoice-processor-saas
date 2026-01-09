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
            
            transformed_items = []
            for item in items:
                new_prices = self.calculate_new_prices(item)
                
                transformed_item = {
                    'part_number': item['part_number'],
                    'description': item['description'],
                    'quantity': item['quantity'],
                    'original_unit_price': item.get('price_per', 0),
                    'discount': item.get('discount', '0'),
                    'cost_per_item': item.get('cost_per_item', 0),
                    'total_amount': item.get('total_amount', 0),
                    'selling_price': new_prices['new_sales_price'],
                    'markup_percent': self._get_markup_percent(item.get('discount', '0')),
                    'profit_per_item': round(new_prices['new_sales_price'] - item.get('cost_per_item', 0), 2)
                }
                transformed_items.append(transformed_item)
            
            return {
                'success': True,
                'items': transformed_items,
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

    def _get_markup_percent(self, discount: str) -> int:
        """Get markup percentage based on discount"""
        try:
            discount_val = float(discount)
        except:
            discount_val = 0
        
        if discount_val == 0:
            return 20
        elif 1 <= discount_val <= 30:
            return 40
        elif 30 < discount_val <= 70:
            return 50
        else:
            return 70

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
                    # First try table-based extraction
                    page_items = self._extract_from_tables(page)
                    
                    if not page_items:
                        # Fallback to coordinate-based extraction
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

    def _extract_from_tables(self, page) -> List[Dict]:
        """Smart table extraction that handles both column-based and row-based formats"""
        items = []
        
        try:
            tables = page.extract_tables()
            if not tables:
                return []
            
            table = tables[0]
            if not table or len(table) == 0:
                return []
            
            # Detect format type
            row = table[0]
            
            # Format 1: Multiple columns (each column is an item) - JER765610 style
            if len(row) > 3 and any(cell and '\n' in str(cell) for cell in row):
                self.logger.info("Detected column-based format (rotated PDF with items in columns)")
                items = self._extract_table_columns(table)
            
            # Format 2: Single column with full row text - JER753997 style
            elif len(row) == 1:
                self.logger.info("Detected row-based format (single column with space-separated data)")
                items = self._extract_single_column_rows(table)
            
            # Format 3: Normal multi-column table
            else:
                self.logger.info("Detected normal table format")
                items = self._extract_normal_table(table)
            
        except Exception as e:
            self.logger.error(f"Error in _extract_from_tables: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
        
        return items

    def _extract_single_column_rows(self, table) -> List[Dict]:
        """Extract items from single-column table where each row is space-separated text"""
        items = []
        
        for row_idx, row in enumerate(table):
            if not row or not row[0]:
                continue
            
            line = row[0].strip()
            
            # Skip header and empty rows
            if not line or 'Qty' in line and 'Item' in line:
                continue
            
            # Parse the space-separated line
            item = self._parse_single_line(line)
            if item:
                items.append(item)
                self.logger.info(f"Extracted row {row_idx}: {item['part_number']} - Qty: {item['quantity']}, Discount: {item['discount']}%")
        
        return items

    def _parse_single_line(self, line: str) -> Dict:
        """Parse a single line like '1 SWA STORM20S Storm Cable Gland M20S 34.78 pack 65% 12.17 J'"""
        try:
            parts = line.split()
            
            if len(parts) < 5:
                return None
            
            # First element is quantity
            try:
                quantity = float(parts[0])
            except:
                return None
            
            # Second element is part number (might be multi-word like "SWA STORM20S")
            part_number_parts = []
            description_parts = []
            price_per = 0.0
            discount = '0'
            total_amount = 0.0
            unit = 'each'
            
            found_price = False
            i = 1
            
            # Extract part number - keep collecting until we hit description text or price
            while i < len(parts):
                part = parts[i]
                
                # Check if this looks like a part number component
                # Part numbers: alphanumeric with hyphens (SWA, STORM20S, 251-100-040, GW44207)
                if re.match(r'^[A-Z0-9\-]+$', part) and not found_price:
                    part_number_parts.append(part)
                    i += 1
                elif part.replace('.', '').isdigit() and '.' in part:
                    # This is the price
                    price_per = float(part)
                    found_price = True
                    i += 1
                    break
                else:
                    # Start of description
                    break
            
            # Everything between part number and price is description
            while i < len(parts) and not found_price:
                part = parts[i]
                if part.replace('.', '').isdigit() and '.' in part:
                    price_per = float(part)
                    found_price = True
                    i += 1
                    break
                else:
                    description_parts.append(part)
                    i += 1
            
            # After price, look for unit, discount, total
            while i < len(parts):
                part = parts[i]
                
                if part in ['each', 'pack', 'm']:
                    unit = part
                elif '%' in part:
                    discount = part.replace('%', '')
                elif 'J' in part:
                    # Total might be before J or combined with it
                    if part == 'J' and i > 0:
                        try:
                            total_amount = float(parts[i-1])
                        except:
                            pass
                    else:
                        try:
                            total_amount = float(part.replace('J', ''))
                        except:
                            pass
                    break
                elif part.replace('.', '').isdigit() and '.' in part:
                    # Could be total amount
                    total_amount = float(part)
                
                i += 1
            
            part_number = ' '.join(part_number_parts)
            description = ' '.join(description_parts)
            
            # Calculate cost per item
            cost_per_item = 0.0
            if total_amount > 0 and quantity > 0:
                cost_per_item = round(total_amount / quantity, 2)
            elif price_per > 0:
                try:
                    discount_val = float(discount) / 100
                    cost_per_item = round(price_per * (1 - discount_val), 2)
                except:
                    cost_per_item = price_per
            
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
            self.logger.error(f"Error parsing single line: {str(e)}")
            return None

    def _extract_table_columns(self, table) -> List[Dict]:
        """Extract items from table where each item is in a column (JER765610 format)"""
        items = []
        
        try:
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
                    self.logger.info(f"Extracted from column {col_idx}: {item['part_number']}")
            
        except Exception as e:
            self.logger.error(f"Error in _extract_table_columns: {str(e)}")
        
        return items

    def _parse_column_cell(self, cell_text: str) -> Dict:
        """Parse a table cell that contains a complete item (JER765610 format)"""
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
                    is_all_caps = re.match(r'^[A-Z0-9\-]+$', line)
                    has_letter = any(c.isalpha() for c in line)
                    
                    if not found_part_number and is_all_caps and has_letter:
                        part_number_lines.append(line)
                    else:
                        if not found_part_number and part_number_lines:
                            found_part_number = True
                        
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
            return None

    def _extract_normal_table(self, table) -> List[Dict]:
        """Extract from normal multi-column table"""
        items = []
        
        try:
            header_idx = -1
            for i, row in enumerate(table):
                if row and any('Qty' in str(cell) for cell in row):
                    header_idx = i
                    break
            
            if header_idx == -1:
                return []
            
            for row in table[header_idx + 1:]:
                if not row or not row[0]:
                    continue
                
                try:
                    item = {
                        'quantity': float(row[0]),
                        'part_number': str(row[1]) if len(row) > 1 else '',
                        'description': str(row[2]) if len(row) > 2 else '',
                        'price_per': float(row[3]) if len(row) > 3 and row[3] else 0.0,
                        'discount': str(row[4]) if len(row) > 4 and row[4] else '0',
                        'total_amount': float(row[5]) if len(row) > 5 and row[5] else 0.0,
                        'cost_per_item': 0.0
                    }
                    
                    if item['total_amount'] > 0 and item['quantity'] > 0:
                        item['cost_per_item'] = round(item['total_amount'] / item['quantity'], 2)
                    
                    if item['part_number']:
                        items.append(item)
                
                except:
                    continue
        
        except Exception as e:
            self.logger.error(f"Error in _extract_normal_table: {str(e)}")
        
        return items

    def _extract_rotated_page(self, page) -> List[Dict]:
        """Fallback: coordinate-based extraction for truly rotated pages"""
        items = []
        try:
            words = page.extract_words(keep_blank_chars=True, x_tolerance=3, y_tolerance=3)
            if not words:
                return []
            # ... (keep existing coordinate-based code as fallback)
        except Exception as e:
            self.logger.error(f"Error in _extract_rotated_page: {str(e)}")
        return items

    def _extract_normal_page(self, page) -> List[Dict]:
        """Fallback for normal pages"""
        return []

    def extract_job_reference(self, pdf_path: str) -> str:
        """Extract job reference from CEF invoice"""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                text = pdf.pages[0].extract_text() if len(pdf.pages) > 0 else ""
                patterns = [r'Your\s+Ref[:\s]+([A-Z0-9\s\-/]+?)(?:\n|$)', r'Order\s+Ref[:\s]+([A-Z0-9\s\-/]+?)(?:\n|$)', r'Order\s+Number[:\s]+([A-Z0-9\s\-/]+?)(?:\n|$)', r'Job[:\s]+([A-Z0-9\s\-/]+?)(?:\n|$)']
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

"""Wholesale Electrics invoice parser"""
import re
import logging
from typing import Dict, List, Optional
from app.parsers.base_parser import BaseInvoiceParser
import pdfplumber

logger = logging.getLogger(__name__)

class WholesaleInvoiceParser(BaseInvoiceParser):
    """Parser for Wholesale Electrics with FIXED purchase cost calculation"""

    def __init__(self):
        super().__init__()
        self.supplier_name = 'WHOLESALE'

    def detect(self, filepath: str) -> bool:
        """Detect if this is a Wholesale invoice"""
        import pdfplumber
        try:
            with pdfplumber.open(filepath) as pdf:
                first_page_text = pdf.pages[0].extract_text() or ''
                return 'wholesale electric' in first_page_text.lower()
        except:
            return False
    def extract_from_tables(self, pdf):
        """Extract invoice data using table extraction"""
        items = []
        try:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    header_row = None
                    for row in table:
                        if row and "Item Code" in str(row) and "Description" in str(row):
                            header_row = row
                            break
                    if header_row:
                        try:
                            item_code_idx = header_row.index("Item Code")
                            desc_idx = header_row.index("Description")
                            quantity_idx = header_row.index("Quantity")
                            price_idx = header_row.index("Price Per")
                            amount_idx = header_row.index("Amount Code")
                        except ValueError:
                            continue

                        for row in table[table.index(header_row) + 1:]:
                            if not row or not row[item_code_idx] or "Goods Value" in str(row):
                                continue
                            item_code = row[item_code_idx]
                            description = row[desc_idx] if row[desc_idx] else ""
                            try:
                                quantity = float(row[quantity_idx])
                            except (ValueError, TypeError):
                                continue
                            price_per = None
                            try:
                                price_parts = str(row[price_idx]).split()
                                for part in price_parts:
                                    if "." in part:
                                        price_per = float(part)
                                        break
                            except (ValueError, TypeError):
                                continue
                            discount = "0"
                            total_amount = None
                            discount_amount = None
                            if row[amount_idx]:
                                amount_text = str(row[amount_idx])
                                if "%" in amount_text:
                                    for part in amount_text.split():
                                        if "%" in part:
                                            try:
                                                discount = part.replace("%", "").strip()
                                                break
                                            except (ValueError, TypeError):
                                                pass
                                found_amounts = []
                                for part in amount_text.split():
                                    if "." in part and "%" not in part:
                                        try:
                                            value = float(part)
                                            if value > 0:
                                                found_amounts.append(value)
                                        except (ValueError, TypeError):
                                            pass
                                if len(found_amounts) > 0:
                                    total_amount = found_amounts[0]
                                if len(found_amounts) > 1:
                                    discount_amount = found_amounts[1]

                            if total_amount is None and quantity and price_per:
                                total_amount = quantity * price_per

                            # FIXED: Calculate cost per item correctly
                            discount_value = float(discount or "0")
                            if discount_value > 0 and discount_value <= 100:
                                discount_value_decimal = discount_value / 100
                                if discount_amount:
                                    expected_discount = quantity * price_per * discount_value_decimal
                                    if abs(discount_amount - expected_discount) < 0.50:
                                        cost_per_item = price_per * (1 - discount_value_decimal)
                                    else:
                                        cost_per_item = total_amount / quantity if quantity > 0 else price_per
                                else:
                                    # KEY FIX: Apply discount percentage to price
                                    cost_per_item = price_per * (1 - discount_value_decimal)
                            else:
                                cost_per_item = price_per

                            items.append({
                                'part_number': item_code,
                                'description': description.strip(),
                                'quantity': quantity,
                                'price_per': round(price_per, 2),
                                'discount': discount,
                                'total_amount': round(total_amount, 2) if total_amount else 0,
                                'cost_per_item': round(cost_per_item, 2),
                                'original_price': round(price_per, 2)
                            })
        except Exception as e:
            logger.error(f"Error extracting from tables: {str(e)}")
        return items

    def extract_item_from_line(self, line: str, item_lines: List[str], current_idx: int) -> Optional[Dict]:
        """Extract item from text line with FIXED purchase cost"""
        try:
            parts = line.split()
            if not parts or len(parts) < 2:
                return None
            item_code = parts[0]
            numeric_sequence_start = -1
            for i in range(1, len(parts)):
                if parts[i].replace('.', '').isdigit():
                    numeric_sequence_start = i
                    break
            if numeric_sequence_start == -1:
                return None
            description = ' '.join(parts[1:numeric_sequence_start])
            try:
                quantity = float(parts[numeric_sequence_start])
            except (IndexError, ValueError):
                return None
            try:
                price_before_discount = float(parts[numeric_sequence_start + 1])
            except (IndexError, ValueError):
                return None
            price_per_amount = 1
            try:
                if numeric_sequence_start + 2 < len(parts):
                    price_per_value = parts[numeric_sequence_start + 2]
                    if price_per_value.isdigit():
                        price_per_amount = int(price_per_value)
            except (IndexError, ValueError):
                price_per_amount = 1
            unit_price = price_before_discount / price_per_amount if price_per_amount != 0 else price_before_discount
            discount_percent = 0
            discount_idx = -1
            for i in range(numeric_sequence_start + 3, min(numeric_sequence_start + 10, len(parts))):
                if i < len(parts) and '%' in parts[i]:
                    try:
                        discount_text = parts[i].replace('%', '')
                        discount_percent = float(discount_text)
                        discount_idx = i
                        break
                    except (ValueError, IndexError):
                        pass
            total_amount = price_before_discount * quantity
            discount_amount = None
            if discount_idx > 0 and discount_idx + 1 < len(parts):
                try:
                    possible_discount_amount = float(parts[discount_idx + 1])
                    if possible_discount_amount > 0 and possible_discount_amount < total_amount:
                        discount_amount = possible_discount_amount
                        if discount_idx + 2 < len(parts):
                            try:
                                possible_total = float(parts[discount_idx + 2])
                                if possible_total > 0:
                                    total_amount = possible_total
                            except (ValueError, IndexError):
                                pass
                except (ValueError, IndexError):
                    pass

            # FIXED: Calculate purchase cost correctly
            if discount_amount is not None:
                original_total = unit_price * quantity
                purchase_cost = original_total - discount_amount
                purchase_cost_per_item = purchase_cost / quantity if quantity > 0 else 0
            elif discount_percent > 0:
                # KEY FIX: Apply discount percentage to unit price
                purchase_cost_per_item = unit_price * (1 - discount_percent / 100)
            else:
                purchase_cost_per_item = unit_price

            purchase_cost = purchase_cost_per_item * quantity

            return {
                'part_number': item_code,
                'description': description.strip(),
                'quantity': quantity,
                'price_per': round(unit_price, 2),
                'discount': str(discount_percent),
                'total_amount': round(total_amount, 2),
                'cost_per_item': round(purchase_cost_per_item, 2),
                'original_price': round(unit_price, 2),
                'purchase_cost': round(purchase_cost, 2)
            }
        except Exception as e:
            logger.error(f"Error extracting item: {str(e)}")
        return None

    def parse(self, pdf_path: str) -> Dict:
        """Parse Wholesale invoice"""
        items = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                table_items = self.extract_from_tables(pdf)
                if table_items:
                    items = table_items
                else:
                    for page in pdf.pages:
                        text = page.extract_text()
                        lines = text.split('\n')
                        in_item_section = False
                        item_lines = []
                        for i, line in enumerate(lines):
                            if "Item Code" in line and "Description" in line and "Quantity" in line:
                                in_item_section = True
                                continue
                            if in_item_section:
                                if "Goods Value" in line or "GST Analysis" in line:
                                    in_item_section = False
                                    break
                                if not line.strip():
                                    continue
                                item_lines.append(line)
                        i = 0
                        while i < len(item_lines):
                            line = item_lines[i]
                            item = self.extract_item_from_line(line, item_lines, i)
                            if item:
                                items.append(item)
                            i += 1
            return {
                'supplier': 'WHOLESALE',
                'items': items,
                'invoice_number': None,
                'invoice_date': None,
                'total': sum(item.get('total_amount', 0) for item in items)
            }
        except Exception as e:
            logger.error(f"Error processing PDF: {str(e)}")
            return {'supplier': 'WHOLESALE', 'items': []}

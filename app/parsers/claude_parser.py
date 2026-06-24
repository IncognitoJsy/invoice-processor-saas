"""Claude API-based invoice parser using vision - handles consolidated invoices"""
import anthropic
import os
import base64
import json
import logging
import re
import io
from decimal import Decimal
from typing import Dict, List

from app.utils.money import money, to_decimal

# Try to import PIL for image enhancement
try:
    from PIL import Image, ImageEnhance, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)

class ClaudeInvoiceParser:
    """Universal invoice parser using Claude's vision capabilities"""
    
    def __init__(self):
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        
        self.client = anthropic.Anthropic(
            api_key=api_key,
            max_retries=2
        )
        self.logger = logging.getLogger(__name__)
        self._known_products_cache = None
    
    def _load_known_products(self, user_id: int = None) -> Dict[str, Dict]:
        """
        Load known products from the user's connected accounting software.
        Only loads from ONE platform - whichever the user has connected.
        Returns a dict mapping part_number -> product info
        """
        if self._known_products_cache is not None:
            self.logger.info(f"📦 Using cached products: {len(self._known_products_cache)} items")
            return self._known_products_cache
        
        known_products = {}
        
        self.logger.info("🔍 Checking for connected accounting software...")
        
        try:
            from flask_login import current_user
            
            if not current_user or not current_user.is_authenticated:
                self.logger.warning("⚠️ No authenticated user - cannot load products")
                self._known_products_cache = known_products
                return known_products
            
            # Check QuickBooks connection
            qb_connection = None
            try:
                from app.models.quickbooks import QuickBooksConnection
                qb_connection = QuickBooksConnection.query.filter_by(
                    user_id=current_user.id,
                    is_active=True
                ).first()
            except Exception as e:
                self.logger.debug(f"QuickBooks model check failed: {e}")
            
            # Check Xero connection
            xero_connection = None
            try:
                from app.models.xero import XeroConnection
                xero_connection = XeroConnection.query.filter_by(
                    user_id=current_user.id,
                    is_active=True
                ).first()
            except Exception as e:
                self.logger.debug(f"Xero model check failed: {e}")
            
            # Load from QuickBooks if connected
            if qb_connection and qb_connection.realm_id:
                self.logger.info(f"📗 User has QuickBooks connected (realm: {qb_connection.realm_id}) - loading products...")
                try:
                    # Use the integrations QuickBooksService which has get_items()
                    from app.integrations.quickbooks_service import QuickBooksService
                    
                    qb_service = QuickBooksService()
                    
                    # get_items expects the qb_connection object
                    response = qb_service.get_items(qb_connection)
                    qb_count = 0
                    
                    # QuickBooks API returns: {"QueryResponse": {"Item": [...]}}
                    if response and isinstance(response, dict):
                        if 'error' in response:
                            self.logger.warning(f"⚠️ QuickBooks API error: {response.get('error')}")
                        else:
                            items = response.get('QueryResponse', {}).get('Item', [])
                            self.logger.info(f"📦 Found {len(items)} items in QuickBooks")
                            
                            for item in items:
                                if isinstance(item, dict):
                                    sku = item.get('Sku') or ''
                                    name = item.get('Name', '')
                                    
                                    if sku:
                                        known_products[sku.upper()] = {
                                            'name': name,
                                            'sku': sku,
                                            'source': 'quickbooks',
                                            'sales_price': float(item.get('UnitPrice') or 0)
                                        }
                                        qb_count += 1
                                    
                                    if name and name.upper() not in known_products:
                                        known_products[name.upper()] = {
                                            'name': name,
                                            'sku': sku or name,
                                            'source': 'quickbooks',
                                            'sales_price': float(item.get('UnitPrice') or 0)
                                        }
                            
                            self.logger.info(f"✅ Loaded {qb_count} products with SKUs from QuickBooks")
                    else:
                        self.logger.warning(f"⚠️ Unexpected response format from QuickBooks: {type(response)}")
                        
                except Exception as e:
                    self.logger.warning(f"⚠️ Could not load QuickBooks products: {e}")
                    import traceback
                    self.logger.debug(traceback.format_exc())
            
            # Load from Xero if connected (only if QuickBooks is NOT connected)
            elif xero_connection and xero_connection.tenant_id:
                self.logger.info(f"📘 User has Xero connected (tenant: {xero_connection.tenant_id}) - loading products...")
                try:
                    # Use the integrations XeroService which has get_items()
                    from app.integrations.xero_service import XeroService
                    
                    xero_service = XeroService()
                    
                    # get_items expects the xero_connection object and returns a list
                    items = xero_service.get_items(xero_connection)
                    xero_count = 0
                    
                    if items and isinstance(items, list):
                        self.logger.info(f"📦 Found {len(items)} items in Xero")
                        
                        for item in items:
                            if isinstance(item, dict):
                                code = item.get('Code', '')
                                name = item.get('Name', '')
                                
                                if code:
                                    # Get sales price from Xero SalesDetails
                                    xero_sales_price = 0
                                    sales_details = item.get('SalesDetails', {})
                                    if sales_details:
                                        xero_sales_price = float(sales_details.get('UnitPrice') or 0)
                                    
                                    known_products[code.upper()] = {
                                        'name': name,
                                        'sku': code,
                                        'source': 'xero',
                                        'sales_price': xero_sales_price
                                    }
                                    xero_count += 1
                                
                                if name and name.upper() not in known_products:
                                    # Get sales price from Xero SalesDetails
                                    xero_sales_price_name = 0
                                    sales_details_name = item.get('SalesDetails', {})
                                    if sales_details_name:
                                        xero_sales_price_name = float(sales_details_name.get('UnitPrice') or 0)
                                    
                                    known_products[name.upper()] = {
                                        'name': name,
                                        'sku': code or name,
                                        'source': 'xero',
                                        'sales_price': xero_sales_price_name
                                    }
                        
                        self.logger.info(f"✅ Loaded {xero_count} products with codes from Xero")
                    else:
                        self.logger.warning(f"⚠️ No products returned from Xero or unexpected format: {type(items)}")
                        
                except Exception as e:
                    self.logger.warning(f"⚠️ Could not load Xero products: {e}")
                    import traceback
                    self.logger.debug(traceback.format_exc())
            
            else:
                self.logger.warning("⚠️ No accounting software connected")
                self.logger.warning("   Connect QuickBooks or Xero to enable part number validation")
            
            if known_products:
                self.logger.info(f"📦 Total products loaded: {len(known_products)}")
                sample_codes = list(known_products.keys())[:10]
                self.logger.info(f"📋 Sample product codes: {sample_codes}")
                    
        except Exception as e:
            self.logger.error(f"❌ Error loading known products: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
        
        self._known_products_cache = known_products
        return known_products
    
    def _load_learned_corrections(self, supplier_name: str = None) -> Dict[str, str]:
        """
        Load learned part number corrections from user's previous edits.
        Returns a dict: {original_ocr_upper: corrected_part}
        """
        learned = {}
        
        try:
            from flask_login import current_user
            
            if not current_user or not current_user.is_authenticated:
                return learned
            
            try:
                from app.models.part_number_correction import PartNumberCorrection
                
                learned = PartNumberCorrection.get_all_corrections_for_user(
                    user_id=current_user.id,
                    supplier_name=supplier_name
                )
                
                if learned:
                    self.logger.info(f"🧠 Loaded {len(learned)} learned corrections for user")
                    
            except ImportError:
                self.logger.debug("PartNumberCorrection model not found - learned corrections disabled")
            except Exception as e:
                self.logger.debug(f"Could not load learned corrections: {e}")
                
        except Exception as e:
            self.logger.debug(f"Error loading learned corrections: {e}")
        
        return learned
    
    def _validate_part_numbers(self, items: List[Dict], supplier_name: str = None) -> List[Dict]:
        """
        Validate and correct part numbers by comparing against known products.
        
        Priority order:
        1. Check learned corrections from user edits (highest confidence)
        2. Check exact match in QuickBooks/Xero products
        3. Try OCR variant matching
        4. Try fuzzy matching
        """
        known_products = self._load_known_products()
        learned_corrections = self._load_learned_corrections(supplier_name)
        
        if not known_products and not learned_corrections:
            self.logger.warning("⚠️ No known products or learned corrections - part number validation skipped")
            self.logger.warning("   Connect QuickBooks or Xero to enable part number cross-checking")
            return items
        
        self.logger.info(f"✅ Validating {len(items)} part numbers against {len(known_products)} products and {len(learned_corrections)} learned corrections")
        
        # Common OCR confusions for alphanumeric codes
        ocr_substitutions = {
            '0': ['O', 'D', 'Q', '5', '6'],
            'O': ['0', 'D', 'Q'],
            '8': ['B', '3'],
            'B': ['8', '3'],
            '1': ['I', 'L', '7'],
            'I': ['1', 'L'],
            'L': ['1', 'I'],
            '5': ['S', '0', '6'],
            'S': ['5'],
            '2': ['Z'],
            'Z': ['2'],
            '6': ['G', '0', '5'],
            'G': ['6'],
            'K': ['X', 'R'],
            'R': ['K', 'P', 'B'],
            'W': ['VV', 'M', 'UV'],
            'M': ['W', 'N', 'NN'],
            'N': ['M', 'H'],
            'H': ['N', 'U'],
            'U': ['V', 'H'],
            'V': ['U', 'Y'],
            'C': ['G', 'O', '0'],
            'E': ['F', '3'],
            'F': ['E', 'P'],
            'P': ['R', 'F'],
            'D': ['O', '0'],
            'Q': ['O', '0', '9'],
            '9': ['Q', 'G'],
            '4': ['A'],
            'A': ['4', 'R'],
            '3': ['8', 'E'],
            '7': ['1', 'T'],
            'T': ['7', 'I'],
        }
        
        def generate_variants(part_number: str) -> List[str]:
            """Generate possible variants of a part number with OCR corrections.
            Handles up to 2 character substitutions to catch multiple OCR errors."""
            variants = set([part_number])
            part_upper = part_number.upper()
            
            # First pass: single character substitutions
            first_pass = set([part_upper])
            for i, char in enumerate(part_upper):
                if char in ocr_substitutions:
                    for sub in ocr_substitutions[char]:
                        variant = part_upper[:i] + sub + part_upper[i+1:]
                        first_pass.add(variant)
            
            variants.update(first_pass)
            
            # Second pass: apply substitutions to first pass results (handles 2 OCR errors)
            for base_variant in list(first_pass):
                for i, char in enumerate(base_variant):
                    if char in ocr_substitutions:
                        for sub in ocr_substitutions[char]:
                            variant = base_variant[:i] + sub + base_variant[i+1:]
                            variants.add(variant)
            
            return list(variants)
        
        def find_best_match(part_number: str) -> tuple:
            """Find best matching product, returns (matched_sku, confidence, source)
            
            Priority:
            1. Learned corrections (100% confidence - user verified)
            2. Exact match in products (100% confidence)
            3. OCR variant match (95% confidence)
            4. Fuzzy match (85-95% confidence)
            """
            if not part_number:
                return None, 0, None
            
            part_upper = part_number.upper().strip()
            
            # 1. Check learned corrections FIRST (highest priority - user verified)
            if part_upper in learned_corrections:
                corrected = learned_corrections[part_upper]
                self.logger.info(f"🧠 Learned correction: '{part_number}' -> '{corrected}' (user verified)")
                return corrected, 100, 'learned'
            
            # 2. Exact match in products
            if part_upper in known_products:
                return known_products[part_upper]['sku'], 100, 'exact'
            
            # 3. Try OCR variant matches
            variants = generate_variants(part_upper)
            for variant in variants:
                if variant in known_products:
                    self.logger.info(f"Part number correction: '{part_number}' -> '{known_products[variant]['sku']}' (OCR fix)")
                    return known_products[variant]['sku'], 95, 'ocr'
            
            # 4. Try partial/fuzzy matching for longer part numbers
            if False and len(part_upper) >= 4:
                best_match = None
                best_score = 0
                
                for known_sku in known_products.keys():
                    # Check if one contains the other (for partial matches)
                    if part_upper in known_sku or known_sku in part_upper:
                        score = min(len(part_upper), len(known_sku)) / max(len(part_upper), len(known_sku)) * 100
                        if score > best_score and score >= 80:
                            best_score = score
                            best_match = known_sku
                    
                    # Check character-by-character similarity
                    if len(part_upper) == len(known_sku):
                        matches = sum(1 for a, b in zip(part_upper, known_sku) if a == b)
                        score = (matches / len(part_upper)) * 100
                        if score > best_score and score >= 85:
                            best_score = score
                            best_match = known_sku
                
                if best_match:
                    self.logger.info(f"Part number fuzzy match: '{part_number}' -> '{known_products[best_match]['sku']}' ({best_score:.0f}% confidence)")
                    return known_products[best_match]['sku'], best_score, 'fuzzy'
            
            return None, 0, None

        def differs_by_digit_swap(printed: str, candidate: str) -> bool:
            """True when `candidate` differs from the printed code at one or more
            positions where BOTH characters are digits (a digit swapped for a
            different digit). Trade part numbers encode size/rating in their
            digits — SB20MWH and SB25MWH are genuinely different products — so a
            digit-for-digit difference is almost always two distinct parts, not a
            scan error. These invoices are digital-text PDFs, so true OCR
            digit/digit confusion does not occur here anyway. Glyph misreads
            (O<->0, I<->1, S<->5, B<->8 ...) are NOT caught because one side is a
            letter, so legitimate OCR correction still works."""
            p, c = printed.upper().strip(), candidate.upper().strip()
            if len(p) != len(c):
                return False
            return any(a != b and a.isdigit() and b.isdigit() for a, b in zip(p, c))

        # Validate each item's part number
        corrected_items = []
        for item in items:
            item_copy = item.copy()
            original_part = item.get('part_number', '')

            matched_sku, confidence, source = find_best_match(original_part)

            # The printed code wins over a weak OCR-variant match when the only
            # difference is digit-for-digit — keep the code as printed unless we
            # have stronger evidence (a user-verified learned correction or an
            # exact catalog hit, neither of which is gated here).
            if (matched_sku and source == 'ocr'
                    and differs_by_digit_swap(original_part, matched_sku)):
                self.logger.info(
                    f"Keeping printed part '{original_part}' over OCR candidate "
                    f"'{matched_sku}' — digit-for-digit difference suggests a "
                    f"distinct part, not a misread"
                )
                matched_sku = None

            if matched_sku and matched_sku.upper() != original_part.upper():
                item_copy['part_number'] = matched_sku
                item_copy['original_ocr_part_number'] = original_part
                item_copy['part_number_confidence'] = confidence
                item_copy['correction_source'] = source  # 'learned', 'ocr', or 'fuzzy'
                self.logger.info(f"Corrected part number: '{original_part}' -> '{matched_sku}'")
            
            corrected_items.append(item_copy)
        
        return corrected_items
    
    def _preprocess_image(self, image_path: str) -> bytes:
        """
        Preprocess image to improve OCR quality before sending to Claude.
        - Upscales small images
        - Enhances contrast and sharpness
        - Converts to high-quality JPEG
        
        Returns: Preprocessed image as bytes
        """
        if not PIL_AVAILABLE:
            self.logger.warning("PIL not available, skipping image preprocessing")
            with open(image_path, 'rb') as f:
                return f.read()
        
        try:
            img = Image.open(image_path)
            original_size = img.size
            self.logger.info(f"Original image size: {original_size}")
            
            # Convert to RGB if necessary (for JPEG output)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Upscale if image is small (less than 2000px on longest side)
            max_dim = max(img.size)
            if max_dim < 2000:
                scale_factor = 2000 / max_dim
                # Cap scale factor at 3x to avoid huge images
                scale_factor = min(scale_factor, 3.0)
                new_size = (int(img.size[0] * scale_factor), int(img.size[1] * scale_factor))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                self.logger.info(f"Upscaled image to: {new_size}")
            
            # Apply slight sharpening to make text clearer
            img = img.filter(ImageFilter.SHARPEN)
            
            # Enhance contrast slightly (1.0 = original, >1.0 = more contrast)
            contrast_enhancer = ImageEnhance.Contrast(img)
            img = contrast_enhancer.enhance(1.2)
            
            # Enhance sharpness further (1.0 = original, >1.0 = sharper)
            sharpness_enhancer = ImageEnhance.Sharpness(img)
            img = sharpness_enhancer.enhance(1.5)
            
            # Convert back to bytes
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=95)
            buffer.seek(0)
            
            processed_bytes = buffer.read()
            self.logger.info(f"Preprocessed image: {len(processed_bytes)} bytes")
            
            return processed_bytes
            
        except Exception as e:
            self.logger.warning(f"Image preprocessing failed: {e}, using original")
            with open(image_path, 'rb') as f:
                return f.read()
    
    def parse(self, pdf_path: str, expected_document_type: str = 'invoice', user_markup_settings: Dict = None) -> Dict:
        """
        Parse invoice using Claude API - handles consolidated invoices
        Supports PDF, JPG, PNG, GIF, and WEBP files
        
        Args:
            pdf_path: Path to PDF or image file
            expected_document_type: 'invoice' or 'quote' - what the user selected
            user_markup_settings: Dict with 'is_admin' and 'default_markup' keys
        """
        try:
            self.logger.info(f"Claude parsing: {pdf_path}")
            self.logger.info(f"Expected document type: {expected_document_type}")
            self.logger.info(f"User markup settings: {user_markup_settings}")
            
            # Store markup settings for use in transform
            self.user_markup_settings = user_markup_settings or {'is_admin': False, 'default_markup': 50.0, 'tax_registered': False, 'tax_rate': 0.0}
            
            # Determine file type and media type
            file_ext = os.path.splitext(pdf_path)[1].lower()
            
            # Map extensions to media types
            media_type_map = {
                '.pdf': 'application/pdf',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }
            
            media_type = media_type_map.get(file_ext)
            if not media_type:
                return {
                    'success': False,
                    'error': f'Unsupported file type: {file_ext}. Supported types: PDF, JPG, PNG, GIF, WEBP'
                }
            
            # Read and preprocess file
            if media_type.startswith('image/'):
                # Preprocess images for better OCR
                file_bytes = self._preprocess_image(pdf_path)
                file_data = base64.standard_b64encode(file_bytes).decode('utf-8')
                # After preprocessing, output is always JPEG
                media_type = 'image/jpeg'
            else:
                # PDF - read as-is
                with open(pdf_path, 'rb') as f:
                    file_data = base64.standard_b64encode(f.read()).decode('utf-8')
            
            # Determine content type for API call
            if media_type == 'application/pdf':
                content_type = "document"
            else:
                content_type = "image"
            
            # Call Claude API with document/image
            message = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=8192,  # Increased for consolidated invoices
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": content_type,
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": file_data
                            }
                        },
                        {
                            "type": "text",
                            "text": self._get_extraction_prompt()
                        }
                    ]
                }]
            )
            
            # Parse response
            response_text = message.content[0].text
            self.logger.info(f"Claude response received: {len(response_text)} chars")
            
            return self._parse_response(response_text, pdf_path, expected_document_type)
            
        except Exception as e:
            self.logger.error(f"Claude parsing error: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': f'Claude API error: {str(e)}'
            }
    
    def _get_extraction_prompt(self) -> str:
        """Get the prompt for invoice extraction"""
        return """You are an expert at extracting data from electrical supplier invoices, quotations, and order documents (YESSS, CEF, Wholesale Electrics, etc).

CRITICAL: First, identify what TYPE of document this is by looking for keywords:
- QUOTATION, QUOTE, ESTIMATE, PROFORMA = This is a QUOTE
- INVOICE, TAX INVOICE, BILL = This is an INVOICE  
- CREDIT, CREDIT NOTE = This is a CREDIT NOTE
- ORDER ACKNOWLEDGEMENT, SALES ORDER, ORDER CONFIRMATION, PURCHASE ORDER, ADVICE NOTE, DELIVERY NOTE = This is an ORDER (treat as invoice)

CRITICAL: This PDF may contain MULTIPLE invoices/quotes (consolidated). Each has its own job reference and should be treated separately.

Extract all documents and return ONLY valid JSON with no markdown formatting, no code blocks, no explanation:

{
    "detected_document_type": "invoice" or "quote" or "credit_note" or "order",
    "supplier_account_number": "the customer's account number with this supplier - VERY IMPORTANT",
    "invoices": [
        {
            "document_type": "invoice" or "quote" or "credit_note" or "order",
            "supplier": "name of supplier (e.g. YESSS Electrical, CEF, Wholesale Electrics)",
            "invoice_number": "EXACT invoice/quote/order number as shown on document - THIS IS CRITICAL",
            "job_reference": "customer reference or job number (e.g. TLC, LA MAISON DE ST JEAN, DAVID HAZZARD, SARAH HOLT, MATT NORIS)",
            "goods_value": 0,
            "item_settlement": 0,
            "total_net_amount": 2788.74,
            "tax_rate": 5.0,
            "tax_amount": 139.44,
            "total_inc_tax": 2928.18,
            "items": [
                {
                    "part_number": "exact part number from document (e.g. JFG320U, WMSSU83, 221-415, HV3PROAAUB075T2, MMT2SFWH)",
                    "description": "complete item description, including all details even if multi-line",
                    "quantity": 2.0,
                    "original_unit_price": 1541.12,
                    "discount": "45",
                    "total_amount": 1695.23
                }
            ]
        }
    ]
}

SUPPLIER ACCOUNT NUMBER EXTRACTION - CRITICAL FOR FRAUD PREVENTION:
1. **WHOLESALE ELECTRICS**: Look for "Account" field in the header area, usually a 4-digit number (e.g., "6729")
2. **YESSS ELECTRICAL**: Look for "ACCOUNT NUMBER" field, format like "47669" or with branch prefix "093/47669" 
3. **CEF**: Look for "Account Code:" field, usually an 8-digit number (e.g., "86100012")
4. **OTHER SUPPLIERS**: Look for any field labeled "Account", "Account No", "Account Number", "Customer Account", "A/C No" etc.
5. This is the CUSTOMER'S account with the supplier, NOT an invoice number
6. Extract it EXACTLY as shown, including any slashes or formatting

DOCUMENT TYPE DETECTION - VERY IMPORTANT:
7. **QUOTE/QUOTATION**: Look for "QUOTATION", "QUOTE", "ESTIMATE", "PROFORMA" prominently displayed at top
8. **INVOICE**: Look for "INVOICE", "TAX INVOICE", "BILL" prominently displayed
9. **CREDIT NOTE**: Has "CREDIT" or "CREDIT NOTE" prominently displayed, negative amounts
10. **ORDER**: Look for "ORDER ACKNOWLEDGEMENT", "SALES ORDER", "ORDER CONFIRMATION", "ADVICE NOTE", "DELIVERY NOTE" - treat same as invoice
11. Set "detected_document_type" to the OVERALL type of the PDF (what's shown at the top)
12. Set each document's "document_type" accordingly

INVOICE/QUOTE/ORDER NUMBER EXTRACTION - VERY IMPORTANT:
13. **CEF**: Number is in TOP RIGHT, starts with "JER" (e.g., JER753997, JER765610)
14. **YESSS Invoices**: Number is under "INVOICE NUMBER", starts with "093" (e.g., 0931234567)
15. **YESSS Quotes**: Number is under "DOCUMENT NUMBER", format like "093QO69883"
16. **YESSS Orders**: Number is under "DOCUMENT NUMBER", format like "006SO201866"
17. **Wholesale Electrics**: Number is below "INVOICE NUMBER", starts with "IN" (e.g., IN123456)
18. Extract the EXACT number - do not modify or abbreviate it

CRITICAL RULES FOR CONSOLIDATED DOCUMENTS:
19. **DETECT MULTIPLE ORDERS**: Look for job reference changes
20. **SEPARATE EACH ORDER**: Create a separate entry in "invoices" array for each job reference
21. **GROUP ITEMS CORRECTLY**: Each entry should only contain items for that specific job reference
22. **TOTALS PER DOCUMENT — NET IS AFTER DISCOUNT**: total_net_amount is the supplier's NET TOTAL
    *after* any settlement/discount — NOT the pre-discount goods value. It must equal the sum of the
    per-line DISCOUNTED amounts for that job. If the invoice shows a separate "Goods Value" (full,
    pre-discount) and an "Item Settlement"/discount line (e.g. Wholesale Electrics), capture them as
    goods_value and item_settlement, with total_net_amount = goods_value − item_settlement. If there
    is no settlement line, set goods_value = total_net_amount and item_settlement = 0.
23. **ACCOUNT NUMBER IS SAME**: The supplier_account_number is the same for all invoices in a consolidated PDF

CRITICAL PRICING RULES FOR WHOLESALE ELECTRICS:
24. Wholesale Electrics columns: Item Code | Description | Quantity | Price Per | Amount | Discount% | Amount
25. "Price Per" shows unit price per X units - DO NOT USE THIS for total_amount
26. TWO SCENARIOS for "Amount" column:
    - If NO discount shown: Amount column IS the final cost (use as total_amount, discount="0")
    - If discount % IS shown: Amount column is BEFORE discount (use as total_amount, extract discount %)
27. Extract discount as just the number (e.g., "91" from "91.00%", "50" from "50.00%")
28. The code will calculate: actual_cost = total_amount * (1 - discount/100)
29. EXAMPLES:
    - "WMSS82 | 6 | 1.80 | 1 | 10.80 | 1" = qty=6, total_amount=10.80, discount=0 (no discount shown)
    - "SA2W | 1 | 61.92 | 1 | 91.00% | 61.92" = qty=1, total_amount=61.92, discount=91
    - "SB631 | 4 | 2.00 | 1 | 50.00% | 8.00" = qty=4, total_amount=8.00, discount=50

STANDARD RULES:
29. Extract EVERY SINGLE item from the document - do not skip any
30. Part numbers must be EXACT as shown on document
31. Descriptions must be COMPLETE - include all text even if it spans multiple lines
32. Prices must be NUMERIC ONLY (no £, $, or currency symbols)
33. Discount is the percentage as a STRING (e.g. "45" not "45%" or 45)
34. original_unit_price is the price BEFORE discount is applied
35. total_amount is the line total shown in the Amount column
34. If quantity is not explicitly shown, it's usually 1
35. Be very careful with decimal points - 1,541.12 means one thousand five hundred forty-one pounds

HANDLING UNKNOWN/NEW SUPPLIERS:
36. If the supplier is NOT YESSS, CEF, or Wholesale Electrics, apply these universal rules:
37. Look for the document title (INVOICE, QUOTE, etc.) prominently displayed at the top
38. Look for column headers - common patterns: Code/SKU/Part No | Description | Qty/Quantity | Unit Price/Price | Amount/Total/Net
39. The supplier name is usually the company logo or name at the very top of the page
40. Invoice/quote number is usually in the top right area, labeled Invoice No, Invoice Number, Quote No, Reference, etc.
41. Customer account number may be labeled: Account, A/C, Customer No, Account Code, etc.
42. Job reference may be labeled: Your Ref, Customer Ref, Order Ref, Job Ref, PO Number, Your Order, Reference, etc.
43. For line items, map columns by their headers - do NOT assume a fixed column order
44. Use the bottom totals to verify your extraction. The NET TOTAL is the figure AFTER any
    discount/settlement, and the sum of the per-line DISCOUNTED amounts should match it. If the
    invoice shows a pre-discount "Goods Value" and a discount/"Item Settlement" line, do NOT use the
    Goods Value as the net — capture goods_value and item_settlement separately (see rule 22).
45. If you see VAT/GST/Tax amounts on the invoice:
    - Extract the NET amount AFTER discount (before tax) as total_net_amount
    - Extract goods_value (full, pre-discount) and item_settlement (total discount) if shown, else
      goods_value = total_net_amount and item_settlement = 0
    - Extract the tax RATE as tax_rate (e.g. 5.0 for 5% GST, 20.0 for 20% VAT)
    - Extract the tax AMOUNT as tax_amount (the actual £ amount of tax charged)
    - Extract the GROSS total (inc tax) as total_inc_tax
    - If no tax is shown, set tax_rate=0, tax_amount=0, total_inc_tax=total_net_amount
46. For part numbers: extract exactly as shown, preserving dashes, slashes, and spaces
47. For descriptions: capture the full text even if it wraps across multiple lines
48. If a discount column exists, extract the discount percentage as a string
49. If no discount column exists, set discount to "0" for all items
50. ALWAYS extract every single line item - never skip items even if the format is unfamiliar

Double-check your work - missing items, wrong document type, wrong account number, or wrong grouping costs real money!"""
    
    def _parse_response(self, text: str, pdf_path: str, expected_document_type: str = 'invoice') -> Dict:
        """Parse Claude's JSON response - handles both single and consolidated invoices"""
        try:
            # Clean up response - remove markdown code blocks if present
            text = text.strip()
            if text.startswith('```'):
                lines = text.split('\n')
                text = '\n'.join(lines[1:-1])
            
            # Parse JSON
            data = json.loads(text)
            
            # Extract supplier account number (same for all invoices in the PDF)
            supplier_account_number = data.get('supplier_account_number')
            
            # Get supplier name for validation (from first invoice if consolidated)
            supplier_for_validation = None
            if 'invoices' in data and isinstance(data['invoices'], list) and len(data['invoices']) > 0:
                supplier_for_validation = data['invoices'][0].get('supplier', '')
            elif 'supplier' in data:
                supplier_for_validation = data.get('supplier', '')
            
            # Validate the account number - reject if it looks like an invoice number
            if supplier_account_number and supplier_for_validation:
                supplier_account_number = self._validate_account_number(supplier_account_number, supplier_for_validation)
            
            if supplier_account_number:
                self.logger.info(f"Validated supplier account number: {supplier_account_number}")
            
            # Check detected document type vs expected
            detected_type = data.get('detected_document_type', 'invoice').lower()
            
            # Normalize detected type
            if detected_type in ['quote', 'quotation', 'estimate', 'proforma']:
                detected_type = 'quote'
            elif detected_type in ['invoice', 'tax invoice', 'bill', 'order', 'order acknowledgement', 'sales order', 'order confirmation', 'advice note', 'advice_note', 'delivery note', 'delivery_note']:
                detected_type = 'invoice'  # Treat orders/advice notes as invoices
            elif detected_type in ['credit', 'credit_note', 'credit note']:
                detected_type = 'credit_note'
            
            self.logger.info(f"Detected document type: {detected_type}, Expected: {expected_document_type}")
            
            # Validate document type matches what user selected
            if detected_type == 'credit_note':
                return {
                    'success': False,
                    'error': 'This document is a Credit Note and cannot be processed.',
                    'is_credit_note': True,
                    'detected_document_type': detected_type
                }
            
            if detected_type != expected_document_type:
                # Mismatch - return error with helpful message
                if detected_type == 'quote' and expected_document_type == 'invoice':
                    return {
                        'success': False,
                        'error': 'This appears to be a QUOTATION, not an Invoice. Please select "Supplier Quote" and upload again.',
                        'document_type_mismatch': True,
                        'detected_document_type': detected_type,
                        'expected_document_type': expected_document_type
                    }
                elif detected_type == 'invoice' and expected_document_type == 'quote':
                    return {
                        'success': False,
                        'error': 'This appears to be an INVOICE, not a Quote. Please select "Supplier Invoice" and upload again.',
                        'document_type_mismatch': True,
                        'detected_document_type': detected_type,
                        'expected_document_type': expected_document_type
                    }
            
            # Check if this is consolidated format (multiple invoices)
            if 'invoices' in data and isinstance(data['invoices'], list):
                self.logger.info(f"Detected consolidated document with {len(data['invoices'])} entries")
                return self._process_consolidated_invoices(data['invoices'], pdf_path, expected_document_type, supplier_account_number)
            
            # Legacy single invoice format
            elif 'items' in data:
                self.logger.info("Detected single document format")
                return self._process_single_invoice(data, expected_document_type, supplier_account_number)
            
            else:
                return {'success': False, 'error': 'No items or invoices found in response'}
            
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parse error: {str(e)}")
            self.logger.error(f"Response text: {text[:500]}")
            return {
                'success': False,
                'error': f'Failed to parse JSON response: {str(e)}'
            }
        except Exception as e:
            self.logger.error(f"Response parsing error: {str(e)}")
            return {
                'success': False,
                'error': f'Failed to process response: {str(e)}'
            }
    
    def _process_consolidated_invoices(self, invoices: List[Dict], pdf_path: str, expected_document_type: str = 'invoice', supplier_account_number: str = None) -> Dict:
        """Process consolidated invoices - returns multiple invoice results, skips credit notes"""
        results = []
        skipped_credits = 0
        
        for idx, invoice_data in enumerate(invoices):
            try:
                # Check if this is a credit note - skip it
                doc_type = invoice_data.get('document_type', 'invoice').lower()
                if doc_type == 'credit_note' or 'credit' in doc_type:
                    self.logger.info(f"Skipping credit note: {invoice_data.get('invoice_number', 'unknown')}")
                    skipped_credits += 1
                    continue
                
                # Get supplier to determine pricing logic
                supplier = invoice_data.get('supplier', 'Unknown')
                inv_tax_rate = float(invoice_data.get('tax_rate') or 0)
                items = self._transform_items(invoice_data.get('items', []), supplier, supplier_tax_rate=inv_tax_rate)
                
                if not items:
                    continue
                
                # Validate and clean invoice number
                invoice_number = self._clean_invoice_number(
                    invoice_data.get('invoice_number'),
                    supplier
                )
                
                results.append({
                    'success': True,
                    'items': items,
                    'job_reference': invoice_data.get('job_reference'),
                    'supplier': supplier,
                    'invoice_number': invoice_number,
                    'supplier_account_number': supplier_account_number,
                    'document_type': expected_document_type,
                    'method': 'claude_api',
                    'consolidated': True,
                    'order_number': idx + 1,
                    'total_orders': len(invoices),
                    'tax_rate': float(invoice_data.get('tax_rate') or 0),
                    'tax_amount': float(invoice_data.get('tax_amount') or 0),
                    'goods_value': float(invoice_data.get('goods_value') or 0),
                    'item_settlement': float(invoice_data.get('item_settlement') or 0),
                    'total_ex_tax': float(invoice_data.get('total_net_amount') or 0),
                    'total_inc_tax': float(invoice_data.get('total_inc_tax') or 0),
                })
                
            except Exception as e:
                self.logger.error(f"Error processing document {idx + 1}: {str(e)}")
                continue
        
        if skipped_credits > 0:
            self.logger.info(f"Skipped {skipped_credits} credit note(s)")
        
        if not results:
            if skipped_credits > 0:
                return {'success': False, 'error': f'All {skipped_credits} documents were credit notes - nothing to process'}
            return {'success': False, 'error': 'No valid documents processed from consolidated PDF'}
        
        # Return as multiple invoices
        return {
            'success': True,
            'consolidated': True,
            'invoices': results,
            'skipped_credits': skipped_credits,
            'supplier_account_number': supplier_account_number,
            'method': 'claude_api',
            'document_type': expected_document_type
        }
    
    def _process_single_invoice(self, data: Dict, expected_document_type: str = 'invoice', supplier_account_number: str = None) -> Dict:
        """Process single invoice format (legacy/fallback)"""
        # Check if this is a credit note
        doc_type = data.get('document_type', 'invoice').lower()
        if doc_type == 'credit_note' or 'credit' in doc_type:
            return {
                'success': False, 
                'error': 'Document is a credit note - skipping',
                'is_credit_note': True
            }
        
        # Get supplier to determine pricing logic
        supplier = data.get('supplier', 'Unknown')
        inv_tax_rate = float(data.get('tax_rate') or 0)
        items = self._transform_items(data.get('items', []), supplier, supplier_tax_rate=inv_tax_rate)
        
        if not items:
            return {'success': False, 'error': 'No items found'}
        
        # Validate and clean invoice number
        invoice_number = self._clean_invoice_number(
            data.get('invoice_number'),
            supplier
        )
        
        # Use supplier_account_number from data if not passed
        if not supplier_account_number:
            supplier_account_number = data.get('supplier_account_number')
        
        return {
            'success': True,
            'items': items,
            'job_reference': data.get('job_reference'),
            'supplier': supplier,
            'invoice_number': invoice_number,
            'supplier_account_number': supplier_account_number,
            'document_type': expected_document_type,
            'method': 'claude_api',
            'consolidated': False,
            'tax_rate': float(data.get('tax_rate') or 0),
            'tax_amount': float(data.get('tax_amount') or 0),
            'goods_value': float(data.get('goods_value') or 0),
            'item_settlement': float(data.get('item_settlement') or 0),
            'total_ex_tax': float(data.get('total_net_amount') or 0),
            'total_inc_tax': float(data.get('total_inc_tax') or 0),
        }
    
    def _clean_invoice_number(self, invoice_number: str, supplier: str) -> str:
        """Clean and validate invoice number based on supplier patterns"""
        if not invoice_number:
            return None
        
        # Remove any whitespace
        invoice_number = str(invoice_number).strip()
        
        supplier_lower = supplier.lower() if supplier else ''
        
        # Validate pattern based on supplier
        if 'cef' in supplier_lower:
            # CEF: Should start with JER
            if not invoice_number.upper().startswith('JER'):
                # Try to extract JER number from the string
                match = re.search(r'(JER\d+)', invoice_number, re.IGNORECASE)
                if match:
                    invoice_number = match.group(1).upper()
            else:
                invoice_number = invoice_number.upper()
                
        elif 'yesss' in supplier_lower:
            # YESSS: Should start with 093
            if not invoice_number.startswith('093'):
                # Try to extract 093 number
                match = re.search(r'(093\w+)', invoice_number)
                if match:
                    invoice_number = match.group(1)
                    
        elif 'wholesale' in supplier_lower:
            # Wholesale: Should start with IN
            if not invoice_number.upper().startswith('IN'):
                # Try to extract IN number
                match = re.search(r'(IN\d+)', invoice_number, re.IGNORECASE)
                if match:
                    invoice_number = match.group(1).upper()
            else:
                invoice_number = invoice_number.upper()
        
        return invoice_number
    
    def _validate_account_number(self, account_number: str, supplier: str) -> str:
        """Validate and clean supplier account number - reject invoice numbers mistakenly captured
        
        This is CRITICAL for fraud prevention. We need to ensure we're capturing the actual
        customer account number, not an invoice number.
        
        Account number patterns:
        - YESSS: Format like "093/47669" (contains slash, NO "IN")
        - CEF: 8-digit number like "86100012" (NO "JER")  
        - Wholesale Electrics: 4-digit number like "6729" (NO "IN" prefix)
        """
        if not account_number:
            return None
        
        account_number = str(account_number).strip()
        supplier_lower = supplier.lower() if supplier else ''
        
        # YESSS validation
        if 'yesss' in supplier_lower:
            # YESSS account numbers can be:
            # - With slash: "093/47669"
            # - Just the number: "47669"
            # Invoice numbers contain "IN" (e.g., "093IN1101998")
            # Quote numbers contain "QO" (e.g., "093QO69883")
            # Order numbers contain "SO" (e.g., "006SO201866")
            if 'IN' in account_number.upper() or 'QO' in account_number.upper() or 'SO' in account_number.upper():
                self.logger.warning(f"Rejecting YESSS account number '{account_number}' - looks like an invoice/quote/order number")
                return None
            # Valid YESSS account should be numeric (possibly with slash)
            clean_account = account_number.replace('/', '').replace(' ', '')
            if not clean_account.isdigit():
                self.logger.warning(f"Rejecting YESSS account number '{account_number}' - should be numeric")
                return None
                
        # CEF validation  
        elif 'cef' in supplier_lower:
            # CEF account numbers are numeric (e.g., "86100012")
            # Invoice numbers start with "JER"
            if 'JER' in account_number.upper():
                self.logger.warning(f"Rejecting CEF account number '{account_number}' - looks like an invoice number (contains 'JER')")
                return None
            # Should be mostly numeric
            if not account_number.replace('-', '').replace(' ', '').isdigit():
                self.logger.warning(f"Rejecting CEF account number '{account_number}' - should be numeric")
                return None
                
        # Wholesale Electrics validation
        elif 'wholesale' in supplier_lower:
            # Wholesale account numbers are short numeric (e.g., "6729")
            # Invoice numbers start with "IN"
            if account_number.upper().startswith('IN'):
                self.logger.warning(f"Rejecting Wholesale account number '{account_number}' - looks like an invoice number (starts with 'IN')")
                return None
            # Should be numeric and relatively short
            if not account_number.replace('-', '').replace(' ', '').isdigit():
                self.logger.warning(f"Rejecting Wholesale account number '{account_number}' - should be numeric")
                return None
        
        self.logger.info(f"Validated account number: '{account_number}' for supplier: {supplier}")
        return account_number
    
    def _get_admin_tiered_markup(self, discount_val: float) -> float:
        """Get markup for admin user based on discount tiers.

        Bands are continuous (no gaps for fractional discounts):
        d <= 0 -> 20%, 0 < d <= 30 -> 40%, 30 < d <= 70 -> 50%, d > 70 -> 70%.
        """
        if discount_val <= 0:
            return 0.20  # 20% markup
        elif discount_val <= 30:
            return 0.40  # 40% markup
        elif discount_val <= 70:
            return 0.50  # 50% markup
        else:
            return 0.70  # 70% markup
    
    def _transform_items(self, items: List[Dict], supplier: str = 'Unknown', supplier_tax_rate: float = None) -> List[Dict]:
        """Transform items to our internal format with pricing
        
        Admin users: Use tiered markup based on discount percentage
        Regular users: Use their flat default_markup setting
        
        PRICE COMPARISON: If product exists in QuickBooks/Xero with a HIGHER
        sales price than calculated, use the higher price to protect margins.
        """
        transformed = []
        supplier_lower = supplier.lower() if supplier else ''
        
        # Get user markup settings
        is_admin = self.user_markup_settings.get('is_admin', False)
        user_default_markup = self.user_markup_settings.get('default_markup', 50.0) / 100  # Convert to decimal
        
        self.logger.info(
            f"Transform items: is_admin={is_admin}, user_markup={user_default_markup*100}%, "
            f"tax_registered={self.user_markup_settings.get('tax_registered', False)}, "
            f"tax_rate={self.user_markup_settings.get('tax_rate', 0)}%"
        )
        
        # Load known products for price comparison
        known_products = self._load_known_products()
        
        for item in items:
            try:
                # Safely parse values - handle 'None' strings and missing values
                # All money maths is Decimal; values are downcast to float only when
                # the result dict is built (it is jsonified in the upload response).
                quantity = to_decimal(item.get('quantity'))
                if quantity is None:
                    self.logger.warning(f"Skipping item {item.get('part_number', 'unknown')} - no quantity")
                    continue

                total_amount = to_decimal(item.get('total_amount'))
                if total_amount is None:
                    self.logger.warning(f"Skipping item {item.get('part_number', 'unknown')} - no total_amount")
                    continue

                # Skip items with zero quantity or amount
                if quantity <= 0 or total_amount <= 0:
                    self.logger.warning(f"Skipping item {item.get('part_number', 'unknown')} - zero value")
                    continue

                # Get discount percentage - safely handle None (kept as string for storage)
                discount = str(item.get('discount', '0') or '0').replace('%', '')
                if discount.lower() == 'none':
                    discount = '0'
                discount_val = to_decimal(discount)
                if discount_val is None:
                    discount_val = Decimal('0')

                # Apply discount to get actual cost
                # For Wholesale Electrics, total_amount is BEFORE discount
                # For YESSS and CEF, total_amount is ALREADY discounted
                if 'wholesale' in supplier_lower and discount_val > 0:
                    discounted_total = total_amount * (1 - discount_val / 100)
                else:
                    # YESSS, CEF, and others already show discounted amounts
                    discounted_total = total_amount

                cost_per_item = money(discounted_total / quantity)

                # ─── BULK CABLE PER-METRE CONVERSION ────────────────────────────
                # Cat6/data cable is sold as 1 box of 305m but needs per-metre pricing
                # for accurate quoting. Twin & Earth etc already show per-metre from supplier.
                description_lower = (item.get('description', '') or '').lower()
                part_lower = (item.get('part_number', '') or '').lower()
                
                is_305m_box = any(p in description_lower or p in part_lower for p in [
                    '305m', '305 m', '305mtr', '305 mtr', 'box 305', '305 metre', '305 meter'
                ])
                
                per_metre_converted = False
                if is_305m_box and quantity <= 10:
                    per_metre_converted = True  # cost is now per-metre; original_unit_price is per-box
                    original_box_cost = cost_per_item
                    cost_per_item = money(cost_per_item / 305, places=4)  # sub-penny unit rate
                    quantity = quantity * 305
                    self.logger.info(
                        f"📏 Per-metre conversion: {item.get('part_number', '')} "
                        f"£{original_box_cost:.2f}/box ÷ 305m = £{cost_per_item:.4f}/m"
                    )
                # ─── END BULK CABLE CONVERSION ─────────────────────────────────
                
                # Determine markup based on user type
                if is_admin:
                    # Admin uses tiered markup based on discount
                    markup = self._get_admin_tiered_markup(discount_val)
                else:
                    # Regular users use their flat markup setting
                    markup = user_default_markup

                # ── TAX-INCLUSIVE COST FOR NON-REGISTERED USERS ──────────────
                # If user is NOT tax/VAT/GST registered they cannot reclaim
                # input tax, so their real cost is tax-inclusive.
                # We must apply markup on the tax-inclusive cost so their
                # margin is protected.
                # If user IS tax registered, they reclaim input tax so cost
                # remains ex-tax (already correct).
                tax_registered = self.user_markup_settings.get('tax_registered', False)
                # Use supplier tax rate from invoice extraction if available,
                # otherwise fall back to user's country tax rate
                invoice_tax_rate = supplier_tax_rate if supplier_tax_rate is not None else self.user_markup_settings.get('tax_rate', 0.0)

                if not tax_registered and invoice_tax_rate > 0:
                    # Non-registered user cannot reclaim input tax
                    # Their real cost = ex-tax cost + irrecoverable tax
                    effective_cost = money(cost_per_item * (1 + to_decimal(invoice_tax_rate) / 100))
                    self.logger.info(
                        f"💰 Non-registered user: cost £{cost_per_item:.2f} "
                        f"+ {invoice_tax_rate}% supplier tax = effective cost £{effective_cost:.2f}"
                    )
                else:
                    # Tax registered — markup on ex-tax cost (they reclaim input tax)
                    effective_cost = cost_per_item

                # Calculate selling price using markup rules on effective cost
                calculated_selling_price = money(effective_cost * (1 + to_decimal(markup)))
                
                # PRICE COMPARISON: Check if accounting software has higher price
                final_selling_price = calculated_selling_price
                actual_markup = markup

                # Supplier list/counter price (per-unit, pre-discount): the ceiling a read-back
                # catalog price may not exceed (retail-cap philosophy). Defined here so the QB
                # override below can clip to it — not only the discounted-line cap further down.
                retail_unit = to_decimal(item.get('original_unit_price', 0) or 0) or Decimal('0')
                QB_NOLIST_MARKUP_CEIL = Decimal('5.0')  # no-list fallback: reject read-back >400% over cost

                if known_products:
                    part_upper = item.get('part_number', '').upper().strip() if item.get('part_number') else ''
                    if part_upper and part_upper in known_products:
                        # QB/Xero stores a PER-UNIT price, and calculated_selling_price
                        # is ALSO per-unit — compare and store on a per-unit basis.
                        existing_unit_price = to_decimal(known_products[part_upper].get('sales_price', 0)) or Decimal('0')
                        calculated_unit_price = calculated_selling_price
                        if existing_unit_price and existing_unit_price > calculated_unit_price:
                            # A read-back catalog price may not exceed the supplier COUNTER price
                            # (retail-cap philosophy). Ceiling = max(list, calc): calc preserves
                            # margin when list <= cost (e.g. GST-folded cost > per-metre list) and
                            # on zero-discount lines. No usable list (missing / per-metre-box
                            # converted, where original_unit_price is per-box) -> coarse fallback.
                            has_list = retail_unit > 0 and not per_metre_converted
                            ceiling = max(retail_unit, calculated_unit_price) if has_list else None
                            if ceiling is not None and existing_unit_price > ceiling:
                                self.logger.warning(
                                    f"⚠️ QB price £{existing_unit_price:.2f} for {part_upper} exceeds counter "
                                    f"ceiling £{ceiling:.2f} (list £{retail_unit:.2f}, calc £{calculated_unit_price:.2f}) "
                                    f"— clipping to ceiling (likely contaminated catalog price)")
                                final_selling_price = money(ceiling)
                            elif ceiling is None and existing_unit_price > calculated_unit_price * QB_NOLIST_MARKUP_CEIL:
                                self.logger.warning(
                                    f"⚠️ QB price £{existing_unit_price:.2f} for {part_upper} implausible vs calc "
                                    f"£{calculated_unit_price:.2f} and no list price — using calculated price")
                            else:
                                # At/below counter (or modest, no-list): adopt the higher QB price.
                                final_selling_price = money(existing_unit_price)
                            if cost_per_item > 0:
                                actual_markup = (final_selling_price - cost_per_item) / cost_per_item
                                source = known_products[part_upper].get('source', 'accounting')
                                self.logger.info(f"📈 Using higher {source} price for {part_upper}: £{existing_unit_price:.2f}/unit = £{final_selling_price:.2f} vs calculated £{calculated_selling_price:.2f}")

                # ── RETAIL CAP (discounted lines only) ───────────────────────
                # On DISCOUNTED lines, our per-unit selling must never exceed the supplier's
                # list/counter price (original_unit_price = unit price BEFORE discount) — the
                # customer could otherwise buy at full retail for less than we charge. Applied
                # AFTER the markup band AND the QB-price override, so retail is the ABSOLUTE
                # ceiling (a stale-high catalog price can't push us above counter price). No-op when:
                #   - the line had NO discount (discount_val == 0): a zero-discount SKU has
                #     list ≈ cost, so capping would force zero/negative margin — the normal markup
                #     is allowed to exceed retail there (deliberate user exception),
                #   - retail is unknown (0 / not extracted — best-effort, no schema enforcement),
                #   - the per-metre cable conversion ran (original_unit_price is per-box, not
                #     per-unit, so not comparable), or
                #   - retail <= our real cost (effective_cost) on a discounted line — capping
                #     there would sell at/below cost, so we leave the price and flag for review.
                # retail_unit computed above (before the QB-price override)
                if (discount_val > 0 and retail_unit > 0 and not per_metre_converted
                        and retail_unit < final_selling_price):
                    if retail_unit > effective_cost:
                        self.logger.info(
                            f"🧢 Retail cap: {item.get('part_number', '?')} £{final_selling_price:.2f} "
                            f"-> £{retail_unit:.2f} (supplier list-price ceiling)"
                        )
                        final_selling_price = money(retail_unit)
                        if cost_per_item > 0:
                            actual_markup = (final_selling_price - cost_per_item) / cost_per_item
                    else:
                        self.logger.warning(
                            f"⚠️ Retail cap skipped for {item.get('part_number', '?')}: list "
                            f"£{retail_unit:.2f} <= effective cost £{effective_cost:.2f} — review line "
                            f"(possible bad list price / would sell at a loss)"
                        )

                profit_per_item = money(final_selling_price - effective_cost)
                
                # Track QB price if different from calculated
                qb_price = None
                if known_products:
                    part_upper = item.get('part_number', '').upper().strip() if item.get('part_number') else ''
                    if part_upper and part_upper in known_products:
                        qb_price = known_products[part_upper].get('sales_price', 0)
                        if qb_price == 0:
                            qb_price = None
                
                transformed.append({
                    'part_number': item['part_number'],
                    'description': item['description'],
                    'quantity': float(quantity),
                    'original_unit_price': float(item.get('original_unit_price', 0) or 0),
                    'discount': discount,
                    # For non-tax-registered users buying from tax-charging suppliers,
                    # store the tax-inclusive cost as their true cost.
                    # For tax-registered users or tax-free suppliers, store ex-tax cost.
                    'cost_per_item': float(effective_cost),
                    'total_amount': float(money(discounted_total)),  # line net (rounded) — authority for totals
                    'selling_price': float(final_selling_price),
                    'calculated_selling_price': float(calculated_selling_price),
                    'qb_selling_price': qb_price,
                    'markup_percent': min(int(actual_markup * 100), 999),
                    'profit_per_item': float(profit_per_item)
                })
            except Exception as e:
                self.logger.error(f"Error processing item: {str(e)}")
                continue
        
        # Validate and correct part numbers against known products
        try:
            transformed = self._validate_part_numbers(transformed, supplier_name=supplier)
        except Exception as e:
            self.logger.warning(f"Part number validation skipped: {e}")
        
        return transformed

"""Product Matching Engine — Match AI-parsed materials against Xero/QB product lists

Matching Strategy (waterfall):
1. Exact part number match (highest confidence)
2. Fuzzy part number match (edit distance)
3. AI-assisted description match (Claude picks best match from candidates)
4. Unmatched (user must manually select or create product)
"""
import json
import logging
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


# ─── Product Fetching ──────────────────────────────────────────

def fetch_xero_products(user):
    """Fetch product/item list from Xero for the connected user.
    
    Returns list of dicts: [{code, name, description, purchase_price, sale_price, supplier_name, ...}]
    """
    from app.models.connection import Connection
    from app.services.xero_service import XeroService
    
    try:
        conn = Connection.query.filter_by(user_id=user.id, provider='xero', active=True).first()
        if not conn:
            return []
        
        xero = XeroService(conn)
        items = xero.get_items()
        
        products = []
        for item in items:
            products.append({
                'id': item.get('ItemID', ''),
                'code': item.get('Code', ''),
                'name': item.get('Name', ''),
                'description': item.get('Description', ''),
                'purchase_description': item.get('PurchaseDescription', ''),
                'purchase_price': float(item.get('PurchaseDetails', {}).get('UnitPrice', 0) or 0),
                'sale_price': float(item.get('SalesDetails', {}).get('UnitPrice', 0) or 0),
                'source': 'xero'
            })
        
        return products
    except Exception as e:
        logger.error(f"Failed to fetch Xero products: {e}")
        return []


def fetch_quickbooks_products(user):
    """Fetch product/item list from QuickBooks for the connected user.
    
    Returns list of dicts matching same format as Xero.
    """
    from app.models.connection import Connection
    from app.services.quickbooks_service import QuickBooksService
    
    try:
        conn = Connection.query.filter_by(user_id=user.id, provider='quickbooks', active=True).first()
        if not conn:
            return []
        
        qb = QuickBooksService(conn)
        items = qb.get_items()
        
        products = []
        for item in items:
            products.append({
                'id': str(item.get('Id', '')),
                'code': item.get('Sku', '') or item.get('Name', ''),
                'name': item.get('Name', ''),
                'description': item.get('Description', ''),
                'purchase_description': item.get('PurchaseDesc', ''),
                'purchase_price': float(item.get('PurchaseCost', 0) or 0),
                'sale_price': float(item.get('UnitPrice', 0) or 0),
                'source': 'quickbooks'
            })
        
        return products
    except Exception as e:
        logger.error(f"Failed to fetch QuickBooks products: {e}")
        return []


def fetch_user_products(user):
    """Fetch products from whichever accounting system the user has connected."""
    products = fetch_xero_products(user)
    if not products:
        products = fetch_quickbooks_products(user)
    return products


# ─── Matching Engine ──────────────────────────────────────────

def normalise(text):
    """Normalise text for matching: lowercase, strip whitespace, remove common noise."""
    if not text:
        return ''
    text = str(text).lower().strip()
    # Remove common catalogue prefixes/suffixes
    text = re.sub(r'\b(pxcable|pxwire)\b', '', text)
    # Remove packaging info
    text = re.sub(r'\b\d+m\b|\b\d+\s*metres?\b|\b\d+\s*pack\b|\bper\s*\w+\b', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def code_similarity(code1, code2):
    """Compare two product codes, handling common variations."""
    if not code1 or not code2:
        return 0.0
    
    c1 = re.sub(r'[\s\-_/]', '', str(code1).upper())
    c2 = re.sub(r'[\s\-_/]', '', str(code2).upper())
    
    # Exact match after normalisation
    if c1 == c2:
        return 1.0
    
    # One contains the other (e.g. "DLT5515000" matches "DLT5515000/MW")
    if c1 in c2 or c2 in c1:
        return 0.9
    
    # Sequence matcher for fuzzy
    return SequenceMatcher(None, c1, c2).ratio()


def description_similarity(desc1, desc2):
    """Compare two product descriptions using normalised sequence matching."""
    n1 = normalise(desc1)
    n2 = normalise(desc2)
    
    if not n1 or not n2:
        return 0.0
    
    return SequenceMatcher(None, n1, n2).ratio()


def match_single_item(item, products, threshold=0.5):
    """Match a single parsed item against the product list.
    
    Args:
        item: dict with at least 'part_number' and 'description'
        products: list of product dicts from accounting system
        threshold: minimum similarity score to consider a match
    
    Returns:
        list of candidate matches sorted by confidence, each:
        {product: {...}, confidence: float, match_type: str}
    """
    part_number = item.get('part_number', '') or ''
    description = item.get('description', '') or ''
    
    candidates = []
    
    for product in products:
        best_score = 0.0
        match_type = 'none'
        
        # 1. Code match (part_number vs product.code)
        code_score = code_similarity(part_number, product.get('code', ''))
        if code_score > best_score:
            best_score = code_score
            match_type = 'exact_code' if code_score == 1.0 else 'fuzzy_code'
        
        # 2. Description match (against both name and description)
        for field in ['name', 'description', 'purchase_description']:
            desc_score = description_similarity(description, product.get(field, ''))
            if desc_score > best_score:
                best_score = desc_score
                match_type = 'description'
        
        # 3. Cross-match: part_number against product description (sometimes codes are in descriptions)
        cross_score = code_similarity(part_number, product.get('name', ''))
        if cross_score > best_score:
            best_score = cross_score
            match_type = 'cross_match'
        
        if best_score >= threshold:
            candidates.append({
                'product': product,
                'confidence': round(best_score, 3),
                'match_type': match_type
            })
    
    # Sort by confidence descending
    candidates.sort(key=lambda x: x['confidence'], reverse=True)
    
    # Return top 5 candidates
    return candidates[:5]


def match_all_materials(combined_materials, products):
    """Match all parsed materials against the product list.
    
    Args:
        combined_materials: list from parsed data's combined_materials
        products: list of product dicts from accounting system
    
    Returns:
        list of match results, one per material:
        {
            material: {original parsed item},
            matches: [candidate matches],
            status: 'matched' | 'review' | 'unmatched',
            selected: {best match or null}
        }
    """
    results = []
    
    for item in combined_materials:
        candidates = match_single_item(item, products)
        
        if candidates and candidates[0]['confidence'] >= 0.95:
            # High confidence — auto-matched
            status = 'matched'
            selected = candidates[0]
        elif candidates and candidates[0]['confidence'] >= 0.6:
            # Medium confidence — needs review
            status = 'review'
            selected = candidates[0]
        else:
            # Low confidence — unmatched
            status = 'unmatched'
            selected = None
        
        results.append({
            'material': item,
            'matches': candidates,
            'status': status,
            'selected': selected
        })
    
    return results


# ─── AI-Assisted Matching ──────────────────────────────────────

def ai_match_unresolved(unmatched_items, products, api_key):
    """Use Claude to match items that the fuzzy matcher couldn't resolve.
    
    Sends unmatched items + a sample of the product list to Claude
    and asks it to pick the best match or confirm no match exists.
    """
    import anthropic
    
    if not unmatched_items or not products:
        return {}
    
    # Build a condensed product list (code + name only, limit to 500 for token efficiency)
    product_list = []
    for p in products[:500]:
        product_list.append(f"{p.get('code', 'N/A')} | {p.get('name', '')} | {p.get('description', '')[:80]}")
    
    items_to_match = []
    for item in unmatched_items:
        mat = item.get('material', {})
        items_to_match.append({
            'index': item.get('index'),
            'part_number': mat.get('part_number', ''),
            'description': mat.get('description', ''),
            'quantity': mat.get('total_quantity', 0)
        })
    
    prompt = f"""You are matching electrical materials from a parsed quote against a contractor's product database.

For each item below, find the BEST matching product from the database, or say "no_match" if nothing fits.

ITEMS TO MATCH:
{json.dumps(items_to_match, indent=2)}

PRODUCT DATABASE (code | name | description):
{chr(10).join(product_list)}

Return ONLY valid JSON — an array of objects:
[
  {{"index": 0, "matched_code": "PRODUCT_CODE" or null, "confidence": 0.0-1.0, "reason": "brief explanation"}}
]

Rules:
- Match by product code first, then by description similarity
- Don't force a match — if nothing fits, return null
- Confidence should reflect how sure you are
- Consider that suppliers use different descriptions for the same product"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = ""
        for block in message.content:
            if hasattr(block, 'text'):
                response_text += block.text
        
        response_text = response_text.strip()
        if response_text.startswith('```'):
            response_text = response_text.split('\n', 1)[1]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            response_text = response_text.strip()
        
        ai_matches = json.loads(response_text)
        
        # Build lookup: index -> matched product
        result = {}
        product_by_code = {p['code'].upper(): p for p in products if p.get('code')}
        
        for match in ai_matches:
            idx = match.get('index')
            code = match.get('matched_code')
            if code and code.upper() in product_by_code:
                result[idx] = {
                    'product': product_by_code[code.upper()],
                    'confidence': match.get('confidence', 0.7),
                    'match_type': 'ai_matched',
                    'reason': match.get('reason', '')
                }
        
        return result
        
    except Exception as e:
        logger.error(f"AI matching failed: {e}")
        return {}


# ─── Clean Description Generator ──────────────────────────────

def generate_clean_descriptions(materials_with_matches, api_key):
    """Generate customer-friendly descriptions for matched products.
    
    Takes the supplier descriptions and creates clean, simple English
    descriptions suitable for customer-facing invoices.
    
    Returns dict: {index: clean_description}
    """
    import anthropic
    
    items = []
    for i, item in enumerate(materials_with_matches):
        mat = item.get('material', {})
        selected = item.get('selected')
        supplier_desc = mat.get('description', '')
        product_desc = selected['product'].get('description', '') if selected else ''
        
        items.append({
            'index': i,
            'part_number': mat.get('part_number', ''),
            'supplier_description': supplier_desc,
            'product_description': product_desc
        })
    
    if not items:
        return {}
    
    prompt = f"""Generate clean, customer-friendly descriptions for these electrical products.

RULES:
- Simple English that a homeowner would understand on an invoice
- Remove supplier codes, catalogue numbers, packaging info (100m, per pack)
- Remove colour codes unless relevant (e.g. keep "matt white" for visible items)
- Keep essential specs: size (2.5mm), type (twin & earth), features (colour switchable)
- Max 50 characters per description
- Don't include brand names unless the customer would care

ITEMS:
{json.dumps(items, indent=2)}

Return ONLY valid JSON — an array:
[
  {{"index": 0, "clean_description": "2.5mm Twin & Earth Cable"}}
]"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = ""
        for block in message.content:
            if hasattr(block, 'text'):
                response_text += block.text
        
        response_text = response_text.strip()
        if response_text.startswith('```'):
            response_text = response_text.split('\n', 1)[1]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            response_text = response_text.strip()
        
        descriptions = json.loads(response_text)
        return {d['index']: d['clean_description'] for d in descriptions}
        
    except Exception as e:
        logger.error(f"Clean description generation failed: {e}")
        return {}

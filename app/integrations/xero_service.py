"""Xero Integration Service - OAuth and API calls"""
import os
import logging
import base64
import re
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from flask import url_for

from app.utils.money import money, to_decimal
from app.utils.tax import effective_output_rate

logger = logging.getLogger(__name__)


class XeroService:
    """Xero OAuth and API integration"""
    
    # Xero OAuth URLs
    AUTH_URL = 'https://login.xero.com/identity/connect/authorize'
    TOKEN_URL = 'https://identity.xero.com/connect/token'
    API_BASE_URL = 'https://api.xero.com/api.xro/2.0'
    CONNECTIONS_URL = 'https://api.xero.com/connections'
    
    # Scopes needed for invoice processing
    SCOPES = [
        'openid',
        'profile',
        'email',
        'accounting.transactions',
        'accounting.contacts',
        'accounting.settings',
        'offline_access'
    ]
    
    def __init__(self, user=None):
        self.client_id = os.environ.get('XERO_CLIENT_ID')
        self.client_secret = os.environ.get('XERO_CLIENT_SECRET')
        self.user = user
        self._output_tax_cache = None  # Cached (tax_type, status) tuple per request
        
        if not self.client_id or not self.client_secret:
            logger.warning("Xero credentials not configured")
    
    def get_auth_url(self, state: str) -> str:
        """Generate Xero OAuth authorization URL"""
        from urllib.parse import urlencode
        
        # Force HTTPS for production
        redirect_uri = url_for('integrations.xero_callback', _external=True)
        redirect_uri = redirect_uri.replace('http://', 'https://')
        
        logger.info(f"Xero redirect_uri: {redirect_uri}")
        
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'scope': ' '.join(self.SCOPES),
            'state': state
        }
        
        auth_url = f"{self.AUTH_URL}?{urlencode(params)}"
        logger.info(f"Xero auth URL: {auth_url}")
        
        return auth_url
    
    def exchange_code_for_tokens(self, auth_code: str) -> Optional[Dict]:
        """Exchange authorization code for access and refresh tokens"""
        redirect_uri = url_for('integrations.xero_callback', _external=True)
        redirect_uri = redirect_uri.replace('http://', 'https://')
        
        # Xero requires Basic auth with client credentials
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'redirect_uri': redirect_uri
        }
        
        try:
            response = requests.post(self.TOKEN_URL, headers=headers, data=data, timeout=30)
            
            if response.status_code == 200:
                tokens = response.json()
                logger.info("Successfully exchanged code for Xero tokens")
                return tokens
            else:
                logger.error(f"Xero token exchange failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Xero token exchange error: {str(e)}")
            return None
    
    def refresh_access_token(self, refresh_token: str) -> Optional[Dict]:
        """Refresh the access token using refresh token"""
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }
        
        try:
            response = requests.post(self.TOKEN_URL, headers=headers, data=data, timeout=30)
            
            if response.status_code == 200:
                tokens = response.json()
                logger.info("Successfully refreshed Xero tokens")
                return tokens
            else:
                logger.error(f"Xero token refresh failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Xero token refresh error: {str(e)}")
            return None
    
    def get_connections(self, access_token: str) -> List[Dict]:
        """Get list of connected Xero organisations (tenants)"""
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.get(self.CONNECTIONS_URL, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get Xero connections: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting Xero connections: {str(e)}")
            return []
    
    def _get_valid_token(self, connection) -> Optional[str]:
        """Get a valid access token, refreshing if necessary.

        Tokens are stored Fernet-encrypted (AUDIT risk #3); decrypt before use
        and encrypt before storing. Pre-encryption plaintext rows decrypt to
        themselves and are re-stored encrypted here on the next refresh.
        """
        from app.extensions import db
        from app.services.token_crypto import encrypt_token, decrypt_token

        # Check if token is expired or about to expire (within 5 minutes)
        if connection.token_expires_at <= datetime.utcnow() + timedelta(minutes=5):
            logger.info("Xero token expired or expiring soon, refreshing...")

            tokens = self.refresh_access_token(decrypt_token(connection.refresh_token))

            if tokens:
                connection.access_token = encrypt_token(tokens['access_token'])
                new_refresh = tokens.get('refresh_token')
                if new_refresh:
                    connection.refresh_token = encrypt_token(new_refresh)
                connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 1800))
                db.session.commit()
                return tokens['access_token']
            else:
                logger.error("Failed to refresh Xero token")
                connection.is_active = False
                db.session.commit()
                return None

        return decrypt_token(connection.access_token)
    
    def _make_request(self, method: str, endpoint: str, connection, data: Optional[Dict] = None) -> Optional[Dict]:
        """Make authenticated request to Xero API"""
        access_token = self._get_valid_token(connection)
        
        if not access_token:
            return None
        
        url = f"{self.API_BASE_URL}{endpoint}"
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Xero-tenant-id': connection.tenant_id,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, headers=headers, json=data, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, headers=headers, json=data, timeout=30)
            
            if response.status_code in [200, 201]:
                return response.json()
            else:
                logger.error(f"Xero API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Xero API request failed: {str(e)}")
            return None
    
    # ==================== Organisation / Company Info ====================
    
    def get_organisation(self, connection) -> Optional[Dict]:
        """Get organisation (company) info"""
        result = self._make_request('GET', '/Organisation', connection)
        if result and 'Organisations' in result:
            return result['Organisations'][0] if result['Organisations'] else None
        return None
    
    # ==================== Accounts ====================
    
    def get_accounts(self, connection) -> List[Dict]:
        """Get all accounts"""
        result = self._make_request('GET', '/Accounts', connection)
        return result.get('Accounts', []) if result else []
    
    def get_expense_accounts(self, connection) -> List[Dict]:
        """Get expense accounts suitable for bills"""
        accounts = self.get_accounts(connection)
        # Filter for expense-type accounts
        expense_types = ['EXPENSE', 'DIRECTCOSTS', 'OVERHEADS']
        return [a for a in accounts if a.get('Type') in expense_types and a.get('Status') == 'ACTIVE']
    
    def get_revenue_accounts(self, connection) -> List[Dict]:
        """Get revenue/income accounts"""
        accounts = self.get_accounts(connection)
        return [a for a in accounts if a.get('Type') == 'REVENUE' and a.get('Status') == 'ACTIVE']
    
    # ==================== Tax Types ====================
    
    def get_tax_rates(self, connection) -> List[Dict]:
        """Get all tax rates from Xero"""
        result = self._make_request('GET', '/TaxRates', connection)
        return result.get('TaxRates', []) if result else []
    
    # TaxRate name keywords that mean "no output GST" (exempt / zero-rated).
    EXEMPT_KEYWORDS = ('exempt', 'no gst', 'no vat', 'no tax', 'zero', 'none', 'out of scope')

    def resolve_output_tax(self, connection):
        """Resolve the output-GST TaxType for THIS user's synced sales lines.

        Returns an (tax_type, status) tuple, cached for the request:
          - (tax_type, 'taxable')  registered user; attach this Xero TaxType (output GST)
          - (tax_type, 'exempt')   unregistered user; a zero/exempt sales TaxType (Xero's
                                   built-in 'NONE' if the org has no named zero rate) ->
                                   no output GST
          - (None, 'unresolved')   registered user but no sales TaxType matches the
                                   expected rate -> callers MUST block (fail closed)

        Mirrors QuickBooksService.resolve_output_tax and is driven by
        self.user.tax_registered so the sync can never disagree with the cost-base
        treatment in claude_parser._transform_items (which folds irrecoverable input
        GST into the markup base only for UNREGISTERED users), making the
        "GST-in-base + output-GST-on-top" double charge impossible.

        Xero differences vs QBO: tax is a TaxType *string* (not a code object); the
        no-tax case is the built-in 'NONE' type rather than an omitted field; and rates
        come from the TaxRate object, so matching is by numeric rate (with a sales-only
        guard so a purchase/input rate is never used on a customer invoice).
        """
        if self._output_tax_cache is not None:
            return self._output_tax_cache

        # No user context -> cannot reason about registration -> fail closed.
        if self.user is None:
            logger.error("resolve_output_tax: no user on service — blocking sync")
            self._output_tax_cache = (None, 'unresolved')
            return self._output_tax_cache

        tax_rates = self.get_tax_rates(connection)
        logger.info(f"Available tax rates: {[tr.get('Name') for tr in tax_rates]}")

        # Unregistered: never charge output GST (their cost base already absorbs it).
        if not self.user.tax_registered:
            exempt = self._select_exempt_tax_type(tax_rates)
            self._output_tax_cache = (exempt, 'exempt')
            logger.info(f"Output tax: user not GST/VAT-registered -> exempt ({exempt})")
            return self._output_tax_cache

        # Registered: lines MUST carry output GST at the user's CONFIGURED rate.
        tax_type = self._select_taxable_tax_type(tax_rates)
        if tax_type:
            logger.info(f"Output tax: registered -> TaxType '{tax_type}' "
                        f"(target rate {effective_output_rate(self.user)}%)")
            self._output_tax_cache = (tax_type, 'taxable')
        else:
            logger.error(
                "Output tax: registered user but no sales tax type matches the configured rate "
                f"{effective_output_rate(self.user)}% — blocking sync")
            self._output_tax_cache = (None, 'unresolved')
        return self._output_tax_cache

    @staticmethod
    def _active(tax_rates):
        return [tr for tr in tax_rates if (tr.get('Status') or 'ACTIVE').upper() == 'ACTIVE']

    @staticmethod
    def _tax_rate_value(tax_rate):
        """Numeric percentage for a TaxRate: EffectiveRate, then DisplayTaxRate, then
        the sum of TaxComponents, then a percentage parsed from the name. None if absent."""
        for key in ('EffectiveRate', 'DisplayTaxRate'):
            v = tax_rate.get(key)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        comps = tax_rate.get('TaxComponents')
        if comps:
            try:
                return float(sum(float(c.get('Rate', 0) or 0) for c in comps))
            except (TypeError, ValueError):
                pass
        m = re.search(r'(\d+(?:\.\d+)?)\s*%', tax_rate.get('Name') or '')
        return float(m.group(1)) if m else None

    @classmethod
    def _is_exempt_rate(cls, tax_rate):
        name = (tax_rate.get('Name') or '').lower()
        if any(k in name for k in cls.EXEMPT_KEYWORDS):
            return True
        rate = cls._tax_rate_value(tax_rate)
        return rate is not None and rate == 0

    @staticmethod
    def _is_sales_applicable(tax_rate):
        """Output (sales) rate, not a purchase/input one. Uses Xero's
        CanApplyToRevenue flag when present, else a TaxType/name heuristic."""
        if 'CanApplyToRevenue' in tax_rate:
            return bool(tax_rate.get('CanApplyToRevenue'))
        tt = (tax_rate.get('TaxType') or '').upper()
        name = (tax_rate.get('Name') or '').upper()
        return not ('INPUT' in tt or 'INPUT' in name or 'PURCHASE' in name)

    def _select_exempt_tax_type(self, tax_rates):
        """A zero/exempt sales TaxType if the org has one, else Xero's built-in 'NONE'."""
        for tr in self._active(tax_rates):
            if self._is_sales_applicable(tr) and self._is_exempt_rate(tr):
                return tr.get('TaxType') or 'NONE'
        return 'NONE'  # Xero's built-in no-tax type — always valid

    def _select_taxable_tax_type(self, tax_rates):
        """Active, sales-applicable, non-exempt TaxType — MATCH-OR-FAIL against the user's
        configured output rate (`effective_output_rate`). The rate's real value must equal the
        configured rate within tolerance, else None (caller fails closed) — so the synced
        invoice never carries a rate the user didn't configure / the document didn't show."""
        expected = float(effective_output_rate(self.user))
        if expected <= 0:
            return None
        candidates = [tr for tr in self._active(tax_rates)
                      if self._is_sales_applicable(tr) and not self._is_exempt_rate(tr)]
        for tr in candidates:
            rate = self._tax_rate_value(tr)
            if rate is not None and abs(rate - expected) < 0.01:
                return tr.get('TaxType')
        return None

    def list_sales_tax_codes(self, connection):
        """Read-only listing of active, sales-applicable TaxTypes with their rate — the data
        source for the Settings output-tax-code picker (Xero mirror of the QBO method). Makes
        no writes. Returns [{'ref': TaxType, 'name': str, 'rate': Decimal|None, 'exempt': bool}]
        (rate is a percent; None when absent)."""
        out = []
        for tr in self._active(self.get_tax_rates(connection)):
            if not self._is_sales_applicable(tr):
                continue
            exempt = self._is_exempt_rate(tr)
            val = self._tax_rate_value(tr)
            rate = to_decimal(val) if val is not None else None
            out.append({'ref': tr.get('TaxType'), 'name': tr.get('Name', ''),
                        'rate': rate, 'exempt': exempt})
        return out

    def get_default_purchase_tax_type(self, connection) -> str:
        """Get the appropriate purchase tax type for bills"""
        try:
            tax_rates = self.get_tax_rates(connection)
            
            if not tax_rates:
                return 'NONE'
            
            # Look for input/purchase tax types
            for tax_rate in tax_rates:
                name = tax_rate.get('Name', '').upper()
                tax_type = tax_rate.get('TaxType', '')
                status = tax_rate.get('Status', '')
                
                if status != 'ACTIVE':
                    continue
                
                # Jersey GST on purchases
                if 'GST' in name and ('INPUT' in name or 'PURCHASE' in name):
                    return tax_type
                    
                # UK VAT INPUT2
                if tax_type == 'INPUT2':
                    return 'INPUT2'
            
            # Fallback to NONE
            return 'NONE'
            
        except Exception as e:
            logger.error(f"Error getting purchase tax type: {str(e)}")
            return 'NONE'
    
    # ==================== Contacts (Suppliers & Customers) ====================
    
    def get_contacts(self, connection) -> List[Dict]:
        """Get all contacts"""
        result = self._make_request('GET', '/Contacts', connection)
        return result.get('Contacts', []) if result else []
    
    def get_suppliers(self, connection) -> List[Dict]:
        """Get supplier contacts"""
        result = self._make_request('GET', '/Contacts?where=IsSupplier==true', connection)
        return result.get('Contacts', []) if result else []
    
    def get_customers(self, connection) -> List[Dict]:
        """Get customer contacts"""
        result = self._make_request('GET', '/Contacts?where=IsCustomer==true', connection)
        return result.get('Contacts', []) if result else []
    
    def create_contact(self, connection, name: str, is_supplier: bool = False, is_customer: bool = False) -> Optional[Dict]:
        """Create a new contact"""
        data = {
            'Contacts': [{
                'Name': name,
                'IsSupplier': is_supplier,
                'IsCustomer': is_customer
            }]
        }
        
        result = self._make_request('POST', '/Contacts', connection, data)
        if result and 'Contacts' in result:
            return result['Contacts'][0] if result['Contacts'] else None
        return None
    
    def find_or_create_supplier(self, connection, supplier_name: str) -> Optional[Dict]:
        """Find existing supplier or create new one"""
        # Search for existing supplier
        suppliers = self.get_suppliers(connection)
        
        for supplier in suppliers:
            if supplier.get('Name', '').lower() == supplier_name.lower():
                return supplier
        
        # Create new supplier
        logger.info(f"Creating new Xero supplier: {supplier_name}")
        return self.create_contact(connection, supplier_name, is_supplier=True)
    
    # ==================== Items (Products/Services) ====================
    
    def get_items(self, connection) -> List[Dict]:
        """Get all items"""
        result = self._make_request('GET', '/Items', connection)
        return result.get('Items', []) if result else []
    
    def create_item(self, connection, code: str, name: str, description: str,
                    purchase_price: float, sale_price: float,
                    purchase_account_code: str, sales_account_code: str) -> Optional[Dict]:
        """Create a new item (product/service)"""
        data = {
            'Items': [{
                'Code': code[:30],  # Xero limit
                'Name': name[:50],  # Xero limit
                'Description': description[:4000] if description else name,
                'PurchaseDetails': {
                    'UnitPrice': purchase_price,
                    'AccountCode': purchase_account_code
                },
                'SalesDetails': {
                    'UnitPrice': sale_price,
                    'AccountCode': sales_account_code
                }
            }]
        }
        
        result = self._make_request('POST', '/Items', connection, data)
        if result and 'Items' in result:
            logger.info(f"Created Xero item: {code}")
            return result['Items'][0] if result['Items'] else None
        return None
    
    def update_item(self, connection, item_id: str, code: str, name: str, description: str,
                    purchase_price: float, sale_price: float,
                    purchase_account_code: str, sales_account_code: str) -> Optional[Dict]:
        """Update an existing item's prices and details"""
        data = {
            'Items': [{
                'ItemID': item_id,
                'Code': code[:30],
                'Name': name[:50],
                'Description': description[:4000] if description else name,
                'PurchaseDetails': {
                    'UnitPrice': purchase_price,
                    'AccountCode': purchase_account_code
                },
                'SalesDetails': {
                    'UnitPrice': sale_price,
                    'AccountCode': sales_account_code
                }
            }]
        }
        
        result = self._make_request('POST', '/Items', connection, data)
        if result and 'Items' in result:
            logger.info(f"Updated Xero item: {code} - Purchase: £{purchase_price}, Sale: £{sale_price}")
            return result['Items'][0] if result['Items'] else None
        return None
    
    def find_or_create_item(self, connection, code: str, name: str, description: str,
                           purchase_price: float, sale_price: float,
                           purchase_account_code: str, sales_account_code: str) -> Optional[Dict]:
        """
        Find existing item by code, update prices if higher, or create new one.
        
        Price update logic:
        - If new sale_price is HIGHER than existing, update the item
        - This ensures we never sell at an old lower price when costs go up
        - Purchase price is also updated to reflect current cost
        """
        items = self.get_items(connection)
        
        for item in items:
            if item.get('Code', '').lower() == code.lower():
                # Found existing item - check if prices need updating
                existing_sale_price = float(item.get('SalesDetails', {}).get('UnitPrice', 0) or 0)
                existing_purchase_price = float(item.get('PurchaseDetails', {}).get('UnitPrice', 0) or 0)
                
                # Update if new sale price is higher OR purchase price changed significantly
                if sale_price > existing_sale_price or abs(purchase_price - existing_purchase_price) > 0.01:
                    logger.info(f"Updating item {code}: Sale £{existing_sale_price} -> £{sale_price}, "
                               f"Purchase £{existing_purchase_price} -> £{purchase_price}")
                    
                    updated_item = self.update_item(
                        connection,
                        item_id=item['ItemID'],
                        code=code,
                        name=name,
                        description=description,
                        purchase_price=purchase_price,
                        sale_price=sale_price,
                        purchase_account_code=purchase_account_code,
                        sales_account_code=sales_account_code
                    )
                    return updated_item if updated_item else item
                
                return item
        
        # Item doesn't exist - create it
        return self.create_item(connection, code, name, description,
                               purchase_price, sale_price,
                               purchase_account_code, sales_account_code)
    
    # ==================== Bills (Supplier Invoices) ====================
    
    def create_bill(self, connection, supplier_contact_id: str, invoice_number: str,
                    invoice_date: str, due_date: str, line_items: List[Dict],
                    reference: str = None) -> Optional[Dict]:
        """Create a bill (accounts payable invoice)"""
        
        # Get the appropriate tax type for this organisation
        purchase_tax_type = self.get_default_purchase_tax_type(connection)
        
        # Format line items for Xero
        xero_line_items = []
        for item in line_items:
            line = {
                'Description': item.get('description', ''),
                'Quantity': item.get('quantity', 1),
                'UnitAmount': item.get('unit_price', 0),
                'AccountCode': item.get('account_code'),
                'TaxType': purchase_tax_type
            }
            if item.get('item_code'):
                line['ItemCode'] = item['item_code']
            xero_line_items.append(line)
        
        data = {
            'Invoices': [{
                'Type': 'ACCPAY',  # Accounts Payable (Bill)
                'Contact': {'ContactID': supplier_contact_id},
                'InvoiceNumber': invoice_number,
                'Date': invoice_date,
                'DueDate': due_date,
                'LineItems': xero_line_items,
                'Status': 'DRAFT'
            }]
        }
        
        if reference:
            data['Invoices'][0]['Reference'] = reference
        
        result = self._make_request('POST', '/Invoices', connection, data)
        if result and 'Invoices' in result:
            logger.info(f"Created Xero bill: {invoice_number}")
            return result['Invoices'][0] if result['Invoices'] else None
        return None
    
    # ==================== Invoices (Customer Invoices) ====================
    
    def create_invoice(self, connection, customer_contact_id: str,
                       line_items: List[Dict], reference: str = None,
                       invoice_date: str = None, due_date: str = None) -> Optional[Dict]:
        """Create a sales invoice"""
        
        if not invoice_date:
            invoice_date = datetime.utcnow().strftime('%Y-%m-%d')
        if not due_date:
            due_date = (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        # Resolve output-GST treatment; fail closed for a registered user with no rate.
        sales_tax_type, tax_status = self.resolve_output_tax(connection)
        if tax_status == 'unresolved':
            logger.error("Blocking Xero invoice creation: TAX_CODE_UNRESOLVED")
            return {'error': 'No valid GST tax type could be resolved — invoice not synced',
                    'code': 'TAX_CODE_UNRESOLVED'}

        # Format line items for Xero
        xero_line_items = []
        for item in line_items:
            line = {
                'Description': item.get('description', ''),
                'Quantity': item.get('quantity', 1),
                'UnitAmount': float(money(item.get('unit_price', 0))),
                'AccountCode': item.get('account_code'),
                'TaxType': sales_tax_type
            }
            if item.get('item_code'):
                line['ItemCode'] = item['item_code']
            xero_line_items.append(line)

        data = {
            'Invoices': [{
                'Type': 'ACCREC',  # Accounts Receivable (Invoice)
                'Contact': {'ContactID': customer_contact_id},
                'Date': invoice_date,
                'DueDate': due_date,
                'LineItems': xero_line_items,
                'Status': 'DRAFT'
            }]
        }
        
        if reference:
            data['Invoices'][0]['Reference'] = reference
        
        result = self._make_request('POST', '/Invoices', connection, data)
        if result and 'Invoices' in result:
            logger.info(f"Created Xero invoice")
            return result['Invoices'][0] if result['Invoices'] else None
        return None
    
    def get_draft_invoices(self, connection, customer_contact_id: str = None) -> List[Dict]:
        """
        Get draft invoices that haven't been sent/approved yet.
        Optionally filter by customer.
        
        In Xero, DRAFT status means not yet approved/sent.
        """
        try:
            # Build query - get DRAFT invoices (ACCREC = customer invoices)
            # Xero API format: /Invoices?Statuses=DRAFT
            endpoint = '/Invoices?Statuses=DRAFT'
            
            result = self._make_request('GET', endpoint, connection)
            
            logger.info(f"Xero draft invoices response: {result.get('Invoices', []) if result else 'None'}")
            
            if not result or 'Invoices' not in result:
                return []
            
            invoices = result['Invoices']
            
            # Filter to only ACCREC (sales invoices, not bills)
            invoices = [inv for inv in invoices if inv.get('Type') == 'ACCREC']
            
            # Filter by customer if specified
            if customer_contact_id:
                invoices = [
                    inv for inv in invoices 
                    if inv.get('Contact', {}).get('ContactID') == customer_contact_id
                ]
            
            logger.info(f"Found {len(invoices)} draft invoices" + 
                       (f" for customer {customer_contact_id}" if customer_contact_id else ""))
            
            return invoices
            
        except Exception as e:
            logger.error(f"Error getting draft invoices: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def add_items_to_invoice(self, connection, invoice_id: str, line_items: List[Dict]) -> Optional[Dict]:
        """
        Add line items to an existing invoice, merging duplicates.
        
        If an item with the same ItemCode already exists:
        - Add to the quantity (accumulate)
        - Update the price to the latest price
        
        This keeps invoices compact and ensures prices are always current.
        """
        try:
            # Get existing invoice
            result = self._make_request('GET', f'/Invoices/{invoice_id}', connection)
            
            if not result or 'Invoices' not in result or not result['Invoices']:
                return {'error': 'Invoice not found'}
            
            invoice = result['Invoices'][0]
            existing_lines = invoice.get('LineItems', [])

            # Resolve output-GST treatment; fail closed for a registered user with no rate.
            sales_tax_type, tax_status = self.resolve_output_tax(connection)
            if tax_status == 'unresolved':
                logger.error("Blocking Xero invoice update: TAX_CODE_UNRESOLVED")
                return {'error': 'No valid GST tax type could be resolved — invoice not updated',
                        'code': 'TAX_CODE_UNRESOLVED'}

            # Build a map of existing items by ItemCode
            # Structure: {item_code: {'line_index': idx, 'quantity': qty, 'line': line_obj}}
            existing_items_map = {}
            for idx, line in enumerate(existing_lines):
                item_code = line.get('ItemCode')
                if item_code:
                    existing_items_map[item_code] = {
                        'line_index': idx,
                        'quantity': float(line.get('Quantity', 0)),
                        'line': line
                    }
            
            # Process each new item
            items_merged = 0
            items_added = 0
            
            for item in line_items:
                item_code = item.get('item_code')
                new_qty = float(item.get('quantity', 1))
                new_price = float(money(item.get('unit_price', 0)))
                description = item.get('description', '')
                account_code = item.get('account_code')
                
                if item_code and item_code in existing_items_map:
                    # Item already exists - merge quantities and update price
                    existing_info = existing_items_map[item_code]
                    line_index = existing_info['line_index']
                    old_qty = existing_info['quantity']
                    combined_qty = old_qty + new_qty
                    
                    # Update the existing line
                    existing_lines[line_index]['Quantity'] = combined_qty
                    existing_lines[line_index]['UnitAmount'] = new_price
                    
                    # CRITICAL: Remove LineAmount so Xero recalculates it
                    # Or set it correctly: LineAmount = Quantity × UnitAmount
                    if 'LineAmount' in existing_lines[line_index]:
                        del existing_lines[line_index]['LineAmount']
                    
                    # Also remove TaxAmount so Xero recalculates
                    if 'TaxAmount' in existing_lines[line_index]:
                        del existing_lines[line_index]['TaxAmount']
                    
                    # Update description if provided
                    if description:
                        existing_lines[line_index]['Description'] = description[:4000]
                    
                    # Update tax type
                    if sales_tax_type:
                        existing_lines[line_index]['TaxType'] = sales_tax_type
                    
                    logger.info(
                        f"Merged item {item_code}: {old_qty} + {new_qty} = {combined_qty} @ £{new_price}"
                    )
                    items_merged += 1
                    
                    # Update the map in case same item appears twice in new items
                    existing_items_map[item_code]['quantity'] = combined_qty
                    
                else:
                    # New item - add as new line
                    new_line = {
                        'Description': description[:4000] if description else '',
                        'Quantity': new_qty,
                        'UnitAmount': new_price,
                        'AccountCode': account_code,
                        'TaxType': sales_tax_type
                    }
                    
                    if item_code:
                        new_line['ItemCode'] = item_code
                    
                    existing_lines.append(new_line)
                    items_added += 1
                    
                    # Add to map
                    if item_code:
                        existing_items_map[item_code] = {
                            'line_index': len(existing_lines) - 1,
                            'quantity': new_qty,
                            'line': new_line
                        }
                    
                    logger.info(f"Added new item: {item_code or description[:30]} - Qty: {new_qty} @ £{new_price}")
            
            # Update the invoice
            update_data = {
                'Invoices': [{
                    'InvoiceID': invoice_id,
                    'LineItems': existing_lines
                }]
            }
            
            result = self._make_request('POST', '/Invoices', connection, update_data)
            
            if result and 'Invoices' in result:
                logger.info(f"Updated invoice {invoice_id}: {items_merged} merged, {items_added} added")
                return {
                    'Invoice': result['Invoices'][0],
                    'items_merged': items_merged,
                    'items_added': items_added
                }
            else:
                return {'error': 'Failed to update invoice'}
                
        except Exception as e:
            logger.error(f"Error adding items to invoice: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {'error': str(e)}
    
    # ==================== Quotes (Estimates) ====================
    
    def create_quote(self, connection, customer_contact_id: str,
                     line_items: List[Dict], reference: str = None,
                     quote_date: str = None, expiry_date: str = None) -> Optional[Dict]:
        """Create a quote"""
        
        if not quote_date:
            quote_date = datetime.utcnow().strftime('%Y-%m-%d')
        if not expiry_date:
            expiry_date = (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        # Resolve output-GST treatment; fail closed for a registered user with no rate.
        sales_tax_type, tax_status = self.resolve_output_tax(connection)
        if tax_status == 'unresolved':
            logger.error("Blocking Xero quote creation: TAX_CODE_UNRESOLVED")
            return {'error': 'No valid GST tax type could be resolved — quote not synced',
                    'code': 'TAX_CODE_UNRESOLVED'}

        # Format line items for Xero
        xero_line_items = []
        for item in line_items:
            line = {
                'Description': item.get('description', ''),
                'Quantity': item.get('quantity', 1),
                'UnitAmount': float(money(item.get('unit_price', 0))),
                'AccountCode': item.get('account_code'),
                'TaxType': sales_tax_type
            }
            if item.get('item_code'):
                line['ItemCode'] = item['item_code']
            xero_line_items.append(line)

        data = {
            'Quotes': [{
                'Contact': {'ContactID': customer_contact_id},
                'Date': quote_date,
                'ExpiryDate': expiry_date,
                'LineItems': xero_line_items,
                'Status': 'DRAFT'
            }]
        }
        
        if reference:
            data['Quotes'][0]['Reference'] = reference
        
        result = self._make_request('POST', '/Quotes', connection, data)
        if result and 'Quotes' in result:
            logger.info(f"Created Xero quote")
            return result['Quotes'][0] if result['Quotes'] else None
        return None
    
    # ==================== High-Level Sync Methods ====================
    
    def sync_invoice_to_bill(self, connection, invoice) -> Dict:
        """Sync a GoZappify invoice to Xero as a Bill"""
        from app.extensions import db
        
        errors = []
        
        try:
            # Find or create supplier
            supplier = self.find_or_create_supplier(connection, invoice.supplier)
            if not supplier:
                return {'success': False, 'errors': ['Failed to find/create supplier in Xero']}
            
            # Get expense account
            if not connection.default_expense_account_code:
                return {'success': False, 'errors': ['Please set a default expense account in Xero settings']}
            
            # Prepare line items
            line_items = []
            for item in invoice.items:
                line_items.append({
                    'description': item.description or '',
                    'quantity': float(item.quantity or 1),
                    'unit_price': float(item.cost_per_item or 0),
                    'account_code': connection.default_expense_account_code
                })
            
            # Create bill
            invoice_date = invoice.invoice_date.strftime('%Y-%m-%d') if invoice.invoice_date else datetime.utcnow().strftime('%Y-%m-%d')
            due_date = (invoice.invoice_date + timedelta(days=30)).strftime('%Y-%m-%d') if invoice.invoice_date else (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%d')
            
            bill = self.create_bill(
                connection,
                supplier_contact_id=supplier['ContactID'],
                invoice_number=invoice.invoice_number or f"INV-{invoice.id}",
                invoice_date=invoice_date,
                due_date=due_date,
                line_items=line_items,
                reference=invoice.job_reference
            )
            
            if bill:
                # Update invoice record
                invoice.xero_bill_id = bill.get('InvoiceID')
                invoice.synced_to_xero = True
                invoice.xero_synced_at = datetime.utcnow()
                db.session.commit()
                
                return {
                    'success': True,
                    'bill_id': bill.get('InvoiceID'),
                    'bill_number': bill.get('InvoiceNumber')
                }
            else:
                return {'success': False, 'errors': ['Failed to create bill in Xero']}
                
        except Exception as e:
            logger.error(f"Error syncing invoice to Xero: {str(e)}")
            return {'success': False, 'errors': [str(e)]}
    
    def sync_products_to_items(self, connection, invoice) -> Dict:
        """Sync invoice line items as Xero Items"""
        results = {'synced': 0, 'failed': 0, 'errors': []}
        
        if not connection.default_expense_account_code or not connection.default_sales_account_code:
            return {'synced': 0, 'failed': 0, 'errors': ['Please configure expense and sales accounts in Xero settings']}
        
        for item in invoice.items:
            try:
                sku = (item.part_number or '')[:30]
                if not sku:
                    sku = f"ITEM-{invoice.id}-{results['synced'] + results['failed'] + 1}"
                
                description = item.description or ''
                purchase_price = float(item.cost_per_item or 0)
                sale_price = float(item.selling_price or purchase_price)
                
                result = self.find_or_create_item(
                    connection,
                    code=sku,
                    name=description[:50] if description else sku,
                    description=description,
                    purchase_price=purchase_price,
                    sale_price=sale_price,
                    purchase_account_code=connection.default_expense_account_code,
                    sales_account_code=connection.default_sales_account_code
                )
                
                if result:
                    results['synced'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append(f"Failed to sync: {description[:50]}")
                    
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(str(e))
        
        return results
    
    def sync_to_customer_invoice(self, connection, invoice, customer_contact_id: str, 
                                   use_existing_invoice: bool = True) -> Dict:
        """
        Sync products and create/update customer invoice in Xero
        
        If use_existing_invoice is True:
        - Looks for an existing DRAFT invoice for this customer
        - If found, adds items to it (merging duplicates)
        - If not found, creates a new invoice
        
        This keeps all items for a customer in one invoice until it's sent.
        """
        errors = []
        
        try:
            # First sync products (updates prices if item exists)
            product_results = self.sync_products_to_items(connection, invoice)
            
            # Prepare line items with markup prices
            line_items = []
            for item in invoice.items:
                sku = (item.part_number or '')[:30]
                if not sku:
                    sku = f"ITEM-{invoice.id}-{len(line_items) + 1}"
                
                line_items.append({
                    'description': item.description or '',
                    'quantity': float(item.quantity or 1),
                    'unit_price': float(item.selling_price or item.cost_per_item or 0),
                    'account_code': connection.default_sales_account_code,
                    'item_code': sku
                })
            
            # Check for existing draft invoice for this customer
            xero_invoice = None
            invoice_action = 'created_new'
            
            if use_existing_invoice:
                draft_invoices = self.get_draft_invoices(connection, customer_contact_id)
                if draft_invoices:
                    # Use the first (most recent) draft invoice
                    xero_invoice = draft_invoices[0]
                    invoice_action = 'added_to_existing'
                    logger.info(f"Found existing draft invoice: {xero_invoice.get('InvoiceID')}")
            
            if xero_invoice:
                # Add items to existing invoice (merges duplicates)
                result = self.add_items_to_invoice(
                    connection,
                    xero_invoice['InvoiceID'],
                    line_items
                )
                
                if result.get('Invoice'):
                    return {
                        'success': True,
                        'invoice_action': invoice_action,
                        'products_synced': product_results['synced'],
                        'products_failed': product_results['failed'],
                        'xero_invoice_id': result['Invoice'].get('InvoiceID'),
                        'xero_invoice_number': result['Invoice'].get('InvoiceNumber'),
                        'items_merged': result.get('items_merged', 0),
                        'items_added': result.get('items_added', 0)
                    }
                else:
                    errors.append(f"Failed to add items to invoice: {result.get('error', 'Unknown error')}")
                    return {
                        'success': False,
                        'code': result.get('code'),
                        'products_synced': product_results['synced'],
                        'products_failed': product_results['failed'],
                        'errors': errors
                    }
            else:
                # Create new invoice
                xero_invoice = self.create_invoice(
                    connection,
                    customer_contact_id=customer_contact_id,
                    line_items=line_items,
                    reference=invoice.job_reference
                )
                
                if xero_invoice and not xero_invoice.get('error'):
                    return {
                        'success': True,
                        'invoice_action': invoice_action,
                        'products_synced': product_results['synced'],
                        'products_failed': product_results['failed'],
                        'xero_invoice_id': xero_invoice.get('InvoiceID'),
                        'xero_invoice_number': xero_invoice.get('InvoiceNumber')
                    }
                else:
                    errors.append((xero_invoice or {}).get('error', 'Failed to create invoice in Xero'))
                    return {
                        'success': False,
                        'code': (xero_invoice or {}).get('code'),
                        'products_synced': product_results['synced'],
                        'products_failed': product_results['failed'],
                        'errors': errors
                    }
                
        except Exception as e:
            logger.error(f"Error syncing to customer invoice: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {'success': False, 'errors': [str(e)]}
    
    def sync_quote_to_xero(self, connection, quote, customer_contact_id: str) -> Dict:
        """Sync a GoZappify quote to Xero as a Quote"""
        errors = []
        
        try:
            # First sync products
            product_results = self.sync_products_to_items(connection, quote)
            
            # Prepare line items
            line_items = []
            for item in quote.items:
                sku = (item.part_number or '')[:30]
                if not sku:
                    sku = f"ITEM-{quote.id}-{len(line_items) + 1}"
                
                line_items.append({
                    'description': item.description or '',
                    'quantity': float(item.quantity or 1),
                    'unit_price': float(item.selling_price or item.cost_per_item or 0),
                    'account_code': connection.default_sales_account_code,
                    'item_code': sku
                })
            
            # Create quote
            xero_quote = self.create_quote(
                connection,
                customer_contact_id=customer_contact_id,
                line_items=line_items,
                reference=quote.job_reference
            )
            
            if xero_quote and not xero_quote.get('error'):
                return {
                    'success': True,
                    'products_synced': product_results['synced'],
                    'products_failed': product_results['failed'],
                    'xero_quote_id': xero_quote.get('QuoteID'),
                    'xero_quote_number': xero_quote.get('QuoteNumber')
                }
            else:
                return {
                    'success': False,
                    'code': (xero_quote or {}).get('code'),
                    'errors': [(xero_quote or {}).get('error', 'Failed to create quote in Xero')]
                }
                
        except Exception as e:
            logger.error(f"Error syncing quote to Xero: {str(e)}")
            return {'success': False, 'errors': [str(e)]}
    
    # ==================== Smart Customer Matching ====================
    
    def match_customer_to_job_reference(self, connection, job_reference: str) -> List[Dict]:
        """
        Use Claude to intelligently match a job reference to a Xero contact
        Returns list of potential matches with confidence scores
        """
        if not job_reference:
            return []
        
        # Get all customers/contacts
        customers = self.get_customers(connection)
        
        if not customers:
            return []
        
        # Build customer name list
        customer_names = [c.get('Name', '') for c in customers if c.get('Name')]
        
        if not customer_names:
            return []
        
        # Use Claude to find best matches
        try:
            import anthropic
            import json
            
            client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

            logger.info(f"Matching job reference: {job_reference} against {len(customer_names)} Xero contacts")
            
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": f"""Match this job reference to the most likely customer(s) from the list.

Job Reference: "{job_reference}"

Customer List:
{chr(10).join(f'- {name}' for name in customer_names)}

Return ONLY valid JSON, no markdown:
{{
    "matches": [
        {{"customer_name": "exact name from list", "confidence": 85, "reason": "brief explanation"}}
    ]
}}

Rules:
1. Match despite typos (e.g., "RIVERWOD" matches "Riverwood")
2. Match partial names (e.g., "JAMES R" could match "James Riverwood")
3. Confidence should be 0-100
4. Return up to 10 best matches
5. If no reasonable match, return empty matches array
6. Only return names that are EXACTLY in the customer list"""
                }]
            )
            
            response_text = message.content[0].text.strip()
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1])
            
            data = json.loads(response_text)
            matches = data.get('matches', [])
            
            # Add contact IDs to matches
            for match in matches:
                for customer in customers:
                    if customer.get('Name') == match.get('customer_name'):
                        match['customer_id'] = customer.get('ContactID')
                        break
            
            return matches[:10]
            
        except Exception as e:
            logger.error(f"Xero customer matching error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            # Fallback to simple search
            return self._simple_customer_match(customers, job_reference)
    
    def _simple_customer_match(self, customers: List[Dict], job_reference: str) -> List[Dict]:
        """Simple fallback matching without AI"""
        matches = []
        job_ref_lower = job_reference.lower()
        
        for customer in customers:
            name = customer.get('Name', '')
            if not name:
                continue
            
            name_lower = name.lower()
            
            # Check for partial match
            if job_ref_lower in name_lower or name_lower in job_ref_lower:
                confidence = 70 if job_ref_lower in name_lower else 50
                matches.append({
                    'customer_name': name,
                    'customer_id': customer.get('ContactID'),
                    'confidence': confidence,
                    'reason': 'Partial name match'
                })
            # Check for word overlap
            else:
                job_words = set(job_ref_lower.split())
                name_words = set(name_lower.split())
                overlap = job_words & name_words
                if overlap:
                    confidence = min(60, len(overlap) * 20)
                    matches.append({
                        'customer_name': name,
                        'customer_id': customer.get('ContactID'),
                        'confidence': confidence,
                        'reason': f'Word match: {", ".join(overlap)}'
                    })
        
        # Sort by confidence
        matches.sort(key=lambda x: x.get('confidence', 0), reverse=True)
        return matches[:10]

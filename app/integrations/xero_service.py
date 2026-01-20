"""Xero Integration Service - OAuth and API calls"""
import os
import logging
import base64
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from flask import url_for

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
        """Get a valid access token, refreshing if necessary"""
        from app.extensions import db
        
        # Check if token is expired or about to expire (within 5 minutes)
        if connection.token_expires_at <= datetime.utcnow() + timedelta(minutes=5):
            logger.info("Xero token expired or expiring soon, refreshing...")
            
            tokens = self.refresh_access_token(connection.refresh_token)
            
            if tokens:
                connection.access_token = tokens['access_token']
                connection.refresh_token = tokens.get('refresh_token', connection.refresh_token)
                connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 1800))
                db.session.commit()
                return connection.access_token
            else:
                logger.error("Failed to refresh Xero token")
                connection.is_active = False
                db.session.commit()
                return None
        
        return connection.access_token
    
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
    
    def find_or_create_item(self, connection, code: str, name: str, description: str,
                           purchase_price: float, sale_price: float,
                           purchase_account_code: str, sales_account_code: str) -> Optional[Dict]:
        """Find existing item by code or create new one"""
        items = self.get_items(connection)
        
        for item in items:
            if item.get('Code', '').lower() == code.lower():
                return item
        
        return self.create_item(connection, code, name, description,
                               purchase_price, sale_price,
                               purchase_account_code, sales_account_code)
    
    # ==================== Bills (Supplier Invoices) ====================
    
    def create_bill(self, connection, supplier_contact_id: str, invoice_number: str,
                    invoice_date: str, due_date: str, line_items: List[Dict],
                    reference: str = None) -> Optional[Dict]:
        """Create a bill (accounts payable invoice)"""
        
        # Format line items for Xero
        xero_line_items = []
        for item in line_items:
            line = {
                'Description': item.get('description', ''),
                'Quantity': item.get('quantity', 1),
                'UnitAmount': item.get('unit_price', 0),
                'AccountCode': item.get('account_code'),
                'TaxType': 'INPUT2'  # Standard UK VAT on purchases
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
        
        # Format line items for Xero
        xero_line_items = []
        for item in line_items:
            line = {
                'Description': item.get('description', ''),
                'Quantity': item.get('quantity', 1),
                'UnitAmount': item.get('unit_price', 0),
                'AccountCode': item.get('account_code'),
                'TaxType': 'OUTPUT2'  # Standard UK VAT on sales
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
    
    # ==================== Quotes (Estimates) ====================
    
    def create_quote(self, connection, customer_contact_id: str,
                     line_items: List[Dict], reference: str = None,
                     quote_date: str = None, expiry_date: str = None) -> Optional[Dict]:
        """Create a quote"""
        
        if not quote_date:
            quote_date = datetime.utcnow().strftime('%Y-%m-%d')
        if not expiry_date:
            expiry_date = (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        # Format line items for Xero
        xero_line_items = []
        for item in line_items:
            line = {
                'Description': item.get('description', ''),
                'Quantity': item.get('quantity', 1),
                'UnitAmount': item.get('unit_price', 0),
                'AccountCode': item.get('account_code'),
                'TaxType': 'OUTPUT2'
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
            for item in invoice.line_items:
                line_items.append({
                    'description': item.get('description', ''),
                    'quantity': item.get('quantity', 1),
                    'unit_price': item.get('unit_price', 0),
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
        
        for item in invoice.line_items:
            try:
                sku = item.get('sku', '')[:30]
                if not sku:
                    sku = f"ITEM-{invoice.id}-{results['synced'] + results['failed'] + 1}"
                
                description = item.get('description', '')
                purchase_price = item.get('unit_price', 0)
                sale_price = item.get('customer_price', purchase_price)
                
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
    
    def sync_to_customer_invoice(self, connection, invoice, customer_contact_id: str) -> Dict:
        """Sync products and create/update customer invoice in Xero"""
        errors = []
        
        try:
            # First sync products
            product_results = self.sync_products_to_items(connection, invoice)
            
            # Prepare line items with markup prices
            line_items = []
            for item in invoice.line_items:
                sku = item.get('sku', '')[:30]
                if not sku:
                    sku = f"ITEM-{invoice.id}-{len(line_items) + 1}"
                
                line_items.append({
                    'description': item.get('description', ''),
                    'quantity': item.get('quantity', 1),
                    'unit_price': item.get('customer_price', item.get('unit_price', 0)),
                    'account_code': connection.default_sales_account_code,
                    'item_code': sku
                })
            
            # Create invoice
            xero_invoice = self.create_invoice(
                connection,
                customer_contact_id=customer_contact_id,
                line_items=line_items,
                reference=invoice.job_reference
            )
            
            if xero_invoice:
                return {
                    'success': True,
                    'products_synced': product_results['synced'],
                    'products_failed': product_results['failed'],
                    'xero_invoice_id': xero_invoice.get('InvoiceID'),
                    'xero_invoice_number': xero_invoice.get('InvoiceNumber')
                }
            else:
                errors.append('Failed to create invoice in Xero')
                return {
                    'success': False,
                    'products_synced': product_results['synced'],
                    'products_failed': product_results['failed'],
                    'errors': errors
                }
                
        except Exception as e:
            logger.error(f"Error syncing to customer invoice: {str(e)}")
            return {'success': False, 'errors': [str(e)]}
    
    def sync_quote_to_xero(self, connection, quote, customer_contact_id: str) -> Dict:
        """Sync a GoZappify quote to Xero as a Quote"""
        errors = []
        
        try:
            # First sync products
            product_results = self.sync_products_to_items(connection, quote)
            
            # Prepare line items
            line_items = []
            for item in quote.line_items:
                sku = item.get('sku', '')[:30]
                if not sku:
                    sku = f"ITEM-{quote.id}-{len(line_items) + 1}"
                
                line_items.append({
                    'description': item.get('description', ''),
                    'quantity': item.get('quantity', 1),
                    'unit_price': item.get('customer_price', item.get('unit_price', 0)),
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
            
            if xero_quote:
                return {
                    'success': True,
                    'products_synced': product_results['synced'],
                    'products_failed': product_results['failed'],
                    'xero_quote_id': xero_quote.get('QuoteID'),
                    'xero_quote_number': xero_quote.get('QuoteNumber')
                }
            else:
                return {'success': False, 'errors': ['Failed to create quote in Xero']}
                
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

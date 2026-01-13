"""QuickBooks Online Integration Service"""
import requests
from flask import current_app, url_for
from datetime import datetime, timedelta
from urllib.parse import urlencode
import base64
import json


class QuickBooksService:
    """Handle QuickBooks OAuth and API interactions"""
    
    AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
    TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    API_BASE_URL = "https://quickbooks.api.intuit.com"
    SANDBOX_API_BASE_URL = "https://sandbox-quickbooks.api.intuit.com"
    
    def __init__(self, user=None):
        self.user = user
        self.client_id = current_app.config.get('QUICKBOOKS_CLIENT_ID')
        self.client_secret = current_app.config.get('QUICKBOOKS_CLIENT_SECRET')
        self.redirect_uri = current_app.config.get('QUICKBOOKS_REDIRECT_URI')
        self.environment = current_app.config.get('QUICKBOOKS_ENVIRONMENT', 'production')
    
    @property
    def api_base_url(self):
        """Get API base URL based on environment"""
        if self.environment == 'sandbox':
            return self.SANDBOX_API_BASE_URL
        return self.API_BASE_URL
    
    def get_auth_url(self, state=None):
        """Generate QuickBooks OAuth authorization URL"""
        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'scope': 'com.intuit.quickbooks.accounting',
            'redirect_uri': self.redirect_uri,
            'state': state or 'random_state'
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"
    
    def exchange_code_for_tokens(self, auth_code):
        """Exchange authorization code for access and refresh tokens"""
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }
        
        data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'redirect_uri': self.redirect_uri
        }
        
        response = requests.post(self.TOKEN_URL, headers=headers, data=data)
        
        if response.status_code == 200:
            return response.json()
        else:
            current_app.logger.error(f"Token exchange failed: {response.text}")
            return None
    
    def refresh_access_token(self, refresh_token):
        """Refresh the access token using refresh token"""
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }
        
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }
        
        response = requests.post(self.TOKEN_URL, headers=headers, data=data)
        
        if response.status_code == 200:
            return response.json()
        else:
            current_app.logger.error(f"Token refresh failed: {response.text}")
            return None
    
    def get_valid_access_token(self, qb_connection):
        """Get a valid access token, refreshing if necessary"""
        from app.extensions import db
        
        # Check if token is expired (with 5 min buffer)
        if qb_connection.token_expires_at and qb_connection.token_expires_at < datetime.utcnow() + timedelta(minutes=5):
            # Token expired or expiring soon, refresh it
            tokens = self.refresh_access_token(qb_connection.refresh_token)
            if tokens:
                qb_connection.access_token = tokens['access_token']
                qb_connection.refresh_token = tokens.get('refresh_token', qb_connection.refresh_token)
                qb_connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 3600))
                db.session.commit()
                return qb_connection.access_token
            else:
                return None
        
        return qb_connection.access_token
    
    def make_api_request(self, qb_connection, endpoint, method='GET', data=None):
        """Make an authenticated API request to QuickBooks"""
        access_token = self.get_valid_access_token(qb_connection)
        
        if not access_token:
            return {'error': 'Unable to get valid access token'}
        
        url = f"{self.api_base_url}/v3/company/{qb_connection.realm_id}/{endpoint}"
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            elif method == 'POST':
                response = requests.post(url, headers=headers, json=data)
            elif method == 'PUT':
                response = requests.put(url, headers=headers, json=data)
            else:
                return {'error': f'Unsupported method: {method}'}
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                # Token might be invalid, try refreshing
                tokens = self.refresh_access_token(qb_connection.refresh_token)
                if tokens:
                    from app.extensions import db
                    qb_connection.access_token = tokens['access_token']
                    qb_connection.refresh_token = tokens.get('refresh_token', qb_connection.refresh_token)
                    qb_connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 3600))
                    db.session.commit()
                    # Retry request
                    headers['Authorization'] = f'Bearer {tokens["access_token"]}'
                    if method == 'GET':
                        response = requests.get(url, headers=headers)
                    elif method == 'POST':
                        response = requests.post(url, headers=headers, json=data)
                    return response.json() if response.status_code == 200 else {'error': response.text}
                return {'error': 'Authentication failed'}
            else:
                current_app.logger.error(f"QBO API error: {response.status_code} - {response.text}")
                return {'error': response.text}
                
        except Exception as e:
            current_app.logger.error(f"QBO API exception: {str(e)}")
            return {'error': str(e)}
    
    def get_company_info(self, qb_connection):
        """Get company information"""
        return self.make_api_request(qb_connection, f"companyinfo/{qb_connection.realm_id}")
    
    def get_vendors(self, qb_connection):
        """Get all vendors"""
        return self.make_api_request(qb_connection, "query?query=SELECT * FROM Vendor MAXRESULTS 1000")
    
    def get_accounts(self, qb_connection):
        """Get chart of accounts"""
        return self.make_api_request(qb_connection, "query?query=SELECT * FROM Account WHERE AccountType = 'Expense' MAXRESULTS 1000")
    
    def get_items(self, qb_connection):
        """Get all items/products"""
        return self.make_api_request(qb_connection, "query?query=SELECT * FROM Item MAXRESULTS 1000")
    
    def create_vendor(self, qb_connection, vendor_name):
        """Create a new vendor"""
        data = {
            "DisplayName": vendor_name
        }
        return self.make_api_request(qb_connection, "vendor", method='POST', data=data)
    
    def find_or_create_vendor(self, qb_connection, vendor_name):
        """Find existing vendor or create new one"""
        # Search for vendor
        query = f"query?query=SELECT * FROM Vendor WHERE DisplayName = '{vendor_name}'"
        result = self.make_api_request(qb_connection, query)
        
        if result.get('QueryResponse', {}).get('Vendor'):
            return result['QueryResponse']['Vendor'][0]
        
        # Create new vendor
        new_vendor = self.create_vendor(qb_connection, vendor_name)
        return new_vendor.get('Vendor')
    
    def create_bill(self, qb_connection, invoice_data):
        """
        Create a bill (supplier invoice) in QuickBooks
        
        invoice_data should contain:
        - supplier_name: str
        - invoice_number: str (optional)
        - invoice_date: date (optional)
        - items: list of {description, amount, quantity, account_id}
        """
        # Find or create vendor
        vendor = self.find_or_create_vendor(qb_connection, invoice_data['supplier_name'])
        if not vendor:
            return {'error': f"Could not find or create vendor: {invoice_data['supplier_name']}"}
        
        # Build line items
        lines = []
        for idx, item in enumerate(invoice_data.get('items', [])):
            line = {
                "Id": str(idx + 1),
                "Amount": float(item.get('amount', 0)),
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {
                        "value": item.get('account_id', invoice_data.get('default_expense_account_id'))
                    }
                },
                "Description": item.get('description', '')[:4000]  # QB limit
            }
            lines.append(line)
        
        # If no line items but we have a total, create single line
        if not lines and invoice_data.get('total'):
            lines.append({
                "Id": "1",
                "Amount": float(invoice_data['total']),
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {
                        "value": invoice_data.get('default_expense_account_id')
                    }
                },
                "Description": f"Invoice from {invoice_data['supplier_name']}"
            })
        
        bill_data = {
            "VendorRef": {
                "value": vendor['Id']
            },
            "Line": lines
        }
        
        # Add optional fields
        if invoice_data.get('invoice_number'):
            bill_data['DocNumber'] = invoice_data['invoice_number'][:21]  # QB limit
        
        if invoice_data.get('invoice_date'):
            bill_data['TxnDate'] = invoice_data['invoice_date'].strftime('%Y-%m-%d')
        
        if invoice_data.get('job_reference'):
            bill_data['PrivateNote'] = f"Job Reference: {invoice_data['job_reference']}"[:4000]
        
        return self.make_api_request(qb_connection, "bill", method='POST', data=bill_data)
    
    def sync_invoice_to_quickbooks(self, qb_connection, invoice):
        """Sync a FluxOps invoice to QuickBooks as a bill"""
        from app.models.invoice import InvoiceItem
        
        items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
        
        invoice_data = {
            'supplier_name': invoice.supplier_name,
            'invoice_number': invoice.invoice_number,
            'invoice_date': invoice.created_at,
            'job_reference': invoice.job_reference,
            'total': float(invoice.total_cost) if invoice.total_cost else 0,
            'default_expense_account_id': qb_connection.default_expense_account_id,
            'items': [
                {
                    'description': f"{item.part_number or ''} - {item.description or ''}".strip(' -'),
                    'amount': float(item.total_amount) if item.total_amount else 0,
                    'quantity': float(item.quantity) if item.quantity else 1,
                    'account_id': qb_connection.default_expense_account_id
                }
                for item in items
            ]
        }
        
        result = self.create_bill(qb_connection, invoice_data)
        
        if result.get('Bill'):
            # Update invoice with QB reference
            from app.extensions import db
            invoice.qb_bill_id = result['Bill']['Id']
            invoice.qb_synced_at = datetime.utcnow()
            db.session.commit()
            return {'success': True, 'bill_id': result['Bill']['Id']}
        else:
            return {'success': False, 'error': result.get('error', 'Unknown error')}
    
    # =========================================================================
    # PRODUCT/ITEM SYNC METHODS
    # =========================================================================
    
    def get_income_accounts(self, qb_connection):
        """Get income accounts for product sales"""
        return self.make_api_request(qb_connection, "query?query=SELECT * FROM Account WHERE AccountType = 'Income' MAXRESULTS 1000")
    
    def find_item_by_name(self, qb_connection, name):
        """Find an existing item by name"""
        # Clean the name for query (escape single quotes)
        clean_name = name.replace("'", "\\'")[:100]
        query = f"query?query=SELECT * FROM Item WHERE Name = '{clean_name}'"
        result = self.make_api_request(qb_connection, query)
        
        if result.get('QueryResponse', {}).get('Item'):
            return result['QueryResponse']['Item'][0]
        return None
    
    def create_or_update_item(self, qb_connection, item_data):
        """
        Create or update a product/service item in QuickBooks
        
        item_data should contain:
        - name: str (part number or product name)
        - description: str
        - cost: float (what you pay - GST exclusive)
        - selling_price: float (what you charge - GST exclusive)
        - income_account_id: str (for sales)
        - expense_account_id: str (for purchases)
        
        Note: Prices are GST EXCLUSIVE - QuickBooks will add 5% GST on top
        """
        # Check if item exists
        existing = self.find_item_by_name(qb_connection, item_data['name'])
        
        # Build item payload
        item_payload = {
            "Name": item_data['name'][:100],  # QB limit
            "Type": "NonInventory",  # Use NonInventory for services/materials
            "IncomeAccountRef": {
                "value": item_data.get('income_account_id')
            },
            "ExpenseAccountRef": {
                "value": item_data.get('expense_account_id')
            },
            # GST Settings - prices are EXCLUSIVE of tax
            "Taxable": True,  # Item is taxable
            "SalesTaxIncluded": False,  # Sales price does NOT include GST
            "PurchaseTaxIncluded": False  # Purchase cost does NOT include GST
        }
        
        # Add description if provided
        if item_data.get('description'):
            item_payload["Description"] = item_data['description'][:4000]
            item_payload["PurchaseDesc"] = item_data['description'][:4000]
        
        # Add cost (purchase cost - GST exclusive)
        if item_data.get('cost'):
            item_payload["PurchaseCost"] = round(float(item_data['cost']), 2)
        
        # Add selling price (unit price - GST exclusive)
        if item_data.get('selling_price'):
            item_payload["UnitPrice"] = round(float(item_data['selling_price']), 2)
        
        if existing:
            # Update existing item
            item_payload["Id"] = existing['Id']
            item_payload["SyncToken"] = existing['SyncToken']
            item_payload["sparse"] = True
            current_app.logger.info(f"Updating existing QB item: {item_data['name']} (ID: {existing['Id']})")
            return self.make_api_request(qb_connection, "item", method='POST', data=item_payload)
        else:
            # Create new item
            current_app.logger.info(f"Creating new QB item: {item_data['name']}")
            return self.make_api_request(qb_connection, "item", method='POST', data=item_payload)
    
    def sync_invoice_items_as_products(self, qb_connection, invoice):
        """
        Sync all line items from an invoice as Products/Services in QuickBooks
        
        Returns dict with success count, failed count, and details
        """
        from app.models.invoice import InvoiceItem
        from app.extensions import db
        
        items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
        
        results = {
            'success': True,
            'synced': 0,
            'skipped': 0,
            'failed': 0,
            'errors': [],
            'products': []
        }
        
        for item in items:
            # Skip items without part numbers
            if not item.part_number:
                results['skipped'] += 1
                continue
            
            item_data = {
                'name': item.part_number,
                'description': item.description or '',
                'cost': float(item.cost_per_item) if item.cost_per_item else 0,
                'selling_price': float(item.selling_price) if item.selling_price else 0,
                'income_account_id': qb_connection.default_income_account_id,
                'expense_account_id': qb_connection.default_expense_account_id
            }
            
            result = self.create_or_update_item(qb_connection, item_data)
            
            if result.get('Item'):
                results['synced'] += 1
                results['products'].append({
                    'part_number': item.part_number,
                    'qb_id': result['Item']['Id'],
                    'name': result['Item']['Name']
                })
            elif result.get('error'):
                results['failed'] += 1
                results['errors'].append(f"{item.part_number}: {result['error']}")
            else:
                results['failed'] += 1
                results['errors'].append(f"{item.part_number}: Unknown error")
        
        # Update invoice sync status
        if results['synced'] > 0:
            invoice.qb_synced_at = datetime.utcnow()
            qb_connection.last_sync_at = datetime.utcnow()
            db.session.commit()
        
        if results['failed'] > 0:
            results['success'] = False
        
        return results
    
    # =========================================================================
    # CUSTOMER MANAGEMENT
    # =========================================================================
    
    def get_customers(self, qb_connection, active_only: bool = True):
        """Get all customers from QuickBooks"""
        query = "query?query=SELECT * FROM Customer"
        if active_only:
            query += " WHERE Active = true"
        query += " MAXRESULTS 1000"
        return self.make_api_request(qb_connection, query)
    
    def find_customer_by_name(self, qb_connection, name: str):
        """Find a customer by display name"""
        clean_name = name.replace("'", "\\'")[:100]
        query = f"query?query=SELECT * FROM Customer WHERE DisplayName = '{clean_name}'"
        result = self.make_api_request(qb_connection, query)
        
        if result.get('QueryResponse', {}).get('Customer'):
            return result['QueryResponse']['Customer'][0]
        return None
    
    def search_customers(self, qb_connection, search_term: str):
        """Search customers by partial name match"""
        clean_term = search_term.replace("'", "\\'")[:100]
        query = f"query?query=SELECT * FROM Customer WHERE DisplayName LIKE '%{clean_term}%' MAXRESULTS 25"
        result = self.make_api_request(qb_connection, query)
        
        if result.get('QueryResponse', {}).get('Customer'):
            return result['QueryResponse']['Customer']
        return []
    
    def match_customer_to_job_reference(self, qb_connection, job_reference: str):
        """
        Use Claude to intelligently match a job reference to a QuickBooks customer
        Returns list of potential matches with confidence scores
        """
        if not job_reference:
            return []
        
        # Get all customers
        customers_result = self.get_customers(qb_connection)
        customers = customers_result.get('QueryResponse', {}).get('Customer', [])
        
        if not customers:
            return []
        
        # Build customer name list
        customer_names = [c.get('DisplayName', '') for c in customers]
        
        # Use Claude to find best matches
        try:
            import anthropic
            import os
            import json
            
            client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
            
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": f"""Match this job reference to the most likely customer(s) from the list.

Job Reference: "{job_reference}"

Customer List:
{chr(10).join(f'- {name}' for name in customer_names[:100])}

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
4. Return up to 3 best matches
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
            
            # Add customer IDs to matches
            for match in matches:
                for customer in customers:
                    if customer.get('DisplayName') == match.get('customer_name'):
                        match['customer_id'] = customer.get('Id')
                        break
            
            return matches
            
        except Exception as e:
            current_app.logger.error(f"Customer matching error: {str(e)}")
            # Fallback to simple search
            return self._simple_customer_match(customers, job_reference)
    
    def _simple_customer_match(self, customers, job_reference: str):
        """Simple fallback customer matching without Claude"""
        matches = []
        job_ref_lower = job_reference.lower()
        
        # Extract words from job reference
        words = [w for w in job_ref_lower.replace('/', ' ').split() if len(w) > 2]
        
        for customer in customers:
            name = customer.get('DisplayName', '')
            name_lower = name.lower()
            
            # Check for word matches
            matching_words = sum(1 for word in words if word in name_lower)
            
            if matching_words > 0:
                confidence = min(95, matching_words * 35)
                matches.append({
                    'customer_name': name,
                    'customer_id': customer.get('Id'),
                    'confidence': confidence,
                    'reason': f'Matched {matching_words} word(s)'
                })
        
        # Sort by confidence
        matches.sort(key=lambda x: x['confidence'], reverse=True)
        return matches[:3]
    
    # =========================================================================
    # INVOICE MANAGEMENT
    # =========================================================================
    
    def get_draft_invoices(self, qb_connection, customer_id: str = None):
        """Get unsent/draft invoices, optionally filtered by customer"""
        # Draft invoices have EmailStatus != 'EmailSent' and Balance > 0
        query = "query?query=SELECT * FROM Invoice WHERE EmailStatus != 'EmailSent'"
        if customer_id:
            query = f"query?query=SELECT * FROM Invoice WHERE CustomerRef = '{customer_id}' AND EmailStatus != 'EmailSent'"
        query += " MAXRESULTS 100"
        
        result = self.make_api_request(qb_connection, query)
        
        invoices = result.get('QueryResponse', {}).get('Invoice', [])
        
        # Filter to only truly draft invoices (not yet sent)
        draft_invoices = []
        for inv in invoices:
            email_status = inv.get('EmailStatus', '')
            # Include if not sent
            if email_status != 'EmailSent':
                draft_invoices.append(inv)
        
        return draft_invoices
    
    def create_invoice(self, qb_connection, customer_id: str, line_items: list, memo: str = None):
        """
        Create a new invoice for a customer
        
        line_items should be list of:
        {
            'item_id': str (QuickBooks Item ID),
            'quantity': float,
            'unit_price': float (optional, uses item default if not provided),
            'description': str (optional)
        }
        """
        # Build line items with GST
        lines = []
        for idx, item in enumerate(line_items):
            line = {
                "Id": str(idx + 1),
                "DetailType": "SalesItemLineDetail",
                "Amount": round(float(item.get('quantity', 1)) * float(item.get('unit_price', 0)), 2),
                "SalesItemLineDetail": {
                    "ItemRef": {
                        "value": item['item_id']
                    },
                    "Qty": float(item.get('quantity', 1)),
                    "TaxCodeRef": {
                        "value": "5"  # Standard GST - you may need to adjust this
                    }
                }
            }
            
            if item.get('unit_price'):
                line["SalesItemLineDetail"]["UnitPrice"] = float(item['unit_price'])
            
            if item.get('description'):
                line["Description"] = item['description'][:4000]
            
            lines.append(line)
        
        invoice_data = {
            "CustomerRef": {
                "value": customer_id
            },
            "Line": lines,
            "GlobalTaxCalculation": "TaxExcluded"  # Prices are GST exclusive
        }
        
        if memo:
            invoice_data["PrivateNote"] = memo[:4000]
        
        return self.make_api_request(qb_connection, "invoice", method='POST', data=invoice_data)
    
    def add_items_to_invoice(self, qb_connection, invoice_id: str, line_items: list):
        """
        Add line items to an existing invoice
        
        Fetches existing invoice, adds new lines, and updates
        """
        # Get existing invoice
        existing = self.make_api_request(qb_connection, f"invoice/{invoice_id}")
        
        if not existing.get('Invoice'):
            return {'error': 'Invoice not found'}
        
        invoice = existing['Invoice']
        existing_lines = invoice.get('Line', [])
        
        # Find next line ID
        max_id = 0
        for line in existing_lines:
            try:
                line_id = int(line.get('Id', 0))
                if line_id > max_id:
                    max_id = line_id
            except:
                pass
        
        # Add new line items
        for item in line_items:
            max_id += 1
            new_line = {
                "Id": str(max_id),
                "DetailType": "SalesItemLineDetail",
                "Amount": round(float(item.get('quantity', 1)) * float(item.get('unit_price', 0)), 2),
                "SalesItemLineDetail": {
                    "ItemRef": {
                        "value": item['item_id']
                    },
                    "Qty": float(item.get('quantity', 1)),
                    "TaxCodeRef": {
                        "value": "5"  # Standard GST
                    }
                }
            }
            
            if item.get('unit_price'):
                new_line["SalesItemLineDetail"]["UnitPrice"] = float(item['unit_price'])
            
            if item.get('description'):
                new_line["Description"] = item['description'][:4000]
            
            existing_lines.append(new_line)
        
        # Update invoice
        update_data = {
            "Id": invoice['Id'],
            "SyncToken": invoice['SyncToken'],
            "sparse": True,
            "Line": existing_lines
        }
        
        return self.make_api_request(qb_connection, "invoice", method='POST', data=update_data)
    
    def sync_invoice_to_customer(self, qb_connection, fluxops_invoice, customer_id: str, 
                                  use_existing_invoice: bool = True):
        """
        Full sync: Update products AND add to customer invoice
        
        1. Sync all products (update prices)
        2. Find or create customer invoice
        3. Add line items with GST
        
        Returns detailed result
        """
        from app.models.invoice import InvoiceItem
        
        results = {
            'success': True,
            'products_synced': 0,
            'products_failed': 0,
            'invoice_action': None,
            'qb_invoice_id': None,
            'errors': []
        }
        
        items = InvoiceItem.query.filter_by(invoice_id=fluxops_invoice.id).all()
        
        if not items:
            return {'success': False, 'error': 'No items to sync'}
        
        # Step 1: Sync all products
        product_results = self.sync_invoice_items_as_products(qb_connection, fluxops_invoice)
        results['products_synced'] = product_results.get('synced', 0)
        results['products_failed'] = product_results.get('failed', 0)
        results['errors'].extend(product_results.get('errors', []))
        
        # Build map of part numbers to QB item IDs
        product_map = {}
        for prod in product_results.get('products', []):
            product_map[prod['part_number']] = prod['qb_id']
        
        # Step 2: Check for existing draft invoice
        qb_invoice = None
        if use_existing_invoice:
            draft_invoices = self.get_draft_invoices(qb_connection, customer_id)
            if draft_invoices:
                qb_invoice = draft_invoices[0]  # Use first draft invoice
                results['invoice_action'] = 'added_to_existing'
                current_app.logger.info(f"Found existing draft invoice: {qb_invoice.get('Id')}")
        
        # Step 3: Build line items for QB invoice
        line_items = []
        for item in items:
            if item.part_number not in product_map:
                continue
            
            line_items.append({
                'item_id': product_map[item.part_number],
                'quantity': float(item.quantity) if item.quantity else 1,
                'unit_price': float(item.selling_price) if item.selling_price else 0,
                'description': item.description or ''
            })
        
        if not line_items:
            results['errors'].append('No products synced successfully - cannot create invoice')
            results['success'] = False
            return results
        
        # Step 4: Add to existing or create new invoice
        if qb_invoice:
            # Add to existing invoice
            invoice_result = self.add_items_to_invoice(
                qb_connection, 
                qb_invoice['Id'], 
                line_items
            )
        else:
            # Create new invoice
            results['invoice_action'] = 'created_new'
            invoice_result = self.create_invoice(
                qb_connection,
                customer_id,
                line_items,
                memo=f"Job: {fluxops_invoice.job_reference}" if fluxops_invoice.job_reference else None
            )
        
        if invoice_result.get('Invoice'):
            results['qb_invoice_id'] = invoice_result['Invoice']['Id']
            results['qb_invoice_number'] = invoice_result['Invoice'].get('DocNumber')
        else:
            results['errors'].append(f"Invoice error: {invoice_result.get('error', 'Unknown')}")
            results['success'] = False
        
        return results

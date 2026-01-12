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

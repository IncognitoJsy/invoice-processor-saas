"""QuickBooks Online Integration Service"""
import requests
from flask import current_app, url_for
from datetime import datetime, timedelta
from urllib.parse import urlencode
import base64
import json
import re
import time
from decimal import Decimal

from app.utils.money import money, to_decimal
from app.utils.tax import effective_output_rate


class QuickBooksService:
    """Handle QuickBooks OAuth and API interactions"""
    
    AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
    TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    API_BASE_URL = "https://quickbooks.api.intuit.com"
    SANDBOX_API_BASE_URL = "https://sandbox-quickbooks.api.intuit.com"
    
    # Rate limiting and retry configuration
    MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 1  # seconds - will be multiplied: 1s, 2s, 4s
    RATE_LIMIT_WAIT = 60  # seconds to wait on 429
    
    def __init__(self, user=None):
        self.user = user
        self.client_id = current_app.config.get('QUICKBOOKS_CLIENT_ID')
        self.client_secret = current_app.config.get('QUICKBOOKS_CLIENT_SECRET')
        self.redirect_uri = current_app.config.get('QUICKBOOKS_REDIRECT_URI')
        self.environment = current_app.config.get('QUICKBOOKS_ENVIRONMENT', 'production')
        self._output_tax_cache = None  # Cached (tax_code, status) tuple per request
    
    @property
    def api_base_url(self):
        """Get API base URL based on environment"""
        if self.environment == 'sandbox':
            return self.SANDBOX_API_BASE_URL
        return self.API_BASE_URL
    
    # =========================================================================
    # TOKEN ENCRYPTION HELPERS
    # =========================================================================
    
    # Token encryption uses the shared TOKEN_ENCRYPTION_KEY helper. The key is
    # validated at startup (AUDIT risk #3), so there is no silent plaintext
    # fallback on encrypt; decrypt still tolerates pre-encryption plaintext rows.
    @staticmethod
    def encrypt_token(plaintext_token):
        """Encrypt a token for secure storage"""
        from app.services.token_crypto import encrypt_token
        return encrypt_token(plaintext_token)

    @staticmethod
    def decrypt_token(encrypted_token):
        """Decrypt a stored token (plaintext rows returned as-is)"""
        from app.services.token_crypto import decrypt_token
        return decrypt_token(encrypted_token)

    # =========================================================================
    # OAUTH METHODS
    # =========================================================================
    
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
            current_app.logger.error(f"Token exchange failed: status={response.status_code}")
            return None
    
    def refresh_access_token(self, refresh_token):
        """Refresh the access token using refresh token"""
        # Decrypt the refresh token if it's encrypted
        decrypted_refresh = self.decrypt_token(refresh_token)
        
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
            'refresh_token': decrypted_refresh
        }
        
        response = requests.post(self.TOKEN_URL, headers=headers, data=data)
        
        if response.status_code == 200:
            return response.json()
        else:
            current_app.logger.error(f"Token refresh failed: status={response.status_code}")
            return None
    
    def revoke_token(self, refresh_token):
        """
        Revoke OAuth tokens when user disconnects.
        Required by Intuit for clean disconnect flow.
        """
        decrypted_refresh = self.decrypt_token(refresh_token)
        
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        data = {
            'token': decrypted_refresh
        }
        
        try:
            response = requests.post(
                'https://developer.api.intuit.com/v2/oauth2/tokens/revoke',
                headers=headers,
                json=data
            )
            if response.status_code in (200, 204):
                current_app.logger.info("Successfully revoked QuickBooks OAuth tokens")
                return True
            else:
                current_app.logger.warning(f"Token revocation returned status {response.status_code}")
                return False
        except Exception as e:
            current_app.logger.error(f"Token revocation failed: {type(e).__name__}")
            return False
    
    def get_valid_access_token(self, qb_connection):
        """Get a valid access token, refreshing if necessary"""
        from app.extensions import db
        
        # Decrypt the stored access token
        access_token = self.decrypt_token(qb_connection.access_token)
        
        # Check if token is expired (with 5 min buffer)
        if qb_connection.token_expires_at and qb_connection.token_expires_at < datetime.utcnow() + timedelta(minutes=5):
            # Token expired or expiring soon, refresh it
            tokens = self.refresh_access_token(qb_connection.refresh_token)
            if tokens:
                # Encrypt tokens before storing
                qb_connection.access_token = self.encrypt_token(tokens['access_token'])
                qb_connection.refresh_token = self.encrypt_token(
                    tokens.get('refresh_token', self.decrypt_token(qb_connection.refresh_token))
                )
                qb_connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 3600))
                db.session.commit()
                return tokens['access_token']  # Return plaintext for immediate use
            else:
                return None
        
        return access_token
    
    # =========================================================================
    # API REQUEST METHOD (with retry logic and rate limit handling)
    # =========================================================================
    
    def make_api_request(self, qb_connection, endpoint, method='GET', data=None):
        """
        Make an authenticated API request to QuickBooks with retry logic.
        
        Handles:
        - 401 Unauthorized: refresh token and retry once
        - 429 Rate Limited: wait and retry with exponential backoff
        - 503 Service Unavailable: retry with exponential backoff
        - 5xx Server Errors: retry with exponential backoff
        """
        access_token = self.get_valid_access_token(qb_connection)
        
        if not access_token:
            return {'error': 'Unable to get valid access token', 'error_code': 'auth_failed'}
        
        url = f"{self.api_base_url}/v3/company/{qb_connection.realm_id}/{endpoint}"
        
        # Add minorversion parameter for better API compatibility
        if '?' in url:
            url += '&minorversion=75'
        else:
            url += '?minorversion=75'
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        last_error = None
        
        for attempt in range(self.MAX_RETRIES):
            try:
                if method == 'GET':
                    response = requests.get(url, headers=headers, timeout=30)
                elif method == 'POST':
                    response = requests.post(url, headers=headers, json=data, timeout=30)
                elif method == 'PUT':
                    response = requests.put(url, headers=headers, json=data, timeout=30)
                else:
                    return {'error': f'Unsupported method: {method}', 'error_code': 'invalid_method'}
                
                # --- SUCCESS ---
                if response.status_code == 200:
                    return response.json()
                
                # --- 401 UNAUTHORIZED: Token expired, refresh and retry once ---
                if response.status_code == 401:
                    if attempt == 0:  # Only try refresh once
                        current_app.logger.info("QB API 401 - refreshing access token")
                        tokens = self.refresh_access_token(qb_connection.refresh_token)
                        if tokens:
                            from app.extensions import db
                            qb_connection.access_token = self.encrypt_token(tokens['access_token'])
                            qb_connection.refresh_token = self.encrypt_token(
                                tokens.get('refresh_token', self.decrypt_token(qb_connection.refresh_token))
                            )
                            qb_connection.token_expires_at = datetime.utcnow() + timedelta(
                                seconds=tokens.get('expires_in', 3600)
                            )
                            db.session.commit()
                            headers['Authorization'] = f'Bearer {tokens["access_token"]}'
                            continue  # Retry with new token
                        else:
                            return {
                                'error': 'QuickBooks authentication failed. Please reconnect your account.',
                                'error_code': 'auth_failed',
                                'reconnect_required': True
                            }
                    else:
                        return {
                            'error': 'QuickBooks authentication failed after token refresh.',
                            'error_code': 'auth_failed',
                            'reconnect_required': True
                        }
                
                # --- 429 RATE LIMITED: Wait and retry ---
                if response.status_code == 429:
                    # Use Retry-After header if provided, otherwise use default
                    retry_after = int(response.headers.get('Retry-After', self.RATE_LIMIT_WAIT))
                    wait_time = min(retry_after, 120)  # Cap at 2 minutes
                    
                    current_app.logger.warning(
                        f"QB API rate limited (429). Attempt {attempt + 1}/{self.MAX_RETRIES}. "
                        f"Waiting {wait_time}s before retry."
                    )
                    
                    if attempt < self.MAX_RETRIES - 1:
                        time.sleep(wait_time)
                        continue
                    else:
                        return {
                            'error': 'QuickBooks API rate limit exceeded. Please try again in a few minutes.',
                            'error_code': 'rate_limited'
                        }
                
                # --- 503 SERVICE UNAVAILABLE: Retry with backoff ---
                if response.status_code == 503:
                    wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)  # 1s, 2s, 4s
                    
                    current_app.logger.warning(
                        f"QB API unavailable (503). Attempt {attempt + 1}/{self.MAX_RETRIES}. "
                        f"Waiting {wait_time}s before retry."
                    )
                    
                    if attempt < self.MAX_RETRIES - 1:
                        time.sleep(wait_time)
                        continue
                    else:
                        return {
                            'error': 'QuickBooks service is temporarily unavailable. Please try again shortly.',
                            'error_code': 'service_unavailable'
                        }
                
                # --- OTHER 5xx SERVER ERRORS: Retry with backoff ---
                if 500 <= response.status_code < 600:
                    wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                    
                    current_app.logger.warning(
                        f"QB API server error ({response.status_code}). "
                        f"Attempt {attempt + 1}/{self.MAX_RETRIES}. Waiting {wait_time}s."
                    )
                    
                    if attempt < self.MAX_RETRIES - 1:
                        time.sleep(wait_time)
                        continue
                    else:
                        return {
                            'error': 'QuickBooks encountered a server error. Please try again later.',
                            'error_code': 'server_error'
                        }
                
                # --- 4xx CLIENT ERRORS (not 401/429): Don't retry ---
                if 400 <= response.status_code < 500:
                    # Parse error details safely without exposing raw response
                    error_detail = self._parse_qb_error(response)
                    current_app.logger.error(
                        f"QB API client error: {response.status_code} on {endpoint} — {error_detail}"
                    )
                    return {
                        'error': error_detail,
                        'error_code': 'client_error',
                        'status_code': response.status_code
                    }
                
                # --- UNEXPECTED STATUS ---
                current_app.logger.error(
                    f"QB API unexpected status: {response.status_code} on {endpoint}"
                )
                last_error = f"Unexpected response from QuickBooks (status {response.status_code})"
                
            except requests.exceptions.Timeout:
                wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                current_app.logger.warning(
                    f"QB API timeout on {endpoint}. Attempt {attempt + 1}/{self.MAX_RETRIES}. "
                    f"Waiting {wait_time}s."
                )
                last_error = 'QuickBooks request timed out. Please try again.'
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(wait_time)
                    continue
                    
            except requests.exceptions.ConnectionError:
                wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                current_app.logger.warning(
                    f"QB API connection error on {endpoint}. "
                    f"Attempt {attempt + 1}/{self.MAX_RETRIES}."
                )
                last_error = 'Could not connect to QuickBooks. Please check your internet connection.'
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(wait_time)
                    continue
                    
            except Exception as e:
                current_app.logger.error(
                    f"QB API unexpected error on {endpoint}: {type(e).__name__}"
                )
                return {
                    'error': 'An unexpected error occurred while communicating with QuickBooks.',
                    'error_code': 'unexpected_error'
                }
        
        # All retries exhausted
        return {'error': last_error or 'Request failed after multiple attempts', 'error_code': 'max_retries'}
    
    def _parse_qb_error(self, response):
        """
        Parse QuickBooks error response into a user-friendly message.
        Never expose raw API responses to the user.
        """
        try:
            error_data = response.json()
            fault = error_data.get('Fault', {})
            errors = fault.get('Error', [])
            
            if errors:
                # Get the first error message
                error = errors[0]
                message = error.get('Message', '')
                detail = error.get('Detail', '')
                
                # Map common errors to user-friendly messages
                if 'Duplicate' in message or 'Duplicate' in detail:
                    return 'A duplicate record was found in QuickBooks. Please check for existing entries.'
                elif 'Stale Object' in message:
                    return 'The record was modified by another process. Please refresh and try again.'
                elif 'Business Validation' in message:
                    # Provide actionable guidance for common validation issues
                    detail_lower = (detail or '').lower()
                    if any(x in detail_lower for x in ['tax', 'taxcode', 'tax code', 'vat', 'gst']):
                        return 'QuickBooks tax settings error. Please check your tax settings in QuickBooks are configured correctly for your region (VAT/GST).'
                    elif any(x in detail_lower for x in ['account', 'income', 'expense']):
                        return 'QuickBooks account mapping error. Please check your Income and Expense account settings in GoZappify under Settings > Integrations > Manage Settings.'
                    else:
                        friendly_detail = detail[:200] if detail else message[:200]
                        return f'QuickBooks validation error: {friendly_detail}. Please check your QuickBooks settings (tax codes, accounts) are configured correctly.'
                elif 'Required' in detail:
                    return f'Missing required field: {detail[:200]}'
                else:
                    # Return sanitised message (limit length, no raw data)
                    return f'QuickBooks error: {message[:200]}' if message else 'QuickBooks returned an error.'
            
            return 'QuickBooks returned an error. Please try again.'
            
        except (ValueError, KeyError):
            return 'QuickBooks returned an unexpected response.'
    
    # =========================================================================
    # COMPANY & DATA QUERIES
    # =========================================================================
    
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
        """Get all items/products with pagination to handle large catalogs"""
        all_items = []
        start_position = 1
        max_results = 1000
        
        while True:
            query = f"query?query=SELECT * FROM Item STARTPOSITION {start_position} MAXRESULTS {max_results}"
            response = self.make_api_request(qb_connection, query)
            
            if not response or 'error' in response:
                break
                
            items = response.get('QueryResponse', {}).get('Item', [])
            
            if not items:
                break
                
            all_items.extend(items)
            current_app.logger.info(f"Loaded {len(all_items)} products so far...")
            
            # If we got fewer than max_results, we've reached the end
            if len(items) < max_results:
                break
                
            start_position += max_results
        
        current_app.logger.info(f"Total products loaded: {len(all_items)}")
        
        # Return in same format as before for compatibility
        return {'QueryResponse': {'Item': all_items}}
    
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
        """Sync a GoZappify invoice to QuickBooks as a bill"""
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
    # TAX CODE MANAGEMENT
    # =========================================================================
    
    # Tax-code name keywords that mean "no output GST" (exempt / zero-rated).
    EXEMPT_KEYWORDS = ('exempt', 'no gst', 'no vat', 'no tax', 'zero',
                       'non-taxable', 'none', 'out of scope', 'ecg')

    def resolve_output_tax(self, qb_connection):
        """Resolve how THIS user's synced lines/items should be taxed.

        Returns an (tax_code, status) tuple, cached for the request:
          - (code, 'taxable')     registered user; attach `code` (carries output GST)
          - (code|None, 'exempt') unregistered user; push tax-exempt. `code` is an
                                  explicit exempt/zero code if the company file has
                                  one, else None (caller omits the ref + Taxable=False)
          - (None, 'unresolved')  registered user but no valid taxable code could be
                                  found — callers MUST block the sync (fail closed)

        Driven entirely by self.user.tax_registered so the sync can never disagree
        with the cost-base treatment in claude_parser._transform_items (which folds
        irrecoverable input GST into the markup base only for UNREGISTERED users) —
        making the "GST-in-base + output-GST-on-top" double charge impossible.
        """
        if self._output_tax_cache is not None:
            return self._output_tax_cache

        # No user context -> cannot reason about registration -> fail closed.
        if self.user is None:
            current_app.logger.error("resolve_output_tax: no user on service — blocking sync")
            self._output_tax_cache = (None, 'unresolved')
            return self._output_tax_cache

        tax_codes = self._fetch_active_tax_codes(qb_connection)

        # Unregistered: never charge output GST (their cost base already absorbs it).
        if not self.user.tax_registered:
            exempt = self._select_exempt_code(tax_codes)
            self._output_tax_cache = (exempt, 'exempt')
            current_app.logger.info(
                f"Output tax: user not GST/VAT-registered -> exempt "
                f"({exempt['name'] if exempt else 'no exempt code; will set Taxable=False'})"
            )
            return self._output_tax_cache

        # Registered: lines MUST carry output GST.
        if not tax_codes:
            current_app.logger.error(
                "Output tax: registered user but QB returned no active tax codes — blocking sync")
            self._output_tax_cache = (None, 'unresolved')
            return self._output_tax_cache

        code = self._select_taxable_code(qb_connection, tax_codes)
        if code:
            current_app.logger.info(
                f"Output tax: registered -> taxable code '{code['name']}' (id {code['value']})")
            self._output_tax_cache = (code, 'taxable')
        else:
            current_app.logger.error(
                "Output tax: registered user but no sales tax code could be resolved "
                f"(tax_rate={getattr(self.user, 'tax_rate', None)}, "
                f"tax_type={getattr(self.user, 'tax_type', None)}) — blocking sync")
            self._output_tax_cache = (None, 'unresolved')
        return self._output_tax_cache

    def _fetch_active_tax_codes(self, qb_connection):
        """Active QB TaxCodes (list); [] on any error."""
        try:
            result = self.make_api_request(
                qb_connection, "query?query=SELECT * FROM TaxCode WHERE Active = true")
            codes = result.get('QueryResponse', {}).get('TaxCode', []) if isinstance(result, dict) else []
            current_app.logger.info(
                f"Available tax codes: {[(tc.get('Name'), tc.get('Id')) for tc in codes]}")
            return codes
        except Exception as e:
            current_app.logger.error(f"Error fetching tax codes: {type(e).__name__}")
            return []

    def _fetch_active_tax_rates(self, qb_connection):
        """{TaxRate Id -> Decimal RateValue} ({} on error). Read-only. No
        `WHERE Active` filter — we only look rates up by the IDs codes reference, so
        over-fetching is harmless and avoids a 400 if Active isn't filterable here."""
        try:
            result = self.make_api_request(qb_connection, "query?query=SELECT * FROM TaxRate")
            rows = result.get('QueryResponse', {}).get('TaxRate', []) if isinstance(result, dict) else []
            out = {}
            for r in rows:
                rid, d = r.get('Id'), to_decimal(r.get('RateValue'))
                if rid is not None and d is not None:
                    out[str(rid)] = d
            return out
        except Exception as e:
            current_app.logger.error(f"Error fetching tax rates: {type(e).__name__}")
            return {}

    @classmethod
    def _is_exempt_code(cls, tax_code):
        name = (tax_code.get('Name') or '').lower()
        return any(k in name for k in cls.EXEMPT_KEYWORDS)

    @staticmethod
    def _tax_code_rate(tax_code):
        """Percentage parsed from a TaxCode's NAME, e.g. 'GST 5%' -> 5.0. None if the
        name has no percentage. Legacy fallback only — the real rate comes from the
        code's TaxRateRef detail (see _code_sales_rate). Also used by the diagnostic."""
        m = re.search(r'(\d+(?:\.\d+)?)\s*%', tax_code.get('Name') or '')
        return float(m.group(1)) if m else None

    @staticmethod
    def _is_sales_applicable(tax_code):
        """Usable on sales: exclude purchase-only codes. Codes with no rate-list info
        are treated as usable (matches prior behaviour)."""
        has_sales = bool((tax_code.get('SalesTaxRateList') or {}).get('TaxRateDetail'))
        has_purchase = bool((tax_code.get('PurchaseTaxRateList') or {}).get('TaxRateDetail'))
        return has_sales or not has_purchase

    def _code_sales_rate(self, tax_code, rate_map):
        """The code's ACTUAL sales rate (Decimal): sum of its SalesTaxRateList
        components resolved via rate_map (TaxRateRef -> TaxRate.RateValue). Falls back
        to a rate parsed from the name only if no detail is resolvable. None if unknown.
        Rates are percents (RateValue 5 == 5%), same unit as user.tax_rate."""
        total = None
        for d in (tax_code.get('SalesTaxRateList') or {}).get('TaxRateDetail') or []:
            rid = (d.get('TaxRateRef') or {}).get('value')
            if rid is not None and str(rid) in rate_map:
                total = (total or Decimal('0')) + rate_map[str(rid)]
        if total is not None:
            return total
        named = self._tax_code_rate(tax_code)
        return to_decimal(named) if named is not None else None

    def _select_exempt_code(self, tax_codes):
        for tc in tax_codes:
            if self._is_exempt_code(tc):
                return {'value': tc['Id'], 'name': tc.get('Name', '')}
        return None

    def _select_taxable_code(self, qb_connection, tax_codes):
        """Pick the sales TaxCode for a registered user — MATCH-OR-FAIL against the user's
        configured output rate (`effective_output_rate`). The chosen code's REAL rate (from
        its TaxRateRef detail) must equal the configured rate within tolerance, so the synced
        invoice can never carry a rate the user didn't configure / the document didn't show.
        Returns None (caller fails closed) when the rate is unconfigured or no code matches."""
        expected = effective_output_rate(self.user)   # registered path -> user.tax_rate
        if expected <= 0:
            # Registered but no output rate configured -> cannot reconcile -> fail closed.
            return None
        candidates = [tc for tc in tax_codes
                      if self._is_sales_applicable(tc) and not self._is_exempt_code(tc)]
        rate_map = self._fetch_active_tax_rates(qb_connection)
        for tc in candidates:
            r = self._code_sales_rate(tc, rate_map)
            if r is not None and abs(r - expected) < Decimal('0.01'):
                return {'value': tc['Id'], 'name': tc.get('Name', '')}
        return None
    
    # =========================================================================
    # PRODUCT/ITEM SYNC METHODS
    # =========================================================================
    
    def get_income_accounts(self, qb_connection):
        """Get income accounts for product sales"""
        return self.make_api_request(qb_connection, "query?query=SELECT * FROM Account WHERE AccountType = 'Income' MAXRESULTS 1000")
    
    def find_item_by_name(self, qb_connection, name):
        """Find an existing item by name"""
        # Clean the name for query (escape single quotes)
        clean_name = name.replace("'", "\\'").replace('"', '\\"')[:100]
        query = f"query?query=SELECT * FROM Item WHERE Name = '{clean_name}'"
        result = self.make_api_request(qb_connection, query)
        
        if result.get('QueryResponse', {}).get('Item'):
            return result['QueryResponse']['Item'][0]
        return None
    
    def find_item_by_sku(self, qb_connection, sku):
        """Find an existing item by SKU"""
        clean_sku = sku.replace("'", "\\'").replace('"', '\\"')[:100]
        query = f"query?query=SELECT * FROM Item WHERE Sku = '{clean_sku}'"
        result = self.make_api_request(qb_connection, query)
        
        if result.get('QueryResponse', {}).get('Item'):
            return result['QueryResponse']['Item'][0]
        return None
    
    def find_item_by_sku_or_name(self, qb_connection, sku, name):
        """
        Find an existing item by SKU first, then by name.
        This prevents duplicate products.
        """
        # Try SKU first (most reliable)
        if sku:
            item = self.find_item_by_sku(qb_connection, sku)
            if item:
                current_app.logger.info(f"Found item by SKU: {sku} -> {item.get('Name')}")
                return item, "sku"
        
        # Try name match
        if name:
            item = self.find_item_by_name(qb_connection, name)
            if item:
                current_app.logger.info(f"Found item by name: {name}")
                return item, "name"
        
        return None, None
    
    def create_or_update_item(self, qb_connection, item_data):
        """
        Create or update a product/service item in QuickBooks
        
        item_data should contain:
        - name: str (part number or product name)
        - sku: str (optional, defaults to name)
        - description: str
        - cost: float (what you pay - GST exclusive)
        - selling_price: float (what you charge - GST exclusive)
        - income_account_id: str (for sales)
        - expense_account_id: str (for purchases)
        
        Note: Prices are GST EXCLUSIVE - QuickBooks will add GST on top
        """
        name = item_data['name'][:100]
        sku = item_data.get('sku', name)[:100]
        
        # Check if item exists by SKU or name
        existing, match_type = self.find_item_by_sku_or_name(qb_connection, sku, name)

        # Resolve output-GST treatment for this user (registration + region aware)
        tax_code, tax_status = self.resolve_output_tax(qb_connection)
        if tax_status == 'unresolved':
            current_app.logger.error(
                f"Blocking QB item sync for '{name}': no valid output tax code for a tax-registered business")
            return {'error': 'Could not resolve a GST tax code for a tax-registered business — item not synced',
                    'code': 'TAX_CODE_UNRESOLVED'}

        # Build item payload. Taxable only when an output code applies (a taxable
        # code, or an explicit exempt/zero code for an unregistered user); when an
        # unregistered file has no exempt code, Taxable=False with no ref.
        item_payload = {
            "Name": name,
            "Sku": sku,
            "Type": "NonInventory",  # Use NonInventory for services/materials
            "Active": True,
            "IncomeAccountRef": {
                "value": item_data.get('income_account_id')
            },
            "ExpenseAccountRef": {
                "value": item_data.get('expense_account_id')
            },
            # Prices are EXCLUSIVE of tax
            "Taxable": bool(tax_code),
            "SalesTaxIncluded": False,
            "PurchaseTaxIncluded": False
        }

        # Add the resolved sales tax code (taxable code, or explicit exempt code)
        if tax_code:
            item_payload["SalesTaxCodeRef"] = {"value": tax_code['value']}
        
        # Add description if provided
        if item_data.get('description'):
            item_payload["Description"] = item_data['description'][:4000]
            item_payload["PurchaseDesc"] = item_data['description'][:4000]
        
        # Add cost (purchase cost - GST exclusive)
        if item_data.get('cost'):
            item_payload["PurchaseCost"] = float(money(item_data['cost']))

        # Add selling price (unit price - GST exclusive)
        if item_data.get('selling_price'):
            item_payload["UnitPrice"] = float(money(item_data['selling_price']))
        
        if existing:
            # Update existing item
            item_payload["Id"] = existing['Id']
            item_payload["SyncToken"] = existing['SyncToken']
            item_payload["sparse"] = True
            
            # If item was found by name but has no SKU, add the SKU
            if match_type == "name" and not existing.get('Sku'):
                current_app.logger.info(f"Adding SKU '{sku}' to existing item: {name}")
            
            current_app.logger.info(f"Updating existing QB item: {name} (ID: {existing['Id']}, matched by {match_type})")
            return self.make_api_request(qb_connection, "item", method='POST', data=item_payload)
        else:
            # Create new item
            current_app.logger.info(f"Creating new QB item: {name} (SKU: {sku})")
            return self.make_api_request(qb_connection, "item", method='POST', data=item_payload)
    
    def sync_invoice_items_as_products(self, qb_connection, invoice):
        """
        Sync all line items from an invoice as Products/Services in QuickBooks
        
        Returns dict with success count, failed count, and details
        """
        from app.models.invoice import InvoiceItem
        from app.extensions import db

        results = {
            'success': True,
            'synced': 0,
            'updated': 0,
            'created': 0,
            'skipped': 0,
            'failed': 0,
            'errors': [],
            'products': []
        }

        # Fail closed BEFORE any API write if a registered user has no tax code.
        _, tax_status = self.resolve_output_tax(qb_connection)
        if tax_status == 'unresolved':
            current_app.logger.error("Blocking QB product sync: TAX_CODE_UNRESOLVED")
            results['success'] = False
            results['code'] = 'TAX_CODE_UNRESOLVED'
            results['errors'].append('No valid GST tax code could be resolved — products not synced')
            return results

        items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()

        for item in items:
            # Skip items without part numbers
            if not item.part_number:
                results['skipped'] += 1
                continue
            
            item_data = {
                'name': item.part_number,
                'sku': item.part_number,  # Use part number as SKU
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
        """Get ALL customers from QuickBooks using pagination"""
        all_customers = []
        start_position = 1
        page_size = 1000
        
        while True:
            query = f"query?query=SELECT * FROM Customer"
            if active_only:
                query += " WHERE Active = true"
            query += f" STARTPOSITION {start_position} MAXRESULTS {page_size}"
            
            result = self.make_api_request(qb_connection, query)
            customers = result.get('QueryResponse', {}).get('Customer', [])
            
            if not customers:
                break
                
            all_customers.extend(customers)
            current_app.logger.info(f"Loaded {len(all_customers)} customers so far...")
            
            # If we got fewer than page_size, we've reached the end
            if len(customers) < page_size:
                break
                
            start_position += page_size
        
        current_app.logger.info(f"Total customers loaded: {len(all_customers)}")
        return {'QueryResponse': {'Customer': all_customers}}
    
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
        
        # Build customer name list (use FullyQualifiedName to include sub-customers like "TLC Home:Project 1")
        customer_names = [c.get('FullyQualifiedName', c.get('DisplayName', '')) for c in customers]
        
        # Use Claude to find best matches
        try:
            import anthropic
            import os
            import json
            
            client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

            current_app.logger.info(f"Matching job reference: {job_reference} against {len(customer_names)} customers")
            
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
3. For parent:child format (e.g., "TLC Home:Project"), if parent matches, include ALL sub-customers
4. Confidence should be 0-100
5. Return up to 10 best matches
6. If no reasonable match, return empty matches array
7. Only return names that are EXACTLY in the customer list"""
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
                    # Check both FullyQualifiedName (for sub-customers) and DisplayName
                    customer_fqn = customer.get('FullyQualifiedName', '')
                    customer_display = customer.get('DisplayName', '')
                    match_name = match.get('customer_name', '')
                    
                    if match_name == customer_fqn or match_name == customer_display:
                        match['customer_id'] = customer.get('Id')
                        break
            
            return matches[:10]
            
        except Exception as e:
            current_app.logger.error(f"Customer matching error: {type(e).__name__}")
            # Fallback to simple search
            return self._simple_customer_match(customers, job_reference)
    
    def _simple_customer_match(self, customers, job_reference: str):
        """Simple fallback customer matching without Claude"""
        matches = []
        job_ref_lower = job_reference.lower()
        
        # Extract words from job reference
        words = [w for w in job_ref_lower.replace('/', ' ').split() if len(w) > 2]
        
        for customer in customers:
            name = customer.get('FullyQualifiedName', customer.get('DisplayName', ''))
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
        return matches[:10]
    
    # =========================================================================
    # INVOICE MANAGEMENT
    # =========================================================================
    
    def get_draft_invoices(self, qb_connection, customer_id: str = None):
        """
        Get unsent/draft invoices, optionally filtered by customer.
        Note: QuickBooks doesn't allow querying by EmailStatus directly,
        so we fetch invoices and filter in code.
        """
        # Query invoices - filter by customer if provided, get recent ones
        if customer_id:
            query = f"query?query=SELECT * FROM Invoice WHERE CustomerRef = '{customer_id}' ORDERBY TxnDate DESC MAXRESULTS 50"
        else:
            query = "query?query=SELECT * FROM Invoice ORDERBY TxnDate DESC MAXRESULTS 50"
        
        result = self.make_api_request(qb_connection, query)
        
        invoices = result.get('QueryResponse', {}).get('Invoice', [])
        
        # Filter to only draft invoices (not yet sent/paid)
        draft_invoices = []
        for inv in invoices:
            email_status = inv.get('EmailStatus', '')
            balance = float(inv.get('Balance', 0))
            
            # Consider draft if not sent AND has balance (not paid)
            if email_status != 'EmailSent' and balance > 0:
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
        # Resolve output-GST treatment; fail closed for a registered user with no code.
        tax_code, tax_status = self.resolve_output_tax(qb_connection)
        if tax_status == 'unresolved':
            current_app.logger.error("Blocking QB invoice creation: TAX_CODE_UNRESOLVED")
            return {'error': 'No valid GST tax code could be resolved — invoice not synced',
                    'code': 'TAX_CODE_UNRESOLVED'}

        # Build line items with GST
        lines = []
        for idx, item in enumerate(line_items):
            # Description-only line (room header)
            if item.get('description_only'):
                line = {
                    "Id": str(idx + 1),
                    "DetailType": "DescriptionOnly",
                    "Description": item.get('description', '')[:4000],
                    "Amount": 0
                }
                lines.append(line)
                continue

            qty = float(item.get('quantity', 1))
            unit_dec = money(item.get('unit_price', 0))
            unit_price = float(unit_dec)
            amount = float(money(unit_dec * to_decimal(item.get('quantity', 1))))
            line = {
                "Id": str(idx + 1),
                "DetailType": "SalesItemLineDetail",
                "Amount": amount,
                "SalesItemLineDetail": {
                    "ItemRef": {
                        "value": item['item_id']
                    },
                    "Qty": qty,
                    "UnitPrice": unit_price
                }
            }

            # Attach the resolved tax code (taxable, or explicit exempt; omitted otherwise)
            if tax_code:
                line["SalesItemLineDetail"]["TaxCodeRef"] = {"value": tax_code['value']}

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
        Add line items to an existing invoice, merging duplicates.
        
        If an item already exists on the invoice:
        - Add to the quantity (accumulate)
        - Update the price to the latest price
        
        This keeps invoices compact and ensures prices are always current.
        """
        # Get existing invoice
        existing = self.make_api_request(qb_connection, f"invoice/{invoice_id}")
        
        if not existing.get('Invoice'):
            return {'error': 'Invoice not found'}
        
        invoice = existing['Invoice']
        existing_lines = invoice.get('Line', [])

        # Resolve output-GST treatment; fail closed for a registered user with no code.
        tax_code, tax_status = self.resolve_output_tax(qb_connection)
        if tax_status == 'unresolved':
            current_app.logger.error("Blocking QB invoice update: TAX_CODE_UNRESOLVED")
            return {'error': 'No valid GST tax code could be resolved — invoice not updated',
                    'code': 'TAX_CODE_UNRESOLVED'}

        # Build a map of existing items by ItemRef ID
        existing_items_map = {}
        for idx, line in enumerate(existing_lines):
            if line.get('DetailType') == 'SalesItemLineDetail':
                item_ref = line.get('SalesItemLineDetail', {}).get('ItemRef', {})
                item_id = item_ref.get('value')
                if item_id:
                    existing_items_map[item_id] = {
                        'line_index': idx,
                        'quantity': float(line.get('SalesItemLineDetail', {}).get('Qty', 0)),
                        'line': line
                    }
        
        # Find next line ID for new items
        max_id = 0
        for line in existing_lines:
            try:
                line_id = int(line.get('Id', 0))
                if line_id > max_id:
                    max_id = line_id
            except (ValueError, TypeError):
                pass
        
        # Process each new item
        items_merged = 0
        items_added = 0
        
        for item in line_items:
            item_id = item['item_id']
            new_qty = float(item.get('quantity', 1))
            new_price = float(money(item.get('unit_price', 0)))
            description = item.get('description', '')
            
            if item_id in existing_items_map:
                # Item already exists - merge quantities and update price
                existing_info = existing_items_map[item_id]
                line_index = existing_info['line_index']
                old_qty = existing_info['quantity']
                combined_qty = old_qty + new_qty
                
                # Update the existing line
                existing_lines[line_index]['SalesItemLineDetail']['Qty'] = combined_qty
                existing_lines[line_index]['SalesItemLineDetail']['UnitPrice'] = new_price
                existing_lines[line_index]['Amount'] = float(money(to_decimal(combined_qty) * to_decimal(new_price)))
                
                # Update description if provided
                if description:
                    existing_lines[line_index]['Description'] = description[:4000]
                
                # Update tax code if we have one
                if tax_code:
                    existing_lines[line_index]['SalesItemLineDetail']['TaxCodeRef'] = {"value": tax_code['value']}
                
                current_app.logger.info(
                    f"Merged item {item_id}: {old_qty} + {new_qty} = {combined_qty}"
                )
                items_merged += 1
                
                # Update the map in case same item appears twice in new items
                existing_items_map[item_id]['quantity'] = combined_qty
                
            else:
                # New item - add as new line
                max_id += 1
                new_line = {
                    "Id": str(max_id),
                    "DetailType": "SalesItemLineDetail",
                    "Amount": float(money(to_decimal(new_qty) * to_decimal(new_price))),
                    "SalesItemLineDetail": {
                        "ItemRef": {
                            "value": item_id
                        },
                        "Qty": new_qty,
                        "UnitPrice": new_price
                    }
                }
                
                # Add tax code if found
                if tax_code:
                    new_line["SalesItemLineDetail"]["TaxCodeRef"] = {"value": tax_code['value']}
                
                if description:
                    new_line["Description"] = description[:4000]
                
                existing_lines.append(new_line)
                
                # Add to map in case same item appears again
                existing_items_map[item_id] = {
                    'line_index': len(existing_lines) - 1,
                    'quantity': new_qty,
                    'line': new_line
                }
                
                current_app.logger.info(f"Added new item {item_id}: {new_qty}")
                items_added += 1
        
        # Update invoice
        update_data = {
            "Id": invoice['Id'],
            "SyncToken": invoice['SyncToken'],
            "sparse": True,
            "Line": existing_lines
        }
        
        result = self.make_api_request(qb_connection, "invoice", method='POST', data=update_data)
        
        if result.get('Invoice'):
            current_app.logger.info(
                f"Invoice updated: {items_merged} items merged, {items_added} items added"
            )
        
        return result

    
    def sync_invoice_to_customer(self, qb_connection, gozappify_invoice, customer_id: str, 
                                  use_existing_invoice: bool = True, sync_mode: str = 'itemised'):
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
        
        items = InvoiceItem.query.filter_by(invoice_id=gozappify_invoice.id).all()
        
        if not items:
            return {'success': False, 'error': 'No items to sync'}
        
        # Step 1: Sync all products
        product_results = self.sync_invoice_items_as_products(qb_connection, gozappify_invoice)
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
        if sync_mode == 'summary':
            # Summary mode: combine all items into one "Materials Used" line
            total_selling = sum(
                (money(to_decimal(item.selling_price or 0) * to_decimal(item.quantity or 1)) for item in items),
                Decimal('0')
            )

            materials_item_id = self._get_or_create_materials_used(qb_connection)
            if not materials_item_id:
                results['errors'].append('Failed to find or create Materials Used product')
                results['success'] = False
                return results
            
            line_items = [{
                'item_id': materials_item_id,
                'quantity': 1,
                'unit_price': float(money(total_selling)),
                'description': 'Materials Used'
            }]
        else:
            # Itemised mode: individual line items
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
            if sync_mode == 'summary':
                invoice_result = self._add_summary_to_invoice(
                    qb_connection,
                    qb_invoice['Id'],
                    line_items[0]
                )
            else:
                invoice_result = self.add_items_to_invoice(
                    qb_connection, 
                    qb_invoice['Id'], 
                    line_items
                )
        else:
            results['invoice_action'] = 'created_new'
            invoice_result = self.create_invoice(
                qb_connection,
                customer_id,
                line_items,
                memo=None
            )
        
        if invoice_result.get('Invoice'):
            results['qb_invoice_id'] = invoice_result['Invoice']['Id']
            results['qb_invoice_number'] = invoice_result['Invoice'].get('DocNumber')
        else:
            results['errors'].append(f"Invoice error: {invoice_result.get('error', 'Unknown')}")
            results['success'] = False
        
        return results

    def _get_or_create_materials_used(self, qb_connection):
        """Find or create a 'Materials Used' product in QuickBooks"""
        try:
            query = "SELECT * FROM Item WHERE Sku = 'MATERIALS-USED'"
            result = self.make_api_request(qb_connection, f"query?query={query}")
            items = result.get('QueryResponse', {}).get('Item', [])
            if items:
                return items[0]['Id']
        except Exception as e:
            current_app.logger.warning(f"Error searching for Materials Used item: {e}")
        
        try:
            query = "SELECT * FROM Item WHERE Name = 'Materials Used'"
            result = self.make_api_request(qb_connection, f"query?query={query}")
            items = result.get('QueryResponse', {}).get('Item', [])
            if items:
                return items[0]['Id']
        except Exception as e:
            current_app.logger.warning(f"Error searching for Materials Used by name: {e}")
        
        try:
            from app.models.quickbooks import QuickBooksConnection
            connection = QuickBooksConnection.query.filter_by(user_id=self.user.id).first()
            
            tax_code, tax_status = self.resolve_output_tax(qb_connection)
            if tax_status == 'unresolved':
                current_app.logger.error("Blocking 'Materials Used' item creation: TAX_CODE_UNRESOLVED")
                return None

            item_data = {
                "Name": "Materials Used",
                "Sku": "MATERIALS-USED",
                "Description": "Materials Used",
                "Type": "NonInventory",
                "Taxable": bool(tax_code),
                "IncomeAccountRef": {"value": connection.default_income_account_id},
                "ExpenseAccountRef": {"value": connection.default_expense_account_id}
            }

            if tax_code:
                item_data["SalesTaxCodeRef"] = {"value": tax_code['value']}
            
            result = self.make_api_request(qb_connection, "item", method='POST', data=item_data)
            if result.get('Item'):
                current_app.logger.info(f"Created Materials Used product in QB: {result['Item']['Id']}")
                return result['Item']['Id']
        except Exception as e:
            current_app.logger.error(f"Failed to create Materials Used item: {e}")
        
        return None
    
    def _add_summary_to_invoice(self, qb_connection, invoice_id, summary_item):
        """Add or accumulate a Materials Used line on an existing invoice"""
        existing = self.make_api_request(qb_connection, f"invoice/{invoice_id}")
        
        if not existing.get('Invoice'):
            return {'error': 'Invoice not found'}

        # Resolve output-GST treatment; fail closed for a registered user with no code.
        tax_code, tax_status = self.resolve_output_tax(qb_connection)
        if tax_status == 'unresolved':
            current_app.logger.error("Blocking Materials Used summary line: TAX_CODE_UNRESOLVED")
            return {'error': 'No valid GST tax code could be resolved — invoice not updated',
                    'code': 'TAX_CODE_UNRESOLVED'}

        invoice = existing['Invoice']
        existing_lines = invoice.get('Line', [])

        materials_line_idx = None
        for idx, line in enumerate(existing_lines):
            if line.get('DetailType') == 'SalesItemLineDetail':
                item_ref = line.get('SalesItemLineDetail', {}).get('ItemRef', {})
                if item_ref.get('value') == summary_item['item_id']:
                    materials_line_idx = idx
                    break
        
        if materials_line_idx is not None:
            old_amount = float(existing_lines[materials_line_idx].get('Amount', 0))
            new_amount = float(money(to_decimal(old_amount) + to_decimal(summary_item['unit_price'])))
            existing_lines[materials_line_idx]['Amount'] = new_amount
            existing_lines[materials_line_idx]['SalesItemLineDetail']['UnitPrice'] = new_amount
            existing_lines[materials_line_idx]['SalesItemLineDetail']['Qty'] = 1
            current_app.logger.info(f"Accumulated Materials Used: {old_amount} + {summary_item['unit_price']} = {new_amount}")
        else:
            max_id = max((int(l.get('Id', 0)) for l in existing_lines if l.get('Id')), default=0)
            new_line = {
                "Id": str(max_id + 1),
                "DetailType": "SalesItemLineDetail",
                "Amount": summary_item['unit_price'],
                "Description": "Materials Used",
                "SalesItemLineDetail": {
                    "ItemRef": {"value": summary_item['item_id']},
                    "Qty": 1,
                    "UnitPrice": summary_item['unit_price']
                }
            }
            if tax_code:
                new_line["SalesItemLineDetail"]["TaxCodeRef"] = {"value": tax_code['value']}
            existing_lines.append(new_line)
        
        update_data = {
            "Id": invoice['Id'],
            "SyncToken": invoice['SyncToken'],
            "sparse": True,
            "Line": existing_lines
        }
        
        return self.make_api_request(qb_connection, "invoice", method='POST', data=update_data)

    # =========================================================================
    # ESTIMATE MANAGEMENT (for Quotes)
    # =========================================================================
    
    def create_estimate(self, qb_connection, customer_id: str, line_items: list, memo: str = None, expiry_days: int = 30):
        """
        Create a new estimate (quote) for a customer
        
        line_items should be list of:
        {
            'item_id': str (QuickBooks Item ID),
            'quantity': float,
            'unit_price': float (optional, uses item default if not provided),
            'description': str (optional)
        }
        """
        from datetime import datetime, timedelta

        # Resolve output-GST treatment; fail closed for a registered user with no code.
        tax_code, tax_status = self.resolve_output_tax(qb_connection)
        if tax_status == 'unresolved':
            current_app.logger.error("Blocking QB estimate creation: TAX_CODE_UNRESOLVED")
            return {'error': 'No valid GST tax code could be resolved — estimate not synced',
                    'code': 'TAX_CODE_UNRESOLVED'}

        # Build line items with GST
        lines = []
        for idx, item in enumerate(line_items):
            # Description-only line (room header)
            if item.get('description_only'):
                line = {
                    "Id": str(idx + 1),
                    "DetailType": "DescriptionOnly",
                    "Description": item.get('description', '')[:4000],
                    "Amount": 0
                }
                lines.append(line)
                continue
            
            qty = float(item.get('quantity', 1))
            unit_dec = money(item.get('unit_price', 0))
            unit_price = float(unit_dec)
            amount = float(money(unit_dec * to_decimal(item.get('quantity', 1))))
            line = {
                "Id": str(idx + 1),
                "DetailType": "SalesItemLineDetail",
                "Amount": amount,
                "SalesItemLineDetail": {
                    "ItemRef": {
                        "value": item['item_id']
                    },
                    "Qty": qty,
                    "UnitPrice": unit_price
                }
            }
            
            # Add tax code if found
            if tax_code:
                line["SalesItemLineDetail"]["TaxCodeRef"] = {"value": tax_code['value']}
            
            if item.get('description'):
                line["Description"] = item['description'][:4000]
            
            lines.append(line)
        
        estimate_data = {
            "CustomerRef": {
                "value": customer_id
            },
            "Line": lines,
            "GlobalTaxCalculation": "TaxExcluded",  # Prices are GST exclusive
            "TxnDate": datetime.utcnow().strftime('%Y-%m-%d'),
            "ExpirationDate": (datetime.utcnow() + timedelta(days=expiry_days)).strftime('%Y-%m-%d')
        }
        
        if memo:
            estimate_data["PrivateNote"] = memo[:4000]
        
        return self.make_api_request(qb_connection, "estimate", method='POST', data=estimate_data)
    
    def get_estimates(self, qb_connection, customer_id: str = None, status: str = None):
        """
        Get estimates, optionally filtered by customer and/or status.
        
        status can be: 'Pending', 'Accepted', 'Closed', 'Rejected'
        """
        query = "query?query=SELECT * FROM Estimate"
        conditions = []
        
        if customer_id:
            conditions.append(f"CustomerRef = '{customer_id}'")
        
        if status:
            conditions.append(f"TxnStatus = '{status}'")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDERBY TxnDate DESC MAXRESULTS 100"
        
        result = self.make_api_request(qb_connection, query)
        return result.get('QueryResponse', {}).get('Estimate', [])
    
    def sync_quote_to_estimate(self, qb_connection, gozappify_quote, customer_id: str):
        """
        Full sync for quotes: Update products AND create customer estimate
        
        1. Sync all products (update prices in QuickBooks)
        2. Create estimate for customer
        
        Returns detailed result
        """
        from app.models.invoice import InvoiceItem
        from app.extensions import db
        
        results = {
            'success': True,
            'products_synced': 0,
            'products_failed': 0,
            'estimate_action': 'created',
            'qb_estimate_id': None,
            'errors': []
        }
        
        items = InvoiceItem.query.filter_by(invoice_id=gozappify_quote.id).all()
        
        if not items:
            return {'success': False, 'error': 'No items to sync'}
        
        # Step 1: Sync all products (this updates QB prices)
        product_results = self.sync_invoice_items_as_products(qb_connection, gozappify_quote)
        results['products_synced'] = product_results.get('synced', 0)
        results['products_failed'] = product_results.get('failed', 0)
        results['errors'].extend(product_results.get('errors', []))
        
        # Build map of part numbers to QB item IDs
        product_map = {}
        for prod in product_results.get('products', []):
            product_map[prod['part_number']] = prod['qb_id']
        
        # Step 2: Build line items for QB estimate
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
            results['errors'].append('No products synced successfully - cannot create estimate')
            results['success'] = False
            return results
        
        # Step 3: Create the estimate
        estimate_result = self.create_estimate(
            qb_connection,
            customer_id,
            line_items,
            memo=None
        )
        
        if estimate_result.get('Estimate'):
            results['qb_estimate_id'] = estimate_result['Estimate']['Id']
            results['qb_estimate_number'] = estimate_result['Estimate'].get('DocNumber')
            
            # Update the GoZappify quote with QB reference
            gozappify_quote.qb_estimate_id = estimate_result['Estimate']['Id']
            gozappify_quote.qb_estimate_synced_at = datetime.utcnow()
            gozappify_quote.matched_customer_id = customer_id
            db.session.commit()
            
            current_app.logger.info(f"Created QB Estimate {results['qb_estimate_id']} for quote {gozappify_quote.id}")
        else:
            results['errors'].append(f"Estimate error: {estimate_result.get('error', 'Unknown')}")
            results['success'] = False
        
        return results

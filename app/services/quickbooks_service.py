"""QuickBooks integration with improved error handling"""
import logging
import time
from typing import Dict, Optional, List
import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

class QuickBooksService:
    """QuickBooks integration with retry logic"""
    
    def __init__(self, access_token: str, realm_id: str, environment: str = 'production'):
        self.access_token = access_token
        self.realm_id = realm_id
        self.environment = environment
        
        if environment == 'sandbox':
            self.base_url = 'https://sandbox-quickbooks.api.intuit.com'
        else:
            self.base_url = 'https://quickbooks.api.intuit.com'
    
    def create_product(self, name: str, sku: str, description: str, 
                      unit_price: float, purchase_cost: float,
                      product_type: str = 'NonInventory', max_retries: int = 3) -> Optional[Dict]:
        """Create a new product in QuickBooks with retries"""
        logger.info(f"Creating product: {name} (SKU: {sku})")
        
        income_account = self._get_income_account()
        expense_account = self._get_expense_account()
        tax_code = self._get_tax_code()
        
        if not income_account or not expense_account:
            logger.error("Could not find required accounts")
            return None
        
        product_data = {
            'Name': name[:100],
            'Sku': sku[:100],
            'Description': description[:4000],
            'Type': product_type,
            'Active': True,
            'UnitPrice': unit_price,
            'PurchaseCost': purchase_cost,
            'IncomeAccountRef': income_account,
            'ExpenseAccountRef': expense_account,
            'Taxable': True,
        }
        
        if tax_code:
            product_data['SalesTaxCodeRef'] = tax_code
        
        for attempt in range(max_retries):
            try:
                result = self._make_request('POST', '/v3/company/{}/item', product_data)
                if result and 'Item' in result:
                    logger.info(f"✓ Created product: {name}")
                    return result['Item']
            except RequestException as e:
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        return None
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """Make HTTP request to QuickBooks API"""
        url = f"{self.base_url}{endpoint.format(self.realm_id)}"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                raise RequestException(f"HTTP {response.status_code}")
        except Exception as e:
            logger.error(f"Request failed: {str(e)}")
            raise
    
    def _get_income_account(self) -> Optional[Dict]:
        """Get income account"""
        try:
            result = self._make_request('GET', '/v3/company/{}/query?query=SELECT * FROM Account WHERE AccountSubType = \'SalesOfProductIncome\' AND Active = true')
            if result and 'QueryResponse' in result:
                accounts = result['QueryResponse'].get('Account', [])
                if accounts:
                    return {'value': accounts[0]['Id'], 'name': accounts[0]['Name']}
        except:
            pass
        return None
    
    def _get_expense_account(self) -> Optional[Dict]:
        """Get expense account"""
        try:
            result = self._make_request('GET', '/v3/company/{}/query?query=SELECT * FROM Account WHERE AccountSubType = \'CostOfGoodsSold\' AND Active = true')
            if result and 'QueryResponse' in result:
                accounts = result['QueryResponse'].get('Account', [])
                if accounts:
                    return {'value': accounts[0]['Id'], 'name': accounts[0]['Name']}
        except:
            pass
        return None
    
    def _get_tax_code(self) -> Optional[Dict]:
        """Get tax code"""
        try:
            result = self._make_request('GET', '/v3/company/{}/query?query=SELECT * FROM TaxCode WHERE Active = true')
            if result and 'QueryResponse' in result:
                codes = result['QueryResponse'].get('TaxCode', [])
                if codes:
                    return {'value': codes[0]['Id'], 'name': codes[0]['Name']}
        except:
            pass
        return None

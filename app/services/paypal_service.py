"""PayPal API Service for subscriptions and one-time payments"""
import os
import requests
import base64
from datetime import datetime, timedelta
from flask import current_app


class PayPalService:
    """Service class for PayPal API interactions"""
    
    def __init__(self):
        self.client_id = os.getenv('PAYPAL_CLIENT_ID')
        self.client_secret = os.getenv('PAYPAL_CLIENT_SECRET')
        self.mode = os.getenv('PAYPAL_MODE', 'sandbox')
        
        if self.mode == 'live':
            self.base_url = 'https://api-m.paypal.com'
        else:
            self.base_url = 'https://api-m.sandbox.paypal.com'
        
        self._access_token = None
        self._token_expires = None
    
    def _get_access_token(self):
        """Get OAuth access token from PayPal"""
        if self._access_token and self._token_expires and datetime.utcnow() < self._token_expires:
            return self._access_token
        
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        
        response = requests.post(
            f"{self.base_url}/v1/oauth2/token",
            headers={
                'Authorization': f'Basic {auth}',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data={'grant_type': 'client_credentials'}
        )
        
        if response.status_code == 200:
            data = response.json()
            self._access_token = data['access_token']
            self._token_expires = datetime.utcnow() + timedelta(hours=8)
            return self._access_token
        else:
            current_app.logger.error(f"PayPal auth failed: {response.text}")
            raise Exception("Failed to authenticate with PayPal")
    
    def _headers(self):
        """Get headers for API requests"""
        return {
            'Authorization': f'Bearer {self._get_access_token()}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    
    def create_subscription(self, plan_id, user_id, return_url, cancel_url, custom_id=None):
        """Create a subscription - returns approval URL for user to complete"""
        payload = {
            'plan_id': plan_id,
            'application_context': {
                'brand_name': 'GoZappify',
                'locale': 'en-GB',
                'shipping_preference': 'NO_SHIPPING',
                'user_action': 'SUBSCRIBE_NOW',
                'return_url': return_url,
                'cancel_url': cancel_url
            }
        }
        
        if custom_id:
            payload['custom_id'] = custom_id
        
        response = requests.post(
            f"{self.base_url}/v1/billing/subscriptions",
            headers=self._headers(),
            json=payload
        )
        
        if response.status_code == 201:
            return response.json()
        else:
            current_app.logger.error(f"Create subscription failed: {response.text}")
            return None
    
    def get_subscription(self, subscription_id):
        """Get subscription details"""
        response = requests.get(
            f"{self.base_url}/v1/billing/subscriptions/{subscription_id}",
            headers=self._headers()
        )
        
        if response.status_code == 200:
            return response.json()
        return None
    
    def cancel_subscription(self, subscription_id, reason='Cancelled by user'):
        """Cancel a subscription"""
        response = requests.post(
            f"{self.base_url}/v1/billing/subscriptions/{subscription_id}/cancel",
            headers=self._headers(),
            json={'reason': reason}
        )
        return response.status_code == 204
    
    def get_update_payment_url(self, subscription_id=None):
        """Get link for user to update their payment method"""
        if self.mode == 'live':
            return 'https://www.paypal.com/myaccount/autopay/'
        else:
            return 'https://www.sandbox.paypal.com/myaccount/autopay/'
    
    def create_order(self, amount, currency='GBP', description='Invoice Credits', custom_id=None):
        """Create a one-time payment order"""
        payload = {
            'intent': 'CAPTURE',
            'purchase_units': [{
                'amount': {
                    'currency_code': currency,
                    'value': str(amount)
                },
                'description': description
            }],
            'application_context': {
                'brand_name': 'GoZappify',
                'locale': 'en-GB',
                'shipping_preference': 'NO_SHIPPING',
                'user_action': 'PAY_NOW'
            }
        }
        
        if custom_id:
            payload['purchase_units'][0]['custom_id'] = custom_id
        
        response = requests.post(
            f"{self.base_url}/v2/checkout/orders",
            headers=self._headers(),
            json=payload
        )
        
        if response.status_code == 201:
            return response.json()
        else:
            current_app.logger.error(f"Create order failed: {response.text}")
            return None
    
    def capture_order(self, order_id):
        """Capture payment for an order after buyer approves"""
        response = requests.post(
            f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
            headers=self._headers()
        )
        
        if response.status_code == 201:
            return response.json()
        else:
            current_app.logger.error(f"Capture order failed: {response.text}")
            return None


# Singleton instance
_paypal_service = None

def get_paypal_service() -> PayPalService:
    """Get or create PayPal service instance"""
    global _paypal_service
    if _paypal_service is None:
        _paypal_service = PayPalService()
    return _paypal_service

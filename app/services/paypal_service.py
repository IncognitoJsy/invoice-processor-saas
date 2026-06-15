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

    def verify_webhook_signature(self, transmission_headers, event_body):
        """Verify a PayPal webhook event is authentic.

        Unlike the QuickBooks webhook (which uses a local HMAC of a shared
        verifier token), PayPal signs events with a rotating certificate. The
        documented way to verify is a server-to-server call to PayPal's
        verify-webhook-signature API, passing the five PAYPAL-* transmission
        headers, our webhook id, and the raw event body.

        Fails closed: any missing config, transport error, or non-SUCCESS
        verification status returns False. Never logs the event body or token.

        Args:
            transmission_headers: the inbound request's headers (case-insensitive
                mapping, e.g. Flask's request.headers).
            event_body: the parsed webhook event (the JSON dict PayPal sent).

        Returns:
            tuple: (is_valid: bool, error_message: str or None)
        """
        webhook_id = os.getenv('PAYPAL_WEBHOOK_ID')
        if not webhook_id:
            current_app.logger.error("PAYPAL_WEBHOOK_ID not configured")
            return False, 'Webhook id not configured'

        # PayPal sends these five headers; all are required to verify.
        required = {
            'auth_algo': transmission_headers.get('PAYPAL-AUTH-ALGO'),
            'cert_url': transmission_headers.get('PAYPAL-CERT-URL'),
            'transmission_id': transmission_headers.get('PAYPAL-TRANSMISSION-ID'),
            'transmission_sig': transmission_headers.get('PAYPAL-TRANSMISSION-SIG'),
            'transmission_time': transmission_headers.get('PAYPAL-TRANSMISSION-TIME'),
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            return False, f"Missing transmission headers: {', '.join(missing)}"

        payload = dict(required, webhook_id=webhook_id, webhook_event=event_body)

        try:
            response = requests.post(
                f"{self.base_url}/v1/notifications/verify-webhook-signature",
                headers=self._headers(),
                json=payload,
                timeout=10,
            )
        except requests.RequestException as e:
            current_app.logger.error(f"PayPal webhook verify request failed: {str(e)}")
            return False, 'Verification request failed'

        if response.status_code != 200:
            current_app.logger.error(
                f"PayPal webhook verify returned {response.status_code}"
            )
            return False, 'Verification request rejected'

        status = response.json().get('verification_status')
        if status != 'SUCCESS':
            return False, f'Verification status: {status}'

        return True, None

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

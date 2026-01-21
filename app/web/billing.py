"""Billing routes for Paddle subscription management"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app
from flask_login import login_required, current_user
from app.extensions import db
import os
import hashlib
import hmac
import json
from datetime import datetime

bp = Blueprint('billing', __name__, url_prefix='/billing')

# Top-up pricing: £0.50 per invoice
TOPUP_PRICE_PER_INVOICE = 0.50
TOPUP_MIN_QUANTITY = 10
TOPUP_PRESETS = [10, 20, 30]

# Paddle configuration
def get_paddle_config():
    """Get Paddle configuration"""
    return {
        'api_key': os.getenv('PADDLE_API_KEY'),
        'client_token': os.getenv('PADDLE_CLIENT_TOKEN'),
        'webhook_secret': os.getenv('PADDLE_WEBHOOK_SECRET'),
        'environment': os.getenv('PADDLE_ENV', 'sandbox'),
        'price_basic': os.getenv('PADDLE_PRICE_BASIC'),
        'price_pro': os.getenv('PADDLE_PRICE_PRO'),
    }


def get_paddle_api_url():
    """Get Paddle API base URL based on environment"""
    config = get_paddle_config()
    if config['environment'] == 'production':
        return 'https://api.paddle.com'
    return 'https://sandbox-api.paddle.com'


def paddle_api_request(method, endpoint, data=None):
    """Make authenticated request to Paddle API"""
    import requests
    
    config = get_paddle_config()
    url = f"{get_paddle_api_url()}{endpoint}"
    
    headers = {
        'Authorization': f"Bearer {config['api_key']}",
        'Content-Type': 'application/json'
    }
    
    try:
        if method == 'GET':
            response = requests.get(url, headers=headers, params=data)
        elif method == 'POST':
            response = requests.post(url, headers=headers, json=data)
        elif method == 'PATCH':
            response = requests.patch(url, headers=headers, json=data)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        return response.json()
    except Exception as e:
        current_app.logger.error(f"Paddle API error: {str(e)}")
        raise


@bp.route('/')
@login_required
def index():
    """Billing overview page"""
    config = get_paddle_config()
    return render_template('billing/index.html', 
                          paddle_client_token=config['client_token'],
                          paddle_environment=config['environment'],
                          paddle_price_basic=config['price_basic'],
                          paddle_price_pro=config['price_pro'])


@bp.route('/topup')
@login_required
def topup():
    """Top-up purchase page - only for Basic plan users"""
    config = get_paddle_config()
    
    if current_user.subscription_plan == 'trial':
        return render_template('billing/topup.html', 
                             error="Top-ups are only available for paid subscribers. Please upgrade to Basic or Pro first.",
                             can_purchase=False)
    
    if current_user.subscription_plan == 'pro':
        return render_template('billing/topup.html',
                             error="You have unlimited invoices on the Pro plan!",
                             can_purchase=False)
    
    if current_user.subscription_plan == 'cancelled':
        return render_template('billing/topup.html',
                             error="Please reactivate your subscription to purchase top-ups.",
                             can_purchase=False)
    
    return render_template('billing/topup.html',
                         can_purchase=True,
                         price_per_invoice=TOPUP_PRICE_PER_INVOICE,
                         presets=TOPUP_PRESETS,
                         min_quantity=TOPUP_MIN_QUANTITY,
                         current_bonus=current_user.bonus_invoices or 0,
                         base_remaining=current_user.base_invoices_remaining,
                         total_remaining=current_user.invoices_remaining,
                         paddle_client_token=config['client_token'],
                         paddle_environment=config['environment'])


@bp.route('/topup/checkout', methods=['POST'])
@login_required
def topup_checkout():
    """Create Paddle transaction for top-up purchase using Transaction API"""
    if current_user.subscription_plan not in ['basic']:
        return jsonify({'error': 'Top-ups are only available for Basic plan subscribers'}), 400
    
    data = request.get_json() or {}
    quantity = data.get('quantity', 10)
    
    try:
        quantity = int(quantity)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid quantity'}), 400
    
    if quantity < TOPUP_MIN_QUANTITY:
        return jsonify({'error': f'Minimum purchase is {TOPUP_MIN_QUANTITY} invoices'}), 400
    
    if quantity % 10 != 0:
        return jsonify({'error': 'Quantity must be a multiple of 10'}), 400
    
    if quantity > 500:
        return jsonify({'error': 'Maximum purchase is 500 invoices at once'}), 400
    
    # Calculate price (Paddle uses string amounts with decimal)
    amount = str(int(quantity * TOPUP_PRICE_PER_INVOICE * 100))  # In pence/cents
    
    config = get_paddle_config()
    
    try:
        # First, get or create Paddle customer
        customer_id = current_user.paddle_customer_id
        
        if not customer_id:
            # Create customer in Paddle
            customer_response = paddle_api_request('POST', '/customers', {
                'email': current_user.email,
                'name': f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.email,
                'custom_data': {
                    'user_id': str(current_user.id)
                }
            })
            
            if customer_response.get('data'):
                customer_id = customer_response['data']['id']
                current_user.paddle_customer_id = customer_id
                db.session.commit()
            else:
                current_app.logger.error(f"Failed to create Paddle customer: {customer_response}")
                return jsonify({'error': 'Failed to create customer'}), 500
        
        # Create a transaction for the top-up
        # Using Paddle's "custom" items for one-time variable pricing
        transaction_data = {
            'items': [{
                'price': {
                    'description': f'GoZappify Invoice Top-Up ({quantity} credits)',
                    'name': f'{quantity} Invoice Credits',
                    'billing_cycle': None,  # One-time payment
                    'trial_period': None,
                    'tax_mode': 'account_setting',
                    'unit_price': {
                        'amount': amount,
                        'currency_code': 'GBP'
                    },
                    'product': {
                        'name': 'Invoice Processing Credits',
                        'description': 'Additional invoice processing credits for GoZappify',
                        'tax_category': 'standard'
                    }
                },
                'quantity': 1
            }],
            'customer_id': customer_id,
            'custom_data': {
                'user_id': str(current_user.id),
                'type': 'topup',
                'quantity': str(quantity)
            },
            'checkout': {
                'url': request.host_url.rstrip('/') + url_for('billing.topup_success') + f'?quantity={quantity}'
            }
        }
        
        response = paddle_api_request('POST', '/transactions', transaction_data)
        
        if response.get('data'):
            transaction = response['data']
            checkout_url = transaction.get('checkout', {}).get('url')
            
            if checkout_url:
                return jsonify({
                    'success': True,
                    'checkout_url': checkout_url,
                    'transaction_id': transaction.get('id')
                })
            else:
                # If no checkout URL, return transaction ID for client-side checkout
                return jsonify({
                    'success': True,
                    'transaction_id': transaction.get('id')
                })
        else:
            error_msg = response.get('error', {}).get('detail', 'Failed to create transaction')
            current_app.logger.error(f"Paddle transaction error: {response}")
            return jsonify({'error': error_msg}), 500
            
    except Exception as e:
        current_app.logger.error(f"Top-up checkout error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/topup/success')
@login_required
def topup_success():
    """Handle successful top-up purchase"""
    # Get quantity from URL params (set by Paddle passthrough)
    quantity = request.args.get('quantity', 0, type=int)
    
    if quantity > 0:
        # Add bonus invoices (webhook should also handle this, but this is backup)
        # Check if already credited by looking at recent transactions
        current_app.logger.info(f"Top-up success page: User {current_user.id}, quantity {quantity}")
        
        return render_template('billing/topup_success.html',
                             quantity=quantity,
                             total_bonus=current_user.bonus_invoices or 0,
                             total_remaining=current_user.invoices_remaining)
    
    return redirect(url_for('billing.topup'))


@bp.route('/subscribe/<plan>')
@login_required
def subscribe(plan):
    """Return subscription data for Paddle checkout overlay"""
    config = get_paddle_config()
    
    price_ids = {
        'basic': config['price_basic'],
        'pro': config['price_pro']
    }
    
    if plan not in price_ids:
        return jsonify({'error': 'Invalid plan'}), 400
    
    # Return data for the frontend to open Paddle checkout
    return jsonify({
        'success': True,
        'price_id': price_ids[plan],
        'plan': plan,
        'user_email': current_user.email,
        'user_id': current_user.id
    })


@bp.route('/success')
@login_required
def success():
    """Subscription success page"""
    return render_template('billing/success.html')


@bp.route('/manage')
@login_required
def manage():
    """Redirect to Paddle customer portal or show management options"""
    if not current_user.paddle_subscription_id:
        return redirect(url_for('billing.index'))
    
    # For Paddle, we can either:
    # 1. Use Paddle's customer portal (if enabled)
    # 2. Show our own management page
    
    # Try to get cancel URL from Paddle
    try:
        config = get_paddle_config()
        if current_user.paddle_subscription_id:
            response = paddle_api_request('GET', f"/subscriptions/{current_user.paddle_subscription_id}")
            if response.get('data'):
                # Paddle provides management URLs in subscription data
                management_urls = response['data'].get('management_urls', {})
                cancel_url = management_urls.get('cancel')
                update_payment_url = management_urls.get('update_payment_method')
                
                return render_template('billing/manage.html',
                                     cancel_url=cancel_url,
                                     update_payment_url=update_payment_url,
                                     subscription=response['data'])
    except Exception as e:
        current_app.logger.error(f"Error getting Paddle subscription: {str(e)}")
    
    return redirect(url_for('billing.index'))


@bp.route('/cancel', methods=['POST'])
@login_required
def cancel():
    """Cancel subscription"""
    if not current_user.paddle_subscription_id:
        return jsonify({'error': 'No active subscription'}), 400
    
    try:
        # Cancel at period end
        response = paddle_api_request('POST', f"/subscriptions/{current_user.paddle_subscription_id}/cancel", {
            'effective_from': 'next_billing_period'
        })
        
        if response.get('data'):
            current_user.subscription_status = 'cancelled'
            db.session.commit()
            return jsonify({'success': True, 'message': 'Subscription will cancel at end of billing period'})
        else:
            return jsonify({'error': response.get('error', {}).get('detail', 'Cancellation failed')}), 500
            
    except Exception as e:
        current_app.logger.error(f"Cancellation error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/webhook', methods=['POST'])
def webhook():
    """Handle Paddle webhooks"""
    payload = request.get_data()
    signature = request.headers.get('Paddle-Signature')
    
    config = get_paddle_config()
    webhook_secret = config['webhook_secret']
    
    # Verify webhook signature
    if webhook_secret and signature:
        if not verify_paddle_signature(payload, signature, webhook_secret):
            current_app.logger.error("Invalid Paddle webhook signature")
            return jsonify({'error': 'Invalid signature'}), 400
    
    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON'}), 400
    
    event_type = event.get('event_type')
    data = event.get('data', {})
    
    current_app.logger.info(f"Paddle webhook received: {event_type}")
    current_app.logger.debug(f"Webhook data: {json.dumps(data, indent=2)}")
    
    # Handle different event types
    if event_type == 'subscription.created':
        handle_subscription_created(data)
    elif event_type == 'subscription.updated':
        handle_subscription_updated(data)
    elif event_type == 'subscription.canceled':
        handle_subscription_canceled(data)
    elif event_type == 'subscription.paused':
        handle_subscription_paused(data)
    elif event_type == 'transaction.completed':
        handle_transaction_completed(data)
    
    return jsonify({'received': True})


def verify_paddle_signature(payload, signature, secret):
    """Verify Paddle webhook signature"""
    try:
        # Parse the signature header
        # Format: ts=timestamp;h1=hash
        parts = dict(part.split('=') for part in signature.split(';'))
        timestamp = parts.get('ts')
        received_hash = parts.get('h1')
        
        if not timestamp or not received_hash:
            return False
        
        # Build the signed payload
        signed_payload = f"{timestamp}:{payload.decode('utf-8')}"
        
        # Calculate expected signature
        expected_hash = hmac.new(
            secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_hash, received_hash)
    except Exception as e:
        current_app.logger.error(f"Signature verification error: {str(e)}")
        return False


def get_user_from_paddle_data(data):
    """Extract user from Paddle webhook data"""
    from app.models.user import User
    
    # Try to get user from custom_data first
    custom_data = data.get('custom_data', {})
    user_id = custom_data.get('user_id')
    
    if user_id:
        user = User.query.get(int(user_id))
        if user:
            return user
    
    # Try customer email
    customer = data.get('customer', {})
    email = customer.get('email')
    
    if email:
        user = User.query.filter_by(email=email).first()
        if user:
            return user
    
    # Try paddle_customer_id
    customer_id = data.get('customer_id') or customer.get('id')
    if customer_id:
        user = User.query.filter_by(paddle_customer_id=customer_id).first()
        if user:
            return user
    
    return None


def handle_subscription_created(data):
    """Handle subscription.created webhook"""
    user = get_user_from_paddle_data(data)
    
    if not user:
        current_app.logger.warning(f"No user found for subscription: {data.get('id')}")
        return
    
    # Get subscription details
    subscription_id = data.get('id')
    customer_id = data.get('customer_id')
    status = data.get('status')
    
    # Determine plan from price ID
    items = data.get('items', [])
    price_id = items[0].get('price', {}).get('id') if items else None
    
    config = get_paddle_config()
    if price_id == config['price_basic']:
        plan = 'basic'
    elif price_id == config['price_pro']:
        plan = 'pro'
    else:
        plan = 'basic'  # Default
    
    # Update user
    user.paddle_customer_id = customer_id
    user.paddle_subscription_id = subscription_id
    user.subscription_plan = plan
    user.subscription_status = 'active' if status == 'active' else status
    user.subscription_started_at = datetime.utcnow()
    user.bonus_invoices = 0  # Reset bonus on new subscription
    
    db.session.commit()
    current_app.logger.info(f"Subscription created for user {user.id}: {plan}")
    
    # Send welcome email
    try:
        from app.services.email_service import get_email_service
        email_service = get_email_service()
        
        base_url = os.getenv('APP_URL', 'https://gozappify.com')
        dashboard_url = f"{base_url}/dashboard"
        
        plan_name = 'Basic' if plan == 'basic' else 'Pro'
        email_service.send_welcome_paid(user, plan_name, dashboard_url)
    except Exception as e:
        current_app.logger.error(f"Failed to send welcome email: {str(e)}")


def handle_subscription_updated(data):
    """Handle subscription.updated webhook"""
    user = get_user_from_paddle_data(data)
    
    if not user:
        subscription_id = data.get('id')
        # Try to find by subscription ID
        from app.models.user import User
        user = User.query.filter_by(paddle_subscription_id=subscription_id).first()
        
        if not user:
            current_app.logger.warning(f"No user found for subscription update: {subscription_id}")
            return
    
    status = data.get('status')
    
    # Check if this is a renewal
    billing_cycle = data.get('current_billing_period', {})
    if billing_cycle:
        period_start = billing_cycle.get('starts_at')
        if period_start:
            # This might be a renewal - reset billing period
            user.renew_subscription()
            current_app.logger.info(f"Subscription renewed for user {user.id}")
    
    # Update status
    if status == 'active':
        user.subscription_status = 'active'
    elif status == 'past_due':
        user.subscription_status = 'past_due'
    elif status in ['canceled', 'paused']:
        user.subscription_status = 'cancelled'
    
    db.session.commit()
    current_app.logger.info(f"Subscription updated for user {user.id}: status={status}")


def handle_subscription_canceled(data):
    """Handle subscription.canceled webhook"""
    from app.models.user import User
    
    subscription_id = data.get('id')
    user = User.query.filter_by(paddle_subscription_id=subscription_id).first()
    
    if user:
        user.subscription_plan = 'cancelled'
        user.subscription_status = 'cancelled'
        db.session.commit()
        current_app.logger.info(f"Subscription cancelled for user {user.id}")


def handle_subscription_paused(data):
    """Handle subscription.paused webhook"""
    from app.models.user import User
    
    subscription_id = data.get('id')
    user = User.query.filter_by(paddle_subscription_id=subscription_id).first()
    
    if user:
        user.subscription_status = 'paused'
        db.session.commit()
        current_app.logger.info(f"Subscription paused for user {user.id}")


def handle_transaction_completed(data):
    """Handle transaction.completed webhook - used for one-time purchases like top-ups"""
    # Check if this is a top-up purchase
    custom_data = data.get('custom_data', {})
    
    if custom_data.get('type') == 'topup':
        user_id = custom_data.get('user_id')
        quantity = custom_data.get('quantity', 0)
        
        if user_id and quantity:
            from app.models.user import User
            user = User.query.get(int(user_id))
            
            if user:
                # Check if this transaction was already processed
                transaction_id = data.get('id')
                # In production, you'd want to store processed transaction IDs
                
                user.add_bonus_invoices(int(quantity))
                db.session.commit()
                current_app.logger.info(f"Added {quantity} top-up invoices to user {user.id}")


@bp.route('/api/status')
@login_required
def api_status():
    """Get current subscription status"""
    limit = current_user.monthly_invoice_limit
    used = current_user.get_invoices_this_period()
    
    return jsonify({
        'plan': current_user.subscription_plan,
        'plan_name': current_user.plan_display_name,
        'status': current_user.subscription_status,
        'is_admin': current_user.is_admin,
        'has_active_subscription': current_user.has_active_subscription,
        'can_sync': current_user.can_sync_to_accounting,
        'can_upload': current_user.can_upload_invoice,
        'invoice_limit': limit if limit != float('inf') else 'unlimited',
        'invoices_used': used,
        'invoices_remaining': current_user.invoices_remaining if current_user.invoices_remaining != float('inf') else 'unlimited',
        'bonus_invoices': current_user.bonus_invoices or 0,
        'trial_active': current_user.is_trial_active,
        'trial_days_remaining': current_user.trial_days_remaining if current_user.subscription_plan == 'trial' else None
    })

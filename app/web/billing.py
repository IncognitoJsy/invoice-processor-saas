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
        'price_topup': os.getenv('PADDLE_PRICE_TOPUP'),
    }


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
                         paddle_environment=config['environment'],
                         paddle_price_topup=config['price_topup'])


@bp.route('/topup/checkout', methods=['POST'])
@login_required
def topup_checkout():
    """Return data for Paddle checkout with quantity"""
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
    
    config = get_paddle_config()
    
    # Return the price ID and quantity for the frontend to open Paddle checkout
    return jsonify({
        'success': True,
        'price_id': config['price_topup'],
        'quantity': quantity,
        'user_id': current_user.id,
        'user_email': current_user.email
    })


@bp.route('/topup/success')
@login_required
def topup_success():
    """Handle successful top-up purchase"""
    quantity = request.args.get('quantity', 0, type=int)
    
    current_app.logger.info(f"Top-up success page: User {current_user.id}, quantity {quantity}")
    
    # Note: The actual credit addition happens via webhook
    # This page just shows confirmation
    
    return render_template('billing/topup_success.html',
                         quantity=quantity,
                         total_bonus=current_user.bonus_invoices or 0,
                         total_remaining=current_user.invoices_remaining)


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
    # Get the plan from URL param (passed from Paddle checkout success URL)
    # This is more reliable than current_user since webhook may not have processed yet
    plan = request.args.get('plan', '')
    
    # Determine display values based on plan param or fall back to current_user
    if plan == 'pro':
        plan_name = 'Pro'
        invoice_limit = 'Unlimited'
    elif plan == 'basic':
        plan_name = 'Basic'
        invoice_limit = '100'
    else:
        # Fall back to current_user (webhook may have already processed)
        plan_name = current_user.plan_display_name
        invoice_limit = 'Unlimited' if current_user.subscription_plan == 'pro' else '100'
    
    return render_template('billing/success.html',
                          plan_name=plan_name,
                          invoice_limit=invoice_limit)


@bp.route('/manage')
@login_required
def manage():
    """Show subscription management page"""
    if not current_user.paddle_subscription_id:
        return redirect(url_for('billing.index'))
    
    config = get_paddle_config()
    
    return render_template('billing/manage.html',
                          paddle_client_token=config['client_token'],
                          paddle_environment=config['environment'],
                          paddle_price_basic=config['price_basic'],
                          paddle_price_pro=config['price_pro'])


@bp.route('/change-plan', methods=['POST'])
@login_required
def change_plan():
    """Change subscription plan - only for DOWNGRADES. Upgrades must go through Paddle checkout."""
    import requests
    
    if not current_user.paddle_subscription_id:
        return jsonify({'error': 'No active subscription'}), 400
    
    data = request.get_json() or {}
    new_plan = data.get('plan')
    
    if new_plan not in ['basic', 'pro']:
        return jsonify({'error': 'Invalid plan'}), 400
    
    # Don't allow changing to the same plan
    if new_plan == current_user.subscription_plan:
        return jsonify({'error': 'You are already on this plan'}), 400
    
    # Only allow downgrades through this endpoint
    # Upgrades MUST go through Paddle checkout to collect payment
    is_downgrade = new_plan == 'basic' and current_user.subscription_plan == 'pro'
    
    if not is_downgrade:
        return jsonify({'error': 'Upgrades must go through checkout'}), 400
    
    config = get_paddle_config()
    new_price_id = config['price_basic']
    
    try:
        # Determine API URL based on environment
        if config['environment'] == 'production':
            api_url = 'https://api.paddle.com'
        else:
            api_url = 'https://sandbox-api.paddle.com'
        
        # Schedule downgrade for next billing period
        # User keeps Pro access until then, no refund needed
        response = requests.patch(
            f"{api_url}/subscriptions/{current_user.paddle_subscription_id}",
            headers={
                'Authorization': f"Bearer {config['api_key']}",
                'Content-Type': 'application/json'
            },
            json={
                'items': [{
                    'price_id': new_price_id,
                    'quantity': 1
                }],
                'proration_billing_mode': 'prorated_next_billing_period',
                'on_payment_failure': 'prevent_change'
            }
        )
        
        result = response.json()
        current_app.logger.info(f"Downgrade response: {result}")
        
        if result.get('data'):
            # Don't change plan yet - Paddle webhook will handle it at next billing
            return jsonify({
                'success': True, 
                'message': 'Plan will change to Basic at your next billing date. You keep Pro access until then.',
                'is_downgrade': True
            })
        else:
            error_msg = result.get('error', {}).get('detail', 'Downgrade failed')
            return jsonify({'error': error_msg}), 500
            
    except Exception as e:
        current_app.logger.error(f"Downgrade error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/cancel', methods=['POST'])
@login_required
def cancel():
    """Cancel subscription"""
    import requests
    
    if not current_user.paddle_subscription_id:
        return jsonify({'error': 'No active subscription'}), 400
    
    config = get_paddle_config()
    
    try:
        # Determine API URL based on environment
        if config['environment'] == 'production':
            api_url = 'https://api.paddle.com'
        else:
            api_url = 'https://sandbox-api.paddle.com'
        
        # Cancel at period end
        response = requests.post(
            f"{api_url}/subscriptions/{current_user.paddle_subscription_id}/cancel",
            headers={
                'Authorization': f"Bearer {config['api_key']}",
                'Content-Type': 'application/json'
            },
            json={'effective_from': 'next_billing_period'}
        )
        
        result = response.json()
        
        if result.get('data'):
            current_user.subscription_status = 'cancelled'
            db.session.commit()
            return jsonify({
                'success': True, 
                'message': 'Your subscription has been cancelled. You will keep access until the end of your current billing period.'
            })
        else:
            return jsonify({'error': result.get('error', {}).get('detail', 'Cancellation failed')}), 500
            
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
            current_app.logger.warning("Invalid webhook signature")
            return jsonify({'error': 'Invalid signature'}), 401
    
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON'}), 400
    
    event_type = data.get('event_type')
    event_data = data.get('data', {})
    
    current_app.logger.info(f"Paddle webhook received: {event_type}")
    current_app.logger.debug(f"Webhook data: {json.dumps(event_data, indent=2)}")
    
    # Route to appropriate handler
    if event_type == 'subscription.created':
        handle_subscription_created(event_data)
    elif event_type == 'subscription.updated':
        handle_subscription_updated(event_data)
    elif event_type == 'subscription.canceled':
        handle_subscription_canceled(event_data)
    elif event_type == 'subscription.paused':
        handle_subscription_paused(event_data)
    elif event_type == 'transaction.completed':
        handle_transaction_completed(event_data)
    else:
        current_app.logger.info(f"Unhandled webhook event: {event_type}")
    
    return jsonify({'status': 'success'}), 200


def verify_paddle_signature(payload, signature, secret):
    """Verify Paddle webhook signature"""
    try:
        # Parse the signature header
        parts = {}
        for part in signature.split(';'):
            if '=' in part:
                key, value = part.split('=', 1)
                parts[key] = value
        
        ts = parts.get('ts', '')
        h1 = parts.get('h1', '')
        
        if not ts or not h1:
            return False
        
        # Build the signed payload
        signed_payload = f"{ts}:{payload.decode('utf-8')}"
        
        # Calculate expected signature
        expected = hmac.new(
            secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, h1)
    except Exception as e:
        current_app.logger.error(f"Signature verification error: {str(e)}")
        return False


def handle_subscription_created(data):
    """Handle subscription.created webhook"""
    from app.models.user import User
    
    # Try multiple ways to find the user
    user = None
    
    # 1. Try custom_data
    custom_data = data.get('custom_data') or {}
    user_id = custom_data.get('user_id')
    if user_id:
        user = User.query.get(int(user_id))
    
    # 2. Try customer email from the subscription data
    if not user:
        customer = data.get('customer') or {}
        email = customer.get('email')
        if email:
            user = User.query.filter_by(email=email).first()
            current_app.logger.info(f"Found user by email: {email}")
    
    # 3. Try customer_id
    if not user:
        customer_id = data.get('customer_id')
        if customer_id:
            user = User.query.filter_by(paddle_customer_id=customer_id).first()
    
    if not user:
        current_app.logger.warning(f"No user found for subscription: {data.get('id')}")
        return
    
    # Get subscription details
    subscription_id = data.get('id')
    customer_id = data.get('customer_id')
    status = data.get('status')
    
    # Determine plan from price ID
    items = data.get('items') or []
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
        current_app.logger.info(f"Welcome email sent to {user.email}")
    except Exception as e:
        current_app.logger.error(f"Failed to send welcome email: {str(e)}")


def handle_subscription_updated(data):
    """Handle subscription.updated webhook"""
    from app.models.user import User
    
    subscription_id = data.get('id')
    user = User.query.filter_by(paddle_subscription_id=subscription_id).first()
    
    if not user:
        # Try by email
        customer = data.get('customer') or {}
        email = customer.get('email')
        if email:
            user = User.query.filter_by(email=email).first()
    
    if not user:
        current_app.logger.warning(f"No user found for subscription update: {subscription_id}")
        return
    
    status = data.get('status')
    
    # Check for plan change (from items)
    items = data.get('items') or []
    if items:
        price_id = items[0].get('price', {}).get('id')
        config = get_paddle_config()
        
        if price_id == config['price_basic']:
            new_plan = 'basic'
        elif price_id == config['price_pro']:
            new_plan = 'pro'
        else:
            new_plan = None
        
        if new_plan and new_plan != user.subscription_plan:
            old_plan = user.subscription_plan
            user.subscription_plan = new_plan
            current_app.logger.info(f"Plan changed for user {user.id}: {old_plan} -> {new_plan}")
    
    # Check if this is a renewal
    billing_cycle = data.get('current_billing_period') or {}
    if billing_cycle:
        period_start = billing_cycle.get('starts_at')
        if period_start:
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
    from app.models.user import User
    
    custom_data = data.get('custom_data') or {}
    user = None
    quantity = 0
    
    # Check if this is a top-up purchase via custom_data
    # custom_data.quantity contains the actual invoice credits (e.g., 30)
    if custom_data.get('type') == 'topup':
        user_id = custom_data.get('user_id')
        quantity = int(custom_data.get('quantity', 0))
        
        if user_id and quantity:
            user = User.query.get(int(user_id))
    
    # Also check items for top-up price if not found via custom_data
    if not user:
        items = data.get('items') or []
        config = get_paddle_config()
        
        for item in items:
            price_id = item.get('price', {}).get('id')
            item_quantity = item.get('quantity', 0)
            
            if price_id == config.get('price_topup') and item_quantity > 0:
                # Paddle quantity is in packs of 10, so multiply to get actual credits
                # e.g., 3 packs = 30 credits
                quantity = int(item_quantity) * 10
                # Find user by email
                customer = data.get('customer') or {}
                email = customer.get('email')
                
                if email:
                    user = User.query.filter_by(email=email).first()
                break
    
    # Add credits and send confirmation email
    if user and quantity > 0:
        user.add_bonus_invoices(quantity)
        db.session.commit()
        current_app.logger.info(f"Webhook: Added {quantity} top-up invoices to user {user.id}")
        
        # Send confirmation email
        try:
            from app.services.email_service import get_email_service
            email_service = get_email_service()
            
            base_url = os.getenv('APP_URL', 'https://gozappify.com')
            dashboard_url = f"{base_url}/dashboard"
            
            # Get total credits (bonus + remaining from plan)
            total_credits = user.invoices_remaining
            if total_credits == float('inf'):
                total_credits = 'Unlimited'
            
            email_service.send_topup_confirmation(user, quantity, total_credits, dashboard_url)
            current_app.logger.info(f"Top-up confirmation email sent to {user.email}")
        except Exception as e:
            current_app.logger.error(f"Failed to send top-up confirmation email: {str(e)}")


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

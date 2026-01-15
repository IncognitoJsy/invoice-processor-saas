"""Billing routes for Stripe subscription management"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app
from flask_login import login_required, current_user
from app.extensions import db
import stripe
import os

bp = Blueprint('billing', __name__, url_prefix='/billing')

def get_stripe():
    """Initialize Stripe with API key"""
    stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
    return stripe


@bp.route('/')
@login_required
def index():
    """Billing overview page"""
    return render_template('billing/index.html')


@bp.route('/subscribe/<plan>')
@login_required
def subscribe(plan):
    """Create Stripe checkout session for subscription"""
    s = get_stripe()
    
    price_ids = {
        'basic': os.getenv('STRIPE_BASIC_PRICE_ID'),
        'pro': os.getenv('STRIPE_PRO_PRICE_ID')
    }
    
    if plan not in price_ids:
        return jsonify({'error': 'Invalid plan'}), 400
    
    try:
        # Create or get Stripe customer
        if current_user.stripe_customer_id:
            customer_id = current_user.stripe_customer_id
        else:
            customer = s.Customer.create(
                email=current_user.email,
                name=f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.email,
                metadata={'user_id': current_user.id}
            )
            current_user.stripe_customer_id = customer.id
            db.session.commit()
            customer_id = customer.id
        
        # Create checkout session
        checkout_session = s.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': price_ids[plan],
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'billing/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'billing/',
            metadata={
                'user_id': current_user.id,
                'plan': plan
            }
        )
        
        return redirect(checkout_session.url)
        
    except Exception as e:
        current_app.logger.error(f"Stripe checkout error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/success')
@login_required
def success():
    """Handle successful subscription"""
    s = get_stripe()
    session_id = request.args.get('session_id')
    
    if session_id:
        try:
            session = s.checkout.Session.retrieve(session_id)
            subscription = s.Subscription.retrieve(session.subscription)
            
            # Determine plan from price
            basic_price = os.getenv('STRIPE_BASIC_PRICE_ID')
            pro_price = os.getenv('STRIPE_PRO_PRICE_ID')
            
            price_id = subscription['items']['data'][0]['price']['id']
            
            if price_id == basic_price:
                plan = 'basic'
            elif price_id == pro_price:
                plan = 'pro'
            else:
                plan = 'basic'
            
            # Update user
            current_user.subscription_plan = plan
            current_user.subscription_status = 'active'
            current_user.stripe_subscription_id = subscription.id
            current_user.trial_ends_at = None  # Clear trial
            db.session.commit()
            
            current_app.logger.info(f"User {current_user.id} subscribed to {plan}")
            
            # Send welcome email
            try:
                from app.services.email_service import get_email_service
                email_service = get_email_service()
                dashboard_url = request.host_url + 'dashboard'
                plan_name = 'Basic' if plan == 'basic' else 'Pro'
                email_service.send_welcome_paid(current_user, plan_name, dashboard_url)
                current_app.logger.info(f"Welcome email sent to {current_user.email}")
            except Exception as e:
                current_app.logger.error(f"Failed to send welcome email: {str(e)}")
            
        except Exception as e:
            current_app.logger.error(f"Error processing subscription success: {str(e)}")
    
    return render_template('billing/success.html')


@bp.route('/manage')
@login_required
def manage():
    """Redirect to Stripe customer portal for subscription management"""
    s = get_stripe()
    
    if not current_user.stripe_customer_id:
        return redirect(url_for('billing.index'))
    
    try:
        portal_session = s.billing_portal.Session.create(
            customer=current_user.stripe_customer_id,
            return_url=request.host_url + 'billing/',
        )
        return redirect(portal_session.url)
    except Exception as e:
        current_app.logger.error(f"Stripe portal error: {str(e)}")
        return redirect(url_for('billing.index'))


@bp.route('/cancel', methods=['POST'])
@login_required
def cancel():
    """Cancel subscription"""
    s = get_stripe()
    
    if not current_user.stripe_subscription_id:
        return jsonify({'error': 'No active subscription'}), 400
    
    try:
        # Cancel at period end (user keeps access until end of billing period)
        s.Subscription.modify(
            current_user.stripe_subscription_id,
            cancel_at_period_end=True
        )
        
        current_user.subscription_status = 'cancelled'
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Subscription will cancel at end of billing period'})
        
    except Exception as e:
        current_app.logger.error(f"Cancellation error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/webhook', methods=['POST'])
def webhook():
    """Handle Stripe webhooks"""
    s = get_stripe()
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
    
    try:
        if webhook_secret:
            event = s.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            event = s.Event.construct_from(request.get_json(), s.api_key)
    except Exception as e:
        current_app.logger.error(f"Webhook error: {str(e)}")
        return jsonify({'error': str(e)}), 400
    
    # Handle events
    event_type = event['type']
    data = event['data']['object']
    
    current_app.logger.info(f"Stripe webhook received: {event_type}")
    
    if event_type == 'checkout.session.completed':
        handle_checkout_completed(data)
    elif event_type == 'customer.subscription.updated':
        handle_subscription_updated(data)
    elif event_type == 'customer.subscription.deleted':
        handle_subscription_deleted(data)
    elif event_type == 'invoice.payment_failed':
        handle_payment_failed(data)
    elif event_type == 'invoice.payment_succeeded':
        handle_payment_succeeded(data)
    
    return jsonify({'received': True})


def handle_checkout_completed(session):
    """Handle checkout.session.completed webhook - send welcome email"""
    from app.models.user import User
    
    customer_id = session.get('customer')
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    
    if not user:
        current_app.logger.warning(f"No user found for customer {customer_id}")
        return
    
    # Get plan from metadata or subscription
    plan = session.get('metadata', {}).get('plan', 'basic')
    plan_name = 'Basic' if plan == 'basic' else 'Pro'
    
    # Send welcome email (webhook is more reliable than success page)
    try:
        from app.services.email_service import get_email_service
        email_service = get_email_service()
        
        # Build dashboard URL
        base_url = os.getenv('APP_URL', 'https://invoice-processor-saas-production.up.railway.app')
        dashboard_url = f"{base_url}/dashboard"
        
        email_service.send_welcome_paid(user, plan_name, dashboard_url)
        current_app.logger.info(f"Welcome email sent to {user.email} via webhook")
    except Exception as e:
        current_app.logger.error(f"Failed to send welcome email via webhook: {str(e)}")


def handle_subscription_updated(subscription):
    """Handle subscription update webhook"""
    from app.models.user import User
    
    customer_id = subscription.get('customer')
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    
    if not user:
        current_app.logger.warning(f"No user found for customer {customer_id}")
        return
    
    status = subscription.get('status')
    
    if status == 'active':
        user.subscription_status = 'active'
    elif status == 'past_due':
        user.subscription_status = 'past_due'
    elif status in ['canceled', 'unpaid']:
        user.subscription_status = 'cancelled'
        user.subscription_plan = 'cancelled'
    
    db.session.commit()
    current_app.logger.info(f"Updated user {user.id} subscription status to {status}")


def handle_subscription_deleted(subscription):
    """Handle subscription cancellation webhook"""
    from app.models.user import User
    
    customer_id = subscription.get('customer')
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    
    if user:
        user.subscription_plan = 'cancelled'
        user.subscription_status = 'cancelled'
        user.stripe_subscription_id = None
        db.session.commit()
        current_app.logger.info(f"Cancelled subscription for user {user.id}")


def handle_payment_failed(invoice):
    """Handle failed payment webhook"""
    from app.models.user import User
    
    customer_id = invoice.get('customer')
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    
    if user:
        user.subscription_status = 'past_due'
        db.session.commit()
        current_app.logger.info(f"Payment failed for user {user.id}")


def handle_payment_succeeded(invoice):
    """Handle successful payment webhook"""
    from app.models.user import User
    
    customer_id = invoice.get('customer')
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    
    if user and user.subscription_status == 'past_due':
        user.subscription_status = 'active'
        db.session.commit()
        current_app.logger.info(f"Payment succeeded for user {user.id}")


@bp.route('/api/status')
@login_required
def api_status():
    """Get current subscription status"""
    limit = current_user.monthly_invoice_limit
    used = current_user.get_invoices_this_month()
    
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
        'trial_active': current_user.is_trial_active,
        'trial_days_remaining': current_user.trial_days_remaining if current_user.subscription_plan == 'trial' else None
    })

"""Billing routes for PayPal subscription management"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.services.paypal_service import get_paypal_service
import os
from datetime import datetime

bp = Blueprint('billing', __name__, url_prefix='/billing')

TOPUP_PRICE_PER_INVOICE = 0.50
TOPUP_MIN_QUANTITY = 10
TOPUP_PRESETS = [10, 20, 30]


def get_paypal_config():
    return {
        'client_id': os.getenv('PAYPAL_CLIENT_ID'),
        'mode': os.getenv('PAYPAL_MODE', 'sandbox'),
        'plan_basic': os.getenv('PAYPAL_PLAN_BASIC'),
        'plan_pro': os.getenv('PAYPAL_PLAN_PRO'),
        'plan_ultimate': os.getenv('PAYPAL_PLAN_ULTIMATE'),
        'plan_basic_annual': os.getenv('PAYPAL_PLAN_BASIC_ANNUAL'),
        'plan_pro_annual': os.getenv('PAYPAL_PLAN_PRO_ANNUAL'),
        'plan_ultimate_annual': os.getenv('PAYPAL_PLAN_ULTIMATE_ANNUAL'),
        # Full platform plans
        'plan_full_starter': os.getenv('PAYPAL_PLAN_FULL_STARTER'),
        'plan_full_pro': os.getenv('PAYPAL_PLAN_FULL_PRO'),
        'plan_full_starter_annual': os.getenv('PAYPAL_PLAN_FULL_STARTER_ANNUAL'),
        'plan_full_pro_annual': os.getenv('PAYPAL_PLAN_FULL_PRO_ANNUAL'),
    }


@bp.route('/')
@login_required
def index():
    config = get_paypal_config()
    paypal = get_paypal_service()
    update_payment_url = paypal.get_update_payment_url()
    
    return render_template('billing/index.html',
                          paypal_client_id=config['client_id'],
                          paypal_mode=config['mode'],
                          update_payment_url=update_payment_url,
                          paypal_plan_full_starter=config['plan_full_starter'],
                          paypal_plan_full_pro=config['plan_full_pro'],
                          paypal_plan_full_starter_annual=config['plan_full_starter_annual'],
                          paypal_plan_full_pro_annual=config['plan_full_pro_annual'])


@bp.route('/topup')
@login_required
def topup():
    config = get_paypal_config()
    
    if current_user.subscription_plan == 'trial':
        return render_template('billing/topup.html', error="Top-ups are only available for paid subscribers.", can_purchase=False)
    
    if current_user.subscription_plan in ['pro', 'ultimate']:
        return render_template('billing/topup.html', error="You have unlimited invoices on your plan!", can_purchase=False)
    
    if current_user.subscription_plan == 'cancelled':
        return render_template('billing/topup.html', error="Please reactivate your subscription to purchase top-ups.", can_purchase=False)
    
    if current_user.subscription_status == 'suspended':
        return render_template('billing/topup.html', error="Please update your payment method before purchasing top-ups.", can_purchase=False)
    
    return render_template('billing/topup.html',
                         can_purchase=True,
                         price_per_invoice=TOPUP_PRICE_PER_INVOICE,
                         presets=TOPUP_PRESETS,
                         min_quantity=TOPUP_MIN_QUANTITY,
                         current_bonus=current_user.bonus_invoices or 0,
                         base_remaining=current_user.base_invoices_remaining,
                         total_remaining=current_user.invoices_remaining,
                         paypal_client_id=config['client_id'])


@bp.route('/subscribe/<plan>')
@login_required
def subscribe(plan):
    config = get_paypal_config()
    
    # Support annual plans: basic-annual, pro-annual, ultimate-annual
    frequency = 'annual' if plan.endswith('-annual') else 'monthly'
    base_plan = plan.replace('-annual', '')
    
    # Full platform plans are separate from sync plans
    if base_plan in ('full-starter', 'full-pro'):
        if frequency == 'annual':
            plan_ids = {
                'full-starter': config['plan_full_starter_annual'],
                'full-pro': config['plan_full_pro_annual'],
            }
        else:
            plan_ids = {
                'full-starter': config['plan_full_starter'],
                'full-pro': config['plan_full_pro'],
            }
    elif frequency == 'annual':
        plan_ids = {
            'basic': config['plan_basic_annual'],
            'pro': config['plan_pro_annual'],
            'ultimate': config['plan_ultimate_annual']
        }
    else:
        plan_ids = {
            'basic': config['plan_basic'],
            'pro': config['plan_pro'],
            'ultimate': config['plan_ultimate']
        }

    if base_plan not in plan_ids:
        return jsonify({'error': 'Invalid plan'}), 400
    
    plan_id = plan_ids[base_plan]
    if not plan_id:
        return jsonify({'error': 'Plan not configured'}), 500
    
    paypal = get_paypal_service()
    base_url = os.getenv('APP_URL', 'https://gozappify.com')
    
    result = paypal.create_subscription(
        plan_id=plan_id,
        user_id=current_user.id,
        return_url=f"{base_url}/billing/subscription/success?plan={base_plan}&frequency={frequency}",
        cancel_url=f"{base_url}/billing/subscription/cancel",
        custom_id=f"user_{current_user.id}_plan_{base_plan}_{frequency}"
    )
    
    if not result:
        return jsonify({'error': 'Failed to create subscription'}), 500
    
    approval_url = None
    for link in result.get('links', []):
        if link.get('rel') == 'approve':
            approval_url = link.get('href')
            break
    
    if not approval_url:
        return jsonify({'error': 'No approval URL returned'}), 500
    
    current_user.pending_subscription_id = result.get('id')
    db.session.commit()
    
    return redirect(approval_url)


@bp.route('/subscription/success')
@login_required
def subscription_success():
    subscription_id = request.args.get('subscription_id') or current_user.pending_subscription_id
    plan = request.args.get('plan', 'basic')
    frequency = request.args.get('frequency', 'monthly')
    
    if subscription_id:
        paypal = get_paypal_service()
        subscription = paypal.get_subscription(subscription_id)
        
        if subscription and subscription.get('status') == 'ACTIVE':
            current_user.paypal_subscription_id = subscription_id
            current_user.subscription_plan = plan
            current_user.billing_frequency = frequency
            current_user.subscription_status = 'active'
            current_user.subscription_started_at = datetime.utcnow()
            current_user.pending_subscription_id = None
            current_user.bonus_invoices = 0
            db.session.commit()
            current_app.logger.info(f"✅ Subscription activated: user {current_user.id} → {plan}")
            
            freq_label = 'Annual' if frequency == 'annual' else 'Monthly'
            current_app.logger.info(f"Subscription activated for user {current_user.id}: {plan} ({freq_label})")
            
            try:
                from app.services.email_service import get_email_service
                email_service = get_email_service()
                base_url = os.getenv('APP_URL', 'https://gozappify.com')
                plan_names = {
                    'basic': 'Basic', 'pro': 'Pro', 'ultimate': 'Ultimate',
                    'full-starter': 'Full Platform Starter', 'full-pro': 'Full Platform Pro'
                }
                plan_name = f"{plan_names.get(plan, 'Basic')} ({freq_label})"
                email_service.send_welcome_paid(current_user, plan_name, f"{base_url}/dashboard")
            except Exception as e:
                current_app.logger.error(f"Failed to send welcome email: {str(e)}")
    
    return render_template('billing/success.html')


@bp.route('/subscription/cancel')
@login_required
def subscription_cancel():
    current_user.pending_subscription_id = None
    db.session.commit()
    return redirect(url_for('billing.index'))


@bp.route('/success')
@login_required
def success():
    return render_template('billing/success.html')


@bp.route('/topup/success')
@login_required
def topup_success():
    quantity = request.args.get('quantity', 0, type=int)
    return render_template('billing/topup_success.html',
                         quantity=quantity,
                         total_bonus=current_user.bonus_invoices or 0,
                         total_remaining=current_user.invoices_remaining)


@bp.route('/manage')
@login_required
def manage():
    if not current_user.paypal_subscription_id:
        return redirect(url_for('billing.index'))
    
    paypal = get_paypal_service()
    update_payment_url = paypal.get_update_payment_url()
    
    return render_template('billing/manage.html', update_payment_url=update_payment_url)


@bp.route('/cancel', methods=['POST'])
@login_required
def cancel():
    if not current_user.paypal_subscription_id:
        flash('No active subscription found.', 'error')
        return redirect(url_for('billing.manage'))
    
    paypal = get_paypal_service()
    
    try:
        if paypal.cancel_subscription(current_user.paypal_subscription_id):
            current_user.subscription_status = 'cancelled'
            db.session.commit()
            flash('Your subscription has been cancelled successfully.', 'success')
            return redirect(url_for('billing.manage'))
        else:
            flash('Failed to cancel subscription. Please try again.', 'error')
            return redirect(url_for('billing.manage'))
    except Exception as e:
        current_app.logger.error(f"Cancellation error: {str(e)}")
        flash('An error occurred while cancelling. Please try again.', 'error')
        return redirect(url_for('billing.manage'))


@bp.route('/topup/create-order', methods=['POST'])
@login_required
def topup_create_order():
    if current_user.subscription_plan != 'basic':
        return jsonify({'error': 'Top-ups only available for Basic plan'}), 400
    
    if current_user.subscription_status == 'suspended':
        return jsonify({'error': 'Please update your payment method first'}), 400
    
    data = request.get_json() or {}
    quantity = data.get('quantity', 10)
    
    try:
        quantity = int(quantity)
    except:
        return jsonify({'error': 'Invalid quantity'}), 400
    
    if quantity < TOPUP_MIN_QUANTITY or quantity > 500 or quantity % 10 != 0:
        return jsonify({'error': 'Quantity must be 10-500 in multiples of 10'}), 400
    
    amount = quantity * TOPUP_PRICE_PER_INVOICE
    paypal = get_paypal_service()
    
    result = paypal.create_order(
        amount=amount,
        currency='GBP',
        description=f'{quantity} Invoice Credits',
        custom_id=f"topup_user_{current_user.id}_qty_{quantity}"
    )
    
    if not result:
        return jsonify({'error': 'Failed to create order'}), 500
    
    return jsonify({'success': True, 'order_id': result.get('id'), 'quantity': quantity, 'amount': amount})


@bp.route('/topup/capture-order', methods=['POST'])
@login_required
def topup_capture_order():
    data = request.get_json() or {}
    order_id = data.get('order_id')
    quantity = int(data.get('quantity', 0))
    
    if not order_id:
        return jsonify({'error': 'Missing order ID'}), 400
    
    paypal = get_paypal_service()
    result = paypal.capture_order(order_id)
    
    if not result:
        return jsonify({'error': 'Failed to capture payment'}), 500
    
    if result.get('status') == 'COMPLETED':
        current_user.add_bonus_invoices(quantity)
        db.session.commit()
        
        current_app.logger.info(f"Top-up completed: User {current_user.id}, quantity {quantity}")
        
        try:
            from app.services.email_service import get_email_service
            email_service = get_email_service()
            base_url = os.getenv('APP_URL', 'https://gozappify.com')
            total = current_user.invoices_remaining
            email_service.send_topup_confirmation(current_user, quantity, total if total != float('inf') else 'Unlimited', f"{base_url}/dashboard")
        except Exception as e:
            current_app.logger.error(f"Failed to send top-up email: {str(e)}")
        
        return jsonify({'success': True, 'quantity': quantity, 'new_balance': current_user.invoices_remaining})
    else:
        return jsonify({'error': f'Payment not completed: {result.get("status")}'}), 400


@bp.route('/webhook', methods=['POST'])
def webhook():
    # --- Webhook signature verification (mandatory, fails closed) ---
    # PayPal events are unauthenticated until verified against PayPal's
    # verify-webhook-signature API. Without this, anyone can POST a forged
    # event to grant a free plan or lock paying users out (AUDIT risk #2).
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({'error': 'Invalid payload'}), 400

    paypal = get_paypal_service()
    is_valid, error_msg = paypal.verify_webhook_signature(request.headers, body)
    if not is_valid:
        current_app.logger.warning(f"PayPal webhook signature verification failed: {error_msg}")
        return jsonify({'error': 'Unauthorized'}), 401

    event_type = body.get('event_type')
    resource = body.get('resource', {})

    current_app.logger.info(f"PayPal webhook: {event_type}")

    try:
        from app.models.user import User
        
        if event_type == 'BILLING.SUBSCRIPTION.ACTIVATED':
            subscription_id = resource.get('id')
            custom_id = resource.get('custom_id', '')
            
            user = None
            plan = 'basic'
            
            frequency = 'monthly'
            if custom_id and '_' in custom_id:
                parts = custom_id.split('_')
                if len(parts) >= 4:
                    try:
                        user = User.query.get(int(parts[1]))
                        plan = parts[3]
                    except:
                        pass
                if len(parts) >= 5:
                    frequency = parts[4]
            
            if not user:
                user = User.query.filter_by(pending_subscription_id=subscription_id).first()
            
            if user:
                user.paypal_subscription_id = subscription_id
                user.subscription_plan = plan
                user.billing_frequency = frequency
                user.subscription_status = 'active'
                user.subscription_started_at = datetime.utcnow()
                user.pending_subscription_id = None
                db.session.commit()
                current_app.logger.info(f"Subscription activated: user {user.id}, plan {plan}, frequency {frequency}")
        
        elif event_type == 'BILLING.SUBSCRIPTION.CANCELLED':
            subscription_id = resource.get('id')
            user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
            if user:
                user.subscription_plan = 'cancelled'
                user.subscription_status = 'cancelled'
                db.session.commit()
        
        elif event_type == 'BILLING.SUBSCRIPTION.SUSPENDED':
            subscription_id = resource.get('id')
            user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
            if user:
                user.subscription_status = 'suspended'
                db.session.commit()
        
        elif event_type == 'BILLING.SUBSCRIPTION.PAYMENT.FAILED':
            subscription_id = resource.get('id')
            user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
            if user:
                user.subscription_status = 'past_due'
                db.session.commit()
        
        elif event_type == 'PAYMENT.SALE.COMPLETED':
            billing_id = resource.get('billing_agreement_id')
            if billing_id:
                user = User.query.filter_by(paypal_subscription_id=billing_id).first()
                if user:
                    user.subscription_status = 'active'
                    user.renew_subscription()
                    db.session.commit()
        
        return jsonify({'success': True})
    
    except Exception as e:
        current_app.logger.error(f"Webhook error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/status')
@login_required
def api_status():
    limit = current_user.monthly_invoice_limit
    remaining = current_user.invoices_remaining
    
    return jsonify({
        'plan': current_user.subscription_plan,
        'plan_name': current_user.plan_display_name,
        'status': current_user.subscription_status,
        'can_upload': current_user.can_upload_invoice,
        'invoice_limit': limit if limit != float('inf') else 'unlimited',
        'invoices_remaining': remaining if remaining != float('inf') else 'unlimited',
        'bonus_invoices': current_user.bonus_invoices or 0,
        'payment_issue': current_user.subscription_status in ['suspended', 'past_due']
    })

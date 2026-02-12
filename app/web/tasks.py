"""Scheduled tasks endpoints - called by external cron service"""
from flask import Blueprint, jsonify, request, current_app
from datetime import datetime, timedelta
from app.extensions import db
import os

bp = Blueprint('tasks', __name__, url_prefix='/tasks')


def verify_cron_secret():
    """Verify the request has the correct cron secret"""
    cron_secret = os.getenv('CRON_SECRET')
    if not cron_secret:
        return True  # No secret configured, allow request
    
    provided_secret = request.headers.get('X-Cron-Secret') or request.args.get('secret')
    return provided_secret == cron_secret


@bp.route('/trial-reminders', methods=['GET', 'POST'])
def send_trial_reminders():
    """Send reminder emails to users whose trial ends tomorrow"""
    
    # Verify request is authorized
    if not verify_cron_secret():
        return jsonify({'error': 'Unauthorized'}), 401
    
    from app.models.user import User
    from app.services.email_service import get_email_service
    
    try:
        email_service = get_email_service()
        
        # Find users whose trial ends tomorrow (between 24-48 hours from now)
        tomorrow_start = datetime.utcnow() + timedelta(hours=24)
        tomorrow_end = datetime.utcnow() + timedelta(hours=48)
        
        users_to_notify = User.query.filter(
            User.subscription_plan == 'trial',
            User.trial_ends_at >= tomorrow_start,
            User.trial_ends_at < tomorrow_end,
            User.trial_reminder_sent == False,
            User.is_active == True
        ).all()
        
        sent_count = 0
        failed_count = 0
        
        base_url = os.getenv('APP_URL', 'https://invoice-processor-saas-production.up.railway.app')
        billing_url = f"{base_url}/billing"
        
        for user in users_to_notify:
            try:
                result = email_service.send_trial_ending(user, billing_url)
                
                if result.get('success'):
                    user.trial_reminder_sent = True
                    sent_count += 1
                    current_app.logger.info(f"Trial reminder sent to {user.email}")
                else:
                    failed_count += 1
                    current_app.logger.error(f"Failed to send trial reminder to {user.email}: {result.get('error')}")
                    
            except Exception as e:
                failed_count += 1
                current_app.logger.error(f"Error sending trial reminder to {user.email}: {str(e)}")
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Trial reminders processed',
            'sent': sent_count,
            'failed': failed_count,
            'total_checked': len(users_to_notify)
        })
        
    except Exception as e:
        current_app.logger.error(f"Trial reminder task error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/expired-trials', methods=['GET', 'POST'])
def handle_expired_trials():
    """Handle expired trials - send notification and update status"""
    
    # Verify request is authorized
    if not verify_cron_secret():
        return jsonify({'error': 'Unauthorized'}), 401
    
    from app.models.user import User
    from app.services.email_service import get_email_service
    
    try:
        email_service = get_email_service()
        
        # Find users whose trial has expired
        now = datetime.utcnow()
        
        expired_users = User.query.filter(
            User.subscription_plan == 'trial',
            User.trial_ends_at < now,
            User.is_active == True
        ).all()
        
        processed_count = 0
        
        base_url = os.getenv('APP_URL', 'https://invoice-processor-saas-production.up.railway.app')
        billing_url = f"{base_url}/billing"
        
        for user in expired_users:
            try:
                # Send expired notification
                email_service.send_trial_expired(user, billing_url)
                
                # Update user plan
                user.subscription_plan = 'cancelled'
                user.subscription_status = 'cancelled'
                
                processed_count += 1
                current_app.logger.info(f"Processed expired trial for {user.email}")
                
            except Exception as e:
                current_app.logger.error(f"Error processing expired trial for {user.email}: {str(e)}")
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Expired trials processed',
            'processed': processed_count
        })
        
    except Exception as e:
        current_app.logger.error(f"Expired trials task error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/health', methods=['GET'])
def health():
    """Health check for cron service"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat()
    })

@bp.route('/fetch-emails', methods=['POST'])
def fetch_emails_task():
    """Cron endpoint to fetch emails for all active users"""
    from app.services.email_fetcher import fetch_all_users
    
    # Verify cron secret
    secret = request.headers.get('X-Cron-Secret') or request.args.get('secret')
    expected = os.environ.get('CRON_SECRET', '')
    if not expected or secret != expected:
        return jsonify({'error': 'Unauthorized'}), 401
    
    results = fetch_all_users()
    return jsonify({'success': True, 'results': {str(k): v for k, v in results.items()}})    

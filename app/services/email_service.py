"""Email service using Resend for transactional emails"""
import os
import resend
from flask import current_app, url_for, render_template_string
from datetime import datetime

# Logo URL - hosted on the app
LOGO_URL = "https://gozappify.com/static/images/gozappify-logo-email.png"

# Email templates
TEMPLATES = {
    'verify_email': {
        'subject': 'Verify your GoZappify email',
        'html': '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f3f4f6; margin: 0; padding: 40px 20px;">
    <div style="max-width: 500px; margin: 0 auto; background: #1f2937; border-radius: 16px; overflow: hidden;">
        <div style="padding: 40px; text-align: center; background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);">
            <img src="''' + LOGO_URL + '''" alt="GoZappify" style="height: 50px; width: auto;" />
        </div>
        <div style="padding: 40px; color: #e5e7eb;">
            <h2 style="color: white; margin: 0 0 20px;">Verify your email</h2>
            <p style="margin: 0 0 30px; line-height: 1.6;">
                Hi {{first_name}},<br><br>
                Welcome to GoZappify! Please verify your email address to get started.
            </p>
            <a href="{{verify_url}}" style="display: inline-block; background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%); color: white; text-decoration: none; padding: 16px 32px; border-radius: 12px; font-weight: 600;">
                Verify Email
            </a>
            <p style="margin: 30px 0 0; font-size: 14px; color: #9ca3af;">
                Or copy this link: {{verify_url}}
            </p>
            <p style="margin: 20px 0 0; font-size: 14px; color: #9ca3af;">
                This link expires in 24 hours.
            </p>
        </div>
    </div>
</body>
</html>
'''
    },
    
    'forgot_password': {
        'subject': 'Reset your GoZappify password',
        'html': '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f3f4f6; margin: 0; padding: 40px 20px;">
    <div style="max-width: 500px; margin: 0 auto; background: #1f2937; border-radius: 16px; overflow: hidden;">
        <div style="padding: 40px; text-align: center; background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);">
            <img src="''' + LOGO_URL + '''" alt="GoZappify" style="height: 50px; width: auto;" />
        </div>
        <div style="padding: 40px; color: #e5e7eb;">
            <h2 style="color: white; margin: 0 0 20px;">Reset your password</h2>
            <p style="margin: 0 0 30px; line-height: 1.6;">
                Hi {{first_name}},<br><br>
                We received a request to reset your password. Click the button below to create a new password.
            </p>
            <a href="{{reset_url}}" style="display: inline-block; background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%); color: white; text-decoration: none; padding: 16px 32px; border-radius: 12px; font-weight: 600;">
                Reset Password
            </a>
            <p style="margin: 30px 0 0; font-size: 14px; color: #9ca3af;">
                Or copy this link: {{reset_url}}
            </p>
            <p style="margin: 20px 0 0; font-size: 14px; color: #9ca3af;">
                This link expires in 1 hour. If you didn't request this, you can safely ignore this email.
            </p>
        </div>
    </div>
</body>
</html>
'''
    },
    
    'password_changed': {
        'subject': 'Your GoZappify password was changed',
        'html': '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f3f4f6; margin: 0; padding: 40px 20px;">
    <div style="max-width: 500px; margin: 0 auto; background: #1f2937; border-radius: 16px; overflow: hidden;">
        <div style="padding: 40px; text-align: center; background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);">
            <img src="''' + LOGO_URL + '''" alt="GoZappify" style="height: 50px; width: auto;" />
        </div>
        <div style="padding: 40px; color: #e5e7eb;">
            <h2 style="color: white; margin: 0 0 20px;">Password changed</h2>
            <p style="margin: 0 0 20px; line-height: 1.6;">
                Hi {{first_name}},<br><br>
                Your GoZappify password was successfully changed on {{changed_at}}.
            </p>
            <p style="margin: 0; line-height: 1.6; color: #fbbf24;">
                ⚠️ If you didn't make this change, please contact us immediately at support@gozappify.com
            </p>
        </div>
    </div>
</body>
</html>
'''
    },
    
    'welcome_paid': {
        'subject': 'Welcome to GoZappify {{plan}}! 🎉',
        'html': '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f3f4f6; margin: 0; padding: 40px 20px;">
    <div style="max-width: 500px; margin: 0 auto; background: #1f2937; border-radius: 16px; overflow: hidden;">
        <div style="padding: 40px; text-align: center; background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);">
            <img src="''' + LOGO_URL + '''" alt="GoZappify" style="height: 50px; width: auto;" />
        </div>
        <div style="padding: 40px; color: #e5e7eb;">
            <h2 style="color: white; margin: 0 0 20px;">Welcome to {{plan}}! 🎉</h2>
            <p style="margin: 0 0 30px; line-height: 1.6;">
                Hi {{first_name}},<br><br>
                Thank you for subscribing to GoZappify {{plan}}! Your account is now fully activated.
            </p>
            <div style="background: #374151; border-radius: 12px; padding: 20px; margin-bottom: 30px;">
                <p style="margin: 0 0 10px; color: #9ca3af; font-size: 14px;">Your plan includes:</p>
                <ul style="margin: 0; padding-left: 20px; color: #e5e7eb;">
                    {{plan_features}}
                </ul>
            </div>
            <a href="{{dashboard_url}}" style="display: inline-block; background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%); color: white; text-decoration: none; padding: 16px 32px; border-radius: 12px; font-weight: 600;">
                Go to Dashboard
            </a>
        </div>
    </div>
</body>
</html>
'''
    },
    
    'trial_ending': {
        'subject': 'Your GoZappify trial ends tomorrow',
        'html': '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f3f4f6; margin: 0; padding: 40px 20px;">
    <div style="max-width: 500px; margin: 0 auto; background: #1f2937; border-radius: 16px; overflow: hidden;">
        <div style="padding: 40px; text-align: center; background: linear-gradient(135deg, #f59e0b 0%, #ef4444 100%);">
            <img src="''' + LOGO_URL + '''" alt="GoZappify" style="height: 50px; width: auto;" />
        </div>
        <div style="padding: 40px; color: #e5e7eb;">
            <h2 style="color: white; margin: 0 0 20px;">Your trial ends tomorrow ⏰</h2>
            <p style="margin: 0 0 30px; line-height: 1.6;">
                Hi {{first_name}},<br><br>
                Your 7-day free trial of GoZappify ends tomorrow. To keep using all features, upgrade to a paid plan.
            </p>
            <div style="background: #374151; border-radius: 12px; padding: 20px; margin-bottom: 30px;">
                <div style="margin-bottom: 15px;">
                    <p style="margin: 0; color: white; font-weight: 600;">Basic - £39/month</p>
                    <p style="margin: 5px 0 0; color: #9ca3af; font-size: 14px;">100 invoices/month</p>
                </div>
                <div>
                    <p style="margin: 0; color: white; font-weight: 600;">Pro - £79/month</p>
                    <p style="margin: 5px 0 0; color: #9ca3af; font-size: 14px;">Unlimited invoices</p>
                </div>
            </div>
            <a href="{{billing_url}}" style="display: inline-block; background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%); color: white; text-decoration: none; padding: 16px 32px; border-radius: 12px; font-weight: 600;">
                Upgrade Now
            </a>
            <p style="margin: 30px 0 0; font-size: 14px; color: #9ca3af;">
                Questions? Email us at support@gozappify.com - we're here to help!
            </p>
        </div>
    </div>
</body>
</html>
'''
    },
    
    'trial_expired': {
        'subject': 'Your GoZappify trial has ended',
        'html': '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f3f4f6; margin: 0; padding: 40px 20px;">
    <div style="max-width: 500px; margin: 0 auto; background: #1f2937; border-radius: 16px; overflow: hidden;">
        <div style="padding: 40px; text-align: center; background: linear-gradient(135deg, #6b7280 0%, #374151 100%);">
            <img src="''' + LOGO_URL + '''" alt="GoZappify" style="height: 50px; width: auto;" />
        </div>
        <div style="padding: 40px; color: #e5e7eb;">
            <h2 style="color: white; margin: 0 0 20px;">Your trial has ended</h2>
            <p style="margin: 0 0 30px; line-height: 1.6;">
                Hi {{first_name}},<br><br>
                Your free trial has expired, but your data is safe. Upgrade anytime to pick up where you left off.
            </p>
            <a href="{{billing_url}}" style="display: inline-block; background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%); color: white; text-decoration: none; padding: 16px 32px; border-radius: 12px; font-weight: 600;">
                Reactivate Account
            </a>
            <p style="margin: 30px 0 0; font-size: 14px; color: #9ca3af;">
                Questions? Email us at support@gozappify.com
            </p>
        </div>
    </div>
</body>
</html>
'''
    }
}


class EmailService:
    """Email service using Resend"""
    
    def __init__(self):
        self.api_key = os.getenv('RESEND_API_KEY')
        self.from_email = os.getenv('MAIL_FROM', 'GoZappify <noreply@gozappify.com>')
        
        if self.api_key:
            resend.api_key = self.api_key
    
    def _render_template(self, template_name: str, **kwargs) -> dict:
        """Render an email template with variables"""
        template = TEMPLATES.get(template_name)
        if not template:
            raise ValueError(f"Unknown template: {template_name}")
        
        subject = template['subject']
        html = template['html']
        
        # Replace variables
        for key, value in kwargs.items():
            subject = subject.replace('{{' + key + '}}', str(value))
            html = html.replace('{{' + key + '}}', str(value))
        
        return {'subject': subject, 'html': html}
    
    def send_email(self, to: str, template_name: str, **kwargs) -> dict:
        """Send an email using a template"""
        if not self.api_key:
            current_app.logger.warning("RESEND_API_KEY not set - email not sent")
            return {'success': False, 'error': 'Email not configured'}
        
        try:
            rendered = self._render_template(template_name, **kwargs)
            
            result = resend.Emails.send({
                "from": self.from_email,
                "to": [to],
                "subject": rendered['subject'],
                "html": rendered['html']
            })
            
            current_app.logger.info(f"Email sent: {template_name} to {to}")
            return {'success': True, 'id': result.get('id')}
            
        except Exception as e:
            current_app.logger.error(f"Email error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    # Convenience methods
    def send_verification_email(self, user, verify_url: str):
        """Send email verification"""
        return self.send_email(
            to=user.email,
            template_name='verify_email',
            first_name=user.first_name or 'there',
            verify_url=verify_url
        )
    
    def send_password_reset(self, user, reset_url: str):
        """Send password reset email"""
        return self.send_email(
            to=user.email,
            template_name='forgot_password',
            first_name=user.first_name or 'there',
            reset_url=reset_url
        )
    
    def send_password_changed(self, user):
        """Send password changed confirmation"""
        return self.send_email(
            to=user.email,
            template_name='password_changed',
            first_name=user.first_name or 'there',
            changed_at=datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')
        )
    
    def send_welcome_paid(self, user, plan: str, dashboard_url: str):
        """Send welcome email after paid signup"""
        features = {
            'Basic': '<li>100 invoices per month</li><li>QuickBooks integration</li><li>Email support</li>',
            'Pro': '<li>Unlimited invoices</li><li>QuickBooks integration</li><li>Priority support</li><li>API access</li>'
        }
        
        return self.send_email(
            to=user.email,
            template_name='welcome_paid',
            first_name=user.first_name or 'there',
            plan=plan,
            plan_features=features.get(plan, ''),
            dashboard_url=dashboard_url
        )
    
    def send_trial_ending(self, user, billing_url: str):
        """Send trial ending reminder"""
        return self.send_email(
            to=user.email,
            template_name='trial_ending',
            first_name=user.first_name or 'there',
            billing_url=billing_url
        )
    
    def send_trial_expired(self, user, billing_url: str):
        """Send trial expired notification"""
        return self.send_email(
            to=user.email,
            template_name='trial_expired',
            first_name=user.first_name or 'there',
            billing_url=billing_url
        )


# Singleton instance
_email_service = None

def get_email_service() -> EmailService:
    """Get or create email service instance"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service

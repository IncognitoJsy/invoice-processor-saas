"""Password Reset Token model"""
from app.extensions import db
from datetime import datetime, timedelta
import secrets


class PasswordResetToken(db.Model):
    """Token for password reset requests"""
    __tablename__ = 'password_reset_tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref=db.backref('reset_tokens', lazy='dynamic'))
    
    @classmethod
    def create_token(cls, user):
        """Create a new reset token for a user"""
        # Invalidate any existing tokens
        cls.query.filter_by(user_id=user.id, used=False).update({'used': True})
        
        token = cls(
            user_id=user.id,
            token=secrets.token_urlsafe(32),
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        db.session.add(token)
        db.session.commit()
        
        return token
    
    @classmethod
    def get_valid_token(cls, token_string):
        """Get a valid (not expired, not used) token"""
        token = cls.query.filter_by(token=token_string, used=False).first()
        
        if token and token.expires_at > datetime.utcnow():
            return token
        return None
    
    def mark_used(self):
        """Mark token as used"""
        self.used = True
        db.session.commit()

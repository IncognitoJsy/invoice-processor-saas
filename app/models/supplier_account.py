"""Supplier account number tracking for anti-abuse detection"""
from app.extensions import db
from datetime import datetime


class SupplierAccount(db.Model):
    __tablename__ = 'supplier_account'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    supplier_name = db.Column(db.String(255), nullable=False)
    account_number = db.Column(db.String(100), nullable=False, index=True)
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    invoice_count = db.Column(db.Integer, default=1)

    @staticmethod
    def check_account(supplier_name, account_number, user_id):
        """Check if supplier account is already used by another user"""
        if not account_number or len(account_number.strip()) < 3:
            return {'allowed': True, 'reason': 'no_account_number'}

        account_number = account_number.strip().upper()

        existing = SupplierAccount.query.filter(
            SupplierAccount.account_number == account_number,
            SupplierAccount.user_id != user_id
        ).first()

        if existing:
            return {
                'allowed': False,
                'reason': 'account_exists',
                'registered_email': existing.email[:3] + '***' + existing.email[existing.email.find('@'):],
                'supplier': existing.supplier_name,
            }
        return {'allowed': True, 'reason': 'new_account'}

    @staticmethod
    def register_account(supplier_name, account_number, user_id):
        """Record or update a supplier account number against a user"""
        if not account_number or len(account_number.strip()) < 3:
            return None

        account_number = account_number.strip().upper()

        from app.models.user import User
        user = User.query.get(user_id)
        email = user.email if user else 'unknown'

        existing = SupplierAccount.query.filter_by(
            user_id=user_id,
            account_number=account_number
        ).first()

        if existing:
            existing.last_seen_at = datetime.utcnow()
            existing.invoice_count = (existing.invoice_count or 0) + 1
        else:
            new = SupplierAccount(
                user_id=user_id,
                email=email,
                supplier_name=supplier_name or 'Unknown',
                account_number=account_number,
            )
            db.session.add(new)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()

        return existing or new

    # Keep backward compat
    @staticmethod
    def check_abuse(account_number, user_id, user_email):
        return SupplierAccount.check_account(None, account_number, user_id)

    @staticmethod
    def record(user_id, user_email, supplier_name, account_number):
        return SupplierAccount.register_account(supplier_name, account_number, user_id)

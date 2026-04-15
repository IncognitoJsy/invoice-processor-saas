"""Employee and Labour Entry models - full platform only"""
from app.extensions import db
from datetime import datetime


class Employee(db.Model):
    __tablename__ = 'employee'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(100))
    mobile = db.Column(db.String(50))
    email = db.Column(db.String(255))
    pay_rate = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    charge_out_rate = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    labour_entries = db.relationship('LabourEntry', backref='employee', lazy='dynamic')

    @property
    def true_hourly_cost(self):
        """Pay rate + employer contribution"""
        from flask_login import current_user
        from app.models.user import User
        user = User.query.get(self.user_id)
        rate = float(user.employer_contribution_rate or 6.5) if user else 6.5
        return float(self.pay_rate or 0) * (1 + rate / 100)

    @property
    def hourly_profit(self):
        return float(self.charge_out_rate or 0) - self.true_hourly_cost

    @property
    def profit_margin_pct(self):
        if not self.charge_out_rate or float(self.charge_out_rate) == 0:
            return 0
        return (self.hourly_profit / float(self.charge_out_rate)) * 100

    @property
    def display_name(self):
        if self.role:
            return f"{self.name} ({self.role})"
        return self.name

    def to_dict(self, contribution_rate=6.5):
        true_cost = float(self.pay_rate or 0) * (1 + contribution_rate / 100)
        profit = float(self.charge_out_rate or 0) - true_cost
        margin = (profit / float(self.charge_out_rate)) * 100 if float(self.charge_out_rate or 0) > 0 else 0
        return {
            'id': self.id,
            'name': self.name,
            'role': self.role,
            'mobile': self.mobile,
            'email': self.email,
            'pay_rate': float(self.pay_rate or 0),
            'charge_out_rate': float(self.charge_out_rate or 0),
            'true_hourly_cost': round(true_cost, 2),
            'hourly_profit': round(profit, 2),
            'profit_margin_pct': round(margin, 1),
            'is_active': self.is_active,
            'display_name': self.display_name,
        }


class LabourEntry(db.Model):
    __tablename__ = 'labour_entry'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False, index=True)
    job_card_id = db.Column(db.Integer, db.ForeignKey('job_card.id'), nullable=True, index=True)
    customer_invoice_id = db.Column(db.Integer, db.ForeignKey('customer_invoice.id'), nullable=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True, index=True)
    hours = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    charge_out_rate = db.Column(db.Numeric(10, 2), nullable=False)
    pay_rate = db.Column(db.Numeric(10, 2), nullable=False)
    employer_contribution_rate = db.Column(db.Numeric(5, 2), nullable=False, default=6.5)
    date_worked = db.Column(db.Date, nullable=True)
    time_worked = db.Column(db.Time, nullable=True)  # Time of day hours were logged
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='logged', index=True)  # logged, invoiced, void
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def charge_total(self):
        return float(self.hours or 0) * float(self.charge_out_rate or 0)

    @property
    def true_cost_per_hour(self):
        return float(self.pay_rate or 0) * (1 + float(self.employer_contribution_rate or 6.5) / 100)

    @property
    def cost_total(self):
        return float(self.hours or 0) * self.true_cost_per_hour

    @property
    def profit_total(self):
        return self.charge_total - self.cost_total

    def to_dict(self):
        emp = self.employee
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': emp.name if emp else '',
            'employee_role': emp.role if emp else '',
            'display_name': emp.display_name if emp else '',
            'hours': float(self.hours or 0),
            'charge_out_rate': float(self.charge_out_rate or 0),
            'pay_rate': float(self.pay_rate or 0),
            'employer_contribution_rate': float(self.employer_contribution_rate or 6.5),
            'charge_total': round(self.charge_total, 2),
            'cost_total': round(self.cost_total, 2),
            'profit_total': round(self.profit_total, 2),
            'date_worked': self.date_worked.strftime('%Y-%m-%d') if self.date_worked else None,
            'time_worked': self.time_worked.strftime('%H:%M') if self.time_worked else None,
            'datetime_worked': (self.date_worked.strftime('%Y-%m-%d') + 'T' + (self.time_worked.strftime('%H:%M') if self.time_worked else '09:00')) if self.date_worked else None,
            'description': self.description,
            'status': self.status,
            'job_card_id': self.job_card_id,
            'customer_id': self.customer_id,
        }

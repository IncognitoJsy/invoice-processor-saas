"""Customer model for full platform mode"""
from app.extensions import db
from datetime import datetime


class Customer(db.Model):
    __tablename__ = 'customer'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    company_name = db.Column(db.String(255))
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
    address_line1 = db.Column(db.String(255))
    address_line2 = db.Column(db.String(255))
    city = db.Column(db.String(100))
    postcode = db.Column(db.String(20))
    country = db.Column(db.String(50))
    notes = db.Column(db.Text)
    payment_terms = db.Column(db.String(20), default='30')

    # Sync-mode link to the accounting-software customer this local row materialises (lazy: a sync
    # user has no local customers until a job needs one). Keyed on the SAME id the sync/cache use —
    # QB Customer.Id / Xero ContactID — so a rename in QBO/Xero updates THIS row (no duplicate /
    # mislink). NULL for full-suite-native customers (they have no external counterpart).
    external_id = db.Column(db.String(200), nullable=True)   # QB Customer.Id / Xero ContactID
    source = db.Column(db.String(20), nullable=True)         # 'quickbooks' | 'xero' | NULL (local)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    jobs = db.relationship('Job', backref='customer', lazy='dynamic')
    documents = db.relationship('CustomerDocument', backref='customer', lazy='dynamic')

    __table_args__ = (
        # One local row per (user, provider, external id). NULLs are distinct in Postgres, so
        # full-suite-native customers (external_id NULL) never collide — the constraint only binds
        # materialised sync customers, guaranteeing find-or-create can't create duplicates.
        db.Index('uq_customer_user_source_ext', 'user_id', 'source', 'external_id', unique=True),
    )

    @property
    def display_name(self):
        # Guard against literal string 'None' being stored
        company = self.company_name if self.company_name and self.company_name.strip().lower() != 'none' else None
        name = self.name if self.name and self.name.strip().lower() != 'none' else None
        return company or name or self.email or 'Unknown'

    @property
    def full_address(self):
        parts = [p for p in [self.address_line1, self.address_line2, self.city, self.postcode, self.country] if p]
        return ', '.join(parts)

    def __repr__(self):
        return f'<Customer {self.id}: {self.name}>'


class Job(db.Model):
    __tablename__ = 'job'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    job_number = db.Column(db.String(50))
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    address = db.Column(db.Text)
    status = db.Column(db.String(30), default='quoted')
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    STATUS_LABELS = {
        'quoted': 'Quoted',
        'accepted': 'Accepted',
        'in_progress': 'In Progress',
        'complete': 'Complete',
        'invoiced': 'Invoiced',
        'paid': 'Paid',
        'cancelled': 'Cancelled',
    }

    STATUS_COLOURS = {
        'quoted': 'blue',
        'accepted': 'purple',
        'in_progress': 'amber',
        'complete': 'green',
        'invoiced': 'indigo',
        'paid': 'emerald',
        'cancelled': 'gray',
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_colour(self):
        return self.STATUS_COLOURS.get(self.status, 'gray')

    def __repr__(self):
        return f'<Job {self.id}: {self.title}>'


class CustomerDocument(db.Model):
    __tablename__ = 'customer_document'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=True)
    doc_type = db.Column(db.String(50))
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255))
    storage_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer)
    doc_date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<CustomerDocument {self.id}: {self.filename}>'

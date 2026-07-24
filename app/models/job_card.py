"""Job Card model - links customers, supplier invoices, customer invoices and quotes.

Also holds the JobSnapshot model (co-located so importing JobCard registers both in db.metadata for
create_all / schema_guard). A JobSnapshot FREEZES a completed job's financials + metadata so the
later comparable-job pricing-reference tool reads a stable historical record, never live @propertys
that would silently drift as prices/pay-rates change.
"""
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB

from app.extensions import db

# JSONB on Postgres (matches prod — risk #10 reconciliation), plain JSON on SQLite (tests).
_JSONB = db.JSON().with_variant(JSONB, 'postgresql')


class JobCard(db.Model):
    __tablename__ = 'job_card'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='new')
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('customer_quote.id'), nullable=True)

    # --- Phase 1 job metadata (comparability axis for the pricing-reference lookup) ---
    job_type = db.Column(db.String(50), nullable=True)          # key from JOB_TYPES; the axis of comparability
    scope_notes = db.Column(db.Text, nullable=True)             # free-text nuance (esp. for job_type 'other')
    room_count = db.Column(db.Integer, nullable=True)
    room_types = db.Column(_JSONB, nullable=True)               # JSON array of room-type strings
    floor_area_sqm = db.Column(db.Numeric(10, 2), nullable=True)   # canonical m² (convert sq ft on input)
    floor_area_unit_pref = db.Column(db.String(8), nullable=True, server_default='sqm')  # display pref: 'sqm'|'sqft'

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship('Customer', backref='job_cards', lazy='select')
    # Pin to quote_id: customer_quote.job_card_id (adopted from prod, risk #10) adds a 2nd FK path.
    quote = db.relationship('CustomerQuote', backref='job_card', lazy='select', foreign_keys=[quote_id])
    snapshots = db.relationship('JobSnapshot', backref='job_card', lazy='dynamic',
                                cascade='all, delete-orphan')

    STATUSES = {
        'new': 'New',
        'in_progress': 'In Progress',
        'complete': 'Complete',
        'invoiced': 'Invoiced',
        'paid': 'Paid',
    }

    # Job type / scope — the comparability axis. Keys are stored & compared (append-friendly; renaming
    # a KEY later needs a data migration, a LABEL does not). 'other' pairs with free-text scope_notes.
    JOB_TYPES = {
        'new_build_first_fix': 'New build – first fix',
        'new_build_second_fix': 'New build – second fix',
        'rewire_full': 'Full rewire',
        'rewire_partial': 'Partial rewire',
        'extension': 'Extension',
        'renovation': 'Renovation / refurb',
        'consumer_unit_swap': 'Consumer unit swap',
        'supply_upgrade': 'Supply upgrade',
        'additional_circuit': 'Additional circuit',
        'kitchen': 'Kitchen',
        'bathroom': 'Bathroom',
        'heating_underfloor': 'Heating / underfloor heating',
        'lighting': 'Lighting',
        'sockets': 'Sockets / outlets',
        'ev_charger': 'EV charger',
        'solar_battery': 'Solar / battery',
        'eicr_testing': 'EICR / testing',
        'remedial': 'Remedial works',
        'fault_finding': 'Fault finding',
        'commercial_fitout': 'Commercial fit-out',
        'fire_emergency': 'Fire alarm / emergency lighting',
        'outdoor': 'Outdoor',
        'other': 'Other',
    }

    @property
    def status_label(self):
        return self.STATUSES.get(self.status, self.status.title())

    @property
    def job_type_label(self):
        return self.JOB_TYPES.get(self.job_type) if self.job_type else None

    @property
    def latest_snapshot(self):
        """Newest frozen snapshot (highest version), or None. The pricing-reference tool reads THIS,
        never the live @propertys below (which drift)."""
        from app.models.job_card import JobSnapshot  # self-module; avoids ordering issues
        return self.snapshots.order_by(JobSnapshot.snapshot_version.desc()).first()

    @property
    def supplier_invoices(self):
        from app.models.invoice import Invoice
        return Invoice.query.filter_by(job_card_id=self.id).all()

    @property
    def customer_invoices(self):
        from app.models.customer_invoice import CustomerInvoice
        return CustomerInvoice.query.filter_by(job_card_id=self.id).all()

    @property
    def total_materials(self):
        return sum(float(i.total_cost or 0) for i in self.supplier_invoices)

    @property
    def total_invoiced(self):
        return sum(float(i.total or 0) for i in self.customer_invoices if i.status != 'void')

    @property
    def total_paid(self):
        return sum(float(i.total or 0) for i in self.customer_invoices if i.status == 'paid')

    @property
    def profit(self):
        return self.total_invoiced - self.total_materials

    @property
    def quote_total(self):
        return float(self.quote.total) if self.quote and self.quote.total else 0


class JobSnapshot(db.Model):
    """A FROZEN financial + metadata snapshot of a job at completion.

    Written by the /jobs update-status route when a job is marked 'complete' (see
    app/services/job_financials.compute_job_financials, the single source of truth). Append-only /
    versioned: re-opening a completed job preserves its snapshot(s); re-completing writes a NEW row
    with snapshot_version + 1 (latest wins). The comparable-job lookup reads the latest snapshot so a
    later price change or employee pay-rise can NEVER retroactively rewrite a historical job's profit.

    Money is stored 2dp Numeric. `labour_breakdown` freezes per-employee detail (hours + the pay/
    charge/employer-contribution rates USED at that time), so the record survives even if the
    underlying labour_entry rows are later edited or deleted. Metadata (job_type/rooms/area) is copied
    in too, so the snapshot is self-contained for comparison independent of later edits to the job.
    """
    __tablename__ = 'job_snapshot'

    id = db.Column(db.Integer, primary_key=True)
    job_card_id = db.Column(db.Integer, db.ForeignKey('job_card.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    snapshot_version = db.Column(db.Integer, nullable=False, server_default='1')
    frozen_at = db.Column(db.DateTime, default=datetime.utcnow)
    status_at_freeze = db.Column(db.String(20), nullable=True)

    # Frozen financials (2dp). materials_sold = Σ selling_price×qty (mode-agnostic — no CustomerInvoice
    # dependency); labour_* from labour_entry's own snapshotted rates.
    materials_cost = db.Column(db.Numeric(10, 2))
    materials_sold = db.Column(db.Numeric(10, 2))
    materials_profit = db.Column(db.Numeric(10, 2))
    labour_hours = db.Column(db.Numeric(10, 2))
    labour_cost = db.Column(db.Numeric(10, 2))
    labour_charged = db.Column(db.Numeric(10, 2))
    labour_profit = db.Column(db.Numeric(10, 2))
    direct_costs_total = db.Column(db.Numeric(10, 2), nullable=False, server_default='0')  # Phase 2 hook
    overall_profit = db.Column(db.Numeric(10, 2))  # materials_profit + labour_profit − direct_costs_total
    labour_breakdown = db.Column(_JSONB, nullable=True)  # per-employee frozen detail

    # Frozen metadata copy (self-contained for comparison).
    job_type = db.Column(db.String(50), nullable=True)
    room_count = db.Column(db.Integer, nullable=True)
    room_types = db.Column(_JSONB, nullable=True)
    floor_area_sqm = db.Column(db.Numeric(10, 2), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('job_card_id', 'snapshot_version', name='uq_job_snapshot_version'),
    )

    def to_dict(self):
        f = lambda v: float(v) if v is not None else None
        return {
            'id': self.id, 'job_card_id': self.job_card_id, 'snapshot_version': self.snapshot_version,
            'frozen_at': self.frozen_at.isoformat() if self.frozen_at else None,
            'status_at_freeze': self.status_at_freeze,
            'materials_cost': f(self.materials_cost), 'materials_sold': f(self.materials_sold),
            'materials_profit': f(self.materials_profit),
            'labour_hours': f(self.labour_hours), 'labour_cost': f(self.labour_cost),
            'labour_charged': f(self.labour_charged), 'labour_profit': f(self.labour_profit),
            'direct_costs_total': f(self.direct_costs_total), 'overall_profit': f(self.overall_profit),
            'labour_breakdown': self.labour_breakdown,
            'job_type': self.job_type, 'room_count': self.room_count, 'room_types': self.room_types,
            'floor_area_sqm': f(self.floor_area_sqm),
        }

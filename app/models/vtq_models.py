"""Voice-to-Quote Job & Transcription models — persistent job-based transcription management"""
from app.extensions import db
from datetime import datetime
import json as _json


class VTQJob(db.Model):
    """A Voice-to-Quote job — groups transcriptions for a single project/quote.
    
    Can be linked to a Xero/QB job reference, or created manually.
    Persists until the quote is approved, then archived.
    """
    __tablename__ = 'vtq_jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    
    # Job reference — from accounting system or manual
    title = db.Column(db.String(300), nullable=False)
    reference = db.Column(db.String(200))
    client_name = db.Column(db.String(300))
    notes = db.Column(db.Text)
    
    # Accounting system link
    accounting_project_id = db.Column(db.String(200))
    accounting_project_name = db.Column(db.String(300))
    accounting_source = db.Column(db.String(20))           # 'xero' | 'quickbooks' | 'manual'
    
    # Status
    status = db.Column(db.String(20), default='draft')     # draft | parsed | matched | quoted | approved | archived
    
    # Parsed results (stored as JSON so it persists between page loads)
    parsed_data = db.Column(db.Text)
    match_data = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    parsed_at = db.Column(db.DateTime)
    matched_at = db.Column(db.DateTime)
    quoted_at = db.Column(db.DateTime)
    
    # Relationships
    transcriptions = db.relationship('VTQTranscription', backref='job', lazy='dynamic',
                                      cascade='all, delete-orphan',
                                      order_by='VTQTranscription.order_index')
    
    def set_parsed_data(self, data):
        """Store parsed data as JSON text"""
        self.parsed_data = _json.dumps(data) if data else None
    
    def get_parsed_data(self):
        """Retrieve parsed data as dict"""
        if self.parsed_data:
            try:
                return _json.loads(self.parsed_data)
            except (_json.JSONDecodeError, TypeError):
                return None
        return None
    
    def set_match_data(self, data):
        """Store match data as JSON text"""
        self.match_data = _json.dumps(data) if data else None
    
    def get_match_data(self):
        """Retrieve match data as dict"""
        if self.match_data:
            try:
                return _json.loads(self.match_data)
            except (_json.JSONDecodeError, TypeError):
                return None
        return None
    
    def to_dict(self, include_transcriptions=False, include_parsed=False):
        d = {
            'id': self.id,
            'title': self.title,
            'reference': self.reference,
            'client_name': self.client_name,
            'notes': self.notes,
            'accounting_project_id': self.accounting_project_id,
            'accounting_project_name': self.accounting_project_name,
            'accounting_source': self.accounting_source,
            'status': self.status,
            'transcription_count': self.transcriptions.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'parsed_at': self.parsed_at.isoformat() if self.parsed_at else None,
            'matched_at': self.matched_at.isoformat() if self.matched_at else None,
            'quoted_at': self.quoted_at.isoformat() if self.quoted_at else None,
        }
        
        if include_transcriptions:
            d['transcriptions'] = [t.to_dict() for t in self.transcriptions.all()]
        
        if include_parsed:
            d['parsed_data'] = self.get_parsed_data()
            d['match_data'] = self.get_match_data()
        
        return d


class VTQTranscription(db.Model):
    """A single transcription within a VTQ job.
    
    One job can have many transcriptions (one per room visit, or multiple visits).
    Each can be parsed individually or combined.
    """
    __tablename__ = 'vtq_transcriptions'
    
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('vtq_jobs.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    
    # Content
    title = db.Column(db.String(200))
    text = db.Column(db.Text, nullable=False)              # The actual transcription text
    source_filename = db.Column(db.String(300))
    
    # Ordering within the job
    order_index = db.Column(db.Integer, default=0)
    
    # Parse status
    is_parsed = db.Column(db.Boolean, default=False)
    parsed_data = db.Column(db.Text)                       # Individual parse result JSON
    parsed_at = db.Column(db.DateTime)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'job_id': self.job_id,
            'title': self.title,
            'text': self.text,
            'source_filename': self.source_filename,
            'order_index': self.order_index,
            'is_parsed': self.is_parsed,
            'parsed_at': self.parsed_at.isoformat() if self.parsed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'char_count': len(self.text) if self.text else 0,
        }

"""Pipeline tests for the arithmetic validator wiring (AUDIT.md risk #1).

Covers the three behaviours added when wiring invoice_validator into the live
path:
  1. save_invoice_to_db flags an invoice whose items don't reconcile.
  2. save_invoice_to_db leaves a clean invoice unflagged.
  3. the sync guard blocks a flagged invoice and the mark-reviewed endpoint
     clears the block.
"""
import json

import pytest

from app.web import upload as upload_module
from app.web.upload import save_invoice_to_db
from app.web.integrations import _sync_validation_block


def _clean_invoice_data():
    """Two lines summing to net 50; net 50 + tax 10 (20%) = gross 60."""
    return {
        'supplier': 'CEF',
        'invoice_number': 'INV-CLEAN',
        'items': [
            {'quantity': 2, 'unit_price': 10, 'total_amount': 20,
             'selling_price': 15, 'profit_per_item': 5, 'cost_per_item': 10,
             'original_unit_price': 10, 'markup_percent': 50},
            {'quantity': 1, 'unit_price': 30, 'total_amount': 30,
             'selling_price': 45, 'profit_per_item': 15, 'cost_per_item': 30,
             'original_unit_price': 30, 'markup_percent': 50},
        ],
        'total_ex_tax': 50, 'tax_amount': 10, 'total_inc_tax': 60, 'tax_rate': 20,
    }


def _mismatched_invoice_data():
    """Same lines (sum 50) but a stated net of 90 — cannot reconcile."""
    data = _clean_invoice_data()
    data['invoice_number'] = 'INV-BROKEN'
    data['total_ex_tax'] = 90
    data['tax_amount'] = 18
    data['total_inc_tax'] = 108
    return data


@pytest.fixture(autouse=True)
def _login(monkeypatch, user):
    """save_invoice_to_db reads current_user.platform_mode; stand in our user."""
    monkeypatch.setattr(upload_module, 'current_user', user)


def test_clean_invoice_is_not_flagged(app, user):
    invoice = save_invoice_to_db(_clean_invoice_data(), 'clean.pdf', user.id)
    assert invoice.needs_review is False
    assert invoice.validation_errors is None
    assert _sync_validation_block(invoice) is None  # clear to sync


def test_mismatched_invoice_is_flagged_and_blocked(app, user):
    invoice = save_invoice_to_db(_mismatched_invoice_data(), 'broken.pdf', user.id)
    # Saved, but flagged with a recorded reason and low confidence
    assert invoice.id is not None
    assert invoice.needs_review is True
    assert invoice.confidence == 'low'
    assert invoice.validation_errors is not None
    reasons = json.loads(invoice.validation_errors)
    assert any('sum' in r.lower() for r in reasons)
    # Sync guard refuses it
    blocked = _sync_validation_block(invoice)
    assert blocked is not None
    body, status = blocked
    assert status == 400
    assert body.json['validation_errors'] == reasons


def test_mark_reviewed_clears_the_block(app, user):
    invoice = save_invoice_to_db(_mismatched_invoice_data(), 'broken.pdf', user.id)
    assert _sync_validation_block(invoice) is not None

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
    resp = client.post(f'/api/invoices/{invoice.id}/mark-reviewed',
                       headers={'X-Forwarded-Proto': 'https'})
    assert resp.status_code == 200
    assert resp.json['success'] is True

    from app.models.invoice import Invoice
    refreshed = Invoice.query.get(invoice.id)
    assert refreshed.validation_errors is None
    assert refreshed.needs_review is False
    assert _sync_validation_block(refreshed) is None  # now syncable


def test_mark_reviewed_is_tenant_isolated(app, user, db):
    """A second user cannot clear the first user's invoice (no IDOR)."""
    from app.models.user import User
    invoice = save_invoice_to_db(_mismatched_invoice_data(), 'broken.pdf', user.id)

    other = User(email='other@example.com', password_hash='x', platform_mode='sync')
    db.session.add(other)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(other.id)
    resp = client.post(f'/api/invoices/{invoice.id}/mark-reviewed',
                       headers={'X-Forwarded-Proto': 'https'})
    assert resp.status_code == 404  # not visible to the other tenant

    from app.models.invoice import Invoice
    assert Invoice.query.get(invoice.id).validation_errors is not None  # still blocked

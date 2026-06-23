"""Read-only DRY RUN of the customer-invoice sync — builds and PRINTS the payload the sync
WOULD post to QuickBooks (and optionally Xero), but sends NOTHING.

HARD INVARIANT — no write reaches QBO/Xero, and nothing is persisted to our DB either:
  1. make_api_request / _make_request is wrapped: **POST is intercepted** (captured + a synthetic
     success returned so the sync keeps running) and **never sent**. Only GET/query reads hit the
     real connection (the same read-only calls check_output_tax.py already does safely).
  2. db.session.commit is no-op'd for the duration, so the sync's `qb_synced_at` / `last_sync_at`
     writes never persist; a final rollback discards everything. (Reads still work via autoflush.)
  3. In-memory tax_registered / tax_rate flips are never committed (user is detached; rollback).

The only network egress is the GET reads (tax codes / tax rates / existing items) and, if the
access token is stale, an OAuth token refresh (auth, not a QBO data write — and its DB persist is
also swallowed by the commit no-op).

Usage (against the env where the QBO token + real invoices live — production):
  railway run --environment production --service GoZappify \
    env DATABASE_URL="<public proxy url>" PYTHONPATH=. .venv/bin/python scripts/dryrun_customer_invoice_sync.py
Optional env: INVOICE_ID=<id> (else picks the most recent supplier invoice with items),
              CHECK_USER_EMAIL=... (default incognito.jsy@gmail.com)
"""
import os
import json
from decimal import Decimal

import requests

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.quickbooks import QuickBooksConnection
from app.models.invoice import Invoice, InvoiceItem
from app.integrations.quickbooks_service import QuickBooksService

USER_EMAIL = os.environ.get('CHECK_USER_EMAIL', 'incognito.jsy@gmail.com')


def _register_all_models():
    import importlib, pkgutil
    import app.models as _models
    for _mod in pkgutil.iter_modules(_models.__path__):
        importlib.import_module(f'app.models.{_mod.name}')


def _dryrun_qb_service(user, captured):
    """A QuickBooksService whose make_api_request lets reads through but captures+fakes writes."""
    svc = QuickBooksService(user)
    real = svc.make_api_request

    def intercept(qb_connection, endpoint, method='GET', data=None):
        if method == 'POST':                       # WRITE — capture, never send
            captured.append((endpoint, data))
            if endpoint.startswith('item'):
                n = sum(1 for ep, _ in captured if ep.startswith('item'))
                return {'Item': {'Id': f'DRYRUN-ITEM-{n}', 'Name': (data or {}).get('Name', '')}}
            if endpoint.startswith('invoice'):
                return {'Invoice': {'Id': 'DRYRUN-INV', 'DocNumber': 'DRYRUN-0001'}}
            if endpoint.startswith('estimate'):
                return {'Estimate': {'Id': 'DRYRUN-EST'}}
            return {'_dryrun': True}
        return real(qb_connection, endpoint, method=method, data=data)   # READ — real

    svc.make_api_request = intercept
    return svc


def _print_qb_run(label, conn, invoice, user, *, tax_registered, tax_rate):
    user.tax_registered = tax_registered
    user.tax_rate = Decimal(str(tax_rate))
    captured = []
    svc = _dryrun_qb_service(user, captured)
    result = svc.sync_invoice_to_customer(
        conn, invoice, customer_id='DRYRUN-CUST',
        use_existing_invoice=False, sync_mode='itemised')

    print(f"\n========== QB {label}  (tax_registered={tax_registered}, tax_rate={tax_rate}) ==========")
    print(f"sync result: success={result.get('success')} action={result.get('invoice_action')} "
          f"errors={result.get('errors')}")
    item_posts = [d for ep, d in captured if ep.startswith('item')]
    invoice_posts = [d for ep, d in captured if ep.startswith('invoice')]
    print(f"captured WRITES (none sent): {len(item_posts)} item POST(s), {len(invoice_posts)} invoice POST(s)")

    if item_posts:
        s = item_posts[0]
        print("  sample item payload (tax view):",
              json.dumps({k: s.get(k) for k in ('Name', 'Taxable', 'SalesTaxCodeRef', 'UnitPrice')}, default=str))

    if not invoice_posts:
        print("  -> NO invoice payload built (sync blocked / fail-closed).")
        return
    for inv in invoice_posts:
        print("  --- invoice payload that WOULD POST to /invoice ---")
        print(json.dumps(inv, indent=2, default=str))
        lines = [l for l in inv.get('Line', []) if l.get('DetailType') == 'SalesItemLineDetail']
        sub = sum((Decimal(str(l.get('Amount', 0))) for l in lines), Decimal('0'))
        taxed = any(l.get('SalesItemLineDetail', {}).get('TaxCodeRef') for l in lines)
        rate = Decimal(str(tax_rate)) if (tax_registered and taxed) else Decimal('0')
        tax = (sub * rate / 100).quantize(Decimal('0.01'))
        print(f"  implied (QBO computes from lines + GlobalTaxCalculation=TaxExcluded): "
              f"subtotal(ex-tax)=£{sub}  tax@{rate}%=£{tax}  total=£{sub + tax}  taxed={taxed}")


def main():
    _register_all_models()
    app = create_app(os.environ.get('APP_CONFIG', 'default'))
    with app.app_context():
        # Belt-and-suspenders: never persist anything to our DB during the dry run.
        db.session.commit = lambda: None

        # Network-layer backstop: physically REFUSE any non-GET to the QBO API host,
        # regardless of which code path emits it. The OAuth token endpoint
        # (oauth.platform.intuit.com) is a different host, so token refresh still works;
        # GET (reads) is left untouched.
        _QBO_API_HOST = 'quickbooks.api.intuit.com'  # matches prod + sandbox-quickbooks.api.intuit.com
        _orig_http = {m: getattr(requests, m) for m in ('post', 'put', 'delete', 'patch')}

        def _guard(name):
            def _blocked(url, *a, **k):
                if _QBO_API_HOST in str(url):
                    raise RuntimeError(f"DRY RUN network backstop: refused {name.upper()} to QBO API ({url})")
                return _orig_http[name](url, *a, **k)
            return _blocked
        for _m in ('post', 'put', 'delete', 'patch'):
            setattr(requests, _m, _guard(_m))

        user = (User.query.filter_by(email=USER_EMAIL).first()
                or User.query.filter_by(is_admin=True).first()
                or User.query.first())
        if user is None:
            print("No user found."); return
        print(f"User: {user.email} (id={user.id})")
        conn = (QuickBooksConnection.query.filter_by(user_id=user.id, is_active=True).first()
                or QuickBooksConnection.query.filter_by(user_id=user.id).first())
        if conn is None:
            print("No QuickBooks connection for this user."); return

        print("Recent supplier invoices:")
        recent = Invoice.query.filter_by(user_id=user.id).order_by(Invoice.id.desc()).limit(8).all()
        for iv in recent:
            n = InvoiceItem.query.filter_by(invoice_id=iv.id).count()
            print(f"  id={iv.id} supplier={iv.supplier_name!r} items={n} total_selling={iv.total_selling}")

        inv_id = os.environ.get('INVOICE_ID')
        if inv_id:
            invoice = Invoice.query.filter_by(id=int(inv_id), user_id=user.id).first()
        else:
            invoice = next((iv for iv in Invoice.query.filter_by(user_id=user.id)
                            .order_by(Invoice.id.desc()).all()
                            if InvoiceItem.query.filter_by(invoice_id=iv.id).count() > 0), None)
        if invoice is None:
            print("No supplier invoice with items found."); return
        n = InvoiceItem.query.filter_by(invoice_id=invoice.id).count()
        print(f"\nUsing invoice id={invoice.id} ({invoice.supplier_name!r}, {n} items, "
              f"company={conn.company_name!r})")

        db.session.expunge(user)  # in-memory tax flips can't flush

        _print_qb_run("REGISTERED 5%", conn, invoice, user, tax_registered=True, tax_rate=5)
        _print_qb_run("UNREGISTERED (exempt)", conn, invoice, user, tax_registered=False, tax_rate=0)
        _print_qb_run("REGISTERED mismatch 17.5%", conn, invoice, user, tax_registered=True, tax_rate=Decimal('17.5'))

        db.session.rollback()
        print("\n(DRY RUN complete. No QBO writes sent; nothing persisted to the DB.)")


if __name__ == '__main__':
    main()

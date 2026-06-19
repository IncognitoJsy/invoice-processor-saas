"""Read-only QBO output-tax verification.

Makes **NO writes to QuickBooks data** — no create / update / POST / delete of any
QBO object (item, invoice, estimate, …). It issues only GET/query calls:
  * QuickBooksService._fetch_active_tax_codes()  -> SELECT ... FROM TaxCode (GET)
  * QuickBooksService.resolve_output_tax()        -> calls the above, then pure
    in-memory selection logic; it does not POST anything.

The only network POST that can occur is the OAuth client refreshing an expired
access token (a normal auth step that updates the token stored in OUR database,
not your QuickBooks company data). The in-memory `tax_registered` flips below are
NEVER committed — the User row is detached from the session and we rollback at the end.

Usage:
    python scripts/check_output_tax.py
    railway run python scripts/check_output_tax.py     # if local DB has no live token

Optional env:
    CHECK_USER_EMAIL=...   (default: incognito.jsy@gmail.com)
    APP_CONFIG=...         (default: default)
"""
import os

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.quickbooks import QuickBooksConnection
from app.integrations.quickbooks_service import QuickBooksService

USER_EMAIL = os.environ.get('CHECK_USER_EMAIL', 'incognito.jsy@gmail.com')


def _rate(tc):
    r = QuickBooksService._tax_code_rate(tc)
    return f"{r}%" if r is not None else "?"


def _register_all_models():
    """Import every model module so db.create_all() (run inside create_app) can
    resolve cross-table foreign keys. Pure imports — no DB writes."""
    import importlib
    import pkgutil
    import app.models as _models
    for _mod in pkgutil.iter_modules(_models.__path__):
        importlib.import_module(f'app.models.{_mod.name}')


def main():
    _register_all_models()
    app = create_app(os.environ.get('APP_CONFIG', 'default'))
    with app.app_context():
        # 1) Load the user (same identity the live sync uses).
        user = (User.query.filter_by(email=USER_EMAIL).first()
                or User.query.filter_by(is_admin=True).first()
                or User.query.first())
        if user is None:
            print("No user found in this database.")
            return

        print(f"User: {user.email} (id={user.id})")
        print(f"  tax_registered={user.tax_registered}  tax_type={user.tax_type!r}  "
              f"tax_rate={user.tax_rate}  country={user.country!r} / "
              f"business_address_country={user.business_address_country!r}")

        # ...and the stored QuickBooks connection the live sync uses.
        conn = (QuickBooksConnection.query.filter_by(user_id=user.id, is_active=True).first()
                or QuickBooksConnection.query.filter_by(user_id=user.id).first())
        if conn is None:
            print("\nNo QuickBooks connection stored for this user in THIS database.")
            print("Your local DB has no live token — run it where the token is valid:")
            print("    railway run python scripts/check_output_tax.py")
            return
        print(f"QuickBooks connection: realm_id={conn.realm_id} "
              f"company={conn.company_name!r} is_active={conn.is_active}")

        # Detach the user so the in-memory tax_registered flips below can NEVER be
        # flushed to the DB.
        db.session.expunge(user)

        # 2) Print every active tax code resolve_output_tax can see (READ-ONLY GET).
        svc = QuickBooksService(user)
        try:
            tax_codes = svc._fetch_active_tax_codes(conn)
        except Exception as e:
            print(f"\nCould not read tax codes (token invalid/expired?): {type(e).__name__}: {e}")
            print("If running locally, try: railway run python scripts/check_output_tax.py")
            return

        print(f"\nActive QBO tax codes resolve_output_tax selects from ({len(tax_codes)}):")
        if not tax_codes:
            print("  (none returned)")
        for tc in tax_codes:
            tag = " [exempt/zero]" if QuickBooksService._is_exempt_code(tc) else " [taxable]"
            print(f"  - name={tc.get('Name')!r:42} id={tc.get('Id')!s:6} rate={_rate(tc):>6}{tag}")

        # 3) Resolve on the REGISTERED path (tax_registered=True, in memory only).
        #    Fresh service per call so the per-request resolver cache doesn't reuse.
        user.tax_registered = True
        reg = QuickBooksService(user).resolve_output_tax(conn)
        print(f"\nREGISTERED   (tax_registered=True):  resolve_output_tax -> {reg}")

        # 4) Resolve on the UNREGISTERED path (tax_registered=False, in memory only).
        user.tax_registered = False
        unreg = QuickBooksService(user).resolve_output_tax(conn)
        print(f"UNREGISTERED (tax_registered=False): resolve_output_tax -> {unreg}")

        # Discard any in-memory ORM state; we commit nothing.
        db.session.rollback()
        print("\n(No QuickBooks writes. In-memory tax_registered flips were not committed.)")


if __name__ == '__main__':
    main()

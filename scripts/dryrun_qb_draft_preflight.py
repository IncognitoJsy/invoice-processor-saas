"""READ-ONLY dry-run: "which open QBO drafts would BLOCK on the next add-to-draft sync?"

Enumerates the user's open/unsent QuickBooks drafts (get_draft_invoices — the exact list the customer
sync path sees) and runs the real add-to-draft pre-flight (_find_unappendable_lines) + block builder
(_draft_not_appendable_block), printing the exact production block message for any draft that contains
a line we can't faithfully re-POST: an amount-mismatch line (Amount != round(Qty*UnitPrice,2)) or an
unsupported line type (Discount/Group/unknown). See the fix in app/integrations/quickbooks_service.py
and tests/integration/test_qb_draft_preflight.py.

Why this exists: QBO's "add to existing draft" forces a full Line re-POST and re-validates every echoed
line, so one stored-but-inconsistent line (e.g. an Amount hand-edited in the QBO UI) fails the whole
sync with the opaque "Amount calculation incorrect in the request". This script surfaces such drafts
BEFORE a user hits that — a periodic "any poisoned drafts?" check.

Only GETs (invoice query). No POST, no sync, no mutation. (An OAuth token refresh may occur — normal
housekeeping; it writes only the token row.)

RUN (read-only, against prod GoZappify DB; needs QB client creds, injected by `railway run`):
    PUBURL="$(railway variables --service Postgres --kv | sed -n 's/^DATABASE_PUBLIC_URL=//p')"
    railway run --service GoZappify -- bash -lc \
      "export DATABASE_URL='$PUBURL' APP_CONFIG=production PYTHONPATH=\$PWD; \
       python scripts/dryrun_qb_draft_preflight.py"
    # target a different account: prepend CHECK_USER_EMAIL='someone@example.com'
"""
import importlib
import os
import pkgutil

import app.models as _models
from app import create_app
from app.models.user import User
from app.models.quickbooks import QuickBooksConnection
from app.integrations.quickbooks_service import QuickBooksService

for _m in pkgutil.iter_modules(_models.__path__):
    importlib.import_module(f'app.models.{_m.name}')

USER_EMAIL = os.environ.get('CHECK_USER_EMAIL', 'rudiholzmeier23@gmail.com')

app = create_app(os.environ.get('APP_CONFIG', 'default'))

with app.app_context():
    user = User.query.filter_by(email=USER_EMAIL).first()
    if not user:
        raise SystemExit(f"No user {USER_EMAIL}")
    conn = QuickBooksConnection.query.filter_by(user_id=user.id).first()
    if not conn:
        raise SystemExit(f"No QuickBooks connection for {USER_EMAIL}")
    svc = QuickBooksService(user)

    drafts = svc.get_draft_invoices(conn)  # open/unsent drafts (balance>0, not EmailSent)
    print(f"Open drafts scanned: {len(drafts)} (company {conn.company_name})\n")

    blocked = []
    for d in drafts:
        problems = svc._find_unappendable_lines(d)
        cust = (d.get('CustomerRef') or {}).get('name', '?')
        tag = f"#{d.get('DocNumber')} (Id {d.get('Id')}) — {cust} — {len(d.get('Line', []))} lines"
        if problems:
            blocked.append((d, problems))
            res = svc._draft_not_appendable_block(d, problems)
            print(f"BLOCK  {tag}")
            print("  ── message the user would see ──")
            for line in res['error'].split("\n"):
                print(f"    {line}")
            print()
        else:
            print(f"ok     {tag}")

    print("=" * 90)
    print(f"SUMMARY: {len(blocked)} of {len(drafts)} open draft(s) would BLOCK on next add-to-draft sync.")
    for d, problems in blocked:
        reasons = ", ".join(sorted({p['reason'] for p in problems}))
        print(f"  - #{d.get('DocNumber')} ({(d.get('CustomerRef') or {}).get('name', '?')}): {reasons}")

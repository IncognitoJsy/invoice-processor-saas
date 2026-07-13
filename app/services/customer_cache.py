"""Per-user cache of QuickBooks/Xero customers (app/models CustomerCache).

Why: the invoice-sync customer picker used to pull ALL ~1300 customers live from the accounting
API on every modal open (~9s). This serves the picker from a local table instead.

Design rule — the live API pull happens ONLY on an explicit refresh (``refresh_customer_cache``),
which the client fires ASYNCHRONOUSLY (page-load background fill, the "Refresh customers" button, or
a search-miss). ``read_cached_customers`` is a pure DB read and never calls the API, so it is
sub-second and never blocks the modal-open path.

Refresh uses UPSERT-by-(user_id, source, external_id) + prune-missing (not delete-all) so each
customer keeps a stable local row/id — leaving the future two-way-sync ID mapping intact.
"""
import logging
from datetime import datetime, timedelta

from app.extensions import db
from app.models.user_preference import CustomerCache

logger = logging.getLogger(__name__)

# Customers change rarely; the explicit Refresh button + search-miss auto-refresh cover new
# customers on demand, so a long backstop TTL is fine.
CUSTOMER_CACHE_TTL_HOURS = 12


def _latest_synced_at(user_id, source):
    row = (CustomerCache.query
           .filter_by(user_id=user_id, source=source)
           .order_by(CustomerCache.synced_at.desc())
           .first())
    return row.synced_at if row else None


def _is_fresh(user_id, source):
    latest = _latest_synced_at(user_id, source)
    if not latest:
        return False
    return latest > datetime.utcnow() - timedelta(hours=CUSTOMER_CACHE_TTL_HOURS)


def _rows(user_id, source):
    return (CustomerCache.query
            .filter_by(user_id=user_id, source=source)
            .order_by(CustomerCache.display_name)
            .all())


def read_cached_customers(user_id, source):
    """Pure DB read — NEVER calls the accounting API. Returns (rows, stale, synced_at).

    ``stale`` is True when the newest row is older than the TTL (or the cache is empty); the client
    uses it to decide whether to kick off a background refresh. This is the modal-open / page-load
    path and must stay sub-second.
    """
    rows = _rows(user_id, source)
    return rows, (not _is_fresh(user_id, source)), _latest_synced_at(user_id, source)


def _upsert_and_prune(user_id, source, incoming):
    """UPSERT each incoming customer by external_id and delete cached rows no longer present.

    ``incoming`` is a list of normalized dicts:
        {external_id, display_name, fully_qualified_name, company_name, email}
    Caller commits.
    """
    now = datetime.utcnow()
    existing = {r.external_id: r for r in CustomerCache.query.filter_by(user_id=user_id, source=source).all()}
    seen = set()

    for c in incoming:
        eid = str(c.get('external_id') or '').strip()
        if not eid:
            continue
        seen.add(eid)
        row = existing.get(eid)
        if row is None:
            row = CustomerCache(user_id=user_id, source=source, external_id=eid)
            db.session.add(row)
        row.display_name = (c.get('display_name') or '')[:255]
        row.fully_qualified_name = (c.get('fully_qualified_name') or None)
        if row.fully_qualified_name:
            row.fully_qualified_name = row.fully_qualified_name[:255]
        row.company_name = (c.get('company_name') or None)
        row.email = (c.get('email') or None)
        row.synced_at = now

    # Prune customers deleted in the accounting software since last sync.
    for eid, row in existing.items():
        if eid not in seen:
            db.session.delete(row)

    return len(seen)


def refresh_customer_cache(user_id, source, fetch_fn):
    """Pull customers live via ``fetch_fn()`` and upsert+prune the cache. Returns (rows, synced_at).

    ``fetch_fn`` returns the list of normalized dicts (the endpoint adapts QB/Xero shapes). This is
    the ONLY function that hits the accounting API — always invoked async by the client, never on
    the modal-open path.

    Fail-safe: on API error OR an empty result, the existing (stale) cache is left intact and
    returned — a refresh never blanks a working cache.
    """
    try:
        incoming = fetch_fn() or []
    except Exception as e:
        logger.error(f"Customer cache refresh failed (user={user_id}, source={source}): "
                     f"{type(e).__name__}: {e}")
        return _rows(user_id, source), _latest_synced_at(user_id, source)

    if not incoming:
        logger.warning(f"Customer refresh returned 0 for user={user_id}, source={source}; keeping stale cache")
        return _rows(user_id, source), _latest_synced_at(user_id, source)

    count = _upsert_and_prune(user_id, source, incoming)
    db.session.commit()
    logger.info(f"Customer cache refreshed for user={user_id}, source={source}: {count} customers")
    return _rows(user_id, source), _latest_synced_at(user_id, source)

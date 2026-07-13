"""Customer cache (Phase A): serve the invoice-sync picker from a local table instead of a ~9s
live QBO/Xero pull on every modal open.

Tested at the service layer (read_cached_customers / refresh_customer_cache) and the match layer,
which is where the logic lives. Proves: the read path never hits the API, refresh upserts+prunes,
stale-fallback never blanks a working cache, TTL flags staleness, the search-miss refresh finds a
customer not previously cached, and the match runs off the cache with NO live pull.
"""
from datetime import datetime, timedelta

import pytest

from app.models.user import User
from app.models.user_preference import CustomerCache
from app.services.customer_cache import (
    read_cached_customers, refresh_customer_cache, CUSTOMER_CACHE_TTL_HOURS,
)
from app.integrations.quickbooks_service import QuickBooksService


def _norm(eid, name, fqn=None, email=None):
    """A normalized customer dict as the endpoint fetch-adapters produce."""
    return {'external_id': eid, 'display_name': name, 'fully_qualified_name': fqn,
            'company_name': None, 'email': email}


def _raise(*a, **k):
    raise RuntimeError('must not be called')


# ── read path never touches the API ──────────────────────────────────────────────────────
def test_empty_cache_reads_stale(app, db, user):
    rows, stale, synced = read_cached_customers(user.id, 'quickbooks')
    assert rows == [] and stale is True and synced is None


def test_refresh_populates_then_read_is_fresh(app, db, user):
    calls = {'n': 0}

    def fetch():
        calls['n'] += 1
        return [_norm('1', 'Alpha Ltd'), _norm('2', 'Beta:Site A', 'Beta:Site A')]

    rows, synced = refresh_customer_cache(user.id, 'quickbooks', fetch)
    assert {r.external_id for r in rows} == {'1', '2'}
    assert calls['n'] == 1

    rows2, stale, _ = read_cached_customers(user.id, 'quickbooks')     # pure DB read
    assert len(rows2) == 2 and stale is False
    # QB shape preserved incl. Parent:Child FullyQualifiedName (used for sub-customers).
    d = next(r.to_dict() for r in rows2 if r.external_id == '2')
    assert d == {'Id': '2', 'DisplayName': 'Beta:Site A', 'FullyQualifiedName': 'Beta:Site A'}


# ── refresh = upsert + prune (stable ids, no delete-all) ─────────────────────────────────
def test_refresh_upserts_and_prunes(app, db, user):
    refresh_customer_cache(user.id, 'quickbooks', lambda: [_norm('1', 'Alpha'), _norm('2', 'Beta')])
    id1 = CustomerCache.query.filter_by(user_id=user.id, external_id='1').first().id

    # Alpha renamed, Beta deleted-in-QBO, Gamma new.
    refresh_customer_cache(user.id, 'quickbooks', lambda: [_norm('1', 'Alpha Renamed'), _norm('3', 'Gamma')])
    rows = {r.external_id: r for r in read_cached_customers(user.id, 'quickbooks')[0]}

    assert set(rows) == {'1', '3'}                       # Beta pruned, Gamma added
    assert rows['1'].display_name == 'Alpha Renamed'     # upserted in place
    assert rows['1'].id == id1                           # SAME local id (stable — upsert, not delete-all)


# ── stale-fallback: a bad/empty refresh never blanks a working cache ─────────────────────
def test_refresh_empty_keeps_stale_cache(app, db, user):
    refresh_customer_cache(user.id, 'quickbooks', lambda: [_norm('1', 'Alpha')])
    rows, _ = refresh_customer_cache(user.id, 'quickbooks', lambda: [])   # API returned nothing
    assert {r.external_id for r in rows} == {'1'}


def test_refresh_error_keeps_stale_cache(app, db, user):
    refresh_customer_cache(user.id, 'quickbooks', lambda: [_norm('1', 'Alpha')])
    rows, _ = refresh_customer_cache(user.id, 'quickbooks', _raise)       # API raised
    assert {r.external_id for r in rows} == {'1'}


# ── TTL: expired cache is still served, just flagged stale ───────────────────────────────
def test_ttl_expiry_flags_stale_but_serves(app, db, user):
    refresh_customer_cache(user.id, 'quickbooks', lambda: [_norm('1', 'Alpha')])
    row = CustomerCache.query.filter_by(user_id=user.id).first()
    row.synced_at = datetime.utcnow() - timedelta(hours=CUSTOMER_CACHE_TTL_HOURS + 1)
    db.session.commit()

    rows, stale, _ = read_cached_customers(user.id, 'quickbooks')
    assert len(rows) == 1 and stale is True


# ── the user's requested test: search-miss → refresh finds a customer NOT in the cache ───
def test_search_miss_refresh_finds_new_customer(app, db, user):
    # Cache seeded WITHOUT "Smith Builders" (simulates: user just created them in QBO).
    refresh_customer_cache(user.id, 'quickbooks', lambda: [_norm('1', 'Alpha Ltd')])
    before = read_cached_customers(user.id, 'quickbooks')[0]
    assert not any('Smith' in r.display_name for r in before)

    # Search-miss path fires a refresh; the live pull now includes the new customer.
    refresh_customer_cache(user.id, 'quickbooks',
                           lambda: [_norm('1', 'Alpha Ltd'), _norm('9', 'Smith Builders')])

    after = read_cached_customers(user.id, 'quickbooks')[0]
    smith = [r for r in after if r.display_name == 'Smith Builders']
    assert len(smith) == 1 and smith[0].external_id == '9'      # now findable, correct QBO id


# ── isolation ────────────────────────────────────────────────────────────────────────────
def test_cache_is_per_user_and_per_source(app, db, user):
    other = User(email='other@example.com', password_hash='x', platform_mode='sync')
    db.session.add(other)
    db.session.commit()

    refresh_customer_cache(user.id, 'quickbooks', lambda: [_norm('1', 'Mine QB')])
    refresh_customer_cache(user.id, 'xero', lambda: [_norm('x1', 'Mine Xero')])

    assert {r.external_id for r in read_cached_customers(user.id, 'quickbooks')[0]} == {'1'}
    assert {r.external_id for r in read_cached_customers(user.id, 'xero')[0]} == {'x1'}
    # Xero row uses Xero shape.
    assert read_cached_customers(user.id, 'xero')[0][0].to_dict() == {
        'ContactID': 'x1', 'Name': 'Mine Xero', 'EmailAddress': None}
    assert read_cached_customers(other.id, 'quickbooks')[0] == []


# ── match runs off the cache with NO live pull ───────────────────────────────────────────
def test_match_uses_cached_list_never_pulls_live(app, db, user, monkeypatch):
    # Force the offline word-overlap fallback (no Claude/network) deterministically.
    monkeypatch.setattr('anthropic.Anthropic', _raise)
    qb = QuickBooksService(user)
    # If the code tries a live pull, this blows up the test.
    monkeypatch.setattr(qb, 'get_customers', _raise)

    cached = [{'Id': '9', 'DisplayName': 'Smith Builders', 'FullyQualifiedName': 'Smith Builders'}]
    matches = qb.match_customer_to_job_reference(None, 'SMITH JOB', customers=cached)

    assert matches and matches[0]['customer_id'] == '9'   # matched from the cached list, no live pull

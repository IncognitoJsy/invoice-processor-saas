"""Sync-mode customer resolution: map a picked QuickBooks/Xero customer to a LOCAL Customer row.

A JobCard.customer_id is a NOT-NULL FK to the local `customer` table, but a sync user's customers
live in their accounting software (served to the picker from CustomerCache, keyed by external id).
This module bridges the two: find-or-create a local Customer keyed on (user_id, source, external_id)
so the link is stable across a rename in QBO/Xero and can never duplicate — critical because a
mislinked customer on a JOB would corrupt the cost history the Jobs feature exists to build.

Materialisation is LAZY: sync users get local Customer rows only for customers that actually get a
job. Full-suite users are untouched (their local customers keep external_id/source NULL).
"""
from app.extensions import db
from app.models.customer import Customer
from app.models.user_preference import CustomerCache
from app.models.quickbooks import QuickBooksConnection
from app.models.xero import XeroConnection


def user_sync_source(user):
    """The user's active accounting provider for the customer picker: 'quickbooks' | 'xero' | None."""
    qb = QuickBooksConnection.query.filter_by(user_id=user.id).first()
    if qb and qb.is_active:
        return 'quickbooks'
    xe = XeroConnection.query.filter_by(user_id=user.id).first()
    if xe and xe.is_active:
        return 'xero'
    return None


def resolve_local_customer(user_id, source, external_id, fallback_name=None):
    """Find-or-create the local Customer mirroring a picked QBO/Xero customer.

    Keyed on (user_id, source, external_id): a QBO/Xero rename updates the SAME row (no duplicate,
    no mislink), and a sub-customer 'Parent:Child' maps to one row via its own external id. Name /
    company / email are taken server-authoritatively from CustomerCache (QB uses the
    FullyQualifiedName so 'Parent:Child' is preserved); ``fallback_name`` covers a cache miss.

    Returns the Customer (flushed; has an id), or None if it neither exists nor can be named.
    Does not commit — the caller commits.
    """
    if not source or not external_id:
        return None
    external_id = str(external_id)

    existing = Customer.query.filter_by(
        user_id=user_id, source=source, external_id=external_id).first()

    cache = CustomerCache.query.filter_by(
        user_id=user_id, source=source, external_id=external_id).first()
    name = company = email = None
    if cache:
        name = cache.fully_qualified_name or cache.display_name
        company = cache.company_name
        email = cache.email
    name = name or fallback_name

    if existing:
        # Keep the local mirror fresh on a rename — same row, never a duplicate.
        if name and existing.name != name:
            existing.name = name
        if company and existing.company_name != company:
            existing.company_name = company
        return existing

    if not name:
        return None  # cache miss AND no fallback — caller asks the user to refresh the list

    c = Customer(user_id=user_id, name=name, company_name=company, email=email,
                 source=source, external_id=external_id)
    db.session.add(c)
    db.session.flush()
    return c

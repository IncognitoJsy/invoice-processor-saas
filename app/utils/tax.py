"""Output-tax config — the single source of truth for the rate a user charges customers.

Both the customer-document tax line (snapshotted at create) and the QB/Xero resolver target
derive from effective_output_rate(user), so the printed document and the synced invoice can't
disagree on the rate for a given config.
"""
from decimal import Decimal

from app.utils.money import to_decimal


def effective_output_rate(user) -> Decimal:
    """The output tax rate (percent) the user charges customers: their configured tax_rate
    when GST/VAT-registered, else Decimal('0') (no output tax). Accepts any object with
    `tax_registered` / `tax_rate` attributes (incl. test doubles)."""
    if user is None or not getattr(user, 'tax_registered', False):
        return Decimal('0')
    return to_decimal(getattr(user, 'tax_rate', 0) or 0) or Decimal('0')


def output_rate_unconfigured(user) -> bool:
    """True when the user is GST/VAT-registered but has no output rate set — a config error:
    documents would show no tax while the resolver attaches the code's rate. Callers should
    block document creation / sync and ask the user to set their rate."""
    return bool(getattr(user, 'tax_registered', False)) and effective_output_rate(user) <= 0


OUTPUT_RATE_UNSET_MESSAGE = (
    "You're marked GST/VAT-registered but haven't set an output tax rate. "
    "Set it in Settings before creating or syncing invoices/quotes."
)

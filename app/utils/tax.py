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
    block document creation / sync and ask the user to set their rate.

    Under the tax-code picker, a registered user's rate is captured from the picked code, so a
    zero rate means "registered but hasn't picked a sales tax code yet" — same block, and the
    Settings tax-code picker is where they resolve it."""
    return bool(getattr(user, 'tax_registered', False)) and effective_output_rate(user) <= 0


def picked_output_code(user):
    """The user's chosen output sales tax code, or None if they haven't picked one.

    Returns a dict {ref, name, provider, rate} captured at pick time — the resolver attaches
    `ref` directly (no per-sync TaxRate read), and `rate` mirrors effective_output_rate(user).
    Accepts any object with the output_tax_code_* / tax_rate attributes (incl. test doubles)."""
    ref = getattr(user, 'output_tax_code_ref', None) if user is not None else None
    if not ref:
        return None
    return {
        'ref': ref,
        'name': getattr(user, 'output_tax_code_name', None),
        'provider': getattr(user, 'output_tax_provider', None),
        'rate': effective_output_rate(user),
    }


OUTPUT_RATE_UNSET_MESSAGE = (
    "You're marked GST/VAT-registered but haven't set an output tax rate. "
    "Set it in Settings before creating or syncing invoices/quotes."
)

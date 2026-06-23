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


def clear_picked_output_code(user, provider=None):
    """Clear the stored output tax-code pick so a stale ref can't be attached after the
    provider it came from is disconnected. When `provider` is given, only clears a pick that
    belongs to that provider (so disconnecting QB doesn't wipe a Xero pick); None clears any.
    Returns True if a pick was cleared. Leaves tax_rate alone (the document keeps working; the
    resolver fails closed without a ref until the user re-picks)."""
    if user is None or not getattr(user, 'output_tax_code_ref', None):
        return False
    if provider is not None and getattr(user, 'output_tax_provider', None) != provider:
        return False
    user.output_tax_code_ref = None
    user.output_tax_code_name = None
    user.output_tax_provider = None
    return True


def picked_but_not_registered(user) -> bool:
    """True when the user has PICKED an output tax code but isn't marked tax_registered — a
    contradictory state: the pick won't apply (the resolver treats them as unregistered and syncs
    exempt). Defense-in-depth signal for the Settings UI; deliberately DISTINCT from
    output_rate_unconfigured (which is the registered-but-no-rate misconfig), so neither
    overloads the other."""
    return bool(getattr(user, 'output_tax_code_ref', None)) and not bool(getattr(user, 'tax_registered', False))


def tax_noun(user) -> str:
    """The output-tax noun for UI labels: the user's configured tax_type if set, else
    region-derived — 'GST' for Jersey / Channel Islands, else 'VAT'. Keeps Settings labels
    correct for a Jersey GST business instead of hardcoding 'VAT'."""
    t = (getattr(user, 'tax_type', None) or '').strip()
    if t:
        return t
    country = (getattr(user, 'country', None) or '').strip().lower()
    if 'jersey' in country or 'channel island' in country or 'guernsey' in country:
        return 'GST'
    return 'VAT'


OUTPUT_RATE_UNSET_MESSAGE = (
    "You're marked GST/VAT-registered but haven't set an output tax rate. "
    "Set it in Settings before creating or syncing invoices/quotes."
)

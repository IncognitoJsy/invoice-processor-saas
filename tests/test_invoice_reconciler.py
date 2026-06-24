"""Phase 1 unit tests for the totals cross-reconciler (app/services/invoice_reconciler.py).

Tested at the reconciler+validator boundary with representative extraction dicts (the stage both
operate on). The reconciler is pure; we apply its canonical net to a copy and re-validate to prove
the gate then passes — mirroring what Phase 2 will wire into save_invoice_to_db.
"""
import copy
import json
import os
from decimal import Decimal

from app.services.invoice_reconciler import reconcile_totals
from app.services.invoice_validator import validate_invoice

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "extractions")


def _load(name):
    with open(os.path.join(FIXTURES, f"{name}.json")) as fh:
        return json.load(fh)


def _apply_canonical(data, result):
    """Mimic Phase 2's wiring: feed the validator the reconciled net."""
    out = copy.deepcopy(data)
    out["total_ex_tax"] = float(result.canonical_net)
    return out


# ── IN391017: Wholesale settlement format → ties out, corrects mislabel, passes ──────────
def test_in391017_ties_corrects_and_passes():
    data = _load("in391017_wholesale_settlement")

    # As it reaches us today, the stated net is the GOODS VALUE → validator blocks (prod state).
    assert not validate_invoice(data).is_valid

    result = reconcile_totals(data)
    assert result.tied
    assert result.canonical_net == Decimal("1078.66")          # line-authority net
    assert result.corrected_from == Decimal("1551.31")          # goods-value mislabel corrected
    assert "lines" in result.anchors
    assert set(result.agreeing) == {"gross_minus_tax", "goods_minus_settlement"}

    # After applying the canonical net, the UNCHANGED validator passes.
    assert validate_invoice(_apply_canonical(data, result)).is_valid


# ── YESSS per-line discount: already correct → ties with NO override, still passes ───────
def test_yesss_per_line_unchanged_no_override():
    data = _load("yesss_per_line_discount")

    assert validate_invoice(data).is_valid                      # already valid today

    result = reconcile_totals(data)
    assert result.tied
    assert result.canonical_net == Decimal("500.00")
    assert result.corrected_from is None                        # stated net was already right
    assert result.agreeing == ["gross_minus_tax"]               # no settlement line on YESSS

    # Applying the (equal) canonical net is a no-op for the gate.
    assert validate_invoice(_apply_canonical(data, result)).is_valid


# ── Broken invoice: line-sum matches nothing → no tie, still blocks ──────────────────────
def test_broken_invoice_not_tied_and_blocks():
    data = _load("broken_inconsistent")

    result = reconcile_totals(data)
    assert not result.tied
    assert result.canonical_net is None
    assert "not confirmed" in result.reason

    # Reconciler is a no-op → validator blocks exactly as today.
    assert not validate_invoice(data).is_valid


# ── Tightening: two header anchors agree with each other but lines don't back them ───────
def test_headers_agree_but_lines_unbacked_must_not_tie():
    data = _load("headers_agree_lines_unbacked")

    # The two header anchors DO agree with each other...
    result = reconcile_totals(data)
    assert result.anchors["gross_minus_tax"] == Decimal("1000.00")
    assert result.anchors["goods_minus_settlement"] == Decimal("1000.00")
    assert result.anchors["lines"] == Decimal("800.00")

    # ...but without the line-sum backing them, it must NOT tie.
    assert not result.tied
    assert result.agreeing == []
    assert result.canonical_net is None

    # And the invoice still blocks at the gate.
    assert not validate_invoice(data).is_valid


# ── Tightening: line-sum entirely absent, even with two agreeing headers → no tie ────────
def test_line_sum_absent_must_not_tie():
    data = _load("headers_agree_lines_unbacked")
    data = copy.deepcopy(data)
    data["items"] = []                                          # remove the line authority

    result = reconcile_totals(data)
    assert not result.tied
    assert result.canonical_net is None
    assert "line-sum anchor absent" in result.reason


# ── Fail-closed: only the line-sum present, no independent stated total → no tie ─────────
def test_no_independent_anchor_does_not_tie():
    data = {
        "supplier": "Solo Lines Ltd",
        "invoice_number": "SOLO-1",
        "total_ex_tax": 300.00,
        "items": [
            {"part_number": "S1", "quantity": 1.0, "total_amount": 100.00},
            {"part_number": "S2", "quantity": 1.0, "total_amount": 200.00},
        ],
    }
    result = reconcile_totals(data)
    assert not result.tied
    assert "no independent stated total" in result.reason

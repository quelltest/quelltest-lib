"""Hand-written suite covering every guard in src/billing.py.

Deliberately placed in tests/integration/ (not tests/test_billing.py) so this
fixture also exercises recursive test discovery — spec10 §4.3. The pre-spec10
checker only looked in three fixed paths and found none of this.

Test names deliberately do NOT contain the target function names, so matching
must come from the call expressions in the bodies, not name substrings.
"""
import pytest
from src.billing import charge, refund


def test_rejects_non_positive_amounts():
    with pytest.raises(ValueError):
        charge(amount=0, currency="USD")


def test_rejects_unknown_currency():
    with pytest.raises(ValueError):
        charge(amount=100, currency="XYZ")


def test_accepts_supported_currency():
    assert charge(amount=100, currency="USD")["amount"] == 100


def test_reversal_requires_identifier():
    with pytest.raises(ValueError):
        refund(charge_id="", amount=50)


def test_reversal_rejects_non_positive():
    with pytest.raises(ValueError):
        refund(charge_id="ch_1", amount=0)

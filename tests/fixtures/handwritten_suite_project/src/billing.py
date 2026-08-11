"""Source with guard clauses, fully covered by a hand-written suite.

Fixture for the spec10 §4.1 regression: quelltest writes zero tests here, and
the score must still not be 0 — the existing suite covers every guard.
"""
from __future__ import annotations

SUPPORTED_CURRENCIES = ("USD", "EUR")


def charge(amount: int, currency: str) -> dict:
    """Charge an amount in a supported currency.

    Raises:
        ValueError: if amount is not positive or currency is unsupported.
    """
    if amount <= 0:
        raise ValueError("amount must be positive")
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError(f"unsupported currency: {currency}")
    return {"amount": amount, "currency": currency}


def refund(charge_id: str, amount: int) -> dict:
    """Refund part or all of a charge.

    Raises:
        ValueError: if charge_id is empty or amount is not positive.
    """
    if not charge_id:
        raise ValueError("charge_id is required")
    if amount <= 0:
        raise ValueError("refund amount must be positive")
    return {"charge_id": charge_id, "refunded": amount}

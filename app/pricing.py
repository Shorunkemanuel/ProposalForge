"""Deterministic, decimal-safe pricing.

All monetary arithmetic in ProposalForge happens here, in ordinary
application code. The AI provider never calculates or overrides these
values; it may only describe the figures this module produces.
"""

from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANTUM = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    """Round a Decimal to a two-decimal monetary value."""
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def calculate_pricing(
    hourly_rate: Decimal,
    estimated_hours: Decimal,
    expenses: Decimal,
) -> dict:
    """Return the authoritative pricing figures for a proposal.

    Labor cost = hourly rate x estimated hours.
    Total      = labor cost + expenses.
    """
    labor_cost = quantize_money(hourly_rate * estimated_hours)
    total = quantize_money(labor_cost + expenses)
    return {
        "hourly_rate": str(quantize_money(hourly_rate)),
        "estimated_hours": str(estimated_hours),
        "expenses": str(quantize_money(expenses)),
        "labor_cost": str(labor_cost),
        "total": str(total),
    }

import unittest
from decimal import Decimal

from app.pricing import calculate_pricing, quantize_money


class PricingTests(unittest.TestCase):
    def test_labor_cost_is_rate_times_hours(self):
        result = calculate_pricing(Decimal("85.00"), Decimal("40"), Decimal("0"))
        self.assertEqual(result["labor_cost"], "3400.00")

    def test_total_is_labor_plus_expenses(self):
        result = calculate_pricing(Decimal("85.00"), Decimal("40"), Decimal("250.00"))
        self.assertEqual(result["labor_cost"], "3400.00")
        self.assertEqual(result["total"], "3650.00")

    def test_fractional_rate_and_hours(self):
        result = calculate_pricing(Decimal("92.50"), Decimal("37.5"), Decimal("100.00"))
        self.assertEqual(result["labor_cost"], "3468.75")
        self.assertEqual(result["total"], "3568.75")

    def test_rounding_is_half_up_to_cents(self):
        result = calculate_pricing(Decimal("0.005"), Decimal("1"), Decimal("0"))
        self.assertEqual(result["labor_cost"], "0.01")

    def test_decimal_safe_no_float_error(self):
        # 0.1 + 0.2 style inputs must not drift.
        result = calculate_pricing(Decimal("0.1"), Decimal("3"), Decimal("0.2"))
        self.assertEqual(result["labor_cost"], "0.30")
        self.assertEqual(result["total"], "0.50")

    def test_zero_expenses_leaves_total_equal_to_labor(self):
        result = calculate_pricing(Decimal("50.00"), Decimal("10"), Decimal("0"))
        self.assertEqual(result["total"], result["labor_cost"])

    def test_quantize_money_half_up(self):
        self.assertEqual(str(quantize_money(Decimal("2.345"))), "2.35")
        self.assertEqual(str(quantize_money(Decimal("2.344"))), "2.34")


if __name__ == "__main__":
    unittest.main()

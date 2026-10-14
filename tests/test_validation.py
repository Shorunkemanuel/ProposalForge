import unittest
from decimal import Decimal

from app.validation import ValidationError, validate_proposal_input


def valid_payload(**overrides):
    payload = {
        "client_name": "Acme Corp",
        "brief": "Acme needs a marketing website for a spring launch.",
        "scope": "Design and build a five-page responsive marketing site.",
        "timeline": "Six weeks starting in November.",
        "hourly_rate": "85.00",
        "estimated_hours": "40",
        "expenses": "250.00",
        "currency": "usd",
    }
    payload.update(overrides)
    return payload


class ValidationTests(unittest.TestCase):
    def test_valid_inputs_normalized(self):
        result = validate_proposal_input(valid_payload())
        self.assertEqual(result["client_name"], "Acme Corp")
        self.assertEqual(result["hourly_rate"], Decimal("85.00"))
        self.assertEqual(result["estimated_hours"], Decimal("40"))
        self.assertEqual(result["expenses"], Decimal("250.00"))
        self.assertEqual(result["currency"], "USD")

    def test_missing_required_fields(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input({})
        for field in ("client_name", "brief", "scope", "timeline", "hourly_rate", "estimated_hours"):
            self.assertIn(field, ctx.exception.errors)

    def test_missing_required_field_single(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(brief=None))
        self.assertIn("brief", ctx.exception.errors)

    def test_text_too_short(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(brief="short"))
        self.assertIn("brief", ctx.exception.errors)

    def test_text_too_long(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(client_name="x" * 201))
        self.assertIn("client_name", ctx.exception.errors)

    def test_invalid_numeric_values(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(hourly_rate="abc", estimated_hours="4o"))
        self.assertIn("hourly_rate", ctx.exception.errors)
        self.assertIn("estimated_hours", ctx.exception.errors)

    def test_negative_rate_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(hourly_rate="-10"))
        self.assertIn("hourly_rate", ctx.exception.errors)

    def test_negative_hours_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(estimated_hours="-1"))
        self.assertIn("estimated_hours", ctx.exception.errors)

    def test_negative_expenses_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(expenses="-5"))
        self.assertIn("expenses", ctx.exception.errors)

    def test_bool_is_not_a_number(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(hourly_rate=True))
        self.assertIn("hourly_rate", ctx.exception.errors)

    def test_nan_and_infinity_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(hourly_rate="NaN"))
        self.assertIn("hourly_rate", ctx.exception.errors)

    def test_expenses_default_to_zero_when_absent(self):
        payload = valid_payload()
        del payload["expenses"]
        result = validate_proposal_input(payload)
        self.assertEqual(result["expenses"], Decimal("0"))

    def test_currency_must_be_three_letters(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(currency="DOLLARS"))
        self.assertIn("currency", ctx.exception.errors)

    def test_non_dict_payload_rejected(self):
        with self.assertRaises(ValidationError):
            validate_proposal_input(["not", "a", "dict"])

    def test_non_string_text_field_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(client_name={"nested": "object"}))
        self.assertIn("client_name", ctx.exception.errors)

    def test_numeric_text_field_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_proposal_input(valid_payload(brief=1234567890))
        self.assertIn("brief", ctx.exception.errors)


if __name__ == "__main__":
    unittest.main()

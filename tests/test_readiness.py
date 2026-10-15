import json
import unittest

from app.readiness import SECTIONS, evaluate_readiness

EXPENSES_FIELD = "expenses"


def valid_payload(**overrides):
    payload = {
        "client_name": "Acme Corp",
        "brief": "Acme needs a marketing website for a spring launch.",
        "scope": "Design and build a five-page responsive marketing site.",
        "timeline": "Six weeks starting in November.",
        "hourly_rate": "85.00",
        "estimated_hours": "40",
        "expenses": "250.00",
        "currency": "USD",
    }
    payload.update(overrides)
    return payload


def section_ids(report):
    return [section["id"] for section in report["sections"]]


def section(report, section_id):
    for item in report["sections"]:
        if item["id"] == section_id:
            return item
    raise AssertionError(f"missing section {section_id}")


class ReadinessTests(unittest.TestCase):
    def test_valid_input_is_ready(self):
        report = evaluate_readiness(valid_payload())
        self.assertTrue(report["ready"])
        self.assertEqual(report["complete_sections"], report["total_sections"])
        self.assertEqual(section_ids(report), ["brief", "scope", "timeline", "pricing"])
        for item in report["sections"]:
            self.assertTrue(item["complete"], item["id"])

    def test_empty_input_is_not_ready(self):
        report = evaluate_readiness({})
        self.assertFalse(report["ready"])
        self.assertEqual(report["complete_sections"], 0)
        for item in report["sections"]:
            self.assertFalse(item["complete"])

    def test_missing_brief_is_flagged_with_message(self):
        report = evaluate_readiness(valid_payload(brief=""))
        self.assertFalse(section(report, "brief")["complete"])
        self.assertFalse(report["ready"])

    def test_short_brief_is_flagged(self):
        report = evaluate_readiness(valid_payload(brief="too short"))
        brief = section(report, "brief")
        self.assertFalse(brief["complete"])
        messages = {i["field"]: i["message"] for i in brief["items"]}
        self.assertIn("brief", messages)
        self.assertTrue(messages["brief"])

    def test_missing_scope_marks_scope_incomplete(self):
        report = evaluate_readiness(valid_payload(scope="   "))
        self.assertFalse(section(report, "scope")["complete"])

    def test_missing_timeline_marks_timeline_incomplete(self):
        report = evaluate_readiness(valid_payload(timeline=None))
        self.assertFalse(section(report, "timeline")["complete"])

    def test_invalid_pricing_numbers_are_flagged(self):
        report = evaluate_readiness(
            valid_payload(hourly_rate="abc", estimated_hours="4o")
        )
        pricing = section(report, "pricing")
        self.assertFalse(pricing["complete"])
        fields = {i["field"]: i for i in pricing["items"]}
        self.assertFalse(fields["hourly_rate"]["complete"])
        self.assertFalse(fields["estimated_hours"]["complete"])
        self.assertTrue(fields["hourly_rate"]["message"])

    def test_negative_pricing_is_flagged(self):
        report = evaluate_readiness(valid_payload(hourly_rate="-1"))
        self.assertFalse(section(report, "pricing")["complete"])

    def test_invalid_currency_is_flagged(self):
        report = evaluate_readiness(valid_payload(currency="DOLLARS"))
        self.assertFalse(section(report, "pricing")["complete"])

    def test_absent_currency_is_ready(self):
        payload = valid_payload()
        del payload["currency"]
        self.assertTrue(evaluate_readiness(payload)["ready"])

    def test_absent_expenses_are_optional(self):
        payload = valid_payload()
        del payload[EXPENSES_FIELD]
        report = evaluate_readiness(payload)
        self.assertTrue(report["ready"])
        self.assertEqual(report["warnings"], [])

    def test_blank_expenses_are_optional(self):
        report = evaluate_readiness(valid_payload(expenses="   "))
        self.assertTrue(report["ready"])
        self.assertEqual(report["warnings"], [])

    def test_valid_optional_expenses_do_not_block_readiness(self):
        report = evaluate_readiness(valid_payload(expenses="250.00"))
        self.assertTrue(report["ready"])
        self.assertEqual(report["warnings"], [])

    def test_negative_expenses_block_readiness_with_warning(self):
        report = evaluate_readiness(valid_payload(expenses="-5"))
        self.assertFalse(report["ready"])
        self.assertEqual(len(report["warnings"]), 1)
        warning = report["warnings"][0]
        self.assertEqual(warning["field"], EXPENSES_FIELD)
        self.assertEqual(warning["label"], "Additional expenses")
        self.assertTrue(warning["message"])

    def test_negative_expenses_warning_does_not_break_other_sections(self):
        report = evaluate_readiness(valid_payload(expenses="-0.01"))
        self.assertFalse(report["ready"])
        # Every required section is still complete; only the optional expense
        # warning keeps the proposal not ready.
        self.assertEqual(report["complete_sections"], report["total_sections"])

    def test_correcting_expenses_clears_warning(self):
        payload = valid_payload(expenses="-5")
        self.assertFalse(evaluate_readiness(payload)["ready"])
        payload[EXPENSES_FIELD] = "5.00"
        report = evaluate_readiness(payload)
        self.assertTrue(report["ready"])
        self.assertEqual(report["warnings"], [])

    def test_expenses_are_not_a_checklist_item(self):
        report = evaluate_readiness(valid_payload())
        for item in report["sections"]:
            fields = {entry["field"] for entry in item["items"]}
            self.assertNotIn(EXPENSES_FIELD, fields)

    def test_non_dict_input_does_not_raise(self):
        report = evaluate_readiness(["not", "a", "dict"])
        self.assertFalse(report["ready"])
        self.assertFalse(report["sections"][0]["complete"])

    def test_report_is_json_serializable(self):
        self.assertIsInstance(json.dumps(evaluate_readiness(valid_payload())), str)
        self.assertIsInstance(
            json.dumps(evaluate_readiness(valid_payload(expenses="-5"))), str
        )

    def test_covers_every_required_server_field(self):
        # The checklist must not silently drop a field that server validation
        # marks required, otherwise a "ready" checklist could still fail.
        checked = {field for _, _, fields in SECTIONS for field, _ in fields}
        required = {
            "client_name",
            "brief",
            "scope",
            "timeline",
            "hourly_rate",
            "estimated_hours",
            "currency",
        }
        self.assertEqual(checked, required)

    def test_complete_count_advances_field_by_field(self):
        report = evaluate_readiness(valid_payload(brief="", scope=""))
        self.assertFalse(report["ready"])
        self.assertEqual(report["total_sections"], 4)
        self.assertLess(report["complete_sections"], report["total_sections"])


if __name__ == "__main__":
    unittest.main()

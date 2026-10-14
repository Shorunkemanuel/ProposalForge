import json
import unittest

from app.proposal import (
    REQUIRED_DRAFT_FIELDS,
    InvalidModelOutput,
    build_proposal,
    parse_model_output,
    validate_draft,
)
from app.providers import ProviderTimeout, ProviderUnavailable
from app.validation import ValidationError


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


def valid_draft(**overrides):
    draft = {
        "introduction": "Thank you for the opportunity.",
        "project_understanding": "A marketing site for the spring launch.",
        "proposed_approach": "Discovery, design, build, and launch.",
        "timeline": "Six weeks as supplied.",
        "relevant_experience": "Experience as supplied by the client.",
        "pricing_explanation": "Based on the supplied rate and hours.",
        "closing": "I look forward to working together.",
        "missing_information": ["Confirm the launch date."],
    }
    draft.update(overrides)
    return draft


class FakeProvider:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []

    def generate(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if self.error is not None:
            raise self.error
        return self.content


class BuildProposalTests(unittest.TestCase):
    def test_successful_generation_with_mocked_provider(self):
        provider = FakeProvider(content=json.dumps(valid_draft()))
        result = build_proposal(valid_payload(), provider)

        self.assertEqual(result["pricing"]["labor_cost"], "3400.00")
        self.assertEqual(result["pricing"]["total"], "3650.00")
        self.assertEqual(result["pricing"]["currency"], "USD")
        self.assertEqual(result["draft"]["introduction"], "Thank you for the opportunity.")
        self.assertEqual(result["draft"]["missing_information"], ["Confirm the launch date."])
        self.assertIn("AI-generated", result["notice"])

    def test_pricing_is_authoritative_when_model_conflicts(self):
        conflicting = valid_draft(total="9999.99", labor_cost="1.00", pricing={"total": "0"})
        provider = FakeProvider(content=json.dumps(conflicting))
        result = build_proposal(valid_payload(), provider)

        self.assertEqual(result["pricing"]["labor_cost"], "3400.00")
        self.assertEqual(result["pricing"]["total"], "3650.00")
        self.assertNotIn("total", result["draft"])
        self.assertNotIn("pricing", result["draft"])

    def test_prompt_contains_only_supplied_facts(self):
        provider = FakeProvider(content=json.dumps(valid_draft()))
        payload = valid_payload(internal_secret="do-not-leak")
        build_proposal(payload, provider)

        _, user_prompt = provider.calls[0]
        self.assertIn("Acme Corp", user_prompt)
        self.assertIn("3400.00", user_prompt)
        self.assertNotIn("do-not-leak", user_prompt)

    def test_invalid_input_never_calls_provider(self):
        provider = FakeProvider(content=json.dumps(valid_draft()))
        with self.assertRaises(ValidationError):
            build_proposal(valid_payload(hourly_rate="-1"), provider)
        self.assertEqual(provider.calls, [])

    def test_malformed_model_output_rejected(self):
        provider = FakeProvider(content="not valid json at all")
        with self.assertRaises(InvalidModelOutput):
            build_proposal(valid_payload(), provider)

    def test_missing_draft_field_rejected(self):
        draft = valid_draft()
        del draft["closing"]
        provider = FakeProvider(content=json.dumps(draft))
        with self.assertRaises(InvalidModelOutput):
            build_proposal(valid_payload(), provider)

    def test_empty_field_rejected(self):
        provider = FakeProvider(content=json.dumps(valid_draft(closing="   ")))
        with self.assertRaises(InvalidModelOutput):
            build_proposal(valid_payload(), provider)

    def test_provider_failure_propagates(self):
        provider = FakeProvider(error=ProviderUnavailable("down"))
        with self.assertRaises(ProviderUnavailable):
            build_proposal(valid_payload(), provider)

    def test_provider_timeout_propagates(self):
        provider = FakeProvider(error=ProviderTimeout("slow"))
        with self.assertRaises(ProviderTimeout):
            build_proposal(valid_payload(), provider)


class ParseAndValidateTests(unittest.TestCase):
    def test_parse_model_output_strips_code_fences(self):
        fenced = "```json\n" + json.dumps(valid_draft()) + "\n```"
        parsed = parse_model_output(fenced)
        self.assertIn("introduction", parsed)

    def test_parse_rejects_empty(self):
        with self.assertRaises(InvalidModelOutput):
            parse_model_output("   ")

    def test_parse_rejects_non_object(self):
        with self.assertRaises(InvalidModelOutput):
            parse_model_output("[1, 2, 3]")

    def test_validate_draft_requires_all_fields(self):
        draft = valid_draft()
        for field in REQUIRED_DRAFT_FIELDS:
            incomplete = dict(draft)
            del incomplete[field]
            with self.assertRaises(InvalidModelOutput):
                validate_draft(incomplete)

    def test_validate_draft_missing_information_must_be_list(self):
        with self.assertRaises(InvalidModelOutput):
            validate_draft(valid_draft(missing_information="not a list"))

    def test_validate_draft_missing_information_defaults_empty(self):
        draft = valid_draft()
        del draft["missing_information"]
        result = validate_draft(draft)
        self.assertEqual(result["missing_information"], [])

    def test_validate_draft_drops_unknown_keys(self):
        result = validate_draft(valid_draft(total="0.01", secret="x"))
        self.assertNotIn("total", result)
        self.assertNotIn("secret", result)


if __name__ == "__main__":
    unittest.main()

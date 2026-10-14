"""Proposal orchestration and model-output validation.

Ties the pipeline together:

    validate input -> calculate pricing -> ask provider -> validate draft

The provider only ever receives the facts the user supplied plus the
application-calculated pricing. The model's output is untrusted input and is
validated before it is shown. Any model-supplied pricing is discarded.
"""

import json
import re

from .pricing import calculate_pricing
from .validation import validate_proposal_input

REQUIRED_DRAFT_FIELDS = (
    "introduction",
    "project_understanding",
    "proposed_approach",
    "timeline",
    "relevant_experience",
    "pricing_explanation",
    "closing",
)

OPTIONAL_DRAFT_FIELDS = ("missing_information",)

MAX_DRAFT_FIELD_LEN = 12000

GENERATION_NOTICE = (
    "AI-generated draft. Review and edit before use. Pricing is calculated by "
    "ProposalForge and is authoritative; the AI only describes it. Verify all "
    "claims, dates, and figures before sending anything to a client."
)

SYSTEM_PROMPT = (
    "You are a careful freelance proposal drafting assistant. "
    "Write a proposal using ONLY the facts supplied in the request. "
    "Never invent work experience, credentials, client requirements, budgets, "
    "pricing, deadlines, guarantees, or commitments not supplied. "
    "Do not calculate or change pricing: restate the provided figures exactly. "
    "If information is missing, list concise questions instead of guessing.\n"
    "Respond with a single JSON object containing exactly these keys: "
    + ", ".join(f'"{field}"' for field in REQUIRED_DRAFT_FIELDS)
    + ', "missing_information". All keys are required; every value except '
    "'missing_information' must be a non-empty string. "
    "'missing_information' must be a JSON array of strings (possibly empty)."
)


class InvalidModelOutput(Exception):
    """Raised when the provider output is malformed or incomplete."""


def _build_user_prompt(normalized: dict, pricing: dict) -> str:
    supplied = {
        "client_name": normalized["client_name"],
        "brief": normalized["brief"],
        "scope": normalized["scope"],
        "timeline": normalized["timeline"],
        "currency": normalized["currency"],
        "hourly_rate": pricing["hourly_rate"],
        "estimated_hours": pricing["estimated_hours"],
        "expenses": pricing["expenses"],
        "labor_cost": pricing["labor_cost"],
        "total": pricing["total"],
    }
    return (
        "Draft a client proposal from these supplied facts. "
        "The pricing figures are authoritative and must be restated unchanged.\n"
        + json.dumps(supplied, ensure_ascii=False)
    )


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```[a-zA-Z0-9]*\s*(.*?)\s*```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def parse_model_output(content: str) -> dict:
    """Parse raw provider content into a JSON object. Raises on failure."""
    if not isinstance(content, str) or not content.strip():
        raise InvalidModelOutput("The AI provider returned an empty response.")
    try:
        parsed = json.loads(_strip_code_fences(content))
    except json.JSONDecodeError as exc:
        raise InvalidModelOutput(
            "The AI provider returned output that is not valid JSON."
        ) from exc
    if not isinstance(parsed, dict):
        raise InvalidModelOutput("The AI provider returned an unexpected structure.")
    return parsed


def validate_draft(raw: dict) -> dict:
    """Validate a parsed model response and return the clean draft.

    Unknown keys, including any model-supplied pricing, are dropped so they
    can never override the authoritative figures.
    """
    draft: dict = {}
    for field in REQUIRED_DRAFT_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise InvalidModelOutput(f"The AI response is missing '{field}'.")
        value = value.strip()
        if len(value) > MAX_DRAFT_FIELD_LEN:
            raise InvalidModelOutput(f"The AI response field '{field}' is too long.")
        draft[field] = value

    missing = raw.get("missing_information", [])
    if missing is None:
        missing = []
    if not isinstance(missing, list) or not all(isinstance(i, str) for i in missing):
        raise InvalidModelOutput(
            "'missing_information' must be a list of strings."
        )
    draft["missing_information"] = [item.strip() for item in missing if item.strip()]
    return draft


def build_proposal(data, provider) -> dict:
    """Run the full pipeline for one proposal request.

    Raises ValidationError for bad input, ProviderError subclasses for
    provider failures, and InvalidModelOutput for unusable model output.
    """
    normalized = validate_proposal_input(data)

    pricing = calculate_pricing(
        normalized["hourly_rate"],
        normalized["estimated_hours"],
        normalized["expenses"],
    )
    pricing["currency"] = normalized["currency"]

    content = provider.generate(SYSTEM_PROMPT, _build_user_prompt(normalized, pricing))
    draft = validate_draft(parse_model_output(content))

    return {
        "notice": GENERATION_NOTICE,
        "pricing": pricing,
        "draft": draft,
    }

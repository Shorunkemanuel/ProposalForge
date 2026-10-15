"""Input validation for client briefs.

Validation is intentionally strict and independent of any AI provider so it
can be unit-tested deterministically. Currency is never converted: a single
currency code is carried through the request unchanged.
"""

from decimal import Decimal, InvalidOperation

MAX_TEXT_LEN = 5000
MIN_BRIEF_LEN = 10
MIN_SCOPE_LEN = 10
MAX_NAME_LEN = 200
MAX_TIMELINE_LEN = 1000

TEXT_FIELDS = {
    "client_name": ("Client or project name", 1, MAX_NAME_LEN),
    "brief": ("Client brief", MIN_BRIEF_LEN, MAX_TEXT_LEN),
    "scope": ("Scope of work", MIN_SCOPE_LEN, MAX_TEXT_LEN),
    "timeline": ("Timeline or schedule", 1, MAX_TIMELINE_LEN),
}

NUMERIC_FIELDS = ("hourly_rate", "estimated_hours", "expenses")

DEFAULT_CURRENCY = "USD"


class ValidationError(Exception):
    """Raised when proposal input fails validation."""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__("Invalid proposal input")


def parse_non_negative_decimal(value):
    """Return ``(Decimal, None)`` or ``(None, message)``.

    Shared by validation and the readiness checklist so both agree on what a
    usable number is. The returned message is user-facing.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "This field is required."
    if isinstance(value, bool):
        return None, "Must be a number."
    try:
        if isinstance(value, str):
            parsed = Decimal(value.strip())
        elif isinstance(value, (int, float, Decimal)):
            parsed = Decimal(str(value))
        else:
            return None, "Must be a number."
    except (InvalidOperation, ValueError):
        return None, "Must be a valid number."
    if not parsed.is_finite():
        return None, "Must be a finite number."
    if parsed < 0:
        return None, "Must not be negative."
    return parsed, None


def _parse_decimal(value, field: str, errors: dict):
    parsed, message = parse_non_negative_decimal(value)
    if message is not None:
        errors[field] = message
        return None
    return parsed


def validate_proposal_input(data) -> dict:
    """Validate and normalize raw proposal input.

    Returns a normalized dict with Decimal monetary values and stripped
    text fields. Raises ValidationError with a field -> message mapping.
    """
    errors: dict = {}
    if not isinstance(data, dict):
        raise ValidationError({"_": "Request body must be a JSON object."})

    normalized: dict = {}

    for field, (label, min_len, max_len) in TEXT_FIELDS.items():
        raw = data.get(field)
        if raw is None:
            errors[field] = "This field is required."
            continue
        if not isinstance(raw, str):
            errors[field] = f"{label} must be text."
            continue
        value = raw.strip()
        if len(value) < min_len:
            errors[field] = f"{label} must be at least {min_len} characters."
        elif len(value) > max_len:
            errors[field] = f"{label} must be at most {max_len} characters."
        else:
            normalized[field] = value

    for field in NUMERIC_FIELDS:
        if field == "expenses" and field not in data:
            normalized[field] = Decimal("0")
            continue
        parsed = _parse_decimal(data.get(field), field, errors)
        if parsed is not None:
            normalized[field] = parsed

    currency = data.get("currency", DEFAULT_CURRENCY)
    currency = str(currency).strip().upper() if currency is not None else ""
    if len(currency) != 3 or not currency.isalpha():
        errors["currency"] = "Currency must be a 3-letter code (e.g. USD)."
    else:
        normalized["currency"] = currency

    if errors:
        raise ValidationError(errors)
    return normalized

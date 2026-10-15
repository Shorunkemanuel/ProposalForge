"""Deterministic proposal-readiness checklist.

Turns raw proposal input into a per-section completeness report so the UI can
tell the user what is still missing *before* a generation request is made.

This is ordinary application logic: no AI model is involved and no provider is
contacted. The checklist deliberately derives its field labels and length
thresholds from :mod:`app.validation` so it cannot drift from the server-side
validation that guards generation.

Expenses are optional. An omitted or valid expense never affects readiness,
but a supplied invalid expense (for example a negative amount) raises a
warning and keeps the proposal out of the ready state.
"""

from .validation import TEXT_FIELDS, parse_non_negative_decimal

# Section id -> (label, tuple of (field, kind)). ``kind`` selects the check.
# Only required inputs appear here; expenses are intentionally absent because
# they are optional.
SECTIONS = (
    (
        "brief",
        "Brief",
        (("client_name", "text"), ("brief", "text")),
    ),
    (
        "scope",
        "Scope & deliverables",
        (("scope", "text"),),
    ),
    (
        "timeline",
        "Timeline",
        (("timeline", "text"),),
    ),
    (
        "pricing",
        "Pricing",
        (
            ("hourly_rate", "number"),
            ("estimated_hours", "number"),
            ("currency", "currency"),
        ),
    ),
)

NUMBER_LABELS = {
    "hourly_rate": "Hourly rate",
    "estimated_hours": "Estimated hours",
    "currency": "Currency",
}

EXPENSES_FIELD = "expenses"
EXPENSES_LABEL = "Additional expenses"


def _text_state(value, min_len, max_len):
    """Return (complete, message) for a required text field."""
    if not isinstance(value, str):
        return False, "Enter text."
    stripped = value.strip()
    if not stripped:
        return False, "Required."
    if len(stripped) < min_len:
        return False, f"At least {min_len} characters."
    if len(stripped) > max_len:
        return False, f"At most {max_len} characters."
    return True, ""


def _number_state(value):
    """Return (complete, message) for a required non-negative number."""
    parsed, message = parse_non_negative_decimal(value)
    if message is not None:
        return False, message
    return True, ""


def _currency_state(data):
    """Return (complete, message) for the currency field.

    Matches server validation: an absent currency defaults to USD, while a
    present value must be a three-letter code.
    """
    if "currency" not in data:
        return True, ""
    value = data.get("currency")
    if value is None:
        return False, "Use a 3-letter code (e.g. USD)."
    code = str(value).strip().upper()
    if len(code) == 3 and code.isalpha():
        return True, ""
    return False, "Use a 3-letter code (e.g. USD)."


def _item_state(field, kind, data):
    if kind == "text":
        _label, min_len, max_len = TEXT_FIELDS[field]
        complete, message = _text_state(data.get(field), min_len, max_len)
    elif kind == "number":
        complete, message = _number_state(data.get(field))
    else:
        complete, message = _currency_state(data)
    return complete, message


def _expense_warning(data):
    """Return a warning message for a supplied-but-invalid expense, or None.

    Expenses are optional: an omitted or blank expense is not a warning. A
    supplied expense must parse as a non-negative finite number, reusing the
    same rule as server-side validation so the two cannot disagree.
    """
    if EXPENSES_FIELD not in data:
        return None
    value = data.get(EXPENSES_FIELD)
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    _parsed, message = parse_non_negative_decimal(value)
    return message


def evaluate_readiness(data) -> dict:
    """    Return a deterministic readiness report for raw proposal ``data``.

    The return value is JSON-serializable and has no provider dependency.
    Non-dict input is treated as entirely incomplete rather than raising.

    ``warnings`` lists optional inputs that were supplied but are invalid.
    A warning keeps ``ready`` false even when every section is complete.
    """
    if not isinstance(data, dict):
        data = {}

    sections = []
    complete_sections = 0
    total_fields = 0
    complete_fields = 0

    for section_id, section_label, fields in SECTIONS:
        items = []
        section_complete = True
        for field, kind in fields:
            label = TEXT_FIELDS[field][0] if kind == "text" else NUMBER_LABELS[field]
            complete, message = _item_state(field, kind, data)
            items.append(
                {
                    "field": field,
                    "label": label,
                    "complete": complete,
                    "message": message,
                }
            )
            total_fields += 1
            if complete:
                complete_fields += 1
            else:
                section_complete = False
        if section_complete:
            complete_sections += 1
        sections.append(
            {
                "id": section_id,
                "label": section_label,
                "complete": section_complete,
                "items": items,
            }
        )

    warnings = []
    expense_message = _expense_warning(data)
    if expense_message is not None:
        warnings.append(
            {
                "field": EXPENSES_FIELD,
                "label": EXPENSES_LABEL,
                "message": expense_message,
            }
        )

    return {
        "ready": complete_sections == len(SECTIONS) and not warnings,
        "complete_sections": complete_sections,
        "total_sections": len(SECTIONS),
        "complete_fields": complete_fields,
        "total_fields": total_fields,
        "warnings": warnings,
        "sections": sections,
    }

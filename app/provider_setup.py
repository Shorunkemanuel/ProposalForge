"""In-app AI provider setup (Milestone 4): settings, status, model discovery.

Hosted-first and database-free. Hosted BYOK is the primary setup path (a
hosted OpenAI-compatible endpoint with the user's own key); a local server
remains an explicitly selectable option. Provider configuration is seeded from
the environment and may be adjusted at runtime; runtime adjustments are held
in memory for this server process only and are never written to disk, a
database, or the browser. The API key, when set, is never returned to any
client — only the boolean ``has_api_key`` is exposed.

Pure handlers return ``(status_code, response_dict)`` so they can be
unit-tested without sockets. Error responses never include stack traces,
environment values, or raw provider payloads.
"""

import math
import os
import re
import threading
from urllib.parse import urlparse

from .providers import (
    CATEGORY_AUTH,
    CATEGORY_INVALID_CONFIG,
    CATEGORY_TIMEOUT,
    CATEGORY_UNREACHABLE,
    CATEGORY_UNSUPPORTED_PROVIDER,
    DEFAULT_PROVIDER,
    DEFAULT_TIMEOUT,
    MAX_MODEL_NAME_LEN,
    PRESETS,
    ProviderConfig,
    ProviderError,
    ProviderUnavailable,
    default_base_url_for,
    documented_models_for,
    get_provider,
)

# Probe (test/discovery) requests use a short timeout so the UI never hangs
# for the full generation timeout.
PROBE_TIMEOUT_CAP = 10.0

MAX_BASE_URL_LEN = 500
MAX_API_KEY_LEN = 4096

# Model names are path/tag-like across providers: Ollama uses tags such as
# "qwen2.5:0.5b", and hosted providers use ids such as
# "meta-llama/llama-3.3-70b-instruct".
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/:@+]*$")

# Passive statuses (no network): the configuration as it stands.
PASSIVE_CONFIGURED = "configured"
PASSIVE_MODEL_NOT_SELECTED = "model_not_selected"
PASSIVE_INVALID_CONFIG = "invalid_config"

# Active probe statuses (after a server-side connection test).
PROBE_READY = "ready"
PROBE_MODEL_NOT_SELECTED = "model_not_selected"
PROBE_MODEL_NOT_FOUND = "model_not_found"
PROBE_NO_MODELS_INSTALLED = "no_models_installed"
PROBE_UNREACHABLE = "unreachable"
PROBE_TIMEOUT = "timeout"
PROBE_AUTH = "auth_error"
PROBE_INVALID_CONFIG = "invalid_config"
PROBE_PROVIDER_ERROR = "provider_error"

# Sentinel: distinguish "field absent" from "field present and empty".
UNSET = object()


class ConfigValidationError(ValueError):
    """Raised for invalid provider configuration input.

    ``fields`` maps a field name to a user-safe message.
    """

    def __init__(self, fields):
        self.fields = dict(fields)
        super().__init__("Provider configuration input is invalid.")


def validate_base_url(raw):
    """Validate and normalize a user-supplied provider base URL.

    Only absolute http(s) URLs without embedded credentials or whitespace
    are accepted. Raises ConfigValidationError with a user-safe message.
    """
    if not isinstance(raw, str):
        raise ConfigValidationError(
            {"base_url": "Enter the provider base URL as text."}
        )
    value = raw.strip()
    if not value:
        raise ConfigValidationError(
            {
                "base_url": (
                    "Enter the provider base URL, for example "
                    "https://api.example.com."
                )
            }
        )
    if len(value) > MAX_BASE_URL_LEN:
        raise ConfigValidationError(
            {"base_url": f"The base URL must be at most {MAX_BASE_URL_LEN} characters."}
        )
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ConfigValidationError(
            {"base_url": "The base URL must not contain spaces or control characters."}
        )
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise ConfigValidationError(
            {"base_url": "The base URL must be a valid http:// or https:// URL."}
        )
    if parsed.username is not None or parsed.password is not None:
        raise ConfigValidationError(
            {
                "base_url": (
                    "Do not put credentials in the URL. Use the optional API "
                    "key field for hosted endpoints."
                )
            }
        )
    return value.rstrip("/")


def validate_model_name(raw):
    """Validate a model name; an empty string clears the selection."""
    if not isinstance(raw, str):
        raise ConfigValidationError({"model": "Enter the model name as text."})
    value = raw.strip()
    if not value:
        return ""
    if len(value) > MAX_MODEL_NAME_LEN:
        raise ConfigValidationError(
            {"model": f"The model name must be at most {MAX_MODEL_NAME_LEN} characters."}
        )
    if not MODEL_NAME_RE.match(value):
        raise ConfigValidationError(
            {
                "model": (
                    "The model name may only contain letters, numbers, and "
                    ". _ - / : @ + characters (for example qwen2.5:0.5b)."
                )
            }
        )
    return value


def validate_provider(raw):
    """Validate a provider preset id; must be one of the known presets."""
    if not isinstance(raw, str):
        raise ConfigValidationError({"provider": "Choose a provider from the list."})
    value = raw.strip().lower()
    known = {preset["id"] for preset in PRESETS}
    if value not in known:
        raise ConfigValidationError(
            {"provider": "Choose a provider from the list."}
        )
    return value


def validate_api_key(raw):
    """Validate an optional API key; an empty string clears it."""
    if not isinstance(raw, str):
        raise ConfigValidationError({"api_key": "Enter the API key as text."})
    value = raw.strip()
    if not value:
        return None
    if len(value) > MAX_API_KEY_LEN:
        raise ConfigValidationError(
            {"api_key": f"The API key must be at most {MAX_API_KEY_LEN} characters."}
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ConfigValidationError(
            {"api_key": "The API key must not contain control characters."}
        )
    return value


class ProviderSettings:
    """Process-scoped provider configuration.

    Seeded from environment variables. ``update()`` applies runtime changes
    held in memory only; nothing is persisted when the process stops, and the
    API key value is never exposed through ``describe()`` or ``snapshot()``.
    """

    def __init__(self, env=None):
        env = os.environ if env is None else env
        self._lock = threading.Lock()
        self._provider = env.get("PROPOSALFORGE_PROVIDER", DEFAULT_PROVIDER).strip().lower()
        base_url_raw = env.get("PROPOSALFORGE_BASE_URL")
        if base_url_raw is None or not base_url_raw.strip():
            self._base_url = default_base_url_for(self._provider)
        else:
            self._base_url = base_url_raw.strip()
        self._model = env.get("PROPOSALFORGE_MODEL", "").strip()
        self._api_key = env.get("PROPOSALFORGE_API_KEY") or None
        timeout_raw = env.get("PROPOSALFORGE_TIMEOUT", str(DEFAULT_TIMEOUT))
        try:
            timeout = float(timeout_raw)
        except ValueError:
            timeout = DEFAULT_TIMEOUT
        if not math.isfinite(timeout) or timeout <= 0:
            timeout = DEFAULT_TIMEOUT
        self._timeout = timeout
        self._source = "environment"

    @classmethod
    def from_env(cls, env=None) -> "ProviderSettings":
        return cls(env)

    def snapshot(self) -> ProviderConfig:
        """Return the current ProviderConfig. May raise ProviderUnavailable
        for an invalid base URL or unsupported provider kind (for example a
        bad PROPOSALFORGE_BASE_URL in the environment)."""
        with self._lock:
            return ProviderConfig(
                base_url=self._base_url,
                model=self._model,
                api_key=self._api_key,
                timeout=self._timeout,
                provider=self._provider,
            )

    def describe(self) -> dict:
        """Return a client-safe description. Never includes the API key."""
        with self._lock:
            return {
                "provider": self._provider,
                "base_url": self._base_url,
                "model": self._model,
                "has_api_key": self._api_key is not None,
                "timeout": self._timeout,
                "source": self._source,
            }

    def preview(self, provider=UNSET, base_url=UNSET, model=UNSET, api_key=UNSET):
        """Validate a candidate configuration without applying it.

        Returns ``(ProviderConfig, client_safe_desc)`` for the values the user
        is currently editing, so connection tests and model discovery can run
        before saving. Fields passed as UNSET fall back to the stored value.
        The stored settings are never modified, and the API key is never
        included in the returned description. Raises ConfigValidationError
        with per-field user-safe messages, or ProviderUnavailable if the
        resulting base URL is not a supported provider endpoint.
        """
        with self._lock:
            provider_val = self._provider
            base_url_val = self._base_url
            model_val = self._model
            api_key_val = self._api_key
            timeout_val = self._timeout
            source_val = self._source

        fields = {}
        if provider is not UNSET:
            try:
                provider_val = validate_provider(provider)
            except ConfigValidationError as exc:
                fields.update(exc.fields)
        if base_url is not UNSET:
            try:
                base_url_val = validate_base_url(base_url)
            except ConfigValidationError as exc:
                fields.update(exc.fields)
        if model is not UNSET:
            try:
                model_val = validate_model_name(model)
            except ConfigValidationError as exc:
                fields.update(exc.fields)
        if api_key is not UNSET:
            try:
                api_key_val = validate_api_key(api_key)
            except ConfigValidationError as exc:
                fields.update(exc.fields)
        if fields:
            raise ConfigValidationError(fields)

        config = ProviderConfig(
            base_url=base_url_val,
            model=model_val,
            api_key=api_key_val,
            timeout=timeout_val,
            provider=provider_val,
        )
        desc = {
            "provider": provider_val,
            "base_url": base_url_val,
            "model": model_val,
            "has_api_key": api_key_val is not None,
            "timeout": timeout_val,
            "source": source_val,
        }
        return config, desc

    def update(self, provider=UNSET, base_url=UNSET, model=UNSET, api_key=UNSET) -> dict:
        """Validate and apply a runtime (in-memory) configuration update.

        Fields passed as UNSET are left unchanged. Raises
        ConfigValidationError with per-field user-safe messages.
        """
        fields = {}
        new_provider = None
        new_base_url = None
        new_model = None
        new_api_key = UNSET

        if provider is not UNSET:
            try:
                new_provider = validate_provider(provider)
            except ConfigValidationError as exc:
                fields.update(exc.fields)
        if base_url is not UNSET:
            try:
                new_base_url = validate_base_url(base_url)
            except ConfigValidationError as exc:
                fields.update(exc.fields)
        if model is not UNSET:
            try:
                new_model = validate_model_name(model)
            except ConfigValidationError as exc:
                fields.update(exc.fields)
        if api_key is not UNSET:
            try:
                new_api_key = validate_api_key(api_key)
            except ConfigValidationError as exc:
                fields.update(exc.fields)

        if fields:
            raise ConfigValidationError(fields)

        with self._lock:
            if new_provider is not None:
                self._provider = new_provider
            if new_base_url is not None:
                self._base_url = new_base_url
            if new_model is not None:
                self._model = new_model
            if new_api_key is not UNSET:
                self._api_key = new_api_key
            if (
                provider is not UNSET
                or base_url is not UNSET
                or model is not UNSET
                or api_key is not UNSET
            ):
                self._source = "runtime"
            return {
                "provider": self._provider,
                "base_url": self._base_url,
                "model": self._model,
                "has_api_key": self._api_key is not None,
                "timeout": self._timeout,
                "source": self._source,
            }


def classify_config(config: ProviderConfig):
    """Passive classification of a validated configuration (no network)."""
    if not config.model:
        return (
            PASSIVE_MODEL_NOT_SELECTED,
            "No model is selected yet. Test the connection to see the models "
            "this endpoint offers, then choose one.",
        )
    return (
        PASSIVE_CONFIGURED,
        f"Configured to use '{config.model}' at {config.base_url}. "
        "Test the connection to verify it is reachable.",
    )


def classify_probe_error(exc: ProviderError, base_url: str):
    """Classify a probe failure into (status, user-safe message)."""
    category = getattr(exc, "category", "provider_error")
    if category == CATEGORY_TIMEOUT:
        return (
            PROBE_TIMEOUT,
            f"The provider at {base_url} did not respond within the time "
            "limit. The service may be busy or unreachable; try again, or "
            "raise PROPOSALFORGE_TIMEOUT.",
        )
    if category == CATEGORY_AUTH:
        return (
            PROBE_AUTH,
            f"The provider at {base_url} rejected the request (HTTP 401/403). "
            "For a hosted endpoint this usually means the API key is missing, "
            "incorrect, or does not have access. Check the API key and try "
            "again.",
        )
    if category == CATEGORY_UNREACHABLE:
        return (
            PROBE_UNREACHABLE,
            f"Could not reach the provider at {base_url}. Check that the "
            "service is running and reachable, or correct the base URL.",
        )
    if category in (CATEGORY_INVALID_CONFIG, CATEGORY_UNSUPPORTED_PROVIDER):
        return PROBE_INVALID_CONFIG, str(exc)
    return PROBE_PROVIDER_ERROR, str(exc)


def classify_probe_models(model: str, base_url: str, models: list, documented=()):
    """Classify a successful model-list probe into (status, message).

    ``documented`` lists identifiers that are valid for the preset even when
    the endpoint's discovery does not return them (for example OpenRouter's
    automatic router). Such a selection is treated as usable rather than
    "not found"; the identifier carries no billing meaning.
    """
    if model and model in documented and model not in models:
        # A documented router identifier (for example OpenRouter's
        # "openrouter/free") is usable even when discovery does not list it,
        # including when discovery returns no models at all.
        return (
            PROBE_READY,
            f"Connected to {base_url}. '{model}' is a documented identifier "
            "for this provider; it will be sent as-is.",
        )
    if not models:
        if model:
            return (
                PROBE_NO_MODELS_INSTALLED,
                f"Connected to {base_url}, but it reports no models. Check "
                "that the endpoint is the right one and offers a model, or "
                "choose a model you know is available.",
            )
        return (
            PROBE_NO_MODELS_INSTALLED,
            f"Connected to {base_url}, but it reports no models. Check that "
            "the endpoint is the right one, then try again.",
        )
    if not model:
        return (
            PROBE_MODEL_NOT_SELECTED,
            f"Connected to {base_url}, but no model is selected. Choose one "
            "of the available models and save.",
        )
    if model not in models:
        return (
            PROBE_MODEL_NOT_FOUND,
            f"Connected to {base_url}, but the selected model '{model}' is "
            "not available there. Choose one of the available models.",
        )
    return (
        PROBE_READY,
        f"Connected to {base_url}. Model '{model}' is available.",
    )


def _presets_payload():
    """Client-safe preset list so the UI and server agree on protocol/bases."""
    return [
        {
            "id": preset["id"],
            "label": preset["label"],
            "base_url": preset["base_url"],
            "requires_key": preset["requires_key"],
            "key_hint": preset["key_hint"],
            "model_hint": preset["model_hint"],
            "documented_models": list(preset["documented_models"]),
            "auto_model": preset["auto_model"],
            "auto_model_label": preset["auto_model_label"],
        }
        for preset in PRESETS
    ]


def _payload(desc, status, message, models=None):
    return {
        "provider": desc["provider"],
        "base_url": desc["base_url"],
        "model": desc["model"],
        "has_api_key": desc["has_api_key"],
        "source": desc["source"],
        "scope": "runtime",
        "status": status,
        "message": message,
        "models": models,
        "presets": _presets_payload(),
    }


def _passive_report(settings):
    desc = settings.describe()
    try:
        config = settings.snapshot()
    except ProviderUnavailable as exc:
        return desc, PASSIVE_INVALID_CONFIG, str(exc)
    status, message = classify_config(config)
    return desc, status, message


def _probe_overrides(payload):
    """Map an optional probe request body to ``preview`` keyword overrides.

    Lets the UI test or discover the values currently in the form before they
    are saved. An absent field falls back to the stored value. An empty
    ``api_key`` means "use the saved key", not "clear it", so a user who
    already saved a key can retry without re-typing it.
    """
    overrides = {}
    if not isinstance(payload, dict):
        return overrides
    if "provider" in payload:
        overrides["provider"] = payload["provider"]
    if "base_url" in payload:
        overrides["base_url"] = payload["base_url"]
    if "model" in payload:
        overrides["model"] = payload["model"]
    api_key = payload.get("api_key")
    if isinstance(api_key, str) and api_key.strip():
        overrides["api_key"] = api_key
    return overrides


def process_provider_status(settings):
    """Passive status handler: (status_code, response_dict). No network."""
    desc, status, message = _passive_report(settings)
    return 200, _payload(desc, status, message)


def process_provider_test(settings, payload=None, probe_timeout=PROBE_TIMEOUT_CAP):
    """Active connection test: (status_code, response_dict).

    Always returns 200 with a classified status; the probe itself is the
    operation under test. When ``payload`` supplies provider/base_url/model
    (and optionally api_key) fields, the probe runs against those values so
    the form can be tested before saving; nothing is persisted. Provider
    models are included when the endpoint could be reached.
    """
    try:
        config, desc = settings.preview(**_probe_overrides(payload))
    except ConfigValidationError as exc:
        saved = settings.describe()
        body = _payload(
            saved,
            PROBE_INVALID_CONFIG,
            "Some provider settings are invalid. Review the highlighted fields.",
        )
        body["fields"] = exc.fields
        return 200, body
    except ProviderUnavailable as exc:
        saved = settings.describe()
        return 200, _payload(saved, PROBE_INVALID_CONFIG, str(exc))

    try:
        provider = get_provider(config)
        models = provider.list_models(timeout=min(config.timeout, probe_timeout))
    except ProviderError as exc:
        status, message = classify_probe_error(exc, config.base_url)
        return 200, _payload(desc, status, message)
    status, message = classify_probe_models(
        config.model,
        config.base_url,
        models,
        documented=documented_models_for(config.provider),
    )
    return 200, _payload(desc, status, message, models=models)


def process_provider_models(settings, payload=None, probe_timeout=PROBE_TIMEOUT_CAP):
    """Model-discovery handler: (status_code, response_dict).

    Queries the requested (or stored) provider endpoint server-side for its
    available models, without saving the request values. Invalid
    configuration returns 400, a timeout 504, an authentication rejection
    401, and other provider failures 502 — each with a safe, actionable
    message.
    """
    try:
        config, desc = settings.preview(**_probe_overrides(payload))
    except ConfigValidationError as exc:
        return 400, {
            "error": "invalid_config",
            "fields": exc.fields,
            "message": "Some provider settings are invalid.",
            "models": None,
        }
    except ProviderUnavailable as exc:
        return 400, {
            "error": "invalid_config",
            "message": str(exc),
            "models": None,
        }
    try:
        provider = get_provider(config)
        models = provider.list_models(timeout=min(config.timeout, probe_timeout))
    except ProviderError as exc:
        status, message = classify_probe_error(exc, config.base_url)
        error_code = {
            PROBE_TIMEOUT: "provider_timeout",
            PROBE_AUTH: "provider_auth",
            PROBE_INVALID_CONFIG: "invalid_config",
            PROBE_UNREACHABLE: "provider_unavailable",
        }.get(status, "provider_error")
        http_status = {
            PROBE_TIMEOUT: 504,
            PROBE_AUTH: 401,
            PROBE_INVALID_CONFIG: 400,
        }.get(status, 502)
        return http_status, {
            "error": error_code,
            "category": status,
            "message": message,
            "models": None,
        }
    return 200, {
        "models": models,
        "count": len(models),
        "base_url": config.base_url,
        "provider": config.provider,
    }


def process_provider_config(settings, payload):
    """Apply a runtime configuration update: (status_code, response_dict).

    Updates are in-memory and process-scoped. Absent fields are left
    unchanged; an empty string clears the model or API key.
    """
    if not isinstance(payload, dict):
        return 400, {
            "error": "invalid_config",
            "message": "Expected a JSON object with base_url, model, or api_key.",
        }
    fields = {}
    kwargs = {}
    if "provider" in payload:
        kwargs["provider"] = payload["provider"]
    if "base_url" in payload:
        kwargs["base_url"] = payload["base_url"]
    if "model" in payload:
        kwargs["model"] = payload["model"]
    if "api_key" in payload:
        kwargs["api_key"] = payload["api_key"]
    try:
        settings.update(**kwargs)
    except ConfigValidationError as exc:
        return 400, {
            "error": "invalid_config",
            "fields": exc.fields,
            "message": "Some provider settings are invalid. Fix the highlighted fields.",
        }

    desc, status, message = _passive_report(settings)
    return 200, _payload(
        desc,
        status,
        "Settings applied to this running server only (in memory; lost when "
        f"it stops). {message}",
    )

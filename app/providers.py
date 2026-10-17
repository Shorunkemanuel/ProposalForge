"""AI provider adapter.

The adapter speaks one of two wire protocols over HTTP (see ``PRESETS``):
the native Ollama API, or the widely used OpenAI-compatible API. Everything
is configured through environment variables so no endpoint, model name, or
secret is hard-coded in the source:

    PROPOSALFORGE_PROVIDER    preset id: ollama, openrouter, openai, gemini,
                              ollama-cloud, or custom (default: openrouter)
    PROPOSALFORGE_BASE_URL    endpoint base URL (default: the preset's
                              documented URL)
    PROPOSALFORGE_MODEL       model name (required)
    PROPOSALFORGE_API_KEY     optional bearer token
    PROPOSALFORGE_TIMEOUT     request timeout in seconds (default: 600)

Each preset expects the API key issued **by that provider**; a key from one
provider does not authenticate with another. Secrets are read from the
environment only and are never logged or returned to the client.
"""

import json
import math
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
# Hosted BYOK is the primary product path, so the default preset is a hosted
# OpenAI-compatible gateway rather than a local server. A local Ollama server
# remains available by explicitly selecting the "ollama" preset (or setting
# PROPOSALFORGE_PROVIDER=ollama).
DEFAULT_PROVIDER = "openrouter"
# Socket timeout for provider requests. This is used for proposal generation,
# which is a single non-streaming request: with "stream": false nothing is
# read from the socket until the whole completion is generated, so this
# timeout must cover the full generation, not just a connection handshake.
# A CPU-only local model can take minutes for the full multi-section JSON
# draft (a tiny prompt already measured ~21s on Android/Termux), so the
# default is intentionally generous while staying bounded. Fast metadata
# probes use their own short cap (see PROBE_TIMEOUT_CAP in provider_setup.py).
DEFAULT_TIMEOUT = 600.0
ALLOWED_URL_SCHEMES = ("http", "https")

# Bounds for a model-list response (/api/tags or /models) so a hostile or
# broken endpoint cannot exhaust memory or flood the UI.
MAX_LIST_RESPONSE_BYTES = 2_000_000
MAX_LISTED_MODELS = 200
MAX_MODEL_NAME_LEN = 200

# Two wire protocols are supported. "ollama" is the native Ollama HTTP API
# (/api/chat + /api/tags). "openai" is the widely implemented OpenAI-compatible
# API (POST /chat/completions + GET /models) used by OpenRouter, OpenAI, the
# Google AI Studio Gemini endpoint, Ollama Cloud, and most self-hosted gateways.
API_FORMAT_OLLAMA = "ollama"
API_FORMAT_OPENAI = "openai"

# Provider presets offered by the in-app setup. This registry is the single
# source of truth for the wire protocol of each preset; the UI reads it from
# the provider status response so the browser and the server cannot disagree.
#
# "documented_models" are identifiers a user may legitimately select even when
# the endpoint's model discovery does not list them (OpenRouter's automatic
# router is the current case). They are never invented for the user, and the
# identifier is a documented router name — no billing status is inferred from
# the model name.
PRESETS = (
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_format": API_FORMAT_OPENAI,
        "requires_key": True,
        "key_hint": "Use an API key issued to your own OpenRouter account.",
        "model_hint": (
            "An OpenRouter model ID such as 'meta-llama/llama-3.3-70b-instruct', "
            "or 'openrouter/free' for OpenRouter's automatic routing. Which "
            "models you can use depends on your OpenRouter account."
        ),
        "documented_models": ("openrouter/free",),
        "auto_model": "openrouter/free",
        "auto_model_label": "Use OpenRouter automatic router (openrouter/free)",
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "api_format": API_FORMAT_OPENAI,
        "requires_key": True,
        "key_hint": "Use an API key issued to your own OpenAI account.",
        "model_hint": "A model ID from your OpenAI account, for example 'gpt-4o-mini'.",
        "documented_models": (),
        "auto_model": "",
        "auto_model_label": "",
    },
    {
        "id": "gemini",
        "label": "Google AI Studio (Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_format": API_FORMAT_OPENAI,
        "requires_key": True,
        "key_hint": "Use a Gemini API key issued in Google AI Studio.",
        "model_hint": "A Gemini model ID, for example 'gemini-2.5-flash'.",
        "documented_models": (),
        "auto_model": "",
        "auto_model_label": "",
    },
    {
        "id": "ollama-cloud",
        "label": "Ollama Cloud",
        "base_url": "https://ollama.com/v1",
        "api_format": API_FORMAT_OPENAI,
        "requires_key": True,
        "key_hint": "Use an API key issued in your Ollama account.",
        "model_hint": "A cloud model identifier, for example 'gemma4:31b'.",
        "documented_models": (),
        "auto_model": "",
        "auto_model_label": "",
    },
    {
        "id": "custom",
        "label": "Custom compatible endpoint",
        "base_url": "",
        "api_format": API_FORMAT_OPENAI,
        "requires_key": False,
        "key_hint": "Only if your own endpoint requires one.",
        "model_hint": "Any model identifier your endpoint accepts.",
        "documented_models": (),
        "auto_model": "",
        "auto_model_label": "",
    },
    {
        "id": "ollama",
        "label": "Ollama (local or native API)",
        "base_url": "http://127.0.0.1:11434",
        "api_format": API_FORMAT_OLLAMA,
        "requires_key": False,
        "key_hint": "A local Ollama server does not use a key.",
        "model_hint": "A model installed locally, for example 'qwen3:0.6b'.",
        "documented_models": (),
        "auto_model": "",
        "auto_model_label": "",
    },
)

PRESET_BY_ID = {preset["id"]: preset for preset in PRESETS}


def preset_for(provider) -> dict:
    """Return the preset dict for a provider id.

    Raises ProviderUnavailable for an unknown kind so a bad environment value
    or a hand-edited request cannot reach a provider call.
    """
    preset = PRESET_BY_ID.get(provider)
    if preset is None:
        raise ProviderUnavailable(
            f"Unsupported provider '{provider}'. Choose one of: "
            + ", ".join(sorted(PRESET_BY_ID))
            + ".",
            CATEGORY_UNSUPPORTED_PROVIDER,
        )
    return preset


def documented_models_for(provider) -> tuple:
    """Identifiers the UI may offer for a preset without model discovery."""
    if provider not in PRESET_BY_ID:
        return ()
    return PRESET_BY_ID[provider]["documented_models"]


def default_base_url_for(provider) -> str:
    """Documented base URL for a preset, or the local default as a fallback.

    Used to seed the base URL when only the provider is configured, so a
    hosted preset does not silently inherit the local Ollama address (and
    vice versa). An unknown preset falls back to the local default; the
    provider itself is still validated when the config is built.
    """
    preset = PRESET_BY_ID.get(provider)
    if preset and preset["base_url"]:
        return preset["base_url"]
    return DEFAULT_BASE_URL


# Failure categories used by the status/diagnostics endpoints to classify
# errors without leaking raw exceptions, stack traces, or secrets.
CATEGORY_TIMEOUT = "timeout"
CATEGORY_UNREACHABLE = "unreachable"
CATEGORY_HTTP_ERROR = "http_error"
# 401/403 from the endpoint: the API key is missing, wrong, or not allowed.
# Only the status code is used; no request headers or secrets are surfaced.
CATEGORY_AUTH = "auth_error"
CATEGORY_INVALID_RESPONSE = "invalid_response"
CATEGORY_INVALID_CONFIG = "invalid_config"
CATEGORY_UNSUPPORTED_PROVIDER = "unsupported_provider"
CATEGORY_NO_MODEL = "no_model"


class ProviderError(Exception):
    """Base class for provider failures safe to surface to the user.

    ``category`` is a stable, non-sensitive identifier used by the status
    endpoints; ``str(exc)`` stays a user-safe message.
    """

    def __init__(self, message, category="provider_error"):
        super().__init__(message)
        self.category = category


class ProviderUnavailable(ProviderError):
    """The provider endpoint could not be reached or returned an error."""


class ProviderTimeout(ProviderError):
    """The provider did not respond within the configured timeout."""

    def __init__(self, message, category=CATEGORY_TIMEOUT):
        super().__init__(message, category)


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    provider: str = DEFAULT_PROVIDER

    @classmethod
    def from_env(cls, env=None) -> "ProviderConfig":
        env = os.environ if env is None else env
        provider = env.get("PROPOSALFORGE_PROVIDER", DEFAULT_PROVIDER).strip().lower()
        base_url_raw = env.get("PROPOSALFORGE_BASE_URL")
        if base_url_raw is None or not base_url_raw.strip():
            base_url = default_base_url_for(provider)
        else:
            base_url = base_url_raw.strip()
        model = env.get("PROPOSALFORGE_MODEL", "").strip()
        api_key = env.get("PROPOSALFORGE_API_KEY") or None
        timeout_raw = env.get("PROPOSALFORGE_TIMEOUT", str(DEFAULT_TIMEOUT))
        try:
            timeout = float(timeout_raw)
        except ValueError:
            timeout = DEFAULT_TIMEOUT
        if not math.isfinite(timeout) or timeout <= 0:
            timeout = DEFAULT_TIMEOUT
        return cls(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout=timeout,
            provider=provider,
        )

    def __post_init__(self):
        scheme = urlparse(self.base_url).scheme.lower()
        if scheme not in ALLOWED_URL_SCHEMES:
            raise ProviderUnavailable(
                "PROPOSALFORGE_BASE_URL must be an http:// or https:// URL.",
                CATEGORY_INVALID_CONFIG,
            )
        if self.provider not in PRESET_BY_ID:
            raise ProviderUnavailable(
                f"Unsupported provider '{self.provider}'. Choose one of: "
                + ", ".join(sorted(PRESET_BY_ID))
                + ".",
                CATEGORY_UNSUPPORTED_PROVIDER,
            )

    @property
    def api_format(self) -> str:
        """Wire protocol for this preset: "ollama" or "openai"."""
        return PRESET_BY_ID[self.provider]["api_format"]


def normalize_model_names(envelope) -> list[str]:
    """Extract a normalized model-name list from an Ollama /api/tags payload.

    Non-dict entries, non-string names, empty names, and names longer than
    MAX_MODEL_NAME_LEN are dropped. The result is de-duplicated, sorted, and
    capped at MAX_LISTED_MODELS so a hostile endpoint cannot flood the UI.
    A payload without a usable "models" list is treated as an unexpected
    response shape.
    """
    if not isinstance(envelope, dict):
        raise ProviderUnavailable(
            "The AI provider returned an unexpected response shape.",
            CATEGORY_INVALID_RESPONSE,
        )
    models = envelope.get("models")
    if not isinstance(models, list):
        raise ProviderUnavailable(
            "The AI provider returned an unexpected response shape.",
            CATEGORY_INVALID_RESPONSE,
        )
    names: set[str] = set()
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str):
            name = entry.get("model")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not name or len(name) > MAX_MODEL_NAME_LEN:
            continue
        names.add(name)
    return sorted(names)[:MAX_LISTED_MODELS]


def normalize_openai_model_names(envelope) -> list[str]:
    """Extract model ids from an OpenAI-compatible GET /models payload.

    The documented shape is ``{"data": [{"id": ...}]}``. Some gateways instead
    return Ollama-style ``{"models": [{"name"|"id"|"model": ...}]}``, so that
    shape is accepted too. The same bounds, de-duplication, sorting, and
    unexpected-shape handling as :func:`normalize_model_names` apply.
    """
    if not isinstance(envelope, dict):
        raise ProviderUnavailable(
            "The AI provider returned an unexpected response shape.",
            CATEGORY_INVALID_RESPONSE,
        )
    entries = envelope.get("data")
    if not isinstance(entries, list):
        entries = envelope.get("models")
    if not isinstance(entries, list):
        raise ProviderUnavailable(
            "The AI provider returned an unexpected response shape.",
            CATEGORY_INVALID_RESPONSE,
        )
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("id")
        if not isinstance(name, str):
            name = entry.get("name")
        if not isinstance(name, str):
            name = entry.get("model")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not name or len(name) > MAX_MODEL_NAME_LEN:
            continue
        names.add(name)
    return sorted(names)[:MAX_LISTED_MODELS]


def _classify_http_error(exc):
    """Map an endpoint HTTP error to a safe, classified ProviderUnavailable.

    401/403 are reported as an authentication problem because a hosted,
    key-authenticated endpoint uses them to reject a missing or wrong key. The
    message repeats only the status code and generic guidance — never the key,
    the Authorization header, or any request detail.
    """
    if exc.code in (401, 403):
        return ProviderUnavailable(
            f"The provider rejected the request (HTTP {exc.code}). For a "
            "hosted endpoint this usually means the API key is missing, "
            "incorrect, or does not have access. Check the API key and try "
            "again.",
            CATEGORY_AUTH,
        )
    return ProviderUnavailable(
        f"The AI provider returned an error (HTTP {exc.code}).",
        CATEGORY_HTTP_ERROR,
    )


class OllamaProvider:
    """HTTP client for the supported provider wire protocols.

    Despite the historical name, this one implementation speaks both the
    native Ollama API and the OpenAI-compatible API used by the hosted
    presets; the wire protocol is chosen by the config's ``api_format``.
    """

    def __init__(self, config: ProviderConfig):
        self.config = config

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Send a chat request and return the raw assistant content string."""
        if not self.config.model:
            raise ProviderUnavailable(
                "No model is configured. Set PROPOSALFORGE_MODEL.",
                CATEGORY_NO_MODEL,
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if self.config.api_format == API_FORMAT_OPENAI:
            # OpenAI-compatible chat completions. No JSON-mode parameter is
            # sent: it is not implemented identically everywhere, so the
            # prompt plus the application's own JSON parsing (which strips
            # code fences) is the portable path.
            url = self.config.base_url.rstrip("/") + "/chat/completions"
            payload = {
                "model": self.config.model,
                "messages": messages,
                "stream": False,
            }
        else:
            # Native Ollama chat; "format": "json" makes the server emit JSON.
            url = self.config.base_url.rstrip("/") + "/api/chat"
            payload = {
                "model": self.config.model,
                "messages": messages,
                "stream": False,
                "format": "json",
            }
        body = json.dumps(payload).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                raw = response.read().decode("utf-8")
        except socket.timeout as exc:
            raise ProviderTimeout("The AI provider timed out.") from exc
        except urllib.error.HTTPError as exc:
            raise _classify_http_error(exc) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, socket.timeout):
                raise ProviderTimeout("The AI provider timed out.") from exc
            raise ProviderUnavailable(
                "The AI provider is unavailable.", CATEGORY_UNREACHABLE
            ) from exc
        except (ConnectionError, OSError) as exc:
            raise ProviderUnavailable(
                "The AI provider is unavailable.", CATEGORY_UNREACHABLE
            ) from exc

        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(
                "The AI provider returned an unreadable response.",
                CATEGORY_INVALID_RESPONSE,
            ) from exc

        content = self._extract_content(envelope)
        if content is None:
            raise ProviderUnavailable(
                "The AI provider returned an unexpected response shape.",
                CATEGORY_INVALID_RESPONSE,
            )
        return content

    def list_models(self, timeout: float | None = None) -> list[str]:
        """Query the provider's model list and return model identifiers.

        Uses GET /models for OpenAI-compatible presets and GET /api/tags for
        the native Ollama API. Returns a normalized, sorted, de-duplicated
        list of non-empty names. Raises ProviderTimeout/ProviderUnavailable
        with a safe category on any failure. The request is made server-side
        so the browser never performs cross-origin requests to the provider.
        """
        if self.config.api_format == API_FORMAT_OPENAI:
            url = self.config.base_url.rstrip("/") + "/models"
        else:
            url = self.config.base_url.rstrip("/") + "/api/tags"
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if timeout is None:
            timeout = self.config.timeout

        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(MAX_LIST_RESPONSE_BYTES + 1)
        except socket.timeout as exc:
            raise ProviderTimeout("The AI provider timed out.") from exc
        except urllib.error.HTTPError as exc:
            raise _classify_http_error(exc) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, socket.timeout):
                raise ProviderTimeout("The AI provider timed out.") from exc
            raise ProviderUnavailable(
                "The AI provider is unavailable.", CATEGORY_UNREACHABLE
            ) from exc
        except (ConnectionError, OSError) as exc:
            raise ProviderUnavailable(
                "The AI provider is unavailable.", CATEGORY_UNREACHABLE
            ) from exc

        if len(raw) > MAX_LIST_RESPONSE_BYTES:
            raise ProviderUnavailable(
                "The AI provider returned an unreadable response.",
                CATEGORY_INVALID_RESPONSE,
            )
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderUnavailable(
                "The AI provider returned an unreadable response.",
                CATEGORY_INVALID_RESPONSE,
            ) from exc
        if self.config.api_format == API_FORMAT_OPENAI:
            return normalize_openai_model_names(envelope)
        return normalize_model_names(envelope)

    def _extract_content(self, envelope):
        if self.config.api_format == API_FORMAT_OPENAI:
            return _extract_openai_content(envelope)
        if not isinstance(envelope, dict):
            return None
        message = envelope.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        if isinstance(envelope.get("response"), str):
            return envelope["response"]
        return None


def _extract_openai_content(envelope):
    """Read choices[0].message.content from an OpenAI-compatible envelope."""
    if not isinstance(envelope, dict):
        return None
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None


def get_provider(config: ProviderConfig | None = None) -> OllamaProvider:
    """Build the configured provider for any supported preset.

    Supports the native Ollama API and OpenAI-compatible presets (OpenRouter,
    OpenAI, Google AI Studio Gemini, Ollama Cloud, custom endpoints). Raises
    ProviderUnavailable for an unknown kind.
    """
    config = config or ProviderConfig.from_env()
    preset_for(config.provider)
    return OllamaProvider(config)

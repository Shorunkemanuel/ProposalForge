"""AI provider adapter.

The adapter speaks the Ollama-compatible chat API over HTTP. Everything is
configured through environment variables so no endpoint, model name, or
secret is hard-coded in the source:

    PROPOSALFORGE_PROVIDER    provider kind (only "ollama" is supported)
    PROPOSALFORGE_BASE_URL    endpoint base URL (default: local Ollama)
    PROPOSALFORGE_MODEL       model name (required)
    PROPOSALFORGE_API_KEY     optional bearer token
    PROPOSALFORGE_TIMEOUT     request timeout in seconds (default: 60)

Secrets are read from the environment only and are never logged or
returned to the client.
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
DEFAULT_TIMEOUT = 60.0
ALLOWED_URL_SCHEMES = ("http", "https")


class ProviderError(Exception):
    """Base class for provider failures safe to surface to the user."""


class ProviderUnavailable(ProviderError):
    """The provider endpoint could not be reached or returned an error."""


class ProviderTimeout(ProviderError):
    """The provider did not respond within the configured timeout."""


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    provider: str = "ollama"

    @classmethod
    def from_env(cls, env=None) -> "ProviderConfig":
        env = os.environ if env is None else env
        provider = env.get("PROPOSALFORGE_PROVIDER", "ollama").strip().lower()
        base_url = env.get("PROPOSALFORGE_BASE_URL", DEFAULT_BASE_URL).strip()
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
                "PROPOSALFORGE_BASE_URL must be an http:// or https:// URL."
            )


class OllamaProvider:
    """Minimal Ollama-compatible chat client."""

    def __init__(self, config: ProviderConfig):
        self.config = config

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Send a chat request and return the raw assistant content string."""
        if not self.config.model:
            raise ProviderUnavailable(
                "No model is configured. Set PROPOSALFORGE_MODEL."
            )
        url = self.config.base_url.rstrip("/") + "/api/chat"
        body = json.dumps(
            {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "format": "json",
            }
        ).encode("utf-8")

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
            raise ProviderUnavailable(
                f"The AI provider returned an error (HTTP {exc.code})."
            ) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, socket.timeout):
                raise ProviderTimeout("The AI provider timed out.") from exc
            raise ProviderUnavailable("The AI provider is unavailable.") from exc
        except (ConnectionError, OSError) as exc:
            raise ProviderUnavailable("The AI provider is unavailable.") from exc

        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(
                "The AI provider returned an unreadable response."
            ) from exc

        content = self._extract_content(envelope)
        if content is None:
            raise ProviderUnavailable(
                "The AI provider returned an unexpected response shape."
            )
        return content

    @staticmethod
    def _extract_content(envelope):
        if not isinstance(envelope, dict):
            return None
        message = envelope.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        if isinstance(envelope.get("response"), str):
            return envelope["response"]
        return None


def get_provider(config: ProviderConfig | None = None) -> OllamaProvider:
    """Build the configured provider. Only the Ollama kind is supported."""
    config = config or ProviderConfig.from_env()
    if config.provider != "ollama":
        raise ProviderUnavailable(
            f"Unsupported provider '{config.provider}'. Only 'ollama' is supported."
        )
    return OllamaProvider(config)

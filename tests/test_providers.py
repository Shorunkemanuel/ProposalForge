import io
import json
import math
import socket
import unittest
import urllib.error
from unittest import mock

from app.providers import (
    CATEGORY_AUTH,
    CATEGORY_HTTP_ERROR,
    DEFAULT_PROVIDER,
    DEFAULT_TIMEOUT,
    OllamaProvider,
    ProviderConfig,
    ProviderTimeout,
    ProviderUnavailable,
    default_base_url_for,
    get_provider,
    preset_for,
)


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def config(**overrides):
    defaults = dict(
        base_url="http://127.0.0.1:11434",
        model="test-model",
        api_key=None,
        timeout=5.0,
        provider="ollama",
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


class ProviderConfigTests(unittest.TestCase):
    def test_from_env_reads_all_values(self):
        env = {
            "PROPOSALFORGE_PROVIDER": "ollama",
            "PROPOSALFORGE_BASE_URL": "https://example.invalid",
            "PROPOSALFORGE_MODEL": "gemma4:31b-cloud",
            "PROPOSALFORGE_API_KEY": "secret-value",
            "PROPOSALFORGE_TIMEOUT": "12.5",
        }
        cfg = ProviderConfig.from_env(env)
        self.assertEqual(cfg.base_url, "https://example.invalid")
        self.assertEqual(cfg.model, "gemma4:31b-cloud")
        self.assertEqual(cfg.api_key, "secret-value")
        self.assertEqual(cfg.timeout, 12.5)

    def test_from_env_defaults(self):
        # Hosted BYOK is the primary path, so an unconfigured environment
        # defaults to a hosted OpenAI-compatible preset, not a local server.
        cfg = ProviderConfig.from_env({})
        self.assertEqual(cfg.provider, DEFAULT_PROVIDER)
        self.assertEqual(cfg.base_url, preset_for(DEFAULT_PROVIDER)["base_url"])
        self.assertIsNone(cfg.api_key)
        self.assertEqual(cfg.timeout, DEFAULT_TIMEOUT)

    def test_from_env_derives_base_url_from_selected_preset(self):
        # Naming only the provider must seed that preset's documented URL
        # (a local preset must not inherit a hosted URL and vice versa).
        cfg = ProviderConfig.from_env({"PROPOSALFORGE_PROVIDER": "ollama"})
        self.assertEqual(cfg.provider, "ollama")
        self.assertEqual(cfg.base_url, "http://127.0.0.1:11434")
        self.assertEqual(cfg.api_format, "ollama")

    def test_from_env_explicit_base_url_wins_over_preset_default(self):
        cfg = ProviderConfig.from_env(
            {
                "PROPOSALFORGE_PROVIDER": "openrouter",
                "PROPOSALFORGE_BASE_URL": "https://gateway.example.invalid/v1",
            }
        )
        self.assertEqual(cfg.base_url, "https://gateway.example.invalid/v1")

    def test_from_env_blank_base_url_falls_back_to_preset(self):
        cfg = ProviderConfig.from_env(
            {
                "PROPOSALFORGE_PROVIDER": "ollama",
                "PROPOSALFORGE_BASE_URL": "   ",
            }
        )
        self.assertEqual(cfg.base_url, "http://127.0.0.1:11434")

    def test_default_base_url_for_falls_back_for_unknown_preset(self):
        self.assertEqual(default_base_url_for("nope"), "http://127.0.0.1:11434")
        self.assertEqual(default_base_url_for("custom"), "http://127.0.0.1:11434")

    def test_default_timeout_is_generous_but_bounded(self):
        # Local CPU generation is slow; the default must allow minutes but
        # must never be unbounded (which would let a request hang forever).
        self.assertGreaterEqual(DEFAULT_TIMEOUT, 120.0)
        self.assertTrue(math.isfinite(DEFAULT_TIMEOUT))
        self.assertLessEqual(DEFAULT_TIMEOUT, 3600.0)

    def test_from_env_bad_timeout_falls_back(self):
        cfg = ProviderConfig.from_env({"PROPOSALFORGE_TIMEOUT": "not-a-number"})
        self.assertEqual(cfg.timeout, DEFAULT_TIMEOUT)

    def test_from_env_non_finite_timeout_falls_back(self):
        for raw in ("nan", "inf", "-inf", "0", "-1"):
            cfg = ProviderConfig.from_env({"PROPOSALFORGE_TIMEOUT": raw})
            self.assertEqual(cfg.timeout, DEFAULT_TIMEOUT, raw)

    def test_from_env_timeout_override_is_preserved(self):
        cfg = ProviderConfig.from_env({"PROPOSALFORGE_TIMEOUT": "450"})
        self.assertEqual(cfg.timeout, 450.0)

    def test_get_provider_rejects_unknown_kind(self):
        with self.assertRaises(ProviderUnavailable):
            get_provider(config(provider="acme-gateway"))

    def test_config_rejects_unknown_provider_kind(self):
        with self.assertRaises(ProviderUnavailable):
            ProviderConfig(base_url="http://127.0.0.1:11434", model="m", provider="acme")

    def test_supported_presets_have_expected_api_format(self):
        for provider in ("ollama",):
            self.assertEqual(config(provider=provider).api_format, "ollama")
        for provider in ("openrouter", "openai", "gemini", "ollama-cloud", "custom"):
            cfg = config(provider=provider, base_url="https://example.invalid/v1")
            self.assertEqual(cfg.api_format, "openai", provider)

    def test_get_provider_accepts_each_preset(self):
        for provider in ("ollama", "openrouter", "openai", "gemini", "ollama-cloud", "custom"):
            provider_obj = get_provider(
                config(provider=provider, base_url="https://example.invalid/v1")
            )
            self.assertIsInstance(provider_obj, OllamaProvider)

    def test_config_rejects_non_http_scheme(self):
        with self.assertRaises(ProviderUnavailable):
            ProviderConfig(base_url="file:///etc/passwd", model="m")

    def test_config_rejects_unknown_scheme(self):
        with self.assertRaises(ProviderUnavailable):
            ProviderConfig(base_url="ftp://example.invalid", model="m")

    def test_config_accepts_http_and_https(self):
        self.assertEqual(
            ProviderConfig(base_url="http://127.0.0.1:11434", model="m").base_url,
            "http://127.0.0.1:11434",
        )
        self.assertEqual(
            ProviderConfig(base_url="https://example.invalid", model="m").base_url,
            "https://example.invalid",
        )


class OllamaProviderTests(unittest.TestCase):
    def test_missing_model_raises_on_generate(self):
        provider = OllamaProvider(config(model=""))
        with self.assertRaises(ProviderUnavailable):
            provider.generate("system", "user")

    def test_successful_generation_extracts_content(self):
        envelope = {"message": {"role": "assistant", "content": '{"ok": true}'}}
        with mock.patch(
            "app.providers.urllib.request.urlopen", return_value=FakeResponse(envelope)
        ):
            content = OllamaProvider(config()).generate("system", "user")
        self.assertEqual(content, '{"ok": true}')

    def test_legacy_response_key_supported(self):
        envelope = {"response": "hello"}
        with mock.patch(
            "app.providers.urllib.request.urlopen", return_value=FakeResponse(envelope)
        ):
            content = OllamaProvider(config()).generate("system", "user")
        self.assertEqual(content, "hello")

    def test_api_key_sent_as_bearer(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["headers"] = request.headers
            return FakeResponse({"message": {"content": "{}"}})

        with mock.patch("app.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            OllamaProvider(config(api_key="tok-123")).generate("s", "u")
        auth = captured["headers"].get("Authorization")
        self.assertEqual(auth, "Bearer tok-123")

    def test_generate_passes_configured_timeout_to_urlopen(self):
        # The configured timeout must bound the whole request, including
        # reading the (non-streamed) completion body, not just connecting.
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["timeout"] = timeout
            return FakeResponse({"message": {"content": "{}"}})

        with mock.patch("app.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            OllamaProvider(config(timeout=123.5)).generate("s", "u")
        self.assertEqual(captured["timeout"], 123.5)

    def test_timeout_raises_provider_timeout(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen", side_effect=socket.timeout()
        ):
            with self.assertRaises(ProviderTimeout):
                OllamaProvider(config()).generate("system", "user")

    def test_url_error_timeout_raises_provider_timeout(self):
        err = urllib.error.URLError(socket.timeout("timed out"))
        with mock.patch("app.providers.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderTimeout):
                OllamaProvider(config()).generate("system", "user")

    def test_http_error_raises_provider_unavailable(self):
        err = urllib.error.HTTPError(
            "http://127.0.0.1:11434/api/chat", 500, "server error", {}, io.BytesIO(b"")
        )
        self.addCleanup(err.close)
        with mock.patch("app.providers.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderUnavailable):
                OllamaProvider(config()).generate("system", "user")

    def test_http_500_is_classified_as_http_error(self):
        err = urllib.error.HTTPError(
            "http://127.0.0.1:11434/api/chat", 500, "boom", {}, io.BytesIO(b"")
        )
        self.addCleanup(err.close)
        with mock.patch("app.providers.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderUnavailable) as ctx:
                OllamaProvider(config()).generate("system", "user")
        self.assertEqual(ctx.exception.category, CATEGORY_HTTP_ERROR)

    def test_http_401_is_classified_as_auth_error(self):
        err = urllib.error.HTTPError(
            "http://127.0.0.1:11434/api/chat", 401, "unauthorized", {}, io.BytesIO(b"")
        )
        self.addCleanup(err.close)
        with mock.patch("app.providers.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderUnavailable) as ctx:
                OllamaProvider(config(api_key="tok-secret-xyz")).generate("system", "user")
        self.assertEqual(ctx.exception.category, CATEGORY_AUTH)
        self.assertIn("401", str(ctx.exception))
        # The bearer token must never appear in the user-facing message.
        self.assertNotIn("tok-secret-xyz", str(ctx.exception))

    def test_http_403_is_classified_as_auth_error(self):
        err = urllib.error.HTTPError(
            "http://127.0.0.1:11434/api/tags", 403, "forbidden", {}, io.BytesIO(b"")
        )
        self.addCleanup(err.close)
        with mock.patch("app.providers.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderUnavailable) as ctx:
                OllamaProvider(config(api_key="tok-secret-abc")).list_models()
        self.assertEqual(ctx.exception.category, CATEGORY_AUTH)
        self.assertIn("403", str(ctx.exception))
        self.assertNotIn("tok-secret-abc", str(ctx.exception))

    def test_connection_error_raises_provider_unavailable(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen", side_effect=urllib.error.URLError("refused")
        ):
            with self.assertRaises(ProviderUnavailable):
                OllamaProvider(config()).generate("system", "user")

    def test_malformed_envelope_raises(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen",
            return_value=FakeResponse({"unexpected": "shape"}),
        ):
            with self.assertRaises(ProviderUnavailable):
                OllamaProvider(config()).generate("system", "user")


if __name__ == "__main__":
    unittest.main()

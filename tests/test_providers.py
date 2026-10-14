import io
import json
import socket
import unittest
import urllib.error
from unittest import mock

from app.providers import (
    OllamaProvider,
    ProviderConfig,
    ProviderTimeout,
    ProviderUnavailable,
    get_provider,
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
        cfg = ProviderConfig.from_env({})
        self.assertEqual(cfg.base_url, "http://127.0.0.1:11434")
        self.assertIsNone(cfg.api_key)
        self.assertEqual(cfg.timeout, 60.0)

    def test_from_env_bad_timeout_falls_back(self):
        cfg = ProviderConfig.from_env({"PROPOSALFORGE_TIMEOUT": "not-a-number"})
        self.assertEqual(cfg.timeout, 60.0)

    def test_from_env_non_finite_timeout_falls_back(self):
        for raw in ("nan", "inf", "-inf", "0", "-1"):
            cfg = ProviderConfig.from_env({"PROPOSALFORGE_TIMEOUT": raw})
            self.assertEqual(cfg.timeout, 60.0, raw)

    def test_get_provider_rejects_unknown_kind(self):
        with self.assertRaises(ProviderUnavailable):
            get_provider(config(provider="openai"))

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

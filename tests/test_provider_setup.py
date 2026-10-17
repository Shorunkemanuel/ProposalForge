import io
import json
import socket
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from app.provider_setup import (
    ConfigValidationError,
    ProviderSettings,
    classify_probe_models,
    process_provider_config,
    process_provider_models,
    process_provider_status,
    process_provider_test,
    validate_api_key,
    validate_base_url,
    validate_model_name,
    validate_provider,
)
from app.providers import (
    DEFAULT_PROVIDER,
    DEFAULT_TIMEOUT,
    PRESETS,
    OllamaProvider,
    ProviderConfig,
    ProviderTimeout,
    ProviderUnavailable,
    default_base_url_for,
    documented_models_for,
    get_provider,
    normalize_model_names,
    normalize_openai_model_names,
    preset_for,
)
from app.server import create_server, process_request


class FakeResponse:
    def __init__(self, payload, raw=None):
        self._body = raw if raw is not None else json.dumps(payload).encode("utf-8")

    def read(self, amount=None):
        if amount is None:
            return self._body
        return self._body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def settings(**env):
    # These tests exercise the local Ollama path by default; pin the provider
    # explicitly so they are independent of the hosted-by-default product
    # default. The hosted default is covered by dedicated tests.
    defaults = {
        "PROPOSALFORGE_PROVIDER": "ollama",
        "PROPOSALFORGE_BASE_URL": "http://127.0.0.1:11434",
        "PROPOSALFORGE_MODEL": "",
    }
    defaults.update(env)
    return ProviderSettings(defaults)


def valid_draft():
    return {
        "introduction": "Hello",
        "project_understanding": "A site.",
        "proposed_approach": "Plan and build.",
        "timeline": "Six weeks.",
        "relevant_experience": "As supplied.",
        "pricing_explanation": "As calculated.",
        "closing": "Thank you.",
        "missing_information": [],
    }


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


class ValidationTests(unittest.TestCase):
    def test_base_url_accepts_http_and_https(self):
        self.assertEqual(
            validate_base_url("http://127.0.0.1:11434"), "http://127.0.0.1:11434"
        )
        self.assertEqual(
            validate_base_url("https://ollama.example"), "https://ollama.example"
        )

    def test_base_url_strips_trailing_slash_and_whitespace(self):
        self.assertEqual(
            validate_base_url("  http://127.0.0.1:11434/  "), "http://127.0.0.1:11434"
        )

    def test_base_url_rejects_bad_scheme_and_empty(self):
        for raw in ("file:///etc/passwd", "ftp://example.invalid", "", "   ", "not a url"):
            with self.subTest(raw=raw):
                with self.assertRaises(ConfigValidationError):
                    validate_base_url(raw)

    def test_base_url_rejects_embedded_credentials(self):
        with self.assertRaises(ConfigValidationError):
            validate_base_url("http://user:pass@example.invalid")

    def test_base_url_rejects_non_string_and_control_chars(self):
        with self.assertRaises(ConfigValidationError):
            validate_base_url(123)
        with self.assertRaises(ConfigValidationError):
            validate_base_url("http://127.0.0.1:11 434")
        with self.assertRaises(ConfigValidationError):
            validate_base_url("http://127.0.0.1:11434/\x01")

    def test_base_url_rejects_overlong(self):
        with self.assertRaises(ConfigValidationError):
            validate_base_url("http://example.invalid/" + "a" * 600)

    def test_model_name_accepts_typical_names(self):
        for name in ("llama3.2", "qwen2.5:0.5b-instruct-q4_K_M", "org/model:tag"):
            with self.subTest(name=name):
                self.assertEqual(validate_model_name(name), name)

    def test_model_name_empty_clears(self):
        self.assertEqual(validate_model_name("   "), "")

    def test_model_name_rejects_bad_chars_and_overlong(self):
        for raw in ("bad name", "bad;name", "-leading", "a" * 201):
            with self.subTest(raw=raw):
                with self.assertRaises(ConfigValidationError):
                    validate_model_name(raw)

    def test_api_key_empty_clears_and_value_accepted(self):
        self.assertIsNone(validate_api_key(""))
        self.assertIsNone(validate_api_key("   "))
        self.assertEqual(validate_api_key("tok-123"), "tok-123")

    def test_api_key_rejects_control_and_overlong(self):
        with self.assertRaises(ConfigValidationError):
            validate_api_key("bad\x00key")
        with self.assertRaises(ConfigValidationError):
            validate_api_key("a" * 5000)


class ProviderSettingsTests(unittest.TestCase):
    def test_seeds_from_environment(self):
        cfg = settings(PROPOSALFORGE_MODEL="m1", PROPOSALFORGE_API_KEY="secret")
        described = cfg.describe()
        self.assertEqual(described["model"], "m1")
        self.assertTrue(described["has_api_key"])
        self.assertEqual(described["source"], "environment")
        self.assertNotIn("api_key", described)
        self.assertNotIn("secret", json.dumps(described))

    def test_update_marks_runtime_source(self):
        cfg = settings()
        described = cfg.update(base_url="http://127.0.0.1:11500", model="m2")
        self.assertEqual(described["base_url"], "http://127.0.0.1:11500")
        self.assertEqual(described["model"], "m2")
        self.assertEqual(described["source"], "runtime")

    def test_update_leaves_unset_fields_unchanged(self):
        cfg = settings(PROPOSALFORGE_MODEL="keepme")
        cfg.update(base_url="http://127.0.0.1:11500")
        self.assertEqual(cfg.describe()["model"], "keepme")

    def test_update_empty_api_key_clears_value(self):
        cfg = settings(PROPOSALFORGE_API_KEY="secret")
        cfg.update(api_key="")
        self.assertFalse(cfg.describe()["has_api_key"])

    def test_update_api_key_value_never_returned(self):
        cfg = settings()
        described = cfg.update(api_key="super-secret")
        self.assertTrue(described["has_api_key"])
        self.assertNotIn("super-secret", json.dumps(described))

    def test_invalid_update_does_not_mutate(self):
        cfg = settings(PROPOSALFORGE_MODEL="stable")
        with self.assertRaises(ConfigValidationError) as ctx:
            cfg.update(base_url="file:///tmp/x", model="bad name")
        self.assertIn("base_url", ctx.exception.fields)
        self.assertIn("model", ctx.exception.fields)
        self.assertEqual(cfg.describe()["model"], "stable")

    def test_snapshot_builds_config(self):
        cfg = settings(PROPOSALFORGE_MODEL="m1")
        snapshot = cfg.snapshot()
        self.assertIsInstance(snapshot, ProviderConfig)
        self.assertEqual(snapshot.model, "m1")

    def test_snapshot_raises_on_invalid_environment_base_url(self):
        cfg = settings(PROPOSALFORGE_BASE_URL="file:///etc/passwd")
        with self.assertRaises(ProviderUnavailable):
            cfg.snapshot()

    def test_default_timeout_is_seeded_from_default(self):
        cfg = settings()
        self.assertEqual(cfg.describe()["timeout"], DEFAULT_TIMEOUT)
        self.assertEqual(cfg.snapshot().timeout, DEFAULT_TIMEOUT)

    def test_timeout_override_is_seeded_from_environment(self):
        cfg = settings(PROPOSALFORGE_TIMEOUT="450")
        self.assertEqual(cfg.describe()["timeout"], 450.0)
        self.assertEqual(cfg.snapshot().timeout, 450.0)

    def test_invalid_timeout_falls_back_to_default(self):
        cfg = settings(PROPOSALFORGE_TIMEOUT="not-a-number")
        self.assertEqual(cfg.describe()["timeout"], DEFAULT_TIMEOUT)


class HostedDefaultTests(unittest.TestCase):
    """The unconfigured default is a hosted OpenAI-compatible preset, not a
    local server, so the primary product path is hosted BYOK."""

    def test_default_provider_is_hosted_openai_compatible(self):
        cfg = ProviderSettings({})
        described = cfg.describe()
        self.assertEqual(described["provider"], DEFAULT_PROVIDER)
        self.assertEqual(
            described["base_url"], preset_for(DEFAULT_PROVIDER)["base_url"]
        )
        self.assertEqual(cfg.snapshot().api_format, "openai")

    def test_default_provider_base_url_is_not_local(self):
        self.assertNotEqual(
            ProviderSettings({}).describe()["base_url"],
            "http://127.0.0.1:11434",
        )

    def test_only_provider_specified_seeds_that_preset_base_url(self):
        cfg = ProviderSettings({"PROPOSALFORGE_PROVIDER": "ollama"})
        described = cfg.describe()
        self.assertEqual(described["provider"], "ollama")
        self.assertEqual(described["base_url"], "http://127.0.0.1:11434")
        self.assertEqual(cfg.snapshot().api_format, "ollama")

    def test_explicit_base_url_is_not_overridden_by_preset(self):
        cfg = ProviderSettings(
            {
                "PROPOSALFORGE_PROVIDER": "openrouter",
                "PROPOSALFORGE_BASE_URL": "https://gateway.example.invalid/v1",
            }
        )
        self.assertEqual(
            cfg.describe()["base_url"], "https://gateway.example.invalid/v1"
        )

    def test_blank_base_url_falls_back_to_preset(self):
        cfg = ProviderSettings(
            {"PROPOSALFORGE_PROVIDER": "ollama", "PROPOSALFORGE_BASE_URL": "  "}
        )
        self.assertEqual(cfg.describe()["base_url"], "http://127.0.0.1:11434")

    def test_status_reports_hosted_default(self):
        status, body = process_provider_status(ProviderSettings({}))
        self.assertEqual(status, 200)
        self.assertEqual(body["provider"], DEFAULT_PROVIDER)
        self.assertEqual(
            body["base_url"], default_base_url_for(DEFAULT_PROVIDER)
        )


class NormalizeModelNamesTests(unittest.TestCase):
    def test_extracts_sorts_and_dedupes(self):
        payload = {
            "models": [
                {"name": "beta:2"},
                {"model": "alpha:1"},
                {"name": "alpha:1"},
                {"name": ""},
                {"name": 5},
                "not-a-dict",
            ]
        }
        self.assertEqual(normalize_model_names(payload), ["alpha:1", "beta:2"])

    def test_empty_list_returns_empty(self):
        self.assertEqual(normalize_model_names({"models": []}), [])

    def test_caps_number_of_models(self):
        payload = {"models": [{"name": f"m{i}"} for i in range(400)]}
        self.assertEqual(len(normalize_model_names(payload)), 200)

    def test_non_dict_or_missing_models_raise(self):
        for payload in ([], "nope", {"unexpected": []}):
            with self.subTest(payload=payload):
                with self.assertRaises(ProviderUnavailable):
                    normalize_model_names(payload)


class OllamaListModelsTests(unittest.TestCase):
    def test_success_uses_api_tags(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            return FakeResponse({"models": [{"name": "alpha:1"}]})

        with mock.patch("app.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            models = OllamaProvider(
                ProviderConfig(
                    base_url="http://127.0.0.1:11434", model="m", provider="ollama"
                )
            ).list_models()
        self.assertEqual(models, ["alpha:1"])
        self.assertTrue(captured["url"].endswith("/api/tags"))
        self.assertEqual(captured["method"], "GET")

    def test_api_key_sent_as_bearer(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["auth"] = request.headers.get("Authorization")
            return FakeResponse({"models": []})

        with mock.patch("app.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            OllamaProvider(
                ProviderConfig(
                    base_url="https://example.invalid", model="m", api_key="tok-1",
                    provider="ollama",
                )
            ).list_models()
        self.assertEqual(captured["auth"], "Bearer tok-1")

    def test_http_error_category(self):
        err = urllib.error.HTTPError(
            "http://127.0.0.1:11434/api/tags", 500, "boom", {}, io.BytesIO(b"")
        )
        self.addCleanup(err.close)
        with mock.patch("app.providers.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderUnavailable) as ctx:
                OllamaProvider(
                    ProviderConfig(
                        base_url="http://127.0.0.1:11434",
                        model="m",
                        provider="ollama",
                    )
                ).list_models()
        self.assertEqual(ctx.exception.category, "http_error")

    def test_timeout_category(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen", side_effect=socket.timeout()
        ):
            with self.assertRaises(ProviderTimeout) as ctx:
                OllamaProvider(
                    ProviderConfig(
                        base_url="http://127.0.0.1:11434",
                        model="m",
                        provider="ollama",
                    )
                ).list_models()
        self.assertEqual(ctx.exception.category, "timeout")

    def test_unreachable_category(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen",
            side_effect=urllib.error.URLError("refused"),
        ):
            with self.assertRaises(ProviderUnavailable) as ctx:
                OllamaProvider(
                    ProviderConfig(
                        base_url="http://127.0.0.1:11434",
                        model="m",
                        provider="ollama",
                    )
                ).list_models()
        self.assertEqual(ctx.exception.category, "unreachable")

    def test_malformed_json_category(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen",
            return_value=FakeResponse(None, raw=b"{not json"),
        ):
            with self.assertRaises(ProviderUnavailable) as ctx:
                OllamaProvider(
                    ProviderConfig(
                        base_url="http://127.0.0.1:11434",
                        model="m",
                        provider="ollama",
                    )
                ).list_models()
        self.assertEqual(ctx.exception.category, "invalid_response")

    def test_oversized_response_rejected(self):
        big = json.dumps({"models": [{"name": "x"}]}).encode() + b" " * 2_000_001
        with mock.patch(
            "app.providers.urllib.request.urlopen",
            return_value=FakeResponse(None, raw=big),
        ):
            with self.assertRaises(ProviderUnavailable) as ctx:
                OllamaProvider(
                    ProviderConfig(
                        base_url="http://127.0.0.1:11434",
                        model="m",
                        provider="ollama",
                    )
                ).list_models()
        self.assertEqual(ctx.exception.category, "invalid_response")


class OpenAIProtocolTests(unittest.TestCase):
    """The OpenAI-compatible wire protocol used by the hosted presets."""

    def openai_config(self, **overrides):
        defaults = dict(
            base_url="https://openrouter.ai/api/v1",
            model="openrouter/free",
            provider="openrouter",
        )
        defaults.update(overrides)
        return ProviderConfig(**defaults)

    def test_generate_posts_to_chat_completions(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({"choices": [{"message": {"content": "{}"}}]})

        with mock.patch("app.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            content = OllamaProvider(self.openai_config()).generate("sys", "usr")
        self.assertEqual(content, "{}")
        self.assertEqual(captured["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["body"]["model"], "openrouter/free")
        self.assertFalse(captured["body"]["stream"])
        # No Ollama-only "format" parameter is sent on the OpenAI path.
        self.assertNotIn("format", captured["body"])
        self.assertEqual(
            captured["body"]["messages"],
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "usr"},
            ],
        )

    def test_generate_trailing_slash_base_url_normalized(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

        cfg = self.openai_config(
            provider="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        with mock.patch("app.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            OllamaProvider(cfg).generate("s", "u")
        self.assertEqual(
            captured["url"],
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )

    def test_generate_sends_bearer_key(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["auth"] = request.headers.get("Authorization")
            return FakeResponse({"choices": [{"message": {"content": "{}"}}]})

        with mock.patch("app.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            OllamaProvider(self.openai_config(api_key="sk-or-secret")).generate("s", "u")
        self.assertEqual(captured["auth"], "Bearer sk-or-secret")

    def test_generate_missing_choices_raises_safe_error(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen",
            return_value=FakeResponse({"unexpected": True}),
        ):
            with self.assertRaises(ProviderUnavailable) as ctx:
                OllamaProvider(self.openai_config(api_key="sk-secret")).generate("s", "u")
        self.assertEqual(ctx.exception.category, "invalid_response")
        self.assertNotIn("sk-secret", str(ctx.exception))

    def test_list_models_gets_models_and_parses_data_ids(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            return FakeResponse(
                {"data": [{"id": "meta-llama/llama-3.3-70b-instruct"}, {"id": "openrouter/free"}]}
            )

        with mock.patch("app.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            models = OllamaProvider(self.openai_config()).list_models()
        self.assertEqual(
            models, ["meta-llama/llama-3.3-70b-instruct", "openrouter/free"]
        )
        self.assertEqual(captured["url"], "https://openrouter.ai/api/v1/models")
        self.assertEqual(captured["method"], "GET")


class PresetRegistryTests(unittest.TestCase):
    def test_presets_cover_required_ids(self):
        ids = {preset["id"] for preset in PRESETS}
        self.assertEqual(
            ids,
            {"openrouter", "openai", "gemini", "ollama-cloud", "custom", "ollama"},
        )

    def test_hosted_presets_use_openai_format_and_documented_base_urls(self):
        expected = {
            "openrouter": "https://openrouter.ai/api/v1",
            "openai": "https://api.openai.com/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "ollama-cloud": "https://ollama.com/v1",
        }
        for preset in PRESETS:
            if preset["id"] not in expected:
                continue
            self.assertEqual(preset["api_format"], "openai")
            self.assertEqual(preset["base_url"], expected[preset["id"]])
            self.assertTrue(preset["requires_key"])

    def test_openrouter_declares_free_router(self):
        self.assertEqual(documented_models_for("openrouter"), ("openrouter/free",))
        self.assertEqual(preset_for("openrouter")["auto_model"], "openrouter/free")

    def test_preset_payload_is_offered_to_clients(self):
        _, body = process_provider_status(settings())
        ids = {preset["id"] for preset in body["presets"]}
        self.assertIn("openrouter", ids)
        self.assertIn("gemini", ids)
        # Preset hints must not contain a secret or ask about free/paid keys.
        joined = json.dumps(body["presets"]).lower()
        self.assertNotIn("api_key", joined)
        self.assertNotIn("free or paid", joined)


class ProviderDocumentedModelsTests(unittest.TestCase):
    def test_documented_router_accepted_without_discovery(self):
        status, message = classify_probe_models(
            "openrouter/free",
            "https://openrouter.ai/api/v1",
            [],
            documented=("openrouter/free",),
        )
        self.assertEqual(status, "ready")
        self.assertIn("openrouter/free", message)

    def test_documented_router_accepted_when_absent_from_a_nonempty_list(self):
        status, _ = classify_probe_models(
            "openrouter/free",
            "https://openrouter.ai/api/v1",
            ["meta-llama/llama-3.3-70b-instruct"],
            documented=("openrouter/free",),
        )
        self.assertEqual(status, "ready")

    def test_undocumented_missing_model_still_reports_not_found(self):
        status, _ = classify_probe_models(
            "ghost/model",
            "https://openrouter.ai/api/v1",
            ["meta-llama/llama-3.3-70b-instruct"],
            documented=("openrouter/free",),
        )
        self.assertEqual(status, "model_not_found")

    def test_empty_discovery_without_documented_model_is_no_models(self):
        status, _ = classify_probe_models("m", "https://x.invalid", [], documented=())
        self.assertEqual(status, "no_models_installed")

    def test_probe_classifies_documented_router_as_ready(self):
        def fake_list_models(provider_self, timeout=None):
            return ["meta-llama/llama-3.3-70b-instruct"]

        cfg = {
            "PROPOSALFORGE_PROVIDER": "openrouter",
            "PROPOSALFORGE_BASE_URL": "https://openrouter.ai/api/v1",
            "PROPOSALFORGE_MODEL": "openrouter/free",
        }
        with mock.patch("app.providers.OllamaProvider.list_models", fake_list_models):
            status, body = process_provider_test(ProviderSettings(cfg))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ready")


class ProviderSelectionConfigTests(unittest.TestCase):
    def test_validate_provider_accepts_known_ids(self):
        self.assertEqual(validate_provider("OpenRouter"), "openrouter")
        self.assertEqual(validate_provider(" custom "), "custom")

    def test_validate_provider_rejects_unknown_and_non_string(self):
        for bad in ("acme", "", 7, None):
            with self.assertRaises(ConfigValidationError, msg=bad):
                validate_provider(bad)

    def test_update_switches_provider_and_marks_runtime(self):
        s = settings()
        desc = s.update(provider="openrouter")
        self.assertEqual(desc["provider"], "openrouter")
        self.assertEqual(desc["source"], "runtime")
        self.assertEqual(s.snapshot().api_format, "openai")

    def test_config_endpoint_rejects_unknown_provider(self):
        status, body = process_provider_config(settings(), {"provider": "acme"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_config")
        self.assertIn("provider", body["fields"])

    def test_config_endpoint_never_returns_api_key(self):
        status, body = process_provider_config(
            settings(),
            {"provider": "openrouter", "api_key": "sk-or-supersecret"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["has_api_key"])
        self.assertNotIn("sk-or-supersecret", json.dumps(body))


class ProviderStatusTests(unittest.TestCase):
    def test_status_without_model(self):
        status, body = process_provider_status(settings())
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "model_not_selected")
        self.assertIsNone(body["models"])
        self.assertEqual(body["scope"], "runtime")

    def test_status_with_model(self):
        status, body = process_provider_status(settings(PROPOSALFORGE_MODEL="m1"))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "configured")
        self.assertIn("m1", body["message"])

    def test_status_invalid_environment(self):
        status, body = process_provider_status(
            settings(PROPOSALFORGE_BASE_URL="file:///etc/passwd")
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "invalid_config")

    def test_status_never_exposes_api_key(self):
        _, body = process_provider_status(
            settings(PROPOSALFORGE_API_KEY="top-secret")
        )
        self.assertTrue(body["has_api_key"])
        self.assertNotIn("top-secret", json.dumps(body))


class ProviderProbeTests(unittest.TestCase):
    def _test(self, cfg, tags_payload=None, error=None):
        if error is not None:
            patcher = mock.patch("app.providers.urllib.request.urlopen", side_effect=error)
        else:
            patcher = mock.patch(
                "app.providers.urllib.request.urlopen",
                return_value=FakeResponse(tags_payload),
            )
        with patcher:
            return process_provider_test(cfg)

    def test_ready_when_model_installed(self):
        status, body = self._test(
            settings(PROPOSALFORGE_MODEL="alpha:1"),
            tags_payload={"models": [{"name": "alpha:1"}, {"name": "beta:2"}]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["models"], ["alpha:1", "beta:2"])

    def test_model_not_selected_when_models_exist(self):
        status, body = self._test(
            settings(), tags_payload={"models": [{"name": "alpha:1"}]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "model_not_selected")

    def test_model_not_found_when_selected_missing(self):
        status, body = self._test(
            settings(PROPOSALFORGE_MODEL="ghost"),
            tags_payload={"models": [{"name": "alpha:1"}]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "model_not_found")

    def test_no_models_installed(self):
        status, body = self._test(
            settings(PROPOSALFORGE_MODEL="alpha:1"), tags_payload={"models": []}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "no_models_installed")

    def test_unreachable_is_classified(self):
        status, body = self._test(settings(), error=urllib.error.URLError("refused"))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unreachable")
        self.assertIn("127.0.0.1", body["message"])

    def test_timeout_is_classified(self):
        status, body = self._test(settings(), error=socket.timeout())
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "timeout")

    def test_http_error_is_classified(self):
        err = urllib.error.HTTPError(
            "http://127.0.0.1:11434/api/tags", 503, "boom", {}, io.BytesIO(b"")
        )
        self.addCleanup(err.close)
        status, body = self._test(settings(), error=err)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "provider_error")

    def test_http_401_is_classified_as_auth_error(self):
        # A hosted, key-authenticated endpoint rejects a bad key with 401.
        # The probe reports a distinct auth status and never leaks the key.
        err = urllib.error.HTTPError(
            "https://api.example.com/api/tags", 401, "unauthorized", {}, io.BytesIO(b"")
        )
        self.addCleanup(err.close)
        cfg = settings(
            PROPOSALFORGE_BASE_URL="https://api.example.com",
            PROPOSALFORGE_MODEL="m1",
            PROPOSALFORGE_API_KEY="sk-secret-do-not-leak",
        )
        status, body = self._test(cfg, error=err)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "auth_error")
        self.assertIn("401", body["message"])
        self.assertNotIn("sk-secret-do-not-leak", json.dumps(body))

    def test_probe_messages_are_provider_neutral(self):
        # Hosted BYOK is the primary path; probe copy must not instruct users
        # to install or start a local Ollama server.
        err = urllib.error.HTTPError(
            "https://api.example.com/api/tags", 401, "unauthorized", {}, io.BytesIO(b"")
        )
        self.addCleanup(err.close)
        messages = [
            self._test(settings(), error=urllib.error.URLError("refused"))[1]["message"],
            self._test(settings(), error=socket.timeout())[1]["message"],
            self._test(
                settings(PROPOSALFORGE_MODEL="m1"), tags_payload={"models": []}
            )[1]["message"],
            self._test(
                settings(PROPOSALFORGE_MODEL="ghost"), tags_payload={"models": [{"name": "a"}]}
            )[1]["message"],
            self._test(settings(), error=err)[1]["message"],
        ]
        joined = " ".join(messages).lower()
        for phrase in ("ollama serve", "ollama pull", "install ollama"):
            self.assertNotIn(phrase, joined)

    def test_invalid_config_is_classified(self):
        status, body = process_provider_test(
            settings(PROPOSALFORGE_BASE_URL="file:///etc/passwd")
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "invalid_config")


class ProviderModelsEndpointTests(unittest.TestCase):
    def test_models_success(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen",
            return_value=FakeResponse({"models": [{"name": "alpha:1"}]}),
        ):
            status, body = process_provider_models(settings())
        self.assertEqual(status, 200)
        self.assertEqual(body["models"], ["alpha:1"])
        self.assertEqual(body["count"], 1)

    def test_models_empty(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen",
            return_value=FakeResponse({"models": []}),
        ):
            status, body = process_provider_models(settings())
        self.assertEqual(status, 200)
        self.assertEqual(body["models"], [])

    def test_models_unreachable_returns_502(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen",
            side_effect=urllib.error.URLError("refused"),
        ):
            status, body = process_provider_models(settings())
        self.assertEqual(status, 502)
        self.assertEqual(body["error"], "provider_unavailable")
        self.assertEqual(body["category"], "unreachable")

    def test_models_timeout_returns_504(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen", side_effect=socket.timeout()
        ):
            status, body = process_provider_models(settings())
        self.assertEqual(status, 504)
        self.assertEqual(body["error"], "provider_timeout")

    def test_models_http_error_returns_502_provider_error(self):
        err = urllib.error.HTTPError(
            "http://127.0.0.1:11434/api/tags", 500, "boom", {}, io.BytesIO(b"")
        )
        self.addCleanup(err.close)
        with mock.patch("app.providers.urllib.request.urlopen", side_effect=err):
            status, body = process_provider_models(settings())
        self.assertEqual(status, 502)
        self.assertEqual(body["error"], "provider_error")

    def test_models_auth_returns_401(self):
        err = urllib.error.HTTPError(
            "https://api.example.com/api/tags", 401, "unauthorized", {}, io.BytesIO(b"")
        )
        self.addCleanup(err.close)
        with mock.patch("app.providers.urllib.request.urlopen", side_effect=err):
            status, body = process_provider_models(
                settings(PROPOSALFORGE_BASE_URL="https://api.example.com")
            )
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "provider_auth")
        self.assertEqual(body["category"], "auth_error")

    def test_models_invalid_config_returns_400(self):
        status, body = process_provider_models(
            settings(PROPOSALFORGE_BASE_URL="file:///etc/passwd")
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_config")


class ProviderProbePayloadTests(unittest.TestCase):
    """Test/refresh may run against values currently in the form (unsaved)."""

    def test_preview_does_not_mutate_settings(self):
        cfg = settings(PROPOSALFORGE_MODEL="saved")
        config, desc = cfg.preview(
            base_url="https://api.example.com", model="typed", api_key="sk-x"
        )
        self.assertEqual(config.base_url, "https://api.example.com")
        self.assertEqual(config.model, "typed")
        self.assertTrue(desc["has_api_key"])
        # Stored settings are unchanged.
        self.assertEqual(cfg.describe()["base_url"], "http://127.0.0.1:11434")
        self.assertEqual(cfg.describe()["model"], "saved")
        self.assertFalse(cfg.describe()["has_api_key"])

    def test_preview_never_includes_api_key(self):
        cfg = settings()
        _, desc = cfg.preview(api_key="sk-do-not-leak")
        self.assertNotIn("sk-do-not-leak", json.dumps(desc))

    def test_preview_rejects_invalid_field(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            settings().preview(base_url="file:///etc/passwd")
        self.assertIn("base_url", ctx.exception.fields)

    def test_probe_uses_payload_base_url(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            return FakeResponse({"models": [{"name": "alpha:1"}]})

        with mock.patch("app.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            status, body = process_provider_test(
                settings(), {"base_url": "http://127.0.0.1:12500", "model": "alpha:1"}
            )
        self.assertEqual(status, 200)
        self.assertIn("127.0.0.1:12500", captured["url"])
        self.assertEqual(body["base_url"], "http://127.0.0.1:12500")
        self.assertEqual(body["status"], "ready")

    def test_probe_empty_api_key_falls_back_to_saved(self):
        err = urllib.error.HTTPError(
            "https://api.example.com/v1/models", 401, "unauthorized", {}, io.BytesIO(b"")
        )
        self.addCleanup(err.close)
        cfg = settings(
            PROPOSALFORGE_BASE_URL="https://api.example.com",
            PROPOSALFORGE_API_KEY="sk-saved-secret",
        )
        with mock.patch("app.providers.urllib.request.urlopen", side_effect=err):
            _, body = process_provider_test(
                cfg, {"base_url": "https://api.example.com", "api_key": ""}
            )
        # The empty field means "use the saved key", so the probe authenticates
        # (and is rejected), and the saved key is never exposed.
        self.assertEqual(body["status"], "auth_error")
        self.assertNotIn("sk-saved-secret", json.dumps(body))

    def test_probe_invalid_payload_returns_invalid_config(self):
        status, body = process_provider_test(settings(), {"base_url": "file:///x"})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "invalid_config")
        self.assertIn("base_url", body["fields"])

    def test_probe_documented_model_ready_without_discovery(self):
        with mock.patch(
            "app.providers.urllib.request.urlopen",
            return_value=FakeResponse({"data": []}),
        ):
            status, body = process_provider_test(
                settings(),
                {
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "model": "openrouter/free",
                },
            )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ready")

    def test_models_uses_payload_base_url(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            return FakeResponse({"data": [{"id": "alpha"}, {"id": "beta"}]})

        with mock.patch("app.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            status, body = process_provider_models(
                settings(),
                {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1"},
            )
        self.assertEqual(status, 200)
        self.assertIn("openrouter.ai", captured["url"])
        self.assertEqual(body["models"], ["alpha", "beta"])

    def test_models_invalid_payload_returns_400(self):
        status, body = process_provider_models(settings(), {"base_url": "file:///x"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_config")
        self.assertIn("base_url", body["fields"])


class ProviderConfigEndpointTests(unittest.TestCase):
    def test_valid_update(self):
        cfg = settings()
        status, body = process_provider_config(
            cfg, {"base_url": "http://127.0.0.1:11500", "model": "m2"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["base_url"], "http://127.0.0.1:11500")
        self.assertEqual(body["model"], "m2")
        self.assertEqual(body["source"], "runtime")

    def test_model_only_update(self):
        cfg = settings(PROPOSALFORGE_BASE_URL="http://127.0.0.1:11434")
        status, body = process_provider_config(cfg, {"model": "m3"})
        self.assertEqual(status, 200)
        self.assertEqual(body["base_url"], "http://127.0.0.1:11434")
        self.assertEqual(body["model"], "m3")

    def test_invalid_base_url_returns_400_fields(self):
        status, body = process_provider_config(settings(), {"base_url": "file:///x"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_config")
        self.assertIn("base_url", body["fields"])

    def test_invalid_model_returns_400_fields(self):
        status, body = process_provider_config(settings(), {"model": "bad name"})
        self.assertEqual(status, 400)
        self.assertIn("model", body["fields"])

    def test_non_dict_payload_returns_400(self):
        status, body = process_provider_config(settings(), "nope")
        self.assertEqual(status, 400)

    def test_api_key_is_never_echoed(self):
        cfg = settings()
        status, body = process_provider_config(cfg, {"api_key": "super-secret"})
        self.assertEqual(status, 200)
        self.assertTrue(body["has_api_key"])
        self.assertNotIn("super-secret", json.dumps(body))

    def test_api_key_can_be_cleared(self):
        cfg = settings(PROPOSALFORGE_API_KEY="secret")
        status, body = process_provider_config(cfg, {"api_key": ""})
        self.assertEqual(status, 200)
        self.assertFalse(body["has_api_key"])


class RuntimeGenerationConfigTests(unittest.TestCase):
    """Generation must use the applied runtime provider configuration.

    The connection test and model discovery run against unsaved form values by
    design and never persist them. These tests prove that the runtime
    configuration a Save establishes is what generation actually uses, that no
    environment fallback overrides a valid runtime model, and that the API key
    reaches only the configured provider and never the client.
    """

    OPENROUTER = {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openrouter/free",
    }

    def _capture_generate(self, captured):
        def fake_generate(provider_self, system_prompt, user_prompt):
            captured["provider"] = provider_self.config.provider
            captured["base_url"] = provider_self.config.base_url
            captured["model"] = provider_self.config.model
            captured["api_format"] = provider_self.config.api_format
            captured["has_api_key"] = provider_self.config.api_key is not None
            return json.dumps(valid_draft())

        return mock.patch("app.providers.OllamaProvider.generate", fake_generate)

    def test_runtime_openrouter_config_reaches_generation(self):
        cfg = settings()
        status, _ = process_provider_config(
            cfg, dict(self.OPENROUTER, api_key="sk-or-runtime-key")
        )
        self.assertEqual(status, 200)
        captured = {}
        with self._capture_generate(captured):
            status, body = process_request(valid_payload(), get_provider(cfg.snapshot()))
        self.assertEqual(status, 200)
        self.assertEqual(captured["provider"], "openrouter")
        self.assertEqual(captured["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(captured["model"], "openrouter/free")
        self.assertEqual(captured["api_format"], "openai")
        self.assertTrue(captured["has_api_key"])
        # Deterministic pricing is unaffected by the provider configuration.
        self.assertEqual(body["pricing"]["total"], "3650.00")

    def test_runtime_model_overrides_environment_model(self):
        cfg = settings(PROPOSALFORGE_MODEL="env-model")
        process_provider_config(cfg, {"model": "runtime-model"})
        captured = {}
        with self._capture_generate(captured):
            process_request(valid_payload(), get_provider(cfg.snapshot()))
        self.assertEqual(captured["model"], "runtime-model")

    def test_environment_model_used_when_no_runtime_config(self):
        cfg = settings(PROPOSALFORGE_MODEL="env-model")
        captured = {}
        with self._capture_generate(captured):
            status, _ = process_request(valid_payload(), get_provider(cfg.snapshot()))
        self.assertEqual(status, 200)
        self.assertEqual(captured["model"], "env-model")

    def test_runtime_provider_selection_is_provider_neutral(self):
        cfg = settings()
        process_provider_config(
            cfg,
            {
                "provider": "custom",
                "base_url": "https://gateway.example.invalid/v1",
                "model": "org/model",
            },
        )
        captured = {}
        with self._capture_generate(captured):
            process_request(valid_payload(), get_provider(cfg.snapshot()))
        self.assertEqual(captured["provider"], "custom")
        self.assertEqual(captured["base_url"], "https://gateway.example.invalid/v1")
        self.assertEqual(captured["model"], "org/model")

    def test_runtime_api_key_never_in_generation_response(self):
        cfg = settings()
        process_provider_config(cfg, dict(self.OPENROUTER, api_key="sk-or-do-not-leak"))
        with self._capture_generate({}):
            status, body = process_request(valid_payload(), get_provider(cfg.snapshot()))
        self.assertEqual(status, 200)
        self.assertNotIn("sk-or-do-not-leak", json.dumps(body))

    def test_runtime_api_key_sent_only_to_configured_provider(self):
        cfg = settings()
        process_provider_config(cfg, dict(self.OPENROUTER, api_key="sk-or-only-key"))
        requests = []

        def fake_urlopen(request, timeout=None):
            requests.append(request)
            return FakeResponse(
                {"choices": [{"message": {"content": json.dumps(valid_draft())}}]}
            )

        with mock.patch("app.providers.urllib.request.urlopen", side_effect=fake_urlopen):
            status, body = process_request(valid_payload(), get_provider(cfg.snapshot()))
        self.assertEqual(status, 200)
        # Exactly one outbound call, to the configured provider only.
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            requests[0].full_url, "https://openrouter.ai/api/v1/chat/completions"
        )
        self.assertEqual(
            requests[0].headers.get("Authorization"), "Bearer sk-or-only-key"
        )
        self.assertNotIn("sk-or-only-key", json.dumps(body))


def expect_http_error(case, expected_code, call, msg=None):
    try:
        response = call()
    except urllib.error.HTTPError as exc:
        with exc:
            case.assertEqual(exc.code, expected_code, msg)
            return exc.read()
    response.close()
    case.fail(f"expected HTTPError {expected_code}" + (f": {msg}" if msg else ""))


class ProviderHttpTests(unittest.TestCase):
    """End-to-end HTTP tests for the provider setup endpoints."""

    @classmethod
    def setUpClass(cls):
        env = {
            "PROPOSALFORGE_PROVIDER": "ollama",
            "PROPOSALFORGE_BASE_URL": "http://127.0.0.1:11434",
            "PROPOSALFORGE_MODEL": "alpha:1",
        }
        cls.settings = ProviderSettings(env)
        cls.server = create_server(
            settings=cls.settings, host="127.0.0.1", port=0
        )
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    # Patching urllib.request.urlopen would also intercept this test's own
    # requests to the local server (it is the same module global), so the
    # provider is stubbed at the OllamaProvider method boundary instead.
    def _patch_generate(self, captured):
        def fake_generate(provider_self, system_prompt, user_prompt):
            captured["provider"] = provider_self.config.provider
            captured["base_url"] = provider_self.config.base_url
            captured["model"] = provider_self.config.model
            captured["has_api_key"] = provider_self.config.api_key is not None
            return json.dumps(valid_draft())

        return mock.patch("app.providers.OllamaProvider.generate", fake_generate)

    def _patch_list_models(self, models):
        def fake_list_models(provider_self, timeout=None):
            return list(models)

        return mock.patch("app.providers.OllamaProvider.list_models", fake_list_models)

    def _post(self, path, payload=None, headers=None):
        body = json.dumps({} if payload is None else payload).encode("utf-8")
        base_headers = {"Content-Type": "application/json"}
        if headers:
            base_headers.update(headers)
        request = urllib.request.Request(
            self.url(path), data=body, headers=base_headers, method="POST"
        )
        return urllib.request.urlopen(request, timeout=5)

    def test_get_status(self):
        with urllib.request.urlopen(self.url("/api/provider/status"), timeout=5) as r:
            self.assertEqual(r.status, 200)
            body = json.loads(r.read())
        self.assertEqual(body["provider"], "ollama")
        self.assertIn("base_url", body)
        self.assertIn(body["status"], ("configured", "model_not_selected"))
        self.assertIsNone(body["models"])

    def test_get_status_sends_security_headers(self):
        with urllib.request.urlopen(self.url("/api/provider/status"), timeout=5) as r:
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("Content-Security-Policy", r.headers)
            self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_get_status_foreign_host_rejected(self):
        data = self._raw_get(f"evil.example:{self.port}")
        self.assertIn(b" 403 ", data.split(b"\r\n", 1)[0])

    def test_get_status_cross_origin_rejected(self):
        data = self._raw_get(f"127.0.0.1:{self.port}", origin="http://evil.example")
        self.assertIn(b" 403 ", data.split(b"\r\n", 1)[0])

    def test_status_is_get_only(self):
        # POST /api/provider/status must not fall through to proposal
        # generation; it is not a POST route.
        expect_http_error(
            self, 404, lambda: self._post("/api/provider/status", valid_payload())
        )

    def test_post_test_ready(self):
        with self._post("/api/provider/config", {"model": "alpha:1"}) as r:
            self.assertEqual(r.status, 200)
        with self._patch_list_models(["alpha:1"]):
            with self._post("/api/provider/test") as r:
                self.assertEqual(r.status, 200)
                body = json.loads(r.read())
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["models"], ["alpha:1"])

    def test_post_models_success(self):
        with self._patch_list_models(["alpha:1", "beta:2"]):
            with self._post("/api/provider/models") as r:
                self.assertEqual(r.status, 200)
                body = json.loads(r.read())
        self.assertEqual(body["models"], ["alpha:1", "beta:2"])

    def test_post_models_requires_json_content_type(self):
        body = expect_http_error(
            self,
            415,
            lambda: self._post(
                "/api/provider/models", headers={"Content-Type": "text/plain"}
            ),
        )
        self.assertEqual(json.loads(body)["error"], "unsupported_media_type")

    def test_post_models_cross_origin_rejected(self):
        body = expect_http_error(
            self,
            403,
            lambda: self._post(
                "/api/provider/models", headers={"Origin": "http://evil.example"}
            ),
        )
        self.assertEqual(json.loads(body)["error"], "forbidden")

    def test_post_config_then_status_reflects_runtime(self):
        with self._post("/api/provider/config", {"model": "beta:2"}) as r:
            self.assertEqual(r.status, 200)
            body = json.loads(r.read())
        self.assertEqual(body["model"], "beta:2")
        self.assertEqual(body["source"], "runtime")
        with urllib.request.urlopen(self.url("/api/provider/status"), timeout=5) as r:
            status_body = json.loads(r.read())
        self.assertEqual(status_body["model"], "beta:2")
        self.assertEqual(status_body["source"], "runtime")

    def test_post_config_invalid_returns_400(self):
        body = expect_http_error(
            self,
            400,
            lambda: self._post("/api/provider/config", {"base_url": "file:///x"}),
        )
        self.assertIn("base_url", json.loads(body)["fields"])

    def test_api_key_never_appears_in_responses(self):
        with self._post("/api/provider/config", {"api_key": "top-secret-value"}) as r:
            self.assertNotIn(b"top-secret-value", r.read())
        with urllib.request.urlopen(self.url("/api/provider/status"), timeout=5) as r:
            self.assertNotIn(b"top-secret-value", r.read())
        # Clean up the runtime key so later tests see a predictable state.
        with self._post("/api/provider/config", {"api_key": ""}) as r:
            self.assertEqual(r.status, 200)

    def test_runtime_model_used_for_generation(self):
        with self._post("/api/provider/config", {"model": "chosen:7"}) as r:
            self.assertEqual(r.status, 200)
        captured = {}
        with self._patch_generate(captured):
            with self._post("/api/proposals", valid_payload()) as r:
                self.assertEqual(r.status, 200)
        self.assertEqual(captured.get("model"), "chosen:7")

    def test_runtime_openrouter_config_used_for_generation(self):
        # A hosted OpenRouter runtime configuration saves normally and then
        # reaches generation with the same provider, base URL, model, and key
        # presence; the key is never echoed back.
        with self._post(
            "/api/provider/config",
            {
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "model": "openrouter/free",
                "api_key": "sk-or-http-secret",
            },
        ) as r:
            self.assertEqual(r.status, 200)
        captured = {}
        with self._patch_generate(captured):
            with self._post("/api/proposals", valid_payload()) as r:
                self.assertEqual(r.status, 200)
                raw = r.read()
        self.assertEqual(captured["provider"], "openrouter")
        self.assertEqual(captured["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(captured["model"], "openrouter/free")
        self.assertTrue(captured["has_api_key"])
        self.assertNotIn(b"sk-or-http-secret", raw)
        # Restore a predictable runtime state for the remaining shared tests.
        with self._post(
            "/api/provider/config",
            {
                "provider": "ollama",
                "base_url": "http://127.0.0.1:11434",
                "model": "alpha:1",
                "api_key": "",
            },
        ) as r:
            self.assertEqual(r.status, 200)

    def test_generation_still_works_after_provider_endpoints(self):
        with self._post("/api/provider/config", {"model": "alpha:1"}) as r:
            self.assertEqual(r.status, 200)
        captured = {}
        with self._patch_generate(captured):
            with self._post("/api/proposals", valid_payload()) as r:
                body = json.loads(r.read())
        self.assertEqual(body["pricing"]["total"], "3650.00")

    def test_readiness_still_works(self):
        with self._post("/api/readiness", valid_payload()) as r:
            self.assertTrue(json.loads(r.read())["ready"])

    def _raw_get(self, host_header, path="/api/provider/status", origin=None):
        lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {host_header}",
        ]
        if origin is not None:
            lines.append(f"Origin: {origin}")
        lines.append("Connection: close")
        request = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(request)
            sock.shutdown(socket.SHUT_WR)
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        return data


if __name__ == "__main__":
    unittest.main()

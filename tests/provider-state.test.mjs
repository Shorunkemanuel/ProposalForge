import test from "node:test";
import assert from "node:assert/strict";

import {
  STATUS_INFO,
  announcementFor,
  apiKeyFieldVisible,
  apiKeyForApply,
  classifyModelList,
  documentedModelsFor,
  initialProviderState,
  isLoopbackHost,
  isReady,
  mergeModels,
  needsProviderApply,
  nextProviderState,
  presetById,
  statusInfo,
} from "../app/static/provider-state.mjs";

const SAMPLE_PRESETS = [
  {
    id: "openrouter",
    label: "OpenRouter",
    base_url: "https://openrouter.ai/api/v1",
    requires_key: true,
    documented_models: ["openrouter/free"],
    auto_model: "openrouter/free",
    auto_model_label: "Use OpenRouter automatic router (openrouter/free)",
  },
  {
    id: "ollama",
    label: "Ollama (local or native API)",
    base_url: "http://127.0.0.1:11434",
    requires_key: false,
    documented_models: [],
    auto_model: "",
    auto_model_label: "",
  },
];

function loaded(overrides = {}) {
  const event = {
    type: "statusLoaded",
    provider: "ollama",
    base_url: "http://127.0.0.1:11434",
    model: "",
    has_api_key: false,
    source: "environment",
    status: "model_not_selected",
    message: "No model selected.",
    models: null,
    presets: SAMPLE_PRESETS,
    ...overrides,
  };
  return nextProviderState(initialProviderState(), event);
}

test("initial state has no model and unknown status", () => {
  const state = initialProviderState();
  assert.equal(state.model, "");
  assert.equal(state.provider, "");
  assert.deepEqual(state.presets, []);
  assert.equal(state.status, "unknown");
  assert.deepEqual(state.models, []);
  assert.equal(state.busy, false);
  assert.deepEqual(state.saved, {
    provider: "",
    baseUrl: "",
    model: "",
    hasApiKey: false,
    source: "environment",
  });
});

test("statusLoaded adopts server configuration", () => {
  const state = loaded({ model: "alpha:1", status: "configured" });
  assert.equal(state.baseUrl, "http://127.0.0.1:11434");
  assert.equal(state.model, "alpha:1");
  assert.equal(state.status, "configured");
  assert.equal(state.dirty, false);
});

test("statusLoaded keeps previously discovered models when none are returned", () => {
  let state = nextProviderState(loaded(), {
    type: "modelsSucceeded",
    models: ["alpha:1", "beta:2"],
  });
  state = nextProviderState(state, {
    type: "statusLoaded",
    base_url: "http://127.0.0.1:11434",
    model: "alpha:1",
    has_api_key: false,
    source: "runtime",
    status: "configured",
    message: "",
    models: null,
  });
  assert.deepEqual(state.models, ["alpha:1", "beta:2"]);
});

test("probe lifecycle sets busy then classifies the result", () => {
  let state = nextProviderState(loaded(), { type: "probeStarted" });
  assert.equal(state.busy, true);
  assert.equal(state.status, "checking");

  state = nextProviderState(state, {
    type: "probeSucceeded",
    status: "ready",
    message: "Connected.",
    models: ["alpha:1"],
    model: "alpha:1",
  });
  assert.equal(state.busy, false);
  assert.equal(state.status, "ready");
  assert.deepEqual(state.models, ["alpha:1"]);
  assert.equal(isReady(state), true);
});

test("probe failure becomes a safe provider error", () => {
  let state = nextProviderState(loaded(), { type: "probeStarted" });
  state = nextProviderState(state, {
    type: "probeFailed",
    message: "Could not reach the ProposalForge server.",
  });
  assert.equal(state.busy, false);
  assert.equal(state.status, "provider_error");
  assert.match(state.message, /could not reach/i);
});

test("models discovery failure keeps prior models and reports an error", () => {
  let state = nextProviderState(loaded(), {
    type: "modelsSucceeded",
    models: ["alpha:1"],
  });
  state = nextProviderState(state, { type: "modelsFailed", message: "No models." });
  assert.deepEqual(state.models, ["alpha:1"]);
  assert.equal(state.status, "provider_error");
});

test("failed discovery never clears a hand-entered model", () => {
  // Model discovery is optional: a failed request must not prevent manual
  // entry or lose what the user typed.
  let state = nextProviderState(loaded(), { type: "modelsStarted" });
  state = nextProviderState(state, { type: "modelChanged", value: "my/custom-model" });
  state = nextProviderState(state, { type: "modelsFailed", message: "No models." });
  assert.equal(state.model, "my/custom-model");
  assert.equal(state.busy, false);
  assert.notEqual(state.status, "checking");
});

test("models discovery success ends loading and never stays on checking", () => {
  let state = nextProviderState(loaded({ model: "" }), { type: "modelsStarted" });
  assert.equal(state.busy, true);
  assert.equal(state.status, "checking");

  state = nextProviderState(state, { type: "modelsSucceeded", models: ["alpha:1"] });
  assert.equal(state.busy, false);
  assert.notEqual(state.status, "checking");
  assert.equal(state.status, "model_not_selected");
  assert.deepEqual(state.models, ["alpha:1"]);
});

test("models discovery success is ready when the selected model is installed", () => {
  const state = nextProviderState(loaded({ model: "alpha:1" }), {
    type: "modelsSucceeded",
    models: ["alpha:1", "beta:2"],
  });
  assert.equal(state.status, "ready");
  assert.equal(state.busy, false);
  assert.equal(isReady(state), true);
  assert.deepEqual(state.models, ["alpha:1", "beta:2"]);
});

test("models discovery success reports the selected model as missing", () => {
  const state = nextProviderState(loaded({ model: "ghost:9" }), {
    type: "modelsSucceeded",
    models: ["alpha:1"],
  });
  assert.equal(state.status, "model_not_found");
  assert.equal(state.busy, false);
});

test("models discovery success with no models preserves the selection but is not ready", () => {
  const state = nextProviderState(loaded({ model: "alpha:1" }), {
    type: "modelsSucceeded",
    models: [],
  });
  assert.equal(state.status, "no_models_installed");
  assert.equal(isReady(state), false);
  // The stale selection is still offered for editing, but the endpoint is
  // not treated as ready.
  assert.deepEqual(state.models, ["alpha:1"]);
});

test("classifyModelList mirrors the server classification", () => {
  assert.equal(classifyModelList("", []), "no_models_installed");
  assert.equal(classifyModelList("alpha:1", []), "no_models_installed");
  assert.equal(classifyModelList("", ["alpha:1"]), "model_not_selected");
  assert.equal(classifyModelList("alpha:1", ["alpha:1"]), "ready");
  assert.equal(classifyModelList("ghost", ["alpha:1"]), "model_not_found");
  // Whitespace and non-string entries never invent a model.
  assert.equal(classifyModelList("", ["  ", 5, null]), "no_models_installed");
  assert.equal(classifyModelList(" alpha:1 ", ["alpha:1"]), "ready");
});

test("classifyModelList accepts a documented router id absent from discovery", () => {
  // OpenRouter's automatic router must be selectable even when not listed.
  assert.equal(
    classifyModelList("openrouter/free", ["meta-llama/llama-3.3-70b"], [
      "openrouter/free",
    ]),
    "ready"
  );
  assert.equal(classifyModelList("openrouter/free", [], ["openrouter/free"]), "ready");
  // An undocumented missing model is still reported as not found.
  assert.equal(
    classifyModelList("ghost/model", ["meta-llama/llama-3.3-70b"], [
      "openrouter/free",
    ]),
    "model_not_found"
  );
  // No documented ids and no discovery stays terminal.
  assert.equal(classifyModelList("openrouter/free", []), "no_models_installed");
});

test("presetById looks up a preset without inventing one", () => {
  assert.equal(presetById(SAMPLE_PRESETS, "openrouter").label, "OpenRouter");
  assert.equal(presetById(SAMPLE_PRESETS, "nope"), null);
  assert.equal(presetById(undefined, "openrouter"), null);
});

test("documentedModelsFor reads the current preset's documented ids", () => {
  assert.deepEqual(documentedModelsFor(loaded({ provider: "openrouter" })), [
    "openrouter/free",
  ]);
  assert.deepEqual(documentedModelsFor(loaded({ provider: "ollama" })), []);
  assert.deepEqual(documentedModelsFor(initialProviderState()), []);
});

test("statusLoaded adopts the provider preset and preset list", () => {
  const state = loaded({ provider: "openrouter" });
  assert.equal(state.provider, "openrouter");
  assert.equal(state.presets.length, 2);
  assert.equal(state.saved.provider, "openrouter");
});

test("presetChanged fills the preset base URL and clears stale models", () => {
  const state = nextProviderState(
    loaded({ provider: "ollama", model: "qwen3:0.6b" }),
    {
      type: "presetChanged",
      id: "openrouter",
    }
  );
  assert.equal(state.provider, "openrouter");
  assert.equal(state.baseUrl, "https://openrouter.ai/api/v1");
  assert.deepEqual(state.models, []);
  // A model chosen for one provider must not leak into another.
  assert.equal(state.model, "");
  assert.equal(state.dirty, true);
  assert.equal(state.status, "unknown");
});

test("presetChanged keeps the current base URL when the preset has none", () => {
  const state = nextProviderState(
    loaded({ provider: "openrouter" }),
    { type: "presetChanged", id: "custom" }
  );
  assert.equal(state.provider, "custom");
  assert.equal(state.baseUrl, "http://127.0.0.1:11434");
});

test("modelsSucceeded treats the documented router as ready", () => {
  let state = loaded({ provider: "openrouter", model: "openrouter/free" });
  state = nextProviderState(state, {
    type: "modelsSucceeded",
    models: ["meta-llama/llama-3.3-70b"],
  });
  assert.equal(state.status, "ready");
});

test("input changes mark the state dirty without inventing a status", () => {
  const state = nextProviderState(loaded({ status: "ready" }), {
    type: "baseUrlChanged",
    value: "http://127.0.0.1:11500",
  });
  assert.equal(state.baseUrl, "http://127.0.0.1:11500");
  assert.equal(state.dirty, true);
  assert.equal(state.status, "unknown");
});

test("configSaved marks the settings as applied", () => {
  const state = nextProviderState(loaded(), {
    type: "configSaved",
    base_url: "http://127.0.0.1:11500",
    model: "beta:2",
    has_api_key: false,
    source: "runtime",
    status: "configured",
    message: "Applied.",
    models: null,
  });
  assert.equal(state.applied, true);
  assert.equal(state.model, "beta:2");
  assert.equal(state.source, "runtime");
});

test("statusLoaded records the active (saved) configuration", () => {
  const state = loaded({
    model: "alpha:1",
    source: "runtime",
    status: "configured",
  });
  assert.equal(state.saved.baseUrl, "http://127.0.0.1:11434");
  assert.equal(state.saved.model, "alpha:1");
  assert.equal(state.saved.source, "runtime");
});

test("editing the model does not change the active (saved) model", () => {
  const state = nextProviderState(loaded({ model: "" }), {
    type: "modelChanged",
    value: "draft:9",
  });
  assert.equal(state.model, "draft:9");
  assert.equal(state.dirty, true);
  assert.equal(state.saved.model, "");
});

test("editing the base URL does not change the active (saved) base URL", () => {
  const state = nextProviderState(loaded(), {
    type: "baseUrlChanged",
    value: "http://127.0.0.1:11999",
  });
  assert.equal(state.baseUrl, "http://127.0.0.1:11999");
  assert.equal(state.dirty, true);
  assert.equal(state.saved.baseUrl, "http://127.0.0.1:11434");
});

test("saving applies the edited configuration as the active one", () => {
  let state = nextProviderState(loaded({ model: "" }), {
    type: "modelChanged",
    value: "new:1",
  });
  state = nextProviderState(state, {
    type: "configSaved",
    base_url: "http://127.0.0.1:11434",
    model: "new:1",
    has_api_key: false,
    source: "runtime",
    status: "configured",
    message: "Applied.",
    models: null,
  });
  assert.equal(state.saved.model, "new:1");
  assert.equal(state.saved.source, "runtime");
  assert.equal(state.dirty, false);
  assert.equal(state.applied, true);
});

test("needsProviderApply is false for clean applied settings", () => {
  // Nothing typed and nothing unsaved: generation uses the configuration the
  // server already holds (environment or a prior save).
  assert.equal(needsProviderApply(loaded({ model: "alpha:1" })), false);
  assert.equal(needsProviderApply(initialProviderState()), false);
});

test("needsProviderApply is true while provider edits are unsaved", () => {
  const edited = nextProviderState(loaded({ model: "" }), {
    type: "modelChanged",
    value: "openrouter/free",
  });
  assert.equal(needsProviderApply(edited), true);
});

test("needsProviderApply is true when only an API key was typed", () => {
  // The key field is never stored in state, so the caller passes whether the
  // user typed one; a freshly typed key must be applied before generating.
  assert.equal(needsProviderApply(loaded({ model: "alpha:1" }), true), true);
  assert.equal(needsProviderApply(loaded({ model: "alpha:1" }), false), false);
});

test("needsProviderApply is false after the edits are applied", () => {
  let state = nextProviderState(loaded({ model: "" }), {
    type: "presetChanged",
    id: "openrouter",
  });
  state = nextProviderState(state, { type: "modelChanged", value: "openrouter/free" });
  assert.equal(needsProviderApply(state), true);
  state = nextProviderState(state, {
    type: "configSaved",
    provider: "openrouter",
    base_url: "https://openrouter.ai/api/v1",
    model: "openrouter/free",
    has_api_key: false,
    source: "runtime",
    status: "configured",
    message: "Applied.",
    models: null,
  });
  assert.equal(needsProviderApply(state), false);
});

test("apiKeyForApply sends a typed key as-is", () => {
  const state = loaded({ provider: "openrouter", model: "openrouter/free" });
  assert.equal(apiKeyForApply(state, "sk-or-typed"), "sk-or-typed");
  assert.equal(apiKeyForApply(state, "  sk-or-padded  "), "  sk-or-padded  ");
});

test("apiKeyForApply preserves the stored key when an unrelated field changed", () => {
  const state = nextProviderState(
    loaded({ provider: "openrouter", model: "openrouter/free" }),
    { type: "baseUrlChanged", value: "https://openrouter.ai/api/v2" }
  );
  assert.equal(state.provider, state.saved.provider);
  assert.equal(apiKeyForApply(state, ""), undefined);
});

test("apiKeyForApply clears the key when the provider changed", () => {
  // A key issued by one provider must never be sent to another.
  const state = nextProviderState(
    loaded({ provider: "openrouter", model: "openrouter/free" }),
    { type: "presetChanged", id: "openai" }
  );
  assert.notEqual(state.provider, state.saved.provider);
  assert.equal(apiKeyForApply(state, ""), "");
});

test("apiKeyForApply prefers a typed key over clearing on provider change", () => {
  const state = nextProviderState(
    loaded({ provider: "openrouter", model: "openrouter/free" }),
    { type: "presetChanged", id: "openai" }
  );
  assert.equal(apiKeyForApply(state, "sk-new-provider"), "sk-new-provider");
});

test("apiKeyForApply returns undefined before any provider is known", () => {
  assert.equal(apiKeyForApply(initialProviderState(), ""), undefined);
  assert.equal(apiKeyForApply(loaded({ provider: "", model: "" }), ""), undefined);
});

test("mergeModels de-duplicates and preserves discovered order", () => {
  assert.deepEqual(mergeModels(["beta:2", "alpha:1", "beta:2"], ""), [
    "beta:2",
    "alpha:1",
  ]);
});

test("mergeModels ensures the current selection is offered", () => {
  assert.deepEqual(mergeModels(["alpha:1"], "custom:9"), ["alpha:1", "custom:9"]);
});

test("mergeModels never invents models", () => {
  assert.deepEqual(mergeModels([], ""), []);
  assert.deepEqual(mergeModels(null, ""), []);
  assert.deepEqual(mergeModels(["", "   ", 5], ""), []);
});

test("statusInfo covers every classified status with a text label", () => {
  for (const status of [
    "unknown",
    "checking",
    "configured",
    "ready",
    "model_not_selected",
    "model_not_found",
    "no_models_installed",
    "unreachable",
    "timeout",
    "auth_error",
    "invalid_config",
    "provider_error",
  ]) {
    const info = statusInfo(status);
    assert.equal(typeof info.label, "string");
    assert.ok(info.label.length > 0, status);
    assert.ok(info.symbol.length > 0, status);
    assert.ok(["info", "ok", "warn", "error"].includes(info.tone), status);
  }
});

test("status labels are provider-neutral (no Ollama-only wording)", () => {
  // Hosted BYOK is the primary path; the reachable-status label must not say
  // "Ollama" as if local inference were the only option.
  assert.ok(!/ollama/i.test(STATUS_INFO.unreachable.label));
});

test("statusInfo falls back safely for an unknown status", () => {
  assert.equal(statusInfo("something-new"), STATUS_INFO.unknown);
});

test("announcementFor builds a label and message for the live region", () => {
  const state = loaded({ status: "unreachable", message: "Could not reach Ollama." });
  const text = announcementFor(state);
  assert.match(text, /unreachable/i);
  assert.match(text, /Could not reach Ollama/);
});

test("announcementFor announces busy state", () => {
  const state = nextProviderState(loaded(), { type: "probeStarted" });
  assert.match(announcementFor(state), /testing the ai provider connection/i);
});

test("isLoopbackHost recognises local addresses only", () => {
  for (const host of ["localhost", "LOCALHOST", "127.0.0.1", "127.5.5.5", "::1", "app.localhost"]) {
    assert.equal(isLoopbackHost(host), true, host);
  }
  for (const host of ["example.com", "10.0.0.5", "192.168.1.10", "128.0.0.1", "999.1.1.1", ""]) {
    assert.equal(isLoopbackHost(host), false, host);
  }
});

test("apiKeyFieldVisible is hidden for local endpoints and shown for hosted ones", () => {
  assert.equal(apiKeyFieldVisible("http://127.0.0.1:11434"), false);
  assert.equal(apiKeyFieldVisible("http://localhost:11434"), false);
  assert.equal(apiKeyFieldVisible("https://ollama.example.com"), true);
  // Incomplete or invalid input keeps the field hidden.
  assert.equal(apiKeyFieldVisible(""), false);
  assert.equal(apiKeyFieldVisible("not a url"), false);
  assert.equal(apiKeyFieldVisible("file:///etc/passwd"), false);
});

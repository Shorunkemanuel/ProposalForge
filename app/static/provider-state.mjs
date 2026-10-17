// Pure, DOM-free provider-setup state for Milestone 4.
//
// This module owns the provider configuration view state: which status is
// shown, which model options are offered, and what gets announced. It has no
// DOM, network, or storage access, so it is unit-testable with Node's built-in
// test runner. `app.js` owns all rendering and network side effects.

// Status information is communicated with a word (label) as well as a symbol;
// colour is never the only signal. The symbols are presentation only and are
// hidden from assistive technology in the DOM.
export const STATUS_INFO = {
  unknown: { label: "Not checked yet", symbol: "?", tone: "info" },
  checking: { label: "Testing connection", symbol: "…", tone: "info" },
  configured: { label: "Configuration set, not yet tested", symbol: "•", tone: "info" },
  ready: { label: "Connected, model available", symbol: "✓", tone: "ok" },
  model_not_selected: { label: "Connected, no model selected", symbol: "!", tone: "warn" },
  model_not_found: { label: "Connected, selected model not installed", symbol: "!", tone: "warn" },
  no_models_installed: { label: "Connected, no models installed", symbol: "!", tone: "warn" },
  unreachable: { label: "Provider unreachable", symbol: "✗", tone: "error" },
  timeout: { label: "Provider timed out", symbol: "✗", tone: "error" },
  auth_error: { label: "API key rejected", symbol: "✗", tone: "error" },
  invalid_config: { label: "Invalid configuration", symbol: "✗", tone: "error" },
  provider_error: { label: "Provider error", symbol: "✗", tone: "error" },
};

const FALLBACK_INFO = STATUS_INFO.unknown;

export function statusInfo(status) {
  return STATUS_INFO[status] || FALLBACK_INFO;
}

export function initialProviderState() {
  return {
    provider: "",
    presets: [],
    baseUrl: "",
    model: "",
    hasApiKey: false,
    source: "environment",
    status: "unknown",
    message: "",
    models: [],
    busy: false,
    dirty: false,
    applied: false,
    saved: {
      provider: "",
      baseUrl: "",
      model: "",
      hasApiKey: false,
      source: "environment",
    },
  };
}

// Look up a preset by id from the server-provided list (never invented).
export function presetById(presets, id) {
  if (!Array.isArray(presets)) return null;
  return presets.find((preset) => preset && preset.id === id) || null;
}

// Documented identifiers valid for the current preset even when a discovery
// response does not list them (for example OpenRouter's "openrouter/free"
// automatic router). These are provider-declared identifiers, not a billing
// signal, and no model is ever treated as free from its name alone.
export function documentedModelsFor(state) {
  const preset = presetById(state.presets, state.provider);
  return preset && Array.isArray(preset.documented_models)
    ? preset.documented_models
    : [];
}

// Merge discovered model names with the current selection so the selection is
// always offered, even before it is rediscovered. No model is ever invented:
// an empty discovery yields only the existing selection (or nothing).
export function mergeModels(discovered, selected) {
  const seen = new Set();
  const merged = [];
  for (const name of normalizeModelNames(discovered)) {
    if (seen.has(name)) continue;
    seen.add(name);
    merged.push(name);
  }
  const current = typeof selected === "string" ? selected.trim() : "";
  if (current && !seen.has(current)) {
    merged.push(current);
  }
  return merged;
}

// Non-empty, trimmed, string model names from a discovered list. Used for
// classification, which must inspect the real discovery (without the
// "current selection is always offered" merge, so a stale selection cannot
// hide that it is no longer installed).
function normalizeModelNames(discovered) {
  const names = [];
  for (const name of Array.isArray(discovered) ? discovered : []) {
    if (typeof name !== "string") continue;
    const value = name.trim();
    if (value) names.push(value);
  }
  return names;
}

// Classify a successful model discovery into a provider status, mirroring the
// server-side classification so a refresh always resolves to a terminal,
// non-loading status. An empty discovery cannot make the endpoint "ready",
// except for a documented identifier that is valid for the preset without
// being listed (for example OpenRouter's automatic router).
export function classifyModelList(selected, discovered, documented = []) {
  const names = normalizeModelNames(discovered);
  const current = typeof selected === "string" ? selected.trim() : "";
  const docs = Array.isArray(documented) ? documented : [];
  if (current && docs.includes(current) && !names.includes(current)) {
    return "ready";
  }
  if (names.length === 0) return "no_models_installed";
  if (!current) return "model_not_selected";
  return names.includes(current) ? "ready" : "model_not_found";
}

export function isReady(state) {
  return state.status === "ready";
}

// Generation must run against the provider configuration the server has
// actually applied, not values still sitting unsaved in the form: the
// connection test and model discovery are intentionally non-persistent. The
// proposal flow calls this before generating so unsaved provider edits are
// applied first. `apiKeyTyped` covers a freshly entered key, which is never
// stored in state because it must not be retained in the browser.
export function needsProviderApply(state, apiKeyTyped = false) {
  return Boolean(state && state.dirty) || Boolean(apiKeyTyped);
}

// The API-key value to send when applying the current provider form.
//
//   - a typed key is sent as-is;
//   - when the provider changed and no new key was typed, an empty string is
//     returned so the previous provider's key is cleared (a key issued by one
//     provider must never be sent to another);
//   - otherwise `undefined` means "leave the stored key in place", so editing
//     an unrelated field does not wipe an already saved key.
export function apiKeyForApply(state, typedKey) {
  const key = typeof typedKey === "string" ? typedKey : "";
  if (key.trim()) {
    return key;
  }
  if (
    state &&
    state.provider &&
    state.saved &&
    state.saved.provider &&
    state.provider !== state.saved.provider
  ) {
    return "";
  }
  return undefined;
}

// A local, loopback endpoint needs no API key, so the API-key field is only
// shown for non-loopback http(s) endpoints (hosted, key-authenticated
// services).
export function isLoopbackHost(hostname) {
  if (typeof hostname !== "string") return false;
  const host = hostname.trim().toLowerCase();
  if (!host) return false;
  if (host === "::1" || host === "[::1]") return true;
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!match) return false;
  const octets = match.slice(1).map(Number);
  if (octets.some((value) => value > 255)) return false;
  return octets[0] === 127;
}

export function apiKeyFieldVisible(baseUrl) {
  let url;
  try {
    url = new URL(baseUrl);
  } catch {
    return false;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return false;
  return !isLoopbackHost(url.hostname);
}

// Text for the polite live region. Only meaningful transitions are announced;
// app.js does not call this for per-keystroke edits.
export function announcementFor(state) {
  if (state.busy) {
    return "Testing the AI provider connection. Please wait.";
  }
  const info = statusInfo(state.status);
  if (state.status === "unknown") {
    return state.message || "";
  }
  const parts = [`AI provider status: ${info.label}.`];
  if (state.message) parts.push(state.message);
  if (state.applied) parts.push("Provider settings saved for this session.");
  return parts.join(" ");
}

function fromStatusEvent(state, event, extra = {}) {
  // A passive/config response carries no model list (models is null); keep the
  // previously discovered list rather than dropping it.
  const discovered = Array.isArray(event.models) ? event.models : state.models;
  const presets =
    Array.isArray(event.presets) && event.presets.length > 0
      ? event.presets
      : state.presets;
  const provider = event.provider || state.provider;
  return {
    provider,
    presets,
    baseUrl: event.base_url,
    model: event.model,
    hasApiKey: Boolean(event.has_api_key),
    source: event.source,
    status: event.status,
    message: event.message || "",
    models: mergeModels(discovered, event.model),
    busy: false,
    dirty: false,
    applied: Boolean(extra.applied),
    saved: {
      provider,
      baseUrl: event.base_url,
      model: event.model,
      hasApiKey: Boolean(event.has_api_key),
      source: event.source,
    },
  };
}

export function nextProviderState(state, event) {
  switch (event.type) {
    case "statusLoaded":
    case "configSaved":
      return {
        ...state,
        ...fromStatusEvent(state, event, { applied: event.type === "configSaved" }),
      };

    case "probeStarted":
    case "modelsStarted":
    case "saveStarted":
      return { ...state, busy: true, status: "checking", message: "", applied: false };

    case "probeSucceeded":
      return {
        ...state,
        busy: false,
        status: event.status,
        message: event.message || "",
        models: mergeModels(event.models, event.model || state.model),
        applied: false,
      };

    case "modelsSucceeded":
      return {
        ...state,
        busy: false,
        models: mergeModels(event.models, state.model),
        status: classifyModelList(
          state.model,
          event.models,
          documentedModelsFor(state)
        ),
        message: "",
        applied: false,
      };

    case "presetChanged": {
      const preset = presetById(state.presets, event.id);
      const nextBase =
        preset && preset.base_url ? preset.base_url : state.baseUrl;
      return {
        ...state,
        provider: event.id,
        baseUrl: nextBase,
        // A model selected for one provider is not valid for another, so the
        // selection and the discovered list are cleared to avoid stale state.
        model: "",
        models: [],
        dirty: true,
        applied: false,
        status: state.status === "checking" ? state.status : "unknown",
        message: "",
      };
    }

    case "probeFailed":
    case "modelsFailed":
    case "configFailed":
      return {
        ...state,
        busy: false,
        status: "provider_error",
        message: event.message || "Could not reach the ProposalForge server.",
        applied: false,
      };

    case "baseUrlChanged":
      return {
        ...state,
        baseUrl: event.value,
        dirty: true,
        applied: false,
        status: state.status === "checking" ? state.status : "unknown",
      };

    case "modelChanged":
      return {
        ...state,
        model: event.value,
        dirty: true,
        applied: false,
        status: state.status === "checking" ? state.status : "unknown",
      };

    default:
      return state;
  }
}

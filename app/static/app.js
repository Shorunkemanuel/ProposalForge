import {
  STALE_NOTICE,
  STALE_STATUS,
  REVIEW_REVOKED_STATUS,
  createState,
  formSignature,
  isCopyEnabled,
  isStale,
  nextState,
} from "./review-state.mjs";

import {
  announcementFor,
  apiKeyFieldVisible,
  apiKeyForApply,
  initialProviderState,
  isReady,
  needsProviderApply,
  nextProviderState,
  presetById,
  statusInfo,
} from "./provider-state.mjs";

const DRAFT_FIELDS = [
  ["introduction", "Introduction"],
  ["project_understanding", "Understanding of the project"],
  ["proposed_approach", "Proposed approach"],
  ["timeline", "Timeline"],
  ["relevant_experience", "Relevant skills or experience"],
  ["pricing_explanation", "Pricing explanation"],
  ["closing", "Closing"],
];

const PRICING_LABELS = [
  ["hourly_rate", "Hourly rate"],
  ["estimated_hours", "Estimated hours"],
  ["labor_cost", "Labor cost"],
  ["expenses", "Additional expenses"],
  ["total", "Total"],
];

const MONEY_KEYS = new Set(["hourly_rate", "labor_cost", "expenses", "total"]);

const form = document.getElementById("proposal-form");
const submitBtn = document.getElementById("submit-btn");
const statusBox = document.getElementById("status");
const errorBox = document.getElementById("error-box");
const pricingCard = document.getElementById("pricing-card");
const pricingTable = document.getElementById("pricing-table");
const draftCard = document.getElementById("draft-card");
const draftNotice = document.getElementById("draft-notice");
const draftFields = document.getElementById("draft-fields");
const missingBox = document.getElementById("missing-box");
const missingList = document.getElementById("missing-list");
const readinessList = document.getElementById("readiness-list");
const readinessWarnings = document.getElementById("readiness-warnings");
const readinessSummary = document.getElementById("readiness-summary");
const readinessStatus = document.getElementById("readiness-status");
const reviewAck = document.getElementById("review-ack");
const copyBtn = document.getElementById("copy-btn");
const copyFallback = document.getElementById("copy-fallback");
const copyFallbackText = document.getElementById("copy-fallback-text");
const staleNotices = document.querySelectorAll("[data-stale]");

let lastPricing = null;
let gate = createState();

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function announce(message) {
  statusBox.textContent = message;
}

const prefersReducedMotion = () =>
  window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function scrollIntoView(el) {
  if (prefersReducedMotion()) {
    el.scrollIntoView();
  } else {
    el.scrollIntoView({ behavior: "smooth" });
  }
}

function hideCopyFallback() {
  copyFallback.hidden = true;
  copyFallbackText.value = "";
}

function setStaleNotice(stale) {
  for (const el of staleNotices) {
    el.hidden = !stale;
    el.textContent = stale ? STALE_NOTICE : "";
  }
  pricingCard.classList.toggle("is-stale", stale);
  draftCard.classList.toggle("is-stale", stale);
  if (stale) {
    setDescribedBy(reviewAck, "stale-notice", null);
    setDescribedBy(copyBtn, "stale-notice", null);
    setDescribedBy(pricingCard, "pricing-stale-notice", null);
  } else {
    setDescribedBy(reviewAck, null, "stale-notice");
    setDescribedBy(copyBtn, null, "stale-notice");
    setDescribedBy(pricingCard, null, "pricing-stale-notice");
  }
}

function syncReviewUi() {
  reviewAck.checked = gate.reviewed;
  copyBtn.disabled = !isCopyEnabled(gate);
  if (!isCopyEnabled(gate)) {
    hideCopyFallback();
  }
  setStaleNotice(isStale(gate));
}

function assembleProposalText() {
  const lines = ["Proposal draft"];
  if (draftNotice.textContent) {
    lines.push(draftNotice.textContent);
  }
  lines.push("");
  for (const [key, label] of DRAFT_FIELDS) {
    const field = document.getElementById(`draft-${key}`);
    lines.push(`${label}:`);
    lines.push(field ? field.value : "");
    lines.push("");
  }

  const missingItems = Array.from(missingList.querySelectorAll("li"));
  if (missingItems.length) {
    lines.push("Missing information to resolve:");
    for (const item of missingItems) {
      lines.push(`- ${item.textContent}`);
    }
    lines.push("");
  }

  lines.push("Calculated pricing (authoritative):");
  if (lastPricing) {
    for (const [key, label] of PRICING_LABELS) {
      const value = MONEY_KEYS.has(key)
        ? `${lastPricing[key]} ${lastPricing.currency}`
        : lastPricing[key];
      lines.push(`${label}: ${value}`);
    }
  }
  return lines.join("\n");
}

function showCopyFallback(text, message) {
  copyFallbackText.value = text;
  copyFallback.hidden = false;
  announce(message);
}

// The clipboard attempt is asynchronous, so the result can go stale or lose
// its review acknowledgement while the write is still pending. Stale content
// must never be offered for manual copying afterwards.
function showCopyFallbackIfEligible(text, message) {
  if (isCopyEnabled(gate)) {
    showCopyFallback(text, message);
    return;
  }
  hideCopyFallback();
}

async function copyProposal() {
  if (copyBtn.disabled) return;
  const text = assembleProposalText();
  hideCopyFallback();

  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      announce("Proposal copied to the clipboard.");
      return;
    } catch (err) {
      showCopyFallbackIfEligible(
        text,
        "Copying to the clipboard was blocked or unavailable. Use the manual copy box below to select and copy the proposal."
      );
      return;
    }
  }

  showCopyFallbackIfEligible(
    text,
    "Clipboard access is not available in this browser. Use the manual copy box below to select and copy the proposal."
  );
}

function setDescribedBy(el, addId, removeId) {
  const ids = (el.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
  const next = ids.filter((id) => id !== removeId);
  if (addId && !next.includes(addId)) next.push(addId);
  if (next.length) el.setAttribute("aria-describedby", next.join(" "));
  else el.removeAttribute("aria-describedby");
}

function clearFieldErrors() {
  for (const el of form.elements) {
    if (!el.name) continue;
    el.removeAttribute("aria-invalid");
    setDescribedBy(el, null, `${el.id}-error`);
    const existing = document.getElementById(`${el.id}-error`);
    if (existing) existing.remove();
  }
}

function showFieldErrors(fields) {
  const messages = [];
  let firstInvalid = null;
  for (const [name, message] of Object.entries(fields)) {
    messages.push(message);
    const el = form.elements[name];
    if (!el || !el.id) continue;
    el.setAttribute("aria-invalid", "true");
    const errorId = `${el.id}-error`;
    let errorEl = document.getElementById(errorId);
    if (!errorEl) {
      errorEl = document.createElement("small");
      errorEl.id = errorId;
      errorEl.className = "field-error";
      el.insertAdjacentElement("afterend", errorEl);
    }
    errorEl.textContent = message;
    setDescribedBy(el, errorId, null);
    if (!firstInvalid) firstInvalid = el;
  }
  if (firstInvalid) firstInvalid.focus();
  return messages;
}

function renderPricing(pricing) {
  lastPricing = pricing;
  pricingTable.innerHTML = "";
  for (const [key, label] of PRICING_LABELS) {
    const row = document.createElement("tr");
    const th = document.createElement("th");
    th.setAttribute("scope", "row");
    th.textContent = label;
    const td = document.createElement("td");
    td.textContent = MONEY_KEYS.has(key)
      ? `${pricing[key]} ${pricing.currency}`
      : pricing[key];
    row.append(th, td);
    pricingTable.appendChild(row);
  }
  pricingCard.hidden = false;
}

function renderDraft(result) {
  draftNotice.textContent = result.notice;
  draftFields.innerHTML = "";
  for (const [key, label] of DRAFT_FIELDS) {
    const wrapper = document.createElement("label");
    wrapper.setAttribute("for", `draft-${key}`);
    wrapper.textContent = label;
    const textarea = document.createElement("textarea");
    textarea.value = result.draft[key];
    textarea.rows = 5;
    textarea.id = `draft-${key}`;
    wrapper.appendChild(textarea);
    draftFields.appendChild(wrapper);
  }

  const missing = result.draft.missing_information || [];
  missingList.innerHTML = "";
  if (missing.length === 0) {
    missingBox.hidden = true;
  } else {
    for (const item of missing) {
      const li = document.createElement("li");
      li.textContent = item;
      missingList.appendChild(li);
    }
    missingBox.hidden = false;
  }
  draftCard.hidden = false;
  draftCard.focus({ preventScroll: true });
  scrollIntoView(draftCard);
}

function collectFormData() {
  const data = {};
  for (const element of form.elements) {
    if (element.name) data[element.name] = element.value;
  }
  return data;
}

let announcedSignature = null;

function renderReadiness(report) {
  const warnings = report.warnings || [];
  readinessList.innerHTML = "";
  for (const section of report.sections) {
    const li = document.createElement("li");
    li.className = "check-item " + (section.complete ? "is-complete" : "is-incomplete");

    const mark = document.createElement("span");
    mark.className = "check-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = section.complete ? "✓" : "✗";

    const body = document.createElement("span");
    body.className = "check-body";

    const label = document.createElement("span");
    label.className = "check-label";
    label.textContent = section.label;

    const state = document.createElement("span");
    state.className = "check-state";
    state.textContent = section.complete ? "Complete" : "Incomplete";

    body.append(label, state);

    if (!section.complete) {
      const details = section.items
        .filter((item) => !item.complete)
        .map((item) => `${item.label}: ${item.message}`);
      const detail = document.createElement("span");
      detail.className = "check-detail";
      detail.textContent = details.join(" ");
      body.appendChild(detail);
    }

    li.append(mark, body);
    readinessList.appendChild(li);
  }

  readinessWarnings.innerHTML = "";
  for (const warning of warnings) {
    const box = document.createElement("p");
    box.className = "readiness-warning";
    const mark = document.createElement("span");
    mark.className = "warn-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = "!";
    const text = document.createElement("span");
    text.textContent = `${warning.label}: ${warning.message}`;
    box.append(mark, text);
    readinessWarnings.appendChild(box);
  }
  readinessWarnings.hidden = warnings.length === 0;

  let summary;
  if (report.ready) {
    summary = "All required sections complete. You can generate the draft.";
  } else if (warnings.length) {
    summary =
      `${report.complete_sections} of ${report.total_sections} sections complete. ` +
      "Fix the highlighted issue before generating.";
  } else {
    summary =
      `${report.complete_sections} of ${report.total_sections} sections complete. ` +
      "Complete the remaining required inputs before generating.";
  }
  readinessSummary.textContent = summary;

  const signature =
    `${report.complete_sections}|` + warnings.map((warning) => warning.message).join(",");
  if (signature !== announcedSignature) {
    announcedSignature = signature;
    const warningText = warnings
      .map((warning) => `${warning.label}: ${warning.message}`)
      .join(" ");
    readinessStatus.textContent = warningText ? `${summary} ${warningText}` : summary;
  }
}

let readinessTimer = null;

async function refreshReadiness() {
  try {
    const response = await fetch("/api/readiness", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectFormData()),
    });
    if (!response.ok) return;
    renderReadiness(await response.json());
  } catch (err) {
    readinessSummary.textContent = "Readiness check unavailable until the server is reachable.";
  }
}

function scheduleReadiness() {
  window.clearTimeout(readinessTimer);
  readinessTimer = window.setTimeout(refreshReadiness, 250);
}

form.addEventListener("input", () => {
  const staleBefore = isStale(gate);
  gate = nextState(gate, { type: "inputsChanged" });
  syncReviewUi();
  if (!staleBefore && isStale(gate)) {
    announce(STALE_STATUS);
  }
  scheduleReadiness();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  clearFieldErrors();

  // The connection test and model discovery run against the form values
  // without persisting them, so generation would otherwise use a stale
  // (or empty) applied configuration. Apply any unsaved provider settings
  // first, through the same runtime configuration endpoint the setup card
  // uses, so what was tested is what generates.
  const apiKeyTyped =
    !providerApiKeyField.hidden && providerApiKey.value.trim() !== "";
  if (needsProviderApply(providerState, apiKeyTyped)) {
    const applied = await saveProviderSettings(providerApplyPayload());
    if (!applied) {
      showError(
        "Generation stopped: the AI provider settings could not be applied.\n" +
          "Check the AI provider setup at the top of the page."
      );
      announce("Generation stopped: the AI provider settings could not be applied.");
      return;
    }
  }

  const data = collectFormData();
  const submittedSig = formSignature(data);

  gate = nextState(gate, { type: "generationStarted" });
  const requestId = gate.requestId;

  submitBtn.disabled = true;
  submitBtn.textContent = "Generating…";
  announce("Generating your proposal draft. Please wait.");

  try {
    const response = await fetch("/api/proposals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const body = await response.json().catch(() => null);

    if (!response.ok) {
      if (requestId !== gate.requestId) {
        return;
      }
      gate = nextState(gate, { type: "generationFailed" });
      syncReviewUi();
      if (body && body.error === "validation_error" && body.fields) {
        const messages = showFieldErrors(body.fields);
        showError("Please correct the highlighted fields:\n" + messages.join("\n"));
        announce("The form has " + messages.length + " error(s). Review and correct them.");
      } else if (body && body.message) {
        const hint =
          typeof body.error === "string" && body.error.startsWith("provider")
            ? "\nCheck the AI provider setup at the top of the page."
            : "";
        showError(body.message + hint);
        announce("Generation failed. " + body.message + hint);
      } else {
        showError("The request failed. Please try again.");
        announce("The request failed. Please try again.");
      }
      return;
    }

    if (requestId !== gate.requestId) {
      return;
    }

    const currentSig = formSignature(collectFormData());
    gate = nextState(gate, {
      type: "generationSucceeded",
      requestId,
      submittedSig,
      currentSig,
    });
    renderPricing(body.pricing);
    renderDraft(body);
    syncReviewUi();
    announce(
      isStale(gate)
        ? STALE_STATUS
        : "Proposal draft generated. Review and edit it before use."
    );
  } catch (err) {
    if (requestId !== gate.requestId) {
      return;
    }
    gate = nextState(gate, { type: "generationFailed" });
    syncReviewUi();
    showError("Could not reach the ProposalForge server.");
    announce("Could not reach the ProposalForge server.");
  } finally {
    if (requestId === gate.requestId) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Generate draft";
    }
  }
});

draftFields.addEventListener("input", () => {
  const wasReviewed = gate.reviewed;
  gate = nextState(gate, { type: "draftEdited" });
  syncReviewUi();
  if (wasReviewed) {
    announce(REVIEW_REVOKED_STATUS);
  }
});

reviewAck.addEventListener("change", () => {
  const attempted = reviewAck.checked;
  gate = nextState(gate, { type: "reviewSet", checked: attempted });
  syncReviewUi();
  if (gate.reviewed) {
    announce("Review confirmed. You can now copy the proposal.");
  } else if (attempted) {
    announce(STALE_STATUS);
  } else {
    announce("Review confirmation removed. Copying is disabled until you confirm again.");
  }
});

copyBtn.addEventListener("click", copyProposal);

const providerForm = document.getElementById("provider-form");
const providerPreset = document.getElementById("provider-preset");
const providerPresetHelp = document.getElementById("provider-preset-help");
const providerBaseUrl = document.getElementById("provider-base-url");
const providerModel = document.getElementById("provider-model");
const providerModelList = document.getElementById("provider-model-list");
const providerModelHelp = document.getElementById("provider-model-help");
const providerAutoModelBtn = document.getElementById("provider-auto-model-btn");
const providerApiKeyField = document.getElementById("provider-api-key-field");
const providerApiKey = document.getElementById("provider-api-key");
const providerTestBtn = document.getElementById("provider-test-btn");
const providerModelsBtn = document.getElementById("provider-models-btn");
const providerSaveBtn = document.getElementById("provider-save-btn");
const providerErrorBox = document.getElementById("provider-error");
const providerStatus = document.getElementById("provider-status");
const providerStatusMark = document.getElementById("provider-status-mark");
const providerStatusLabel = document.getElementById("provider-status-label");
const providerStatusMessage = document.getElementById("provider-status-message");
const providerNextSteps = document.getElementById("provider-next-steps");
const providerAnnounce = document.getElementById("provider-announce");
const providerCurrentProvider = document.getElementById("provider-current-provider");
const providerCurrentUrl = document.getElementById("provider-current-url");
const providerCurrentModel = document.getElementById("provider-current-model");
const providerCurrentKeyState = document.getElementById("provider-current-key-state");

let providerState = initialProviderState();

function showProviderError(message) {
  providerErrorBox.textContent = message;
  providerErrorBox.hidden = false;
}

function clearProviderError() {
  providerErrorBox.hidden = true;
  providerErrorBox.textContent = "";
}

function announceProvider() {
  providerAnnounce.textContent = announcementFor(providerState);
}

function syncProviderInput(input, value) {
  if (document.activeElement !== input && input.value !== value) {
    input.value = value;
  }
}

function renderProviderModels() {
  providerModelList.innerHTML = "";
  for (const name of providerState.models) {
    const option = document.createElement("option");
    option.value = name;
    providerModelList.appendChild(option);
  }
}

let renderedPresetSignature = "";

function renderProviderPresets() {
  const presets = providerState.presets;
  const signature = presets.map((preset) => preset.id).join(",");
  if (signature && signature !== renderedPresetSignature) {
    providerPreset.innerHTML = "";
    for (const preset of presets) {
      const option = document.createElement("option");
      option.value = preset.id;
      option.textContent = preset.label;
      providerPreset.appendChild(option);
    }
    renderedPresetSignature = signature;
  }
  if (providerPreset.value !== providerState.provider) {
    providerPreset.value = providerState.provider;
  }
}

function renderProviderHints(preset) {
  providerPresetHelp.textContent = preset
    ? preset.key_hint
    : "Choose a provider preset to fill in its documented base URL, or pick a custom compatible endpoint.";
  providerModelHelp.textContent = preset
    ? preset.model_hint
    : "Type the model identifier offered by your endpoint, or choose one discovered from it.";
}

function renderAutoModelButton(preset) {
  const auto = preset && preset.auto_model;
  providerAutoModelBtn.hidden = !auto;
  if (auto) {
    providerAutoModelBtn.textContent =
      preset.auto_model_label || `Use ${auto}`;
  }
}

function renderProvider() {
  const preset = presetById(providerState.presets, providerState.provider);
  const savedPreset = presetById(providerState.presets, providerState.saved.provider);
  const savedLabel = savedPreset ? savedPreset.label : "Not selected";
  providerCurrentProvider.textContent =
    providerState.saved.source === "runtime"
      ? `${savedLabel} (adjusted this session)`
      : savedLabel;
  providerCurrentUrl.textContent = providerState.saved.baseUrl || "—";
  providerCurrentModel.textContent = providerState.saved.model || "None selected";
  providerCurrentKeyState.textContent = providerState.saved.hasApiKey
    ? "Set (value hidden)"
    : "Not set";

  renderProviderPresets();
  syncProviderInput(providerBaseUrl, providerState.baseUrl);
  syncProviderInput(providerModel, providerState.model);

  const apiKeyVisible = apiKeyFieldVisible(providerBaseUrl.value || providerState.baseUrl);
  providerApiKeyField.hidden = !apiKeyVisible;
  if (!apiKeyVisible) providerApiKey.value = "";

  renderProviderModels();
  renderProviderHints(preset);
  renderAutoModelButton(preset);

  const info = statusInfo(providerState.status);
  providerStatus.className = "provider-status tone-" + info.tone;
  providerStatusMark.textContent = info.symbol;
  providerStatusLabel.textContent = info.label;
  providerStatusMessage.textContent = providerState.message;

  providerNextSteps.hidden = isReady(providerState);

  providerTestBtn.disabled = providerState.busy;
  providerModelsBtn.disabled = providerState.busy;
  providerSaveBtn.disabled = providerState.busy;
}

function clearProviderFieldErrors() {
  for (const el of providerForm.elements) {
    if (!el.name) continue;
    el.removeAttribute("aria-invalid");
    setDescribedBy(el, null, `${el.id}-error`);
    const existing = document.getElementById(`${el.id}-error`);
    if (existing) existing.remove();
  }
}

function showProviderFieldErrors(fields) {
  const messages = [];
  let firstInvalid = null;
  for (const [name, message] of Object.entries(fields)) {
    messages.push(message);
    const el = providerForm.elements[name];
    if (!el || !el.id) continue;
    el.setAttribute("aria-invalid", "true");
    const errorId = `${el.id}-error`;
    let errorEl = document.getElementById(errorId);
    if (!errorEl) {
      errorEl = document.createElement("small");
      errorEl.id = errorId;
      errorEl.className = "field-error";
      el.insertAdjacentElement("afterend", errorEl);
    }
    errorEl.textContent = message;
    setDescribedBy(el, errorId, null);
    if (!firstInvalid) firstInvalid = el;
  }
  if (firstInvalid) firstInvalid.focus();
  showProviderError(
    "Please correct the highlighted provider settings:\n" + messages.join("\n")
  );
}

async function providerRequest(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => null);
  return { response, body };
}

function providerFormPayload() {
  const payload = { base_url: providerBaseUrl.value, model: providerModel.value };
  if (providerPreset.value) {
    payload.provider = providerPreset.value;
  }
  if (!providerApiKeyField.hidden && providerApiKey.value.trim()) {
    payload.api_key = providerApiKey.value;
  }
  return payload;
}

function providerFormOptions() {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(providerFormPayload()),
  };
}

// Payload for applying the provider form before generation. It clears a
// previously saved key when the provider changed (a key issued by one provider
// must never be sent to another) and otherwise omits the key so an existing
// saved key is preserved across unrelated edits.
function providerApplyPayload() {
  const payload = { base_url: providerBaseUrl.value, model: providerModel.value };
  if (providerPreset.value) {
    payload.provider = providerPreset.value;
  }
  const key = apiKeyForApply(
    providerState,
    providerApiKeyField.hidden ? "" : providerApiKey.value
  );
  if (key !== undefined) {
    payload.api_key = key;
  }
  return payload;
}

async function refreshProviderStatus() {
  try {
    const { response, body } = await providerRequest("/api/provider/status");
    if (!response.ok || !body || !body.status) {
      throw new Error("unexpected");
    }
    providerState = nextProviderState(providerState, { type: "statusLoaded", ...body });
  } catch (err) {
    providerState = nextProviderState(providerState, {
      type: "probeFailed",
      message: "Could not load provider status from the ProposalForge server.",
    });
  }
  renderProvider();
  announceProvider();
}

async function testProvider() {
  clearProviderError();
  clearProviderFieldErrors();
  providerState = nextProviderState(providerState, { type: "probeStarted" });
  renderProvider();
  announceProvider();
  try {
    const { response, body } = await providerRequest("/api/provider/test", providerFormOptions());
    if (!response.ok || !body || !body.status) {
      throw new Error("unexpected");
    }
    providerState = nextProviderState(providerState, {
      type: "probeSucceeded",
      status: body.status,
      message: body.message,
      models: body.models,
      model: body.model,
    });
  } catch (err) {
    providerState = nextProviderState(providerState, {
      type: "probeFailed",
      message: "Could not reach the ProposalForge server to test the provider.",
    });
  }
  renderProvider();
  announceProvider();
}

async function refreshModels() {
  clearProviderError();
  providerState = nextProviderState(providerState, { type: "modelsStarted" });
  renderProvider();
  announceProvider();
  try {
    const { response, body } = await providerRequest("/api/provider/models", providerFormOptions());
    if (response.ok && body && Array.isArray(body.models)) {
      providerState = nextProviderState(providerState, {
        type: "modelsSucceeded",
        models: body.models,
      });
    } else {
      providerState = nextProviderState(providerState, {
        type: "modelsFailed",
        message: (body && body.message) || "Could not list models from the provider.",
      });
    }
  } catch (err) {
    providerState = nextProviderState(providerState, {
      type: "modelsFailed",
      message: "Could not reach the ProposalForge server to list models.",
    });
  }
  renderProvider();
  announceProvider();
}

// Apply a provider configuration to the running server. This is the same
// authoritative runtime configuration mechanism the setup card's Save button
// uses; generation and the provider setup endpoints therefore share one source
// of truth and no configuration is duplicated in the browser.
async function saveProviderSettings(payload) {
  providerState = nextProviderState(providerState, { type: "saveStarted" });
  renderProvider();
  announceProvider();

  try {
    const { response, body } = await providerRequest("/api/provider/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.status === 400 && body && body.fields) {
      providerState = nextProviderState(providerState, {
        type: "configFailed",
        message: "Some provider settings are invalid.",
      });
      renderProvider();
      showProviderFieldErrors(body.fields);
      announceProvider();
      return false;
    }
    if (!response.ok || !body || !body.status) {
      providerState = nextProviderState(providerState, {
        type: "configFailed",
        message: (body && body.message) || "Could not save provider settings.",
      });
      renderProvider();
      announceProvider();
      return false;
    }
    providerState = nextProviderState(providerState, { type: "configSaved", ...body });
    if (!providerApiKeyField.hidden) providerApiKey.value = "";
  } catch (err) {
    providerState = nextProviderState(providerState, {
      type: "configFailed",
      message: "Could not reach the ProposalForge server to save provider settings.",
    });
    renderProvider();
    announceProvider();
    return false;
  }
  renderProvider();
  announceProvider();
  return true;
}

providerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearProviderError();
  clearProviderFieldErrors();

  const payload = { base_url: providerBaseUrl.value, model: providerModel.value };
  if (providerPreset.value) {
    payload.provider = providerPreset.value;
  }
  if (!providerApiKeyField.hidden) {
    payload.api_key = providerApiKey.value;
  }

  await saveProviderSettings(payload);
});

providerBaseUrl.addEventListener("input", () => {
  providerState = nextProviderState(providerState, {
    type: "baseUrlChanged",
    value: providerBaseUrl.value,
  });
  renderProvider();
});

providerPreset.addEventListener("change", () => {
  clearProviderError();
  // A key issued by one provider must not be silently reused for another, so
  // the (password) key input is cleared when the provider changes.
  providerApiKey.value = "";
  providerState = nextProviderState(providerState, {
    type: "presetChanged",
    id: providerPreset.value,
  });
  renderProvider();
  announceProvider();
});

providerAutoModelBtn.addEventListener("click", () => {
  const preset = presetById(providerState.presets, providerState.provider);
  if (!preset || !preset.auto_model) return;
  providerModel.value = preset.auto_model;
  providerState = nextProviderState(providerState, {
    type: "modelChanged",
    value: preset.auto_model,
  });
  renderProvider();
});

providerModel.addEventListener("input", () => {
  providerState = nextProviderState(providerState, {
    type: "modelChanged",
    value: providerModel.value,
  });
  renderProvider();
});

providerTestBtn.addEventListener("click", testProvider);
providerModelsBtn.addEventListener("click", refreshModels);

renderProvider();
refreshProviderStatus();

scheduleReadiness();

"use strict";

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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  clearFieldErrors();

  const data = {};
  for (const element of form.elements) {
    if (element.name) data[element.name] = element.value;
  }

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
      if (body && body.error === "validation_error" && body.fields) {
        const messages = showFieldErrors(body.fields);
        showError("Please correct the highlighted fields:\n" + messages.join("\n"));
        announce("The form has " + messages.length + " error(s). Review and correct them.");
      } else if (body && body.message) {
        showError(body.message);
        announce("Generation failed. " + body.message);
      } else {
        showError("The request failed. Please try again.");
        announce("The request failed. Please try again.");
      }
      return;
    }

    renderPricing(body.pricing);
    renderDraft(body);
    announce("Proposal draft generated. Review and edit it before use.");
  } catch (err) {
    showError("Could not reach the ProposalForge server.");
    announce("Could not reach the ProposalForge server.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Generate draft";
  }
});

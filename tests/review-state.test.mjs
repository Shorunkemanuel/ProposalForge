import test from "node:test";
import assert from "node:assert/strict";

import {
  createState,
  formSignature,
  isCopyEnabled,
  isStale,
  nextState,
} from "../app/static/review-state.mjs";

const SIG_A = formSignature({ client_name: "Acme", brief: "A brief that is long enough." });
const SIG_B = formSignature({ client_name: "Beta", brief: "A different brief that is long." });

function generated(submittedSig = SIG_A, currentSig = SIG_A) {
  let state = nextState(createState(), { type: "generationStarted" });
  const requestId = state.requestId;
  state = nextState(state, {
    type: "generationSucceeded",
    requestId,
    submittedSig,
    currentSig,
  });
  return state;
}

function reviewed(state) {
  return nextState(state, { type: "reviewSet", checked: true });
}

test("initial state is not stale and not copy-eligible", () => {
  const state = createState();
  assert.equal(isStale(state), false);
  assert.equal(isCopyEnabled(state), false);
});

test("generation alone does not enable copy; review enables it", () => {
  const state = generated();
  assert.equal(state.hasResult, true);
  assert.equal(isStale(state), false);
  assert.equal(isCopyEnabled(state), false);

  const acked = reviewed(state);
  assert.equal(acked.reviewed, true);
  assert.equal(isCopyEnabled(acked), true);
});

test("draft edit after acknowledgement revokes review and disables copy", () => {
  const acked = reviewed(generated());
  assert.equal(isCopyEnabled(acked), true);

  const edited = nextState(acked, { type: "draftEdited" });
  assert.equal(edited.reviewed, false);
  assert.equal(isStale(edited), false);
  assert.equal(isCopyEnabled(edited), false);
});

test("draft edit before acknowledgement keeps copy disabled without stale", () => {
  const state = generated();
  const edited = nextState(state, { type: "draftEdited" });
  assert.equal(edited.hasResult, true);
  assert.equal(edited.reviewed, false);
  assert.equal(isStale(edited), false);
  assert.equal(isCopyEnabled(edited), false);
});

test("source change after generation marks stale, revokes review, disables copy", () => {
  const state = nextState(reviewed(generated()), { type: "inputsChanged" });
  assert.equal(isStale(state), true);
  assert.equal(state.reviewed, false);
  assert.equal(isCopyEnabled(state), false);
});

test("source change is latched and does not clear without regeneration", () => {
  let state = nextState(generated(), { type: "inputsChanged" });
  assert.equal(isStale(state), true);
  // Further edits (or reverting the value) do not restore eligibility.
  state = nextState(state, { type: "inputsChanged" });
  assert.equal(isStale(state), true);
  assert.equal(isCopyEnabled(state), false);

  // Only a successful regeneration for the current inputs clears stale.
  state = nextState(state, { type: "generationStarted" });
  state = nextState(state, {
    type: "generationSucceeded",
    requestId: state.requestId,
    submittedSig: SIG_A,
    currentSig: SIG_A,
  });
  assert.equal(isStale(state), false);
  assert.equal(state.reviewed, false);
  assert.equal(isCopyEnabled(state), false);
});

test("successful regeneration with changed inputs during flight stays stale", () => {
  const state = generated(SIG_A, SIG_B);
  assert.equal(isStale(state), true);
  assert.equal(isCopyEnabled(state), false);
});

test("older in-flight response is ignored", () => {
  let state = nextState(createState(), { type: "generationStarted" });
  const olderId = state.requestId;
  state = nextState(state, { type: "generationStarted" });
  const newerId = state.requestId;

  const afterOlder = nextState(state, {
    type: "generationSucceeded",
    requestId: olderId,
    submittedSig: SIG_A,
    currentSig: SIG_A,
  });
  assert.equal(afterOlder, state);

  const afterNewer = nextState(state, {
    type: "generationSucceeded",
    requestId: newerId,
    submittedSig: SIG_A,
    currentSig: SIG_A,
  });
  assert.equal(afterNewer.hasResult, true);
  assert.equal(isStale(afterNewer), false);
});

test("failed regeneration after a source change stays stale and non-copyable", () => {
  let state = nextState(reviewed(generated()), { type: "inputsChanged" });
  state = nextState(state, { type: "generationStarted" });
  state = nextState(state, { type: "generationFailed" });
  assert.equal(isStale(state), true);
  assert.equal(state.reviewed, false);
  assert.equal(isCopyEnabled(state), false);
});

// Documented design decision: a failed resubmission for UNCHANGED inputs
// leaves the previous result current and copy-eligible, because nothing about
// it became outdated. Invalidation only comes from input/draft edits or a
// successful regeneration for different inputs.
test("unchanged-input resubmission failure keeps the previous result current and copy-eligible", () => {
  const acknowledged = reviewed(generated());
  assert.equal(isCopyEnabled(acknowledged), true);

  let state = nextState(acknowledged, { type: "generationStarted" });
  state = nextState(state, {
    type: "generationFailed",
    requestId: state.requestId,
  });

  assert.equal(state.hasResult, true);
  assert.equal(isStale(state), false);
  assert.equal(state.reviewed, true);
  assert.equal(isCopyEnabled(state), true);
});

test("unchanged-input resubmission failure without a prior review stays unreviewed and non-copyable", () => {
  let state = nextState(generated(), { type: "generationStarted" });
  state = nextState(state, {
    type: "generationFailed",
    requestId: state.requestId,
  });

  assert.equal(isStale(state), false);
  assert.equal(state.reviewed, false);
  assert.equal(isCopyEnabled(state), false);
});

test("review cannot be acknowledged while the result is stale", () => {
  const stale = nextState(generated(), { type: "inputsChanged" });
  const attempted = nextState(stale, { type: "reviewSet", checked: true });
  assert.equal(attempted.reviewed, false);
  assert.equal(isCopyEnabled(attempted), false);

  const unset = nextState(attempted, { type: "reviewSet", checked: false });
  assert.equal(unset.reviewed, false);
});

test("source change before any generation is not marked stale", () => {
  const state = nextState(createState(), { type: "inputsChanged" });
  assert.equal(state.hasResult, false);
  assert.equal(isStale(state), false);
  assert.equal(isCopyEnabled(state), false);
});

test("formSignature is stable and changes with source input", () => {
  assert.equal(formSignature({ client_name: "Acme" }), formSignature({ client_name: "Acme" }));
  assert.notEqual(formSignature({ client_name: "Acme" }), formSignature({ client_name: "Beta" }));
  assert.notEqual(formSignature({ brief: "x" }), formSignature({ brief: "y" }));
});

test("successful regeneration resets the gate and requires a fresh acknowledgement", () => {
  let state = nextState(reviewed(generated()), { type: "inputsChanged" });
  assert.equal(isStale(state), true);

  state = nextState(state, { type: "generationStarted" });
  state = nextState(state, {
    type: "generationSucceeded",
    requestId: state.requestId,
    submittedSig: SIG_B,
    currentSig: SIG_B,
  });
  assert.equal(state.hasResult, true);
  assert.equal(isStale(state), false);
  assert.equal(state.reviewed, false);
  assert.equal(isCopyEnabled(state), false);

  assert.equal(isCopyEnabled(reviewed(state)), true);
});

// In-flight guard: app.js checks the request id on BOTH the success and the
// failure path (error response branch and network-error catch) before it
// touches gate state or the error/status regions, so a late failure from an
// older request cannot overwrite the current request's state.
test("late failure from an older in-flight request cannot overwrite the current state", () => {
  const acknowledged = reviewed(generated());

  let state = nextState(acknowledged, { type: "generationStarted" });
  const requestA = state.requestId;
  state = nextState(state, { type: "inputsChanged" });
  state = nextState(state, { type: "generationStarted" });

  const current = state;
  state = nextState(state, { type: "generationFailed", requestId: requestA });
  assert.equal(state, current);
  assert.equal(isStale(state), true);
  assert.equal(state.reviewed, false);
  assert.equal(isCopyEnabled(state), false);
});

test("late failure after a newer request succeeded does not revert the fresh result", () => {
  let state = nextState(createState(), { type: "generationStarted" });
  const requestA = state.requestId;
  state = nextState(state, { type: "generationStarted" });
  const requestB = state.requestId;
  state = nextState(state, {
    type: "generationSucceeded",
    requestId: requestB,
    submittedSig: SIG_B,
    currentSig: SIG_B,
  });

  const current = state;
  state = nextState(state, { type: "generationFailed", requestId: requestA });
  assert.equal(state, current);
  assert.equal(state.hasResult, true);
  assert.equal(isStale(state), false);
  assert.equal(state.reviewed, false);
});

test("copy is disabled while the result is stale", () => {
  const acknowledged = reviewed(generated());
  assert.equal(isCopyEnabled(acknowledged), true);

  const stale = nextState(acknowledged, { type: "inputsChanged" });
  assert.equal(isStale(stale), true);
  assert.equal(isCopyEnabled(stale), false);

  const furtherEdits = nextState(stale, { type: "inputsChanged" });
  assert.equal(isCopyEnabled(furtherEdits), false);

  const draftEdit = nextState(acknowledged, { type: "draftEdited" });
  assert.equal(isCopyEnabled(draftEdit), false);
});

// app.js hides and clears the manual-copy fallback whenever copy is not
// eligible (syncReviewUi) and refuses to reveal it for a non-eligible result
// (showCopyFallbackIfEligible), so this single predicate gates the fallback.
test("stale state hides the manual-copy fallback until the new draft is reviewed", () => {
  const acknowledged = reviewed(generated());
  assert.equal(isCopyEnabled(acknowledged), true);

  const stale = nextState(acknowledged, { type: "inputsChanged" });
  assert.equal(isCopyEnabled(stale), false);

  const started = nextState(stale, { type: "generationStarted" });
  const regenerated = nextState(started, {
    type: "generationSucceeded",
    requestId: started.requestId,
    submittedSig: SIG_A,
    currentSig: SIG_A,
  });
  assert.equal(isCopyEnabled(regenerated), false);

  assert.equal(isCopyEnabled(reviewed(regenerated)), true);
});

// Pricing stays server-authoritative: app.js only renders the pricing object
// the server returned, and the gate itself carries no pricing data that a
// stale/review transition could modify. Server pricing arithmetic is covered
// by the Python suite (tests/test_pricing.py, tests/test_server.py).
test("stale and review state never carry pricing data", () => {
  const gateKeys = ["hasResult", "inputsDirty", "requestId", "reviewed"];
  const assertGateKeys = (state) => {
    assert.deepEqual(Object.keys(state).sort(), gateKeys);
  };

  let state = createState();
  assertGateKeys(state);

  const flow = [nextState(state, { type: "inputsChanged" })];
  state = reviewed(generated());
  flow.push(state);
  flow.push(nextState(state, { type: "inputsChanged" }));
  flow.push(nextState(state, { type: "draftEdited" }));
  state = nextState(state, { type: "generationStarted" });
  flow.push(state);
  flow.push(
    nextState(state, {
      type: "generationSucceeded",
      requestId: state.requestId,
      submittedSig: SIG_B,
      currentSig: SIG_B,
    })
  );
  flow.push(nextState(state, { type: "generationFailed", requestId: state.requestId }));

  for (const step of flow) {
    assertGateKeys(step);
  }
});

test("source signature treats pricing inputs as opaque values, never computed", () => {
  assert.equal(
    formSignature({ hourly_rate: "85.00", estimated_hours: "40", expenses: "250.00" }),
    formSignature({ hourly_rate: "85.00", estimated_hours: "40", expenses: "250.00" })
  );
  // No normalisation or arithmetic: "85.00" and "85" are different snapshots.
  assert.notEqual(
    formSignature({ hourly_rate: "85.00" }),
    formSignature({ hourly_rate: "85" })
  );
  assert.notEqual(
    formSignature({ expenses: "250.00" }),
    formSignature({ expenses: "" })
  );
});

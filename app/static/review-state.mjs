// Pure, DOM-free review/copy gate for Milestone 3-C.
//
// This module owns only the revision-aware state transitions. It has no DOM,
// network, storage, or pricing logic, so it can be unit-tested with Node's
// built-in test runner. `app.js` owns all rendering and side effects.

// The client-brief inputs whose change invalidates a generated result.
export const SOURCE_FIELDS = [
  "client_name",
  "brief",
  "scope",
  "timeline",
  "hourly_rate",
  "estimated_hours",
  "expenses",
  "currency",
];

export const STALE_NOTICE =
  "This result is out of date: the client details changed after it was " +
  "generated. Generate a new draft and review it again before copying.";

export const STALE_STATUS =
  "Client details changed since this draft was generated. The result is out " +
  "of date, so copying stays disabled until you generate and review again.";

export const REVIEW_REVOKED_STATUS =
  "Draft edited. Review the draft again before copying.";

// A stable signature of the source-input snapshot used for a generation.
export function formSignature(data) {
  const pairs = SOURCE_FIELDS.map((key) => {
    const value = data && data[key] != null ? String(data[key]) : "";
    return [key, value];
  });
  return JSON.stringify(pairs);
}

export function createState() {
  return {
    hasResult: false,
    inputsDirty: false,
    reviewed: false,
    requestId: 0,
  };
}

// The result is current only while its input snapshot still matches the form.
export function isStale(state) {
  return state.hasResult && state.inputsDirty;
}

// Copy is allowed only for a current, acknowledged result.
export function isCopyEnabled(state) {
  return state.hasResult && state.reviewed && !isStale(state);
}

export function nextState(state, event) {
  switch (event.type) {
    case "inputsChanged":
      // Once a result exists, any source change latches it stale and revokes
      // review. Reverting the input later does not restore eligibility.
      return {
        ...state,
        inputsDirty: state.hasResult ? true : state.inputsDirty,
        reviewed: state.hasResult ? false : state.reviewed,
      };

    case "draftEdited":
      // Editing the draft always revokes an existing acknowledgement. Before
      // acknowledgement this is a no-op because review is already false.
      return { ...state, reviewed: false };

    case "generationStarted":
      return { ...state, requestId: state.requestId + 1 };

    case "generationSucceeded":
      // Ignore a response that belongs to an older request.
      if (event.requestId !== state.requestId) {
        return state;
      }
      return {
        ...state,
        hasResult: true,
        inputsDirty: event.submittedSig !== event.currentSig,
        reviewed: false,
      };

    case "generationFailed":
      // Keep the previous result and its current stale/review state.
      return state;

    case "reviewSet":
      return {
        ...state,
        reviewed: event.checked ? !isStale(state) : false,
      };

    default:
      return state;
  }
}

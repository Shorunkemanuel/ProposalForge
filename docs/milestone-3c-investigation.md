# ProposalForge — Milestone 3-C Investigation

Status: INVESTIGATION COMPLETE — IMPLEMENTATION NOT STARTED

Current commit: d9de5e4

Current branch: feat/milestone-3b-review-copy

Investigation date: 2026-10-15

## Executive conclusion

**Original Milestone 3-C specification could not be recovered.**

No repository file, commit, branch, DevRelay challenge requirement, saved DevRelay agent session, or available historical project-planning record specifies what ProposalForge 3-C was meant to be. The challenge establishes what the project should demonstrate, not the order or names of this project's milestones.

The recommendation below is therefore a maintainer-defined proposal, not recovered intent:

**PROPOSED NEW SCOPE — NOT RECOVERED FROM HISTORY**

Make the existing review-and-copy gate revision-aware. If the user changes the generated draft or the source inputs after reviewing it, revoke the acknowledgement and prevent copying until the current inputs have a current generated result and the user reviews that result again.

This is the smallest evidence-based next step because it closes a state-consistency gap in the existing 3-B flow, directly supports human review, does not expand the MVP boundary, and can be completed within the remaining Week 2 challenge window.

## Investigation method and scope

Read-only repository inspection covered `README.md`, tracked files under `app/` and `tests/`, `scripts/live_smoke.py`, `.env.example`, the available Git history, local and remote branches, and the diffs for Milestones 1, 2, 3-A, and 3-B. Repository keyword searches included milestone and future-work terms as well as provider/model, security, accessibility, responsive UX, validation, review, copy, export, and persistence terms.

The repository was on `feat/milestone-3b-review-copy` at `d9de5e4`, tracking the remote branch at the same commit. The worktree was clean before this document was created. The available refs were `main`, the 3-B feature branch, and their remote counterparts; no other branch was present. The `docs/` directory did not exist before this investigation. No `.agents/AGENTS.md` is present in the working tree or available Git history.

The current source has a Python standard-library server and provider adapter, deterministic validation/pricing/readiness logic, and a plain HTML/CSS/JavaScript interface. The tests are six Python test modules using `unittest`; their current inventory is 123 tests. No package manifest or JavaScript test framework is present. The README documents `python3 -m unittest discover -v` and an opt-in live-provider smoke test.

The maintainer-provided Milestone 3-B Codespace report says all 9 browser checks passed, including draft rendering, review-gated copy, clipboard success and fallback states, responsive overflow, zero axe violations, and no inline script blocks. This is recorded as supplied verification context; it was not independently rerun in this investigation.

## Repository and Git evidence

The complete available project history is:

| Commit | Recorded milestone/change | Evidence in the change |
|---|---|---|
| `8bffef8` | Initial commit | README placeholder only. |
| `cca51c5` | Milestone 1 investigation/baseline | README-only investigation and proposed MVP; no application or test code. |
| `de2b71e` | Milestone 2 foundation | Python server, proposal pipeline, Ollama-compatible provider, validation, deterministic pricing, browser UI, live smoke script, `.env.example`, and automated tests. |
| `fc320cd` | Milestone 3-A readiness checklist | Adds deterministic readiness logic and its tests, wires the readiness endpoint/UI, and updates validation and documentation. |
| `d9de5e4` | Milestone 3-B review acknowledgement and copy | Updates the README and browser HTML/CSS/JavaScript for acknowledgement, copy, and manual-copy fallback; it adds no automated test files. |

The repository has no later commit and no branch containing a 3-C specification. The README documents 3-A and 3-B, the Milestone 2 foundation, Milestone 1's proposed MVP, and known limitations, but has no 3-C section, next-milestone instruction, or deferred milestone order.

### Earlier milestone boundaries and deferred work

**Milestone 1** was explicitly an investigation/baseline, not implementation. Its proposed first product was a local proposal-drafting workflow for freelancers/independent consultants: collect client facts and explicit scope/pricing, calculate pricing in application code, use an open-weight model to draft wording, and leave the result for the user to review and copy. Its proposed boundaries excluded a database, document uploads, retrieval, accounts, payments, CRM, PDF export, email integration, public hosting, and creating DigitalOcean resources. It also said not to add a provider abstraction until a second provider was needed; Milestone 2 later added a single Ollama-compatible adapter. That is a documented design evolution, not evidence of a planned 3-C.

**Milestone 2** implemented the local vertical slice: validation, decimal-safe server pricing, model-generated draft text, schema/output validation, editable draft fields, and safe provider-error handling. The README explicitly says client data is not stored or sent to clients, human review is mandatory, and the tool has no persistence, accounts, sending, PDF export, retrieval, or deployment. The server binds to loopback only, enforces request/host/origin/content-type/body-size checks, sets restrictive security headers, and returns generic unexpected errors. The application supports only the Ollama-compatible provider. Model output quality can vary, and the README does not claim automated factual verification.

**Milestone 3-A** added a deterministic, provider-free readiness checklist. It uses existing validation rules, reports incomplete required sections and invalid optional expenses, and offers responsive, text-labelled status updates. It did not add proposal persistence or another provider.

**Milestone 3-B** added a transient browser-only acknowledgement, editable generated fields, a user-triggered copy action combining draft text and server-returned pricing, and a manual-copy fallback when Clipboard API access fails or is unavailable. It does not store acknowledgement or proposal data, call a provider for copying, recalculate prices in JavaScript, or send the proposal.

### Current-flow observation relevant to a new scope

In `app/static/app.js`, review acknowledgement is reset when `renderDraft()` runs and when the checkbox is unchecked. However, editing the generated text after checking the box does not revoke acknowledgement. Editing the source form after generation also does not invalidate the displayed draft/pricing or revoke acknowledgement. A failed later generation request can therefore leave the earlier result visible and still copy-eligible. The copied figures remain the last server-returned figures; the concern is that the user may mistake that result for one corresponding to the subsequently changed inputs.

This is a directly observed state-consistency gap, not evidence that 3-C originally targeted it. It is not described as a security vulnerability: the current app is local-only and the issue is stale review/copy state and potential user confusion.

## DevRelay findings

DevRelay was checked using read-only retrieval only. No public action, publication, submission, registration, resource claim, or external project change was performed.

| What was checked | Finding and source/context | Effect on 3-C |
|---|---|---|
| Hacktoberfest 2026 knowledge guide | Retrieved through DevRelay's `get_knowledge_document` for `hacktoberfest`. The guide is static program context, last verified 2026-09-30. | Provides general context only; it does not specify a ProposalForge milestone. |
| DEV Challenges listing and Week 2 full details | `get_challenges` identified **Hacktoberfest Open-Source AI Challenge: Week 2**, event ID **80**, slug `hacktoberfest-week2-2026-10-12`; `get_challenge_details(80)` supplied the full challenge text. The challenge runs 2026-10-12 19:00 UTC through 2026-10-19 06:59 UTC. The challenge text gives the deadline as October 18 at 11:59 PM PDT, equivalent to October 19 at 06:59 UTC. At the investigation date, it is active with about 3 days 18 hours remaining. [Challenge details](https://dev.to/events/challenges/hacktoberfest-week2-2026-10-12) | Sets a short delivery window and useful evaluation goals, but not a roadmap or required feature. |
| Week 2 theme and judging | The theme is **Side Hustle**: build something with open-weight models or open-source AI at its core that someone would actually pay for. The full details say to think small, specific, and useful. Judging weights writing quality most heavily, then relevance to the prompt/theme, creativity, and technical execution. Meaningful partner-technology use applies only to optional partner categories. The challenge asks for a DEV post using its Side Hustle template, the required `#hf26challenge` tag, a demo, an explanation of who would pay and why open innovation matters; landing a first user is a bonus. | Supports a focused, demonstrably useful improvement and working demo. No challenge criterion mandates a particular 3-C feature or sponsor integration. |
| Saved DevRelay agent sessions | `list_agent_sessions` returned an empty list. | No saved ProposalForge session or roadmap was available there. |
| Connected MLH project list | `list_my_projects` returned one project named “Field-Note: Turning Real-World Observations into Evidence-Backed AI Drafts,” not ProposalForge. | Does not provide a ProposalForge project plan. |
| Private project planning evidence | Available cross-session history contained seven ProposalForge session records dated October 14-15. Retrieved context covered Milestone 1 recovery and Milestone 3-B verification. Searches for roadmap/deferred/next-milestone decisions did not surface an authoritative 3-C scope. | Historical context confirms earlier boundaries and verification, not original 3-C intent. |

**DevRelay conclusion:** No DevRelay result located in this investigation contains evidence about what ProposalForge Milestone 3-C was intended to be. Challenge context is not treated as proof of a project-specific roadmap. The challenge page does not identify a ProposalForge sponsor/category obligation. The project’s final challenge eligibility, live-model behavior, and first-user evidence remain unverified by this investigation.

## Reconstructed roadmap: evidence classes

### Confirmed evidence

- The only available Git history contains the initial README and Milestones 1, 2, 3-A, and 3-B; none defines 3-C.
- The current README describes the architecture, MVP constraints, and limitations, and documents 3-A and 3-B without prescribing 3-C.
- The MVP is a local-first proposal-drafting tool with deterministic pricing, an AI-generated editable draft, human review, and copy-out.
- Persistence, accounts, sending, PDF export, retrieval, and deployment are explicitly outside the documented MVP; several other integrations were excluded in Milestone 1.
- The current review acknowledgement is not invalidated when the user edits the generated text or source form after acknowledgement.
- The Week 2 challenge requires a useful open-source/open-weight AI product and a demo/post; it does not specify ProposalForge's milestone sequence.
- DevRelay's saved agent-session list was empty, and the returned MLH project was not ProposalForge.

### Strong inference

- A next milestone that preserves the existing local, single-user, no-persistence boundary is better supported than adding a new product category or integration.
- Hardening the review/copy lifecycle is a direct continuation of 3-B and addresses a concrete behavior visible in the current code.
- A small reliability improvement is more compatible with the remaining challenge window than adding a large subsystem.
- These are reasons to choose a new maintainer-defined scope, not evidence that this was the original roadmap.

### Speculation

- Any claim that the original 3-C was persistence, PDF/email export, user accounts, another provider, a sponsor integration, or any specific new feature would be speculation. No such intended milestone was recovered.
- The challenge's optional categories, bonus for landing a first user, and general judging rubric do not establish a project-specific sponsor track or feature requirement.

## Scope options

All three options below are new candidates, not recovered plans.

### Option 1 — Revision-aware review and copy gate (recommended)

- **User value:** Prevents an acknowledgement of one draft from authorizing a later-edited draft or a result whose inputs/pricing are stale.
- **Technical complexity:** Low to medium; primarily browser state and request-version handling in the existing `app/static/app.js`.
- **Implementation risk:** Low to medium. The main risk is mishandling edits during an in-flight generation request or leaving an old result copyable after a failure.
- **Testing burden:** Moderate. The state transitions are currently browser-only and need dependency-free automated coverage plus focused browser checks.
- **Accessibility implications:** Keep the checkbox native and labelled; announce meaningful stale/review state changes without speaking on every keystroke; retain visible focus and keyboard operation.
- **Security implications:** No new endpoint or data flow. This is an integrity/usability safeguard, not a security boundary or proof of proposal accuracy.
- **Hackathon/demo value:** High for a small change: the reviewer can demonstrate that changes require a fresh review, and that the copied price remains server-authoritative.
- **Estimated effort:** 4-8 hours including tests and browser verification.
- **Relationship to existing code:** Directly extends `resetReviewControls()`, `renderDraft()`, the form input handler, draft textareas, `lastPricing`, and `copyProposal()`.
- **MVP boundary:** Preserves it; no storage, external service, provider, or workflow expansion.

### Option 2 — Explicitly clear the current local session

- **User value:** Lets a user remove the currently visible client brief, draft, pricing, acknowledgement, and fallback text without relying on closing or reloading the page.
- **Technical complexity:** Low to medium; coordinates the form reset, readiness timer/result, generated output, status/error regions, and review/copy state.
- **Implementation risk:** Low to medium. The main risk is leaving some displayed client data or asynchronous readiness state behind, or clearing data accidentally without a clear interaction.
- **Testing burden:** Moderate; exercise reset from initial, generated, acknowledged, and clipboard-fallback states.
- **Accessibility implications:** Provide a clearly named keyboard-operable action, communicate completion, and avoid a disruptive confirmation dialog unless user testing establishes a need.
- **Security implications:** Supports privacy hygiene but is not secure memory erasure and must not be described as such. It adds no persistence or network flow.
- **Hackathon/demo value:** Moderate; reinforces the local-first privacy story but is less central to completing a proposal.
- **Estimated effort:** 3-6 hours including tests and browser checks.
- **Relationship to existing code:** Uses the existing form, draft/pricing cards, readiness UI, status/error regions, and `resetReviewControls()`.
- **MVP boundary:** Preserves it if scoped to current page state only.

### Option 3 — Stronger model-draft factuality/grounding safeguards

- **User value:** Could increase confidence that generated wording does not add unsupported experience, commitments, dates, or terms.
- **Technical complexity:** High if the goal is to establish factual support rather than merely change prompt wording; natural-language paraphrases are not reliably verified by the existing schema validator.
- **Implementation risk:** High. A deterministic check can reject malformed output, but cannot prove semantic truth. A false “verified” signal would be worse than the current explicit human-review warning.
- **Testing burden:** High; mocks can test schema and known edge cases, but model variability and semantic correctness require carefully scoped real-model evaluation. The existing live smoke test only verifies that a live draft validates, not that it is factually grounded.
- **Accessibility implications:** Any warnings or uncertainty indicators must be understandable in text, announced appropriately, and not conveyed by color alone.
- **Security implications:** Continue treating model output as untrusted text; do not render it as HTML or send additional client data to a service. No new data source is justified by this investigation.
- **Hackathon/demo value:** Potentially high because reliable AI behavior matters to technical execution, but a credible claim is difficult to demonstrate in the remaining time.
- **Estimated effort:** 2-4 days for a carefully limited prototype and evaluation; substantially more to make a defensible factuality guarantee.
- **Relationship to existing code:** Touches `SYSTEM_PROMPT`, `validate_draft()`, model-output tests, and possibly the draft UI. The current implementation already constrains output shape, drops unknown fields, preserves server pricing, and asks the model to surface missing information.
- **MVP boundary:** Could remain within the boundary only if it stays local and makes no guarantee it cannot support. Retrieval, external fact-checking, or new providers are excluded.

## Recommended definition — proposed new scope

**PROPOSED NEW SCOPE — NOT RECOVERED FROM HISTORY**

### Goal

Make review acknowledgement apply only to the current generated draft and its current source inputs, so edited or stale proposal content cannot be copied as though it had just been reviewed.

### User story

As a freelancer reviewing a generated proposal, I need ProposalForge to require another review after I change either the draft or the inputs used to generate it, so I do not accidentally copy outdated or newly edited content under an earlier acknowledgement.

### In scope

- Treat generated output as current only while its source-input snapshot still matches the form values used for that generation.
- On any source-form edit after generation, clearly mark the displayed result stale, revoke acknowledgement, disable copying, and hide/clear any manual-copy fallback. Keep the old result visible if useful, but do not present it as current.
- On any generated-draft text edit after acknowledgement, revoke acknowledgement, disable copying, and hide/clear the fallback until the user reviews the edited text again.
- On successful regeneration, replace the prior output and pricing with the response for the submitted inputs, clear the stale state, and require a fresh acknowledgement.
- Ensure an in-flight generation response cannot re-enable copying or replace the current result as fresh if its submitted inputs have since changed.
- Preserve user-initiated clipboard access, the existing manual-copy fallback, and authoritative server-returned pricing.

### Out of scope

- Persistence, browser storage, accounts, payments, CRM, retrieval/RAG, document uploads, PDF/file export, email/sending, public hosting, or a database.
- A new provider, sponsor integration, cloud service, or API endpoint.
- JavaScript calculation or modification of pricing.
- Claiming that a checkbox verifies accuracy, that the model cannot hallucinate, or that the application provides legal/financial review.
- Redesigning the proposal format or expanding supported currencies.
- Automatically discarding an edited draft or silently treating stale data as current.

### Acceptance criteria

1. A newly generated proposal starts with review unchecked and copy disabled.
2. Checking the review box enables copy for the current draft and current server-returned pricing only.
3. Editing any generated draft field after acknowledgement immediately unchecks review, disables copy, and removes any displayed manual-copy fallback. A new review is required before copying.
4. Editing any source input after generation marks the result stale, unchecks review, disables copy, and removes any displayed fallback. Reverting the input does not silently restore eligibility; a successful regeneration is required.
5. A stale result remains visibly identified as stale if retained on screen. It is never announced or labelled as current.
6. A successful regeneration for unchanged submitted inputs replaces the result and pricing, clears the stale indication, and returns to unchecked/disabled review state.
7. If generation fails after source inputs changed, the error is shown and the previous result remains non-current and non-copyable. The earlier review acknowledgement is not restored.
8. If inputs change while generation is in progress, that response cannot make the changed inputs appear generated or restore copy eligibility.
9. Copy output continues to contain the current editable draft, any displayed missing-information list, and the authoritative server-returned pricing; the browser does not calculate or infer prices.
10. Clipboard success is announced only after the write succeeds. Clipboard rejection or unavailability reveals the existing manual-copy fallback only for an eligible, freshly reviewed result.
11. No proposal, acknowledgement, or new client data is persisted or sent anywhere beyond the existing generation request.

### Accessibility — WCAG 2.2 Level AA

- Keep the review checkbox and buttons native, explicitly labelled, keyboard-operable, and in a logical focus order. Disabled and stale states must have clear text explanations, not color-only differences.
- Preserve visible focus indicators and ensure focused controls are not obscured; meet applicable 1.4.3 text contrast (at least 4.5:1 for normal text and 3:1 for large text), 1.4.11 non-text contrast (at least 3:1 for required UI indicators), 2.4.7 focus-visible, 2.4.11 focus-not-obscured, 2.5.8 target-size, and 4.1.3 status-message expectations.
- Keep the checkbox target at least 24 by 24 CSS pixels (or satisfy WCAG 2.2 AA spacing exceptions) and retain usable button targets.
- Announce the transition to stale/re-review-required through the existing polite status mechanism. Do not emit a live announcement on each keystroke; do not move focus merely because the state changed.
- Associate stale/review guidance with the relevant controls. Continue to announce errors and clipboard results accurately.
- Respect reduced-motion preferences and do not introduce animation as the only stale-state cue.

### Responsive UX

- Retain the existing single-column layout at narrow widths and the current page-width behavior.
- Verify at 320, 360, 620, and 860 CSS-pixel viewport widths, plus 200% zoom/reflow: no horizontal document overflow, clipped stale guidance, or unusable copy fallback.
- Keep stale status, acknowledgement text, and controls readable when labels wrap. The status must not depend on hover, pointer-only interaction, or color.
- Keep the form editable while a request is pending, or otherwise communicate any temporary restriction. In either design, edits during the request must not cause a stale response to become eligible.

### Security and privacy

- Add no endpoint, storage, cookie, session, third-party request, or provider call for review-state changes.
- Keep clipboard writes explicitly user-initiated and never claim success before the browser confirms it.
- Preserve the existing loopback-only server, Host/Origin/body-size/content-type checks, CSP, and no-store API responses; do not broaden server exposure as part of this work.
- Treat model-generated and user-edited text as untrusted plain text. Do not insert it as executable HTML or place secrets/provider configuration in the copy payload.
- Treat revision-aware acknowledgement as a UX/integrity safeguard only. It does not certify factual accuracy or replace the user's responsibility to verify claims and pricing.

### Automated tests

- Add dependency-free automated coverage for the browser state transitions. A small harness using Node's built-in test/assert modules is acceptable; do not add a third-party runtime dependency solely for this milestone.
- Verify default unchecked/disabled state; acknowledgement enables copy; editing a draft after acknowledgement revokes it; changing source inputs marks the result stale and revokes it; successful regeneration resets review; failed regeneration does not restore stale eligibility; and an in-flight response for an outdated input snapshot is ignored or remains non-copyable.
- Verify copy assembly still uses editable draft text plus server-returned pricing and does not recalculate it.
- Verify copy success, Clipboard API rejection, API unavailability, fallback clearing, and re-acknowledgement behavior.
- Keep the existing `python3 -m unittest discover -v` suite passing. No provider call or live credentials should be needed for automated tests.
- Do not introduce or install browser/test dependencies as part of the proposed scope unless a maintainer separately approves the tooling change.

### Browser verification

Repeat the existing 9/9 Milestone 3-B checks as regression coverage, then add these manual/browser checks:

1. Generate a draft, acknowledge it, edit a draft textarea, and verify review is unchecked, copying is disabled, and fallback content is hidden.
2. Acknowledge again, change a source input, and verify a stale notice appears, review is unchecked, copying is disabled, and old pricing is not represented as current.
3. Change source inputs while generation is pending; verify the old response cannot make the new inputs copy-eligible.
4. Regenerate unchanged/current inputs successfully; verify the new server pricing is displayed and copy remains disabled until re-review.
5. Make regeneration fail after changing inputs; verify the error is explicit and the previous result remains stale and non-copyable.
6. Exercise successful clipboard write, rejected write, and unavailable API after a fresh review; verify status and fallback accurately describe the outcome.
7. Repeat the transitions with keyboard only and a screen reader/status announcement check. Confirm focus is not unexpectedly moved and status is not announced per keystroke.
8. Check for no horizontal overflow at 320, 360, 620, and 860 CSS pixels and at 200% zoom.
9. Run an axe scan and confirm zero violations, including after stale and fallback states are shown.
10. Confirm the page still has no inline JavaScript and no new client/network data flow.

### Codespace verification

- Verify the target branch and expected implementation commit before implementation work; preserve any pre-existing workspace changes.
- Run `python3 -m unittest discover -v` and the dependency-free JavaScript state tests. Record passed, failed, skipped, warnings, and errors.
- Run the documented `python3 -m compileall -q app tests` and `node --check app/static/app.js` checks if the implementation changes those files.
- Start the application on its documented loopback address. Confirm the page/readiness UI still loads without a configured model and confirm no provider is called for input edits or review/copy state transitions.
- Run the full browser-verification list above in Codespace, including responsive, accessibility, clipboard, stale-input, draft-edit, failed-regeneration, and in-flight response cases.
- Confirm the implementation remains local-only, no persistent client data is added, and the browser verification is performed against the expected branch/commit.

### Risks

- In-flight generation and readiness requests can race with user edits; state must be tied to the exact input snapshot or invalidated on every edit.
- A stale indicator that is too subtle could still let users mistake old pricing/draft content for a current result.
- Resetting review after edits can surprise users unless the reason is communicated concisely and accessibly.
- Clipboard behavior differs by browser/security context; the existing manual fallback must remain available without exposing stale content.
- Automated tests currently exercise Python logic, not browser DOM behavior. A dependency-free state test harness and the specified manual browser verification are needed; no test framework should be assumed to exist.
- This scope does not solve model hallucination or establish the accuracy of a proposal. Existing human-review notices and responsibility remain necessary.

### Open questions

No unresolved product or architecture decision blocks this proposed scope. The recommendation is to retain stale output visibly with a clear stale notice while disabling review/copy eligibility, rather than deleting the user's draft. This is a proposed UX choice for maintainer approval, not recovered behavior or a historical decision.

### Estimated implementation effort

**4-8 hours (approximately half to one engineering day)** for the current architecture, including implementation, dependency-free state tests, regression checks, and browser verification. The remaining challenge window is roughly 3 days and 18 hours as of 2026-10-15, so this is feasible without adding a provider, sponsor service, or broad MVP feature.

## Final recommendation

Do not label any feature as the original Milestone 3-C: **Original Milestone 3-C specification could not be recovered.**

If the maintainer approves a new milestone, adopt **revision-aware review and copy gating** as **PROPOSED NEW SCOPE — NOT RECOVERED FROM HISTORY**. It is grounded in the current 3-B interaction and a concrete state-consistency issue, supports the challenge's emphasis on a working and useful tool, is testable within the available window, and preserves the explicitly documented MVP boundaries.

No application implementation is included in this investigation. This file is the only requested repository change; do not commit it until the maintainer has reviewed and approved it.

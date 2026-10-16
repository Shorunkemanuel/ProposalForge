# ProposalForge

Milestone 3-A adds a deterministic, accessible proposal-readiness checklist, Milestone 3-B adds the review acknowledgement and copy gate, and Milestone 3-C makes that gate revision-aware. All of this builds on the Milestone 2 vertical slice. Milestone 2 (implementation) and Milestone 1 (investigation) are retained below.

## Milestone 3-A — readiness checklist

Before generating, the form shows a live checklist that groups the required inputs into **Brief**, **Scope & deliverables**, **Timeline**, and **Pricing**. It updates as the user edits fields and names the specific inputs that are still missing (for example, "Client brief: at least 10 characters"). Expenses are optional; omitting them or supplying a valid amount never blocks readiness, but a supplied invalid expense (such as a negative amount) is shown as a warning and keeps the checklist not ready.

- The checklist is plain application logic in `app/readiness.py`; no AI model is involved.
- It reuses the same field definitions, length thresholds, and non-negative-number parser as server-side validation (`app/validation.py`), so the checklist cannot drift from the validation that guards generation.
- The browser calls `POST /api/readiness` (debounced) and renders the report; the server route reuses the same Host/origin/content-type/body-size guards as `POST /api/proposals`.
- Accessibility: each item has a visible text state (not colour-only) plus a decorative mark, a heading-labelled list, a visible summary, and a polite `aria-live` status that announces progress without per-keystroke noise. Layout is responsive down to small screens and honours `prefers-reduced-motion`.

## Milestone 3-B — review acknowledgement and copy

After generating, the draft stays explicitly unapproved until the user confirms they have reviewed it. A native checkbox records that acknowledgement as **transient browser state only** — it is never written to local storage, cookies, a database, or a server session. The copy action stays disabled until the box is checked, and removing the acknowledgement disables copying again. The label states plainly that ProposalForge does not verify the draft's accuracy; acknowledgement is the user's review, not an application check.

Once acknowledged, **Copy proposal** copies the assembled draft text together with the authoritative pricing figures. The text is built in the browser from the validated draft fields and the pricing the server already returned; JavaScript never calculates, infers, or changes a price. The copied text contains only the draft fields, the missing-information list, and the pricing breakdown — no page chrome, provider configuration, or internal metadata.

Copying prefers `navigator.clipboard.writeText`. The clipboard API is feature-detected, and rejected promises (for example a permission denial) are handled. If the API is unavailable or the write fails, the interface explains the failure and reveals a read-only **manual copy box** so the proposal text can still be selected and copied by hand. Success is announced only after the write resolves; failure never leaves the interface claiming the copy worked. No deprecated `document.execCommand` technique is used.

- Local and deterministic: no new endpoint, no provider call, and no proposal data leaves the page.
- The acknowledgement and status changes are announced through the existing polite live region (`#status`); focus is not moved when status text changes.
- Accessibility: native labelled controls, keyboard-operable; state conveyed in text rather than colour alone; checkbox and button meet the 24 × 24 CSS-pixel target size, keep visible focus indicators, and honour `prefers-reduced-motion`.

## Milestone 3-C — revision-aware review and copy gate

Milestone 3-B's acknowledgement is transient browser state; Milestone 3-C makes it apply only to the *current* generated draft and its *current* source inputs, so edited or stale content cannot be copied as though it had just been reviewed. This is a UX/integrity safeguard, not factual verification.

- A generated result is **current only while its source-input snapshot still matches** the form values used for that generation. The snapshot is a signature over the client-brief fields (`app/static/review-state.mjs`).
- Any source-input edit after a result exists **latches the result stale**: the review box is cleared, copying is disabled, and any manual-copy fallback is cleared. Reverting the input does not silently restore eligibility; a successful regeneration is required.
- Editing any generated-draft textarea after acknowledgement **revokes the acknowledgement** and disables copying until the edited draft is reviewed again. Editing a draft before acknowledgement is a no-op (review is already unconfirmed).
- A **successful regeneration** replaces the draft and pricing with the new server response, clears stale state, and requires a fresh acknowledgement. A **failed regeneration** leaves the previous result visibly stale and non-copyable rather than restoring eligibility.
- An **older in-flight response** is ignored via a request id, and a response whose submitted snapshot no longer matches the current form is shown as stale rather than current.
- The gate lives in `app/static/review-state.mjs` as pure, DOM-free state logic; `app/static/app.js` owns all rendering, the `fetch` lifecycle, and the clipboard. Pricing remains **server-authoritative**: JavaScript still never calculates or changes a price, and stale/review state never mutates pricing.
- Accessibility: the stale state is conveyed in visible text and announced **once** through the existing polite `#status` region (not per keystroke); the disabled controls describe the stale reason; native keyboard operation and focus behaviour are unchanged.

## Future roadmap

ProposalForge currently focuses on a local-first proposal-generation workflow: structured client inputs, deterministic pricing, AI-assisted drafting, human review, and copy-out.

Future versions may introduce a hosted SaaS experience after the core workflow has been validated with real users.

Potential future capabilities include:

- User accounts and secure proposal history
- Saved proposal templates and business profiles
- Usage limits and proposal quotas
- Free and paid subscription tiers
- Advanced proposal customization
- Proposal analytics and follow-up tools
- Team/agency workspaces
- Additional AI/model providers
- Export and integration features

### Potential subscription model

A future freemium model may include:

- **Free** — limited monthly proposal generation with the core proposal workflow.
- **Plus** — higher usage limits, saved history, templates, and additional customization.
- **Pro/Premium** — advanced workflows, higher limits, analytics, branding, and other professional features.
- **Team/Agency** — shared workspaces, collaboration, and team-level controls.

These tiers are future product hypotheses, not current product commitments. Pricing, limits, and feature boundaries will be determined after testing ProposalForge with real users and learning which capabilities customers are willing to pay for.

The immediate priority is validating the core proposal workflow, deploying a usable version, and finding early users before introducing accounts, billing, persistence, or subscription infrastructure.

## Milestone 2 — implementation

### What it does

`client brief -> readiness checklist -> input validation -> deterministic pricing -> AI-generated draft -> editable draft for human review`

The AI provider only drafts wording from the facts the user supplies. All pricing is calculated by application code and can never be changed by model output. The draft is clearly marked AI-generated and unapproved; nothing is sent to clients and no client data is stored.

### Architecture

- Python standard library only (`http.server`, `urllib.request`, `decimal`, `json`). No third-party runtime dependencies.
- Plain HTML/CSS/JavaScript for the browser UI.
- A single small provider adapter (`app/providers.py`) for the Ollama-compatible chat API.
- `decimal.Decimal` (half-up, 2 dp) for monetary arithmetic.
- `unittest` for the automated test suite.

Layout:

```
app/
  __main__.py      run: python -m app
  server.py        HTTP server + JSON API + error mapping
  proposal.py      pipeline, prompt building, model-output validation
  providers.py     Ollama-compatible adapter + config + error types
  validation.py    input validation (fields, lengths, numerics, currency)
  readiness.py     deterministic readiness checklist (no AI)
  pricing.py       deterministic decimal-safe pricing
  static/          index.html, styles.css, app.js, review-state.mjs
tests/             123 Python tests + review-state.test.mjs (no live credentials required)
scripts/live_smoke.py   opt-in live inference check
```

### Provider configuration

All provider settings come from environment variables. No endpoint, model name, or secret is hard-coded. See `.env.example`.

| Variable | Purpose | Default |
| --- | --- | --- |
| `PROPOSALFORGE_PROVIDER` | Provider kind; only `ollama` is supported | `ollama` |
| `PROPOSALFORGE_BASE_URL` | Ollama-compatible base URL | `http://127.0.0.1:11434` |
| `PROPOSALFORGE_MODEL` | Model name (required to generate) | *(none)* |
| `PROPOSALFORGE_API_KEY` | Optional bearer token for hosted endpoints | *(none)* |
| `PROPOSALFORGE_TIMEOUT` | Request timeout, seconds | `60` |

The variables are read from the process environment; `.env` is **not** auto-loaded. The server binds to `127.0.0.1` by default and must not be exposed publicly. Milestone 2 supports loopback binds only (`127.0.0.1`, `localhost`, `::1`); wildcard or LAN addresses such as `0.0.0.0`/`::` are refused at startup, and every `POST /api/proposals` `Host` header must name an allowed loopback host.

### API

- `GET /` — serve the application; `GET /static/<path>` — assets.
- `POST /api/proposals` — JSON body with `client_name`, `brief`, `scope`, `timeline`, `hourly_rate`, `estimated_hours`, `expenses`, `currency`. Returns `{ notice, pricing, draft }`.
- `POST /api/readiness` — JSON body with any subset of the proposal fields. Returns a deterministic readiness report (`ready`, `complete_sections`, `total_sections`, per-section items, and `warnings` for supplied-but-invalid optional inputs). No provider is contacted; an omitted expense is ignored, while a supplied negative expense is a warning.
- Errors: `400` invalid/malformed input, `403` cross-origin or disallowed `Host`, `413` oversized body, `415` non-JSON content type, `502` provider failure or invalid model output, `504` provider timeout, `500` unexpected (generic message only). Errors never include stack traces, secrets, or raw provider payloads.
- Responses send `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and a restrictive `Content-Security-Policy`; JSON API responses are `Cache-Control: no-store`.

### Currency behavior

A single 3-letter currency code is carried through unchanged. ProposalForge does **not** convert currencies and does not perform FX lookup.

### Running locally (Termux)

```sh
export PROPOSALFORGE_MODEL=qwen2.5:0.5b-instruct-q4_K_M
python3 -m app            # http://127.0.0.1:8000
```

### Running in GitHub Codespaces

Python 3.10+ is required (uses `X | None` type syntax). In a Codespace:

```sh
export PROPOSALFORGE_BASE_URL=<verified-ollama-endpoint>
export PROPOSALFORGE_MODEL=<verified-model>
python3 -m app --host 127.0.0.1 --port 8000
```

If the Codespace has no reachable provider, the UI still loads and returns a clear provider error on generate. Automated tests do not need a provider.

### Tests

```sh
python3 -m unittest discover -v
node --test tests/review-state.test.mjs
```

The Python suite covers the server, pipeline, validation, pricing, and readiness logic. The Node test uses only Node's built-in `node:test`/`node:assert` (no `package.json`, no installed dependency) and covers the pure review/copy gate state transitions in `app/static/review-state.mjs`.

### Live-provider smoke test (opt-in)

```sh
export PROPOSALFORGE_MODEL=<verified-model>
python3 scripts/live_smoke.py
```

This makes a real inference call. Do not treat a mocked test as a live success.

### Known limitations

- Local models (`qwen2.5:0.5b-instruct-q4_K_M`, `qwen2.5-coder:1.5b`) are installed locally; JSON-output quality is variable at this size.
- `gemma4:31b-cloud` is configured as an opencode integration model but is not installed or verified reachable; it was not used. No cloud credential was present.
- No persistence, accounts, sending, PDF export, retrieval, or deployment. Human review is mandatory.

---

## Milestone 1 — investigation and baseline

Milestone 1 is an investigation and baseline, not a product implementation.

## Repository baseline

- The repository has one initial commit, dated 2026-10-14. The only tracked project file is this README; no repository-instructions file (for example, an `AGENTS.md`) is present, so these notes are the available guidance.
- There are no source files, dependency manifests, lockfiles, tests, build scripts, or CI configuration, so the repository currently defines no test or build command.
- Available local tools include Python 3.14, Node.js 24, npm 11, .NET 10, and Docker. Ollama is not installed, and its local API endpoint was not running when checked.
- No OpenAI, Anthropic, Gemini, Hugging Face, or DigitalOcean API credential was present in the environment. Credential values were not read.

## Proposed MVP for review

**Working user assumption:** a freelancer or independent consultant needs to turn a client brief into a proposal draft. Confirm the target user and the fields needed before implementation.

1. A small browser form collects a brief and explicit scope, schedule, rate, hours, and expenses.
2. A local Python HTTP service validates inputs and calculates prices with ordinary application code.
3. A local open-weight model drafts the proposal wording; it does not set prices, invent experience, or make binding commitments.
4. The user reviews and edits the draft, then copies it. The first version does not store client data or send proposals.

**Proposed dependencies:** Python's standard library for the local API, plain HTML/CSS/JavaScript for the browser UI, and Ollama with an open-weight model for inference. No Python or npm package is needed for this initial design. Ollama and a model are not currently available in the environment, and model selection should wait for a resource and quality check. A hosted inference endpoint is an alternative only after its provider, data handling, access, and cost are verified; it is not the default. A closed-weight hosted model would not satisfy the Week 2 challenge's open-source/open-weight core requirement.

Keep the first version local, without a database, document uploads, retrieval, accounts, payments, CRM, PDF export, or email integration. Avoid a provider abstraction until a second provider is actually required. Do not expose the development server publicly or create DigitalOcean resources as part of this milestone.

## Proposed MVP acceptance criteria

- A user can enter a client brief and explicit scope/pricing inputs and receive an editable proposal draft.
- Price calculations are deterministic, tested independently, and cannot be changed by model output.
- The model uses an open-weight model or open-source AI as a core part of the workflow. Missing facts are surfaced for user input rather than fabricated.
- Provider errors, invalid output, and timeouts are shown as errors; no proposal is silently treated as successful.
- The draft is clearly unapproved until the user reviews it. The application does not send it or persist client data.
- Tests cover input validation, pricing arithmetic, missing information, and model failure/invalid-output paths. A separate live-model check is documented because it depends on a locally installed model.

## Hacktoberfest Week 2 research

The [Hacktoberfest Open-Source AI Challenge: Week 2](https://dev.to/events/challenges/hacktoberfest-week2-2026-10-12) is the “Side Hustle” challenge: build something with open-weight models or open-source AI that someone would pay for. The challenge describes a **Best Use of DigitalOcean** category among its featured categories; its listed featured-category prize is **$200**. Entries must meaningfully use the partner technology to qualify for that category. The challenge asks for a DEV post using its Side Hustle template and `#hf26challenge`, with a demo and an explanation of who would pay and why open innovation matters.

The challenge's full details give the DEV submission deadline as **October 18, 2026 at 11:59 PM PDT (October 19 at 06:59 UTC)**. The linked MLH event record gives an end time one day earlier, **October 18 at 06:59 UTC**. Use the DEV challenge details for the DEV-post deadline and confirm any MLH-specific submission window separately. The initial repository commit is dated within the challenge window, but that alone does not establish challenge eligibility.

DevRelay's Week 2 offer listing contained no sponsor offers. The challenge details mention free partner credits for Tinker, Render, Backboard, and ElevenLabs, but do not describe a DigitalOcean credit or hosting entitlement. **No DigitalOcean credits, expiry, account eligibility, or redemption instructions have been confirmed.** Check the [Hacktoberfest participant dashboard](https://hacktoberfest.com/my/) for account-specific benefits before relying on any offer. Do not create infrastructure or incur charges without separate approval.

## Remaining risks and decisions

- The intended user, supported currencies, proposal fields, and quality bar need confirmation.
- Local inference, model capacity, quality, and latency have not been tested; Ollama is not installed and no model is selected.
- AI output can still invent unsupported terms. Human review and deterministic financial logic are required; the first version should not provide legal or financial advice.
- A local-only design avoids sending briefs to a hosted provider, but local storage, logs, and public deployment would need an explicit privacy/security review.
- DigitalOcean's contest category is not evidence of a free hosting credit. Account-specific credit eligibility and expiry remain unverified.
- There is no existing application test/build suite. Add one with the first implementation rather than claiming a baseline test passed.

## Research references

- [Week 2 challenge details](https://dev.to/events/challenges/hacktoberfest-week2-2026-10-12)
- [Hacktoberfest 2026 program guide](https://hacktoberfest.com/)
- [Quote Forge: local-first proposal and quote builder](https://dev.to/shikhar_ahirwar_60abbcba4/quote-forge-28lj)
- [Schema-Valid Isn't Correct: 4 Checks Before You Trust LLM Extraction](https://dev.to/michael_maurice/schema-valid-correct-4-checks-before-you-trust-llm-extraction-4n6f)

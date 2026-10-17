# ProposalForge

Milestone 4 turns the environment-variable-only AI configuration into an in-app provider setup experience (configure a compatible endpoint, test the connection, discover or enter a model) without adding persistence or accounts. The primary path is a **hosted open-weight model through your own API key (BYOK)**; running a local server is optional. Milestone 3-A adds a deterministic, accessible proposal-readiness checklist, Milestone 3-B adds the review acknowledgement and copy gate, and Milestone 3-C makes that gate revision-aware. All of this builds on the Milestone 2 vertical slice. Milestone 2 (implementation) and Milestone 1 (investigation) are retained below.

## Milestone 4 — in-app provider setup

A first-time user no longer has to edit environment variables to find out which AI provider ProposalForge uses, whether it is reachable, or which model is selected. The app shows an **AI provider setup** card at the top of the page that reports the provider kind, the base URL, the selected model, and an API-key presence flag, and lets the user change the base URL, model, and (for hosted endpoints) their own API key, test the connection, and pick a discovered model. The connection test and model discovery use the values currently in the form, so you can verify an endpoint before saving. Generation always runs against the applied runtime configuration: if there are unsaved provider edits when you generate, ProposalForge applies them first through the same in-memory configuration path as **Save settings**, so what you tested is what generates and the model the draft uses is always the one the panel reports.

- **Provider presets**: the card offers a provider selector with presets for **OpenRouter**, **OpenAI**, **Google AI Studio (Gemini)**, **Ollama Cloud**, and a **Custom compatible endpoint**, plus **Ollama (local/native)**. With nothing configured, the default is the hosted **OpenRouter** preset; the local Ollama preset is opt-in. Selecting a preset fills in its documented base URL; the custom preset keeps manual base-URL, model, and key entry.
  - OpenRouter also offers a convenience **automatic routing** option (`openrouter/free`, OpenRouter's documented router id). That identifier is usable even when model discovery does not list it, and the specific-model field remains available. ProposalForge does not treat the identifier as a billing signal.
  - All four hosted presets are OpenAI-compatible (`POST /chat/completions`, `GET /models`, bearer auth); the local Ollama preset uses the native API (`POST /api/chat`, `GET /api/tags`). The same file handles methods both protocols are known to implement; only the previously documented 401/403 classification is added. Live generation has been verified with a real key against **OpenRouter** (`openrouter/free`) and **Ollama Cloud** (`gemma4:31b`); the **OpenAI** and **Gemini** presets share the same code path but have not been verified live, and a mocked test is not a live success.
  - Each provider expects the API key issued **by that provider** — a key from one provider does not authenticate with another. ProposalForge never asks whether a key is free or paid: model availability, quotas, and any charges depend on the user's provider account and model choice.
  - Open-weight caveat: OpenAI and Gemini models are not assumed to be open-weight. For challenge eligibility, inspect the model actually returned by a real response and choose a model that satisfies the requirement.
- **Hosted BYOK is the primary setup path.** Enter the HTTPS base URL of a compatible open-weight API, a model identifier, and your own API key. ProposalForge sends the key only to the configured endpoint as a bearer token and never creates an account, subscription, or payment. API cost, if any, is between the user and their chosen provider; ProposalForge does not promise that any API is free.
- **Local inference is optional.** A user who specifically wants local processing can point the base URL at a compatible server they run themselves (for example an Ollama-compatible endpoint on loopback). Local server setup is not required to use ProposalForge or to run the demo.
- **Configuration lifetime is unchanged and database-free**: settings are seeded from the environment (`PROPOSALFORGE_*`). In-app changes are held **in memory for the running server process only** and reset when it stops. Nothing is written to a database, browser storage, cookies, or an account. The interface states this plainly.
- **Model discovery is server-side** (`POST /api/provider/models` queries the configured endpoint's compatible model-list API). The browser never makes a cross-origin request to the provider. The response is normalized (de-duplicated, sorted, bounded) and empty/invalid/hostile responses are handled safely. No model list is hard-coded, and a model identifier can also be entered directly, so the UI stays usable when discovery is unavailable.
- **Connection test** (`POST /api/provider/test`) probes the endpoint server-side with a short timeout and returns a classified status the UI can explain: connected with the model available, reachable but no usable model selected, the selected model not available, no models offered, unreachable, timed out, authentication rejected, invalid configuration, or a provider/request error. Messages tell the user what to do next and never include stack traces, secrets, or raw provider payloads.
- **API key only where technically appropriate**: the optional API-key field appears solely when the base URL is a non-loopback (hosted) endpoint. A loopback endpoint needs no key. The value is never returned to the browser (only a `has_api_key` flag), never written to disk, and is sent to the provider as a bearer token only.
- **First-run guidance**: until the provider is ready, the card shows a short "first-time setup" path (enter URL and model → add key if hosted → test connection → save → continue to the brief). Generation failures that come from the provider point the user back to this card instead of a mysterious error.
- Accessibility: labelled controls, keyboard-operable, visible focus, status conveyed in text (and a symbol) rather than colour alone, per-field validation errors with `aria-invalid`, and a single polite live region that announces meaningful transitions without per-keystroke noise.
- Security: the new endpoints reuse the existing Host/origin/content-type/body-size guards; the base URL is validated server-side (http/https only, no embedded credentials, no control characters, length-bounded) before any request is made; responses keep the existing CSP and security headers and are `Cache-Control: no-store`.

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
- A single small provider adapter (`app/providers.py`) for both the native Ollama chat API and the OpenAI-compatible chat API used by the hosted presets.
- `decimal.Decimal` (half-up, 2 dp) for monetary arithmetic.
- `unittest` for the automated test suite.

Layout:

```
app/
  __main__.py      run: python -m app
  server.py        HTTP server + JSON API + error mapping
  proposal.py      pipeline, prompt building, model-output validation
  providers.py     provider adapter (Ollama-native + OpenAI-compatible) + config + error types + model list
  provider_setup.py in-app provider settings, presets, status, and model discovery
  validation.py    input validation (fields, lengths, numerics, currency)
  readiness.py     deterministic readiness checklist (no AI)
  pricing.py       deterministic decimal-safe pricing
  static/          index.html, styles.css, app.js, review-state.mjs, provider-state.mjs
tests/             253 Python tests + provider-state.test.mjs + review-state.test.mjs (no live credentials required)
scripts/live_smoke.py   opt-in live inference check
```

### Provider configuration

Provider settings come from environment variables by default; no endpoint, model name, or secret is hard-coded. See `.env.example`. The primary intended setup is a **hosted open-weight endpoint with your own API key (BYOK)**. They can also be adjusted in the **AI provider setup** card in the app (Milestone 4), which applies them to the running process only.

| Variable | Purpose | Default |
| --- | --- | --- |
| `PROPOSALFORGE_PROVIDER` | Preset id: `openrouter`, `openai`, `gemini`, `ollama-cloud`, `custom`, or `ollama` | `openrouter` |
| `PROPOSALFORGE_BASE_URL` | Compatible API base URL (hosted HTTPS or a local server) | the selected preset's documented URL |
| `PROPOSALFORGE_MODEL` | Model identifier (required to generate) | *(none)* |
| `PROPOSALFORGE_API_KEY` | Bearer token issued by the chosen provider (BYOK) | *(none)* |
| `PROPOSALFORGE_TIMEOUT` | Request timeout, seconds | `600` |

Hosted BYOK is the default product path: with nothing configured, the provider is `openrouter` and the base URL is its documented value. A local server is opt-in — select the `ollama` preset (or set `PROPOSALFORGE_PROVIDER=ollama`, which seeds the local base URL). When only `PROPOSALFORGE_PROVIDER` is set, the base URL defaults to that preset's documented URL; an explicit `PROPOSALFORGE_BASE_URL` always wins.

Documented preset base URLs: OpenRouter `https://openrouter.ai/api/v1`, OpenAI `https://api.openai.com/v1`, Google AI Studio (Gemini) `https://generativelanguage.googleapis.com/v1beta/openai/`, Ollama Cloud `https://ollama.com/v1`. The `custom` preset defaults to the OpenAI-compatible protocol and requires the user to supply the base URL.

The variables are read from the process environment; `.env` is **not** auto-loaded. The server binds to `127.0.0.1` by default and must not be exposed publicly. Milestone 2 supports loopback binds only (`127.0.0.1`, `localhost`, `::1`); wildcard or LAN addresses such as `0.0.0.0`/`::` are refused at startup, and every `POST /api/proposals` `Host` header must name an allowed loopback host. Provider settings changed through the app (Milestone 4) are held in memory for the running process only and are lost when it stops; they are never written to disk, a database, or browser storage.

### API

- `GET /` — serve the application; `GET /static/<path>` — assets.
- `GET /api/provider/status` — passive provider status (no network call). Returns the provider preset id, base URL, selected model, an `has_api_key` flag (never the key itself), whether the settings came from the environment or a runtime change, the list of available provider `presets`, and a status of `configured`, `model_not_selected`, or `invalid_config` with a user-safe message.
- `POST /api/proposals` — JSON body with `client_name`, `brief`, `scope`, `timeline`, `hourly_rate`, `estimated_hours`, `expenses`, `currency`. Returns `{ notice, pricing, draft }`.
- `POST /api/readiness` — JSON body with any subset of the proposal fields. Returns a deterministic readiness report (`ready`, `complete_sections`, `total_sections`, per-section items, and `warnings` for supplied-but-invalid optional inputs). No provider is contacted; an omitted expense is ignored, while a supplied negative expense is a warning.
- `POST /api/provider/test` — server-side connection test (short timeout). Optional JSON body with `provider`, `base_url`, `model`, and/or `api_key` tests those values without saving them (an absent field falls back to the saved value; an empty `api_key` reuses the saved key). Always `200` with a classified `status` (`ready`, `model_not_selected`, `model_not_found`, `no_models_installed`, `unreachable`, `timeout`, `auth_error`, `invalid_config`, `provider_error`), a user-safe `message`, and `models` when the endpoint was reachable.
- `POST /api/provider/models` — server-side compatible model-list discovery. Optional JSON body with `provider`, `base_url`, `model`, and/or `api_key` discovers against those values without saving them. `200` with a normalized `models` list and `count`; `400` invalid configuration, `401` authentication rejected, `502` provider failure, `504` timeout.
- `POST /api/provider/config` — runtime (in-memory, process-scoped) update of `provider`, `base_url`, `model`, and/or `api_key`. Absent fields are unchanged; an empty `api_key`/`model` clears it. An unknown `provider` returns `400`. `400` with per-field messages for invalid input; `200` with the updated safe description. The API-key value is never returned.
- Errors: `400` invalid/malformed input, `403` cross-origin or disallowed `Host`, `401` provider auth rejection, `413` oversized body, `415` non-JSON content type, `502` provider failure or invalid model output, `504` provider timeout, `500` unexpected (generic message only). Errors never include stack traces, secrets, API keys, or raw provider payloads.
- Responses send `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and a restrictive `Content-Security-Policy`; JSON API responses are `Cache-Control: no-store`.

### Currency behavior

A single 3-letter currency code is carried through unchanged. ProposalForge does **not** convert currencies and does not perform FX lookup.

### Running locally

Python 3.10+ is required (the code uses `X | None` type syntax) on Linux, macOS, Windows, or Termux. Use your platform's shell syntax to export the variables:

```sh
# Linux / macOS / Termux (sh)
export PROPOSALFORGE_MODEL=<model-identifier>
python3 -m app            # http://127.0.0.1:8000
```

```powershell
# Windows PowerShell
$env:PROPOSALFORGE_MODEL = "<model-identifier>"
python -m app            # http://127.0.0.1:8000
```

As of Milestone 4 the `PROPOSALFORGE_*` variables are optional for getting started: you can start the server with no provider configured and use the **AI provider setup** card in the app to enter a hosted endpoint, add your API key, test the connection, and pick a model. For a hosted OpenAI-compatible provider, select its preset in the card (or set the variables directly):

```sh
# Linux / macOS / Termux — OpenRouter example
export PROPOSALFORGE_PROVIDER=openrouter
export PROPOSALFORGE_MODEL=openrouter/free
export PROPOSALFORGE_API_KEY=<your-own-openrouter-key>
python3 -m app
```

### Running in GitHub Codespaces

In a Codespace (or any Linux environment):

```sh
export PROPOSALFORGE_PROVIDER=<verified-preset>
export PROPOSALFORGE_BASE_URL=<verified-endpoint>
export PROPOSALFORGE_MODEL=<verified-model>
python3 -m app --host 127.0.0.1 --port 8000
```

If the environment has no reachable provider, the UI still loads and returns a clear provider error on generate. Automated tests do not need a provider.

### Tests

```sh
python3 -m unittest discover -v
node --test tests/review-state.test.mjs tests/provider-state.test.mjs
```

The Python suite covers the server, pipeline, validation, pricing, readiness, and the provider setup endpoints (status, connection test, model discovery, and runtime configuration) with a mocked provider — it does **not** require a running endpoint. This includes the OpenAI-compatible protocol path (chat-completions request shape, `/models` parsing, authorization handling) and the preset registry. The Node tests use only Node's built-in `node:test`/`node:assert` (no `package.json`, no installed dependency) and cover the pure review/copy gate state transitions in `app/static/review-state.mjs` and the provider setup state, preset selection, model-list merging, documented-model handling, and status classification in `app/static/provider-state.mjs`.

### Live-provider smoke test (opt-in)

```sh
export PROPOSALFORGE_MODEL=<verified-model>
python3 scripts/live_smoke.py
```

This makes a real inference call. Do not treat a mocked test as a live success.

### Known limitations

- Live hosted generation has been verified with the operator's own key for two presets: **OpenRouter** (`openrouter/free`) and **Ollama Cloud** (`gemma4:31b`). The **OpenAI** and **Gemini** presets use the same OpenAI-compatible code path but have not been verified live. All automated tests remain mocked and require no credentials; treat a mocked test as unit coverage, not as a live provider success. Whether a given model satisfies the challenge's open-weight requirement must be confirmed against an actual response.
- Local inference is optional. A local server and model are not required for setup, demo, or tests; where used, JSON-output quality at small model sizes is variable.
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

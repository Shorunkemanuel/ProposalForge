# ProposalForge

Milestone 1 is an investigation and baseline, not a product implementation. This proposal is for review; no application code, dependencies, paid services, or cloud resources were set up.

## Repository baseline

- The repository has one initial commit, dated 2026-10-14. The only tracked project file is this README; `.agents/AGENTS.md` contains repository instructions and is not application code.
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

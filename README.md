# Vera Message Engine — magicpin AI Challenge submission

A deterministic decision engine + LLM phrasing layer implementing the `compose(category, merchant, trigger, customer?)`
contract behind Vera, exposed as the 5-endpoint HTTP service the judge harness calls
(`/v1/healthz`, `/v1/metadata`, `/v1/context`, `/v1/tick`, `/v1/reply`), per `challenge-testing-brief.md`.

## Architecture

```
trigger arrives (tick / context push)
        │
        ▼
signal_selector.py   — picks the ONE grounded fact this trigger should anchor on,
                        per trigger kind. External-event kinds (research digests,
                        regulation changes, competitors, festivals, supply alerts)
                        require the fact to already exist in the pushed payload or
                        category digest — never invented. Internal kinds (perf
                        dip/spike, milestones, dormancy, renewal, lapse) fall back
                        to live merchant/customer state when the trigger payload is
                        a stub. If nothing grounded is available → skip (no send).
        │
        ▼
strategy.py           — eligibility gates (suppression key already used, merchant
                        opted out, trigger expired, customer consent), CTA shape
                        per category+kind, send_as, deterministic conversation_id,
                        urgency ranking + the 20-actions-per-tick / one-new-
                        conversation-per-merchant-per-tick caps.
        │
        ▼
composer.py            — turns the decision into text. Curates the allowed facts,
   (+ llm/client.py)    calls the LLM (Groq's `gpt-oss-120b`) at temperature=0
                        to phrase them, JSON-mode parsed.
        │
        ▼
validator.py            — checks the LLM output for fabricated numbers (against
                        the full pushed context, with percent-derivation
                        allowed), taboo vocabulary, URLs, multiple CTAs, and
                        exact repetition. Any failure discards the LLM output
                        and falls back to a template built directly from the
                        same facts — so the bot is never left without a
                        grounded, valid message, and never blocks on the LLM.
        │
        ▼
   HTTP response
```

`engine/conversation.py` runs the same signal_selector → composer → validator pipeline for
`/v1/reply`: it classifies the incoming message (auto-reply / hostile / rejection / acceptance /
deferral / on-or-off-topic question) with keyword heuristics, re-resolves the original trigger's
grounding facts from the conversation's stored `trigger_id`, and decides `send` / `wait` / `end`.
The classification and action are deterministic; only the wording of a `send` goes through the
composer.

`category/*.py` holds **behavioral bias only** (register, salutation style, CTA-per-kind
defaults, urgency multipliers for compliance) — never facts. All factual content (voice, offer
catalog, peer stats, digest, seasonal beats) comes exclusively from the `CategoryContext` payload
pushed via `/v1/context`, so nothing here needs to change as new categories or digest items arrive.

### Why an LLM is optional, not required

The service works correctly with **no LLM key configured** — every message uses the deterministic
fallback template, which is always grounded (built straight from the selected anchor fact) and
always passes the same validator. This means a `/v1/tick` or `/v1/reply` call is never blocked by
LLM latency/availability, and CI/tests run with zero API cost. Setting `GROQ_API_KEY` upgrades
message quality (natural phrasing, code-mixed Hindi-English, tighter compulsion framing) without
changing any business decision — the LLM only phrases what the deterministic layer already decided.

## Project layout

```
app/
├── main.py                 FastAPI app + router wiring
├── api/                    one file per endpoint (context, tick, reply, health, metadata, teardown)
├── engine/
│   ├── signal_selector.py  picks the one grounded fact per trigger kind (25+ kinds covered)
│   ├── strategy.py         eligibility, CTA, send_as, conversation_id, ranking/caps
│   ├── composer.py         LLM prompt + deterministic fallback template
│   ├── validator.py        grounding/taboo/URL/single-CTA/repetition checks
│   └── conversation.py     /v1/reply state machine
├── category/                per-vertical behavioral hints (non-factual)
├── llm/client.py           Groq (OpenAI-compatible) wrapper, temperature=0, hard timeout, JSON parsing
├── models/schemas.py       Pydantic request/response models matching the testing brief exactly
└── storage/state.py        in-memory, thread-safe context/conversation/suppression store
dataset/                    provided challenge dataset (unmodified)
tests/                      pytest suite (engine unit tests + full API contract tests)
judge_simulator.py          provided local judge (unmodified)
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optionally set GROQ_API_KEY for LLM-phrased messages
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Run tests:

```bash
pytest tests/ -v
```

Run the provided local judge simulator against it (edit `LLM_PROVIDER`/`LLM_API_KEY`/`BOT_URL`
at the top of `judge_simulator.py` first — it needs its own LLM key to *score* the bot, separate
from the bot's own optional key):

```bash
python judge_simulator.py
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | unset | Enables LLM phrasing via Groq's OpenAI-compatible API. Without it, the deterministic template path is used for every message. |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Groq-hosted open-weight model, sized for the 30s per-call budget across up to 20 tick actions. |
| `LLM_TIMEOUT_SECONDS` | `8` | Hard client-side timeout; on expiry the fallback template is used instead of blowing the request budget. |
| `TEAM_NAME`, `TEAM_MEMBERS`, `CONTACT_EMAIL`, `BOT_VERSION`, `APPROACH` | see `.env.example` | Surfaced verbatim via `/v1/metadata`. |

## API behavior notes (see `challenge-testing-brief.md` for the full contract)

- **`/v1/context`**: idempotent on `(scope, context_id)`; re-posting the same or a lower `version`
  returns `409 stale_version` (matching `examples/api-call-examples.md` §1.5 exactly); a higher
  version replaces atomically; invalid `scope` or a payload over 500KB returns `400`.
- **`/v1/tick`**: ranks the judge's `available_triggers` hint by urgency, applies the eligibility
  gates, caps at 20 actions, and allows at most one *new* merchant-facing conversation per merchant
  per tick (distinct customer-facing conversations to different customers are independent).
  Suppression keys are marked immediately on send, so a re-fired trigger never double-sends.
- **`/v1/reply`**: auto-reply detection escalates `send → wait(24h) → end` on repeats (matching the
  replay-test pattern in `examples/case-studies.md` §4.1); hostile/global-opt-out replies end the
  conversation and suppress the merchant for 30 days; explicit acceptance switches straight to a
  single low-friction confirm ask (no re-qualification); deferrals map to a `wait` with a duration
  inferred from the phrasing.
- **Customer consent**: every customer-scoped trigger checks `consent.scope` (or
  `preferences.reminder_opt_in` for generated customers) before it's eligible to send at all.

## Tradeoffs / what more context would help with

- The grounding validator does substring/percentage-derivation matching against the full pushed
  context rather than tracing exact provenance per number — a deliberate choice for robustness
  under the 30s budget, at the cost of not catching a hallucinated number that happens to coincide
  with an unrelated real one elsewhere in the payload.
- Date-arithmetic derivations (e.g. "5 months since last visit" computed from two ISO dates) aren't
  separately grounding-checked beyond the two source dates being real; a stricter numeric-diff
  checker would close this gap.
- Off-topic vs. on-topic classification in `/v1/reply` uses a simple keyword-overlap heuristic
  against the trigger's anchor summary; a real intent classifier would generalize better to novel
  curveballs in the replay test.

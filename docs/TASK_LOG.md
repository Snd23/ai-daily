# TASK_LOG.md

Narrative record of the tasks carried out during the project review that
started on 2026-10-01. Each entry explains **why** the task exists, **what**
was decided and done, and **how** it was verified. `TODO.md` remains the
roadmap and status list; this file holds the explanations.

Entry template: Status, Motivation, Scope, Out of scope, Changes, Verification,
Follow-ups.

---

## Review findings (2026-10-01)

Why the PDF looks short and incomplete, and which provider is in use:

- Provider: `.env` selected `LLM_PROVIDER=anthropic` (paid). `GeminiProvider`
  existed but was never activated and no `GEMINI_API_KEY` was configured.
- Missing sections: AI SENZA SBATTI and TERMINE DEL GIORNO are never generated
  (`generation.py` passes no concept explanation); WHAT TO WATCH is always empty
  (`future_date` is never computed).
- Short stories: the summarizer only receives title + RSS excerpt; full article
  text is never fetched.

These findings are split into the tasks below, done one at a time.

---

## TASK-029 — Switch to the free Gemini provider

**Status:** COMPLETED (2026-10-01).

**Motivation:** the LLM provider must be free for now. Anthropic and OpenAI
require paid keys; the Gemini Developer API (Google AI Studio) has a free tier.

**Scope:**
- select `gemini` as the active provider in the local configuration;
- confirm the default Gemini model ID is valid;
- run one real end-to-end call to confirm the key and model work.

**Out of scope:** changing the code default of `Settings.llm_provider`,
touching the Anthropic/OpenAI providers, prompt or content changes.

**Changes so far:**
- local `.env` (git-ignored): `LLM_PROVIDER=gemini`, empty `GEMINI_API_KEY=`
  line added. No code changed.
- Model ID check: the official models page (ai.google.dev/gemini-api/docs/models)
  lists `gemini-3.8-flash` as a valid stable ID, matching
  `DEFAULT_GEMINI_MODEL`. The docs do **not** state free-tier eligibility or
  rate-limit numbers; the actual limits are visible in Google AI Studio.
- Free tier confirmed: the official pricing page (ai.google.dev/gemini-api/docs/pricing)
  lists `gemini-3.8-flash` as "Free of charge" for input and output tokens on
  the free tier. Alternatives compared on 2026-10-01 and not adopted: Groq
  (free, needs a provider change), Mistral (free quota requires opting in to
  data training), OpenRouter (50 requests/day), Cerebras (no free tier since
  2026-07-16).

**Verification:**
- Real call through `create_llm_provider(load_settings())` with the project's
  `.env`: provider `gemini` -> `GeminiProvider`, response `'OK'`, usage
  `input_tokens=6 output_tokens=1`.
- The first attempts returned `503 UNAVAILABLE` ("high demand"), a transient
  Google-side overload (the key was accepted); the call succeeded on retry.
  Expect occasional 503s on the free tier: they surface as `LLMProviderError`
  and skip one event (`generation.py`); a retry policy is not part of this task.
- `pytest`: 960 passed. `ruff check`: OK. `mypy app`: OK.
- `ruff format --check`: 16 files would be reformatted -- pre-existing, no code
  was touched by this task; not fixed here (out of scope).

**Follow-ups / flagged items:**
- Uncommitted change in `app/llm/anthropic_provider.py` (default model
  `claude-haiku-4-5-20251001` → `claude-sonnet-5`) predates this task and is
  unrelated. Decision (user, 2026-10-01): keep it as is; it is not part of
  this task and is left uncommitted for the user to commit separately.
- Free-tier rate limits may constrain the number of events per run (two LLM
  calls per event); to be checked once real usage is measured.

---

## TASK-030 — Measure LLM token usage of one edition

**Status:** COMPLETED (2026-10-01) — measurement done, partial token data, two blocking findings.

**Motivation:** the free tier of the Gemini API has request and token limits
(visible in Google AI Studio). Before lengthening prompts or inputs
(TASK-031), we need to know how many LLM calls and tokens one real edition
consumes (CLAUDE.md §35, §44).

**Scope:**
- run one real edition with the Gemini provider;
- collect the existing per-call log lines (`LLM usage: stage=... input_tokens=...
  output_tokens=...`, `app/pipeline/generation.py`) and sum them per stage;
- compare the totals with the free-tier limits shown in AI Studio.

**Out of scope:** changing prompts, inputs, models or provider code. A code
change (e.g. a per-run usage total in the log) is made only if the existing
log lines turn out to be insufficient, and is then recorded here first.

**Verification:** a table in this entry with calls and input/output tokens per
stage and per run, plus the free-tier limits it was compared to.

**Results (one real run, `ai-daily run --language it`, Gemini `gemini-3.8-flash`):**

| Item | Value |
|---|---|
| Articles collected | 101 new (13 sources, 2 failed: The Verge 403, 1 more) |
| Events created | 101 (101 articles -> 101 events: clustering merged nothing) |
| LLM calls needed | 2 per event (summarize + developer impact) = 202 |
| Calls that succeeded | 2 summarize calls, then everything else failed |
| Tokens per summarize call | 538 in / 80 out and 660 in / 131 out |
| Tokens per developer-impact call | not measured (never completed) |
| Failures | 503 UNAVAILABLE (transient) and 429 RESOURCE_EXHAUSTED |
| Edition result | 0 events, 101 failed; a 1.7 KB PDF was still written and the edition row marked `published` |

Free-tier limit hit: `generate_content_free_tier_requests`,
`PerMinutePerProjectPerModel-FreeTier`, **limit 5 requests per minute**
(retry hint 45 s). A per-day cap was not observed in this run.

**Conclusions:**
- Tokens are not the bottleneck (about 600 in / 100 out per call); requests per
  minute are. 202 calls at 5 per minute need at least 40 minutes of perfect
  throttling, and the pipeline has none.
- The pipeline sends **every** event to the LLM. CLAUDE.md §35 expects local
  filtering/ranking down to ~15 events and 8-12 final stories first. That
  stage does not exist yet (ranking is computed but not used to limit LLM input).
- There is no retry/backoff for 429/503: every failed event is dropped.
- When all events fail, an empty edition is still written and marked published.

**Side effects of this run (local, git-ignored):** `data/ai_daily.db` now holds
101 events for 2026-10-01 and edition number 2; `data/editions/2026-10-01-it.pdf`
is an empty edition. A backup of the DB taken before the run is in the session
scratchpad. Re-running `generate` today reuses these events and overwrites that PDF.

**Follow-ups (new tasks, not implemented):** TASK-032, TASK-033, TASK-034 below.

---

## TASK-032 — Select candidate events before calling the LLM

**Status:** PLANNED.

**Motivation:** the run above sent all 101 events to the LLM. CLAUDE.md §35
describes filtering/ranking first, so only the top candidates (about 15) are
summarized. This is also what makes a free tier workable (about 30 calls per
edition instead of 202).

**Open decisions:** how many events (N), whether the limit is a configuration
value, and whether low-importance or `UNVERIFIED` events are dropped or only
left without LLM content.

**Out of scope:** clustering quality (101 articles -> 101 events suggests
clustering merges little; to be analyzed separately), new sections, longer content.

**Verification:** tests for the selection; one real run shows the number of LLM
calls equals 2 x N.

---

## TASK-033 — Rate-limit handling for the LLM provider

**Status:** COMPLETED (2026-10-01).

**Motivation:** the free tier allows 5 requests/minute and returns transient
503s. Today a single 429/503 permanently drops the event for that run.

**Decisions (user, 2026-10-01):**
- Where: a generic wrapper, `RetryingProvider(LLMProvider)`, in its own module
  `app/llm/retrying_provider.py`; it wraps any provider and is applied at the CLI
  call site. Existing providers and the factory are unchanged, except that a
  provider marks a failure as retryable.
- Pacing: new optional setting `LLM_MIN_INTERVAL_SECONDS` (default 0 = no pause).
  For Gemini free it is set to 13 (5 requests/minute = one every 12 s, plus margin).
- Retry: 3 retries on retryable errors (429 and 503), fixed in code. The wait is
  the provider's own hint when present (Gemini sends `retryDelay`, e.g. 45 s),
  otherwise 5 / 15 / 45 seconds. After the last retry the error is raised as
  today and the event is skipped.

**Scope:**
- `app/llm/errors.py`: `LLMProviderError` gains `retryable` and `retry_after_seconds`;
- `app/llm/gemini_provider.py`: marks HTTP 429/503 as retryable and reads the
  `retryDelay` hint. Anthropic/OpenAI are not touched: their official SDKs
  already retry these errors by themselves;
- `app/llm/retrying_provider.py` (new): pacing + retry;
- `app/config/settings.py`, `.env.example`: the new setting;
- `app/cli/main.py`: wrap the provider in `generate`;
- tests for each of the above; documentation (ARCHITECTURE §2.1, README).

**Out of scope:** reducing the number of calls (TASK-032), empty-edition
handling (TASK-034), switching provider, changing prompts, a configurable retry count.

**Verification:** unit tests with fake clocks (no real sleeping) covering pacing,
retry with hint, retry with backoff, non-retryable errors, exhaustion; then
`pytest`, `ruff check`, `mypy app`; plus one real call after the change.

**Results:**
- `pytest`: 981 passed (21 new). `ruff check`: OK. `mypy app`: OK.
- Formatting: the files this task touches are formatted, except
  `app/cli/main.py` and `tests/test_gemini_provider.py`, which were already
  unformatted before this task (part of the 16 pre-existing files).
- Real run: 7 consecutive Gemini calls through `RetryingProvider`. Calls 1-4
  took 4-6 s each; call 5 received three consecutive `503 UNAVAILABLE`, waited
  5 + 15 + 45 s and succeeded on the 4th attempt (+101 s); calls 6-7 succeeded.
  No 429 appeared in this burst (each call takes ~5 s, so the 5/minute limit
  was not reached); the 429 hint parsing is covered by unit tests only.
- `.env` (local) now has `LLM_MIN_INTERVAL_SECONDS=13`.

**Follow-ups:** with ~5 s latency plus a 13 s pause, 202 calls would still take
about an hour; reducing the number of calls is TASK-032. 503 overload from
Gemini was frequent today, so a worst-case wait of 65 s per call is possible.

---

## TASK-034 — Do not publish an empty edition

**Status:** PLANNED.

**Motivation:** with 0 usable events the pipeline still wrote a PDF and set the
edition status to `published`, reporting exit code 0. CLAUDE.md §34 says a
critical failure must fail explicitly and legibly.

**Open decisions:** fail with a clear error and non-zero exit code, or write
nothing; and what status the edition row keeps.

**Verification:** a test with a provider that always fails; the CLI exits
non-zero and no `published` row is created.

---

## TASK-031 — Longer, richer story content

**Status:** PLANNED — needs a spec (interview) after TASK-030.

**Motivation:** stories are 2-4 lines because the summarizer only receives the
article title and RSS excerpt; full article text is never fetched.

**Scope (to be refined):** decide and implement how more source material
reaches the summarizer, and how the prompts ask for a longer, still
source-grounded summary.

**Open product decisions (to ask before implementing):**
- fetch full article text (new collector step, treated as untrusted input per
  CLAUDE.md §10-11) or only use longer feed excerpts?
- which sources allow it (robots/terms), and what happens when fetching fails?
- target length per story, within the free-tier budget measured in TASK-030.

**Out of scope:** new sections (AI SENZA SBATTI, WHAT TO WATCH), provider changes.

**Verification:** to be defined in the spec; at minimum tests, lint, type
check and one real edition compared before/after.

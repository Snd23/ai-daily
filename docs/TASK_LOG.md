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

**Status:** COMPLETED (2026-10-01); real run confirmed in TASK-035.

**Motivation:** the TASK-030 run sent all 101 events to the LLM. CLAUDE.md §35
describes filtering/ranking first, so only the top candidates are summarized.
This is also what makes the free tier workable (about 30 calls per edition
instead of 202).

**Decisions (user, 2026-10-01):**
- N = 15 events per edition, a constant (`MAX_EDITION_EVENTS`) in
  `app/pipeline/generation.py`, next to `MAX_TOP_STORIES`; not a setting.
- Selection order: `importance_score` descending; on equal importance,
  verification status first (`VERIFIED`, `PARTIALLY_VERIFIED`, `DEVELOPING`,
  `UNVERIFIED`); then `id` ascending. `UNVERIFIED` events are not excluded.

**Scope:**
- `app/pipeline/generation.py`: select the top N of the day's events before the
  per-event LLM stage; log how many events were selected out of how many;
- tests in `tests/test_pipeline_generation.py`; documentation (ARCHITECTURE §4.14).

**Out of scope:** clustering quality (101 articles -> 101 events is analyzed
separately), backfilling when a selected event fails, changing importance
scoring, a configurable N.

**Behavior notes:** events not selected stay persisted without content; the
selection is deterministic, so re-running or generating another language the
same day picks the same events and reuses their stored content.

**Verification:** tests (cap respected, order by importance, verified wins ties,
LLM calls equal 2 x selected events); `pytest`, `ruff check`, `mypy app`.

**Results (2026-10-01):**
- `pytest`: 985 passed (4 new). `ruff check`: OK. `mypy app`: OK.
- Real run (`ai-daily generate --language it`): log line `Selected 15 of 101
  event(s) for the edition` -- the selection works on real data.
- The real run could not produce summaries: every call returned
  `429 RESOURCE_EXHAUSTED`, quota `GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
  **limit 20 requests per day** for `gemini-3.8-flash` (model-specific, global).
  Today's 20 requests were already used by earlier checks and runs. I stopped the
  run manually after it was clear nothing could succeed.
- Consequence for planning: at 2 calls per event the free tier of this model
  allows at most 10 events per day, so N = 15 (30 calls) does not fit. This is
  a finding about the provider quota, not a defect of the selection.

**Follow-ups (new decisions needed):**
- Daily quota vs N: lower N, merge the two calls per event into one, or use a
  different free model/provider with a larger daily quota (limits are shown in
  Google AI Studio and change over time).
- `RetryingProvider` retries a daily-quota 429 (waits ~26-47 s three times per
  call), which cannot succeed until the next day; it should fail fast on
  `PerDay` quotas.

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

**Status:** COMPLETED (2026-10-01).

**Motivation:** with 0 usable events the pipeline wrote a PDF, set the edition
status to `published` and exited with code 0 (seen in the TASK-030 run).
CLAUDE.md §34: a critical failure must fail explicitly and legibly.

**Decisions (user, 2026-10-01):**
- Every event failed, or there are no events at all: both cases are an error.
  `generate` (and therefore `run`) exits with code 1, writes no PDF and prints a
  clear message (which of the two cases it is, and the per-event errors).
- The edition row is marked `failed`. This reverses the TASK-024 choice that an
  empty database still produces an edition (test
  `test_an_empty_database_still_produces_an_edition`, to be replaced).

**Scope:**
- `app/pipeline/generation.py`: new `EmptyEditionError`, raised when the edition
  has no event, before any rendering; the edition row is marked `failed`, unless
  it is already `published` (a rerun must not downgrade a good edition);
- `app/database/edition_repository.py`: `update_status`;
- `app/cli/main.py`: `generate` turns the error into a message and exit code 1;
- tests; documentation (ARCHITECTURE §4.14, README usage).

**Out of scope:** retrying failed events later, partial-edition thresholds
(e.g. failing when only 1 of 15 events succeeds), notifications.

**Verification:** tests for both cases (no event, all events fail), the row
status, the preserved `published` edition, and the CLI exit code; `pytest`,
`ruff check`, `mypy app`.

---

**Results:**
- `pytest`: 992 passed (7 new or rewritten for the new behavior: 5 existing tests
  that asserted an empty edition were adapted). `ruff check`: OK. `mypy app`: OK.
- Real CLI run on an empty temporary database: message `generate failed: no event
  available for this edition; no PDF written.`, exit code 1, no PDF.
- Formatting: remaining `ruff format` differences in the touched files are
  pre-existing (`NewspaperMetadata(...)` call, `_fail_second_call`, `main.py`,
  `test_cli.py`).

---

## TASK-035 — Use a Gemini model with a larger free daily quota

**Status:** COMPLETED (2026-10-01).

**Motivation:** TASK-032 showed `gemini-3.8-flash` allows only 20 requests per
day on the free tier (quota is per model), i.e. 10 events per day at 2 calls each.

**Decision (user, 2026-10-01):** use another free model. One real call per
candidate on 2026-10-01: `gemini-3.5-flash-lite` (1.2 s), `gemini-3.1-flash-lite`
(2.2 s), `gemini-3.6-flash` (1.6 s), `gemini-3.5-flash` (11 s) and
`gemini-3.7-flash` (84 s) answered; `gemini-2.5-flash` and `gemini-2.5-flash-lite`
return 404 (no longer available). Third-party guides report about 500 requests/day for the
Flash-Lite models and about 20 for `3.5-flash`; Google does not publish fixed
numbers, so these are **unverified** -- the real limit is visible in AI Studio
(https://aistudio.google.com/rate-limit). Chosen: `gemini-3.5-flash-lite`.

**Scope:** change `DEFAULT_GEMINI_MODEL` in `app/llm/gemini_provider.py` and the
documentation that names the old default. No new setting (a constant, like the
other providers' defaults).

**Out of scope:** fast-failing on daily-quota 429s (separate follow-up), merging
the two LLM calls, changing prompts, other providers.

**Risk:** Flash-Lite is a smaller model; summary quality must be checked on a
real edition (CLAUDE.md §17: no invented facts).

**Verification:** `pytest`, `ruff check`, `mypy app`; one real
`ai-daily generate --language it` run that completes, and a read of the
resulting PDF text.

**Results:**
- `pytest`: 985 passed. `ruff check`: OK. `mypy app`: OK.
- Real run with `gemini-3.5-flash-lite`, `LLM_MIN_INTERVAL_SECONDS=13`
  (`ai-daily generate --language it`, 15 of 101 events selected): 22 LLM calls
  succeeded, no 429/503 and no retry, about 5 minutes in total. The 4 other events were not
  generated because of an unrelated problem (below). Edition 2 of 2026-10-01 now
  has 11 events and 4 pages, built from articles of 29-30 September.
- Token usage (completes TASK-030): 11 summarize calls = 6,241 in / 930 out
  (about 570 / 85 per call); 11 developer-impact calls = 10,003 in / 244 out
  (about 910 / 22 per call). One edition of 11 events = about 16.2k in / 1.2k out.
- Quality check by reading the PDF text: the summaries are short, faithful to the
  excerpts and in Italian; no invented figures seen in the first two pages. A full
  editorial review is not part of this task.
- The real daily limit of `gemini-3.5-flash-lite` is still unverified (22 requests
  were used without hitting it); check AI Studio.

**Findings, not fixed here (new tasks, TASK-036 and TASK-037):**
- 4 of the 15 selected events were skipped with `ArticleContext ... excerpt: must
  not be blank`: an article with an empty `normalized_text` and `raw_excerpt`
  makes the whole event fail before any LLM call, and wastes a selection slot.
- `RetryingProvider` should fail fast on a daily-quota 429 (see TASK-032).
- Observation: Top Stories are printed again in their category section, so the
  same story appears twice in the PDF; confirm whether this is intended
  (docs/PRD.md §17) before treating it as a defect.

---

## TASK-036 — Events whose articles have no excerpt

**Status:** COMPLETED (2026-10-01).

**Motivation:** 4 of the 15 selected events were dropped in the TASK-035 run.
Real data: all 4 are single-article events from Hugging Face (3 of 3 articles)
and Google DeepMind (1 of 2), whose feeds carry only a title. `ArticleContext`
requires a non-blank excerpt, so the event failed before any LLM call, after
winning a selection slot (high importance, Tier 1 sources).

**Decision (user, 2026-10-01):** exclude such events from the selection now;
the root cause (fetching the article text) belongs to TASK-031.

**Scope** (`app/pipeline/generation.py`):
- an event is eligible for the edition only if at least one of its articles has
  text (`normalized_text` or `raw_excerpt`, non-blank);
- eligibility is checked before the top-N selection, so excluded events do not
  use one of the 15 slots; the number of excluded events is logged;
- in an eligible event, articles without text are left out of the LLM context
  (and therefore of the citations shown), instead of failing the whole event.

**Out of scope:** title-only entries, using the title as text, fetching the page
(TASK-031), changing `ArticleContext`.

**Verification:** tests (a text-less event is neither selected nor reported as
failed; a mixed event still produces content); `pytest`, `ruff check`,
`mypy app`; a real `generate` is not needed, because the change needs no LLM
call, but the exclusion is checked on the real database (events 2330, 2331,
2351, 2353 must be excluded).

---

**Results:**
- `pytest`: 988 passed (3 new). `ruff check`: OK. `mypy app`: OK.
- Real database check (no LLM call): of today's 101 events, 97 are eligible and the
  4 text-less ones (2330, 2331, 2351, 2353) are excluded; the 15 selected events
  are all eligible. A new real `generate` was not run: it would only repeat the
  TASK-035 result with 4 more events and today's quota use is unknown.
- Effect: events from title-only feeds (Hugging Face, DeepMind) are absent from
  the edition until TASK-031 fetches their text.

---

## TASK-037 — Fail fast on daily-quota errors

**Status:** DONE (awaiting approval/commit).

**Motivation:** a 429 whose quota is per day cannot succeed on retry;
`RetryingProvider` waited and retried it three times per call (about 2 minutes
per call, seen in the TASK-032 run).

**Decision (local, small; CLAUDE.md §36):** `GeminiProvider` marks a 429 as
`retryable=False` when any violation in the error's `QuotaFailure` details has a
`quotaId` containing `PerDay` (real example:
`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). Per-minute 429s and 503s
stay retryable. `RetryingProvider` is unchanged: it already raises
non-retryable errors immediately.

**Scope:** `app/llm/gemini_provider.py`, its tests, `docs/ARCHITECTURE.md` §2.1.

**Out of scope:** stopping the whole run after the first daily-quota error (each
remaining event still makes one fast failing call), other providers.

**Verification:** unit tests (daily 429 not retryable, per-minute 429 retryable,
payload without details); `pytest`, `ruff check`, `mypy app`.

**Changes:** `app/llm/gemini_provider.py` (`_is_daily_quota`, `_error_details`);
two tests in `tests/test_gemini_provider.py`; `docs/ARCHITECTURE.md` §2.1.

**Verification results:** `pytest` 994 passed; `ruff check` OK; `mypy app` OK.
No real daily-quota 429 was reproduced end to end (unit tests use the real
payload shape seen in the TASK-032 run).

**Flagged:** the uncommitted `DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"` change
in `app/llm/anthropic_provider.py` is not part of this task (see chat).

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

---

## TASK-031 — Longer, richer story content

**Status:** DONE (awaiting approval/commit).

**Motivation:** stories are too short and not exhaustive; the reader wants a
complete summary with all the information needed to understand the news. Root
cause measured on the real database (average `normalized_text` per article):
Ars Technica 75 chars, DeepMind 81, BBC 94, OpenAI 155, MIT Tech Review 334,
Guardian 655, Hugging Face 0. The LLM only sees the RSS excerpt, so no prompt
can produce a complete summary without inventing facts (CLAUDE.md §17). The
SUMMARIZE prompt also asks for a "concise" output and sets no length target.

**Decisions (user interview, 2026-10-01):**
- Text extraction: new dependency `trafilatura` (extracts the article body from
  arbitrary HTML; alternative `beautifulsoup4` + per-source selectors rejected as
  fragile).
- Length scaled by importance: top stories about 250-350 words, the others about
  120-180 words.
- Cost control (§35): the full text is fetched and sent only for the events
  already selected for the edition (about 15), never for all collected articles,
  with a per-article character cap (about 6000).

**Scope** (to be refined against the code before implementing):
- a fetcher that downloads an article page and extracts its text with
  `trafilatura`; page content is untrusted input (§10-11);
- fetch failures (403, timeout, paywall, empty text) fall back to the RSS excerpt
  and are logged; they never fail the pipeline (§33-34);
- `app/ai/event_summarizer.py`: prompt asks for a complete summary with a length
  target; it must still preserve uncertainty and never add facts;
- `app/pipeline/generation.py`: fetch step after selection, before the LLM;

**Out of scope:** changing source tiers, ranking, verification, developer impact
and AI Senza Sbatti prompts, PDF layout redesign, headless-browser rendering of
JavaScript-only pages.

**Verification:** unit tests (extraction, fallback on error, length cap, prompt);
`pytest`, `ruff check`, `mypy app`; a real `generate` on today's database
comparing summary length and token usage before/after, against the free-tier
limits measured in TASK-030.

**Changes:** `app/collectors/article_text.py` (new: `fetch_article_text`);
`app/ai/event_summarizer.py` (prompt: complete summary + length target,
`EventSummaryInput.is_top_story`); `app/pipeline/generation.py` (fetch after
selection, only when content is not stored; first `MAX_TOP_STORIES` events are
top stories); `app/newspaper/renderer.py` (one `Paragraph` per summary line,
added during the task: without it the multi-paragraph summaries were rendered as
one block); `pyproject.toml`/`uv.lock` (`trafilatura` 2.2.0, brings `lxml` and
other transitive packages); `tests/conftest.py` (autouse fixture: tests never
download pages); new and updated tests; `docs/PRD.md` (Completeness),
`docs/ARCHITECTURE.md` §1.2 and §4.8.

**Verification results:**
- `pytest` 1008 passed; `ruff check` OK; `mypy app` OK.
- Real run on a copy of the database (Gemini `gemini-3.5-flash-lite`,
  `generate --language it`, today's 15 selected events, content regenerated):
  summary length average 282 -> 1190 characters (max 1837); 15 summaries, 9 with
  several paragraphs; PDF of 10 pages written.
- Tokens, 30 calls: summarize 22,899 in / 4,513 out; developer impact 26,169 in /
  614 out; total about 49k in / 5.1k out per edition (about 1,530 in per summarize
  call, was 540-660 in TASK-030). No LLM call failed.
- Page fetch check on real URLs: TechCrunch, BBC, Hugging Face, DeepMind and
  OpenAI returned text; Ars Technica returned 403 and falls back to the excerpt.

**Flagged / follow-ups:**
- Events from title-only feeds (Hugging Face: 865 articles, 0 chars of text;
  DeepMind) are still excluded by TASK-036's eligibility check, which runs before
  the fetch. Their pages are fetchable (checked), so fetching before the check
  would make them eligible again. Separate task.
- Sources that block bots (Ars Technica, The Verge: 403) keep the short RSS
  excerpt, so their summaries stay short.
- Top-story summaries came out below the 250-350 word target in the sample
  (longest 1837 characters, about 280 words); not tuned further.
- The summary is stored per event once; a Top Story status change on a later day
  does not regenerate it.

**Review (`/code-review`):** acted on two findings: page text can no longer close
the prompt's `<article>` block (`</article` is neutralized in
`fetch_article_text`), and only http(s) URLs are requested. Reported, not done:
no private-address blocking or response-size cap on page downloads; fetches are
sequential with no per-event limit on articles or time, and the 6000-character cap
is per article, not per event; `rank` counts events later skipped, so a skipped
Top Story leaves the edition with fewer long summaries.

---

## Findings behind TASK-038 to TASK-042 (edition of 2026-10-01 reviewed)

Review of the real edition (15 stories, 143 articles collected that day):
143 articles became 143 events (clustering merged nothing); all stories had a
single source yet were `VERIFIED` (Tier 1 announcements about themselves); 7
stories tied at importance 6.5, so the Top Stories were picked among ties; the
same OpenAI DevDay was split into three stories and the "dots" announcement
exists as three separate events (OpenAI, Wired, BBC); non-AI items (BMW Serie 3,
GeForce NOW games, a NVIDIA fellowship) were published; Top Stories are printed
twice; source dates appear as raw ISO strings. Tasks are done one at a time, in
the order below; TASK-039 to TASK-042 get their full entry (motivation, scope,
decisions) when they start.

---

## TASK-038 — Cross-source event clustering

**Status:** DONE (awaiting approval/commit).

**Motivation:** the clusterer groups articles only when their normalized titles
are identical, so articles of different outlets about the same event never merge
(real example: "Introducing dots" / "OpenAI's Dots Are Always-On AI Agents..." /
"OpenAI unveils AI assistant 'dots'..."). Consequences: duplicated stories in the
newspaper (CLAUDE.md §16) and no corroboration by independent sources (§15).

**Decisions (user interview, 2026-10-01):**
- Approach: local rules produce candidate groups (time window, distinctive words in
  common); one LLM call over the candidates' titles decides the groups (CLAUDE.md
  §20 semantic deduplication, §35 cost control). No embeddings.
- The clustering only groups. The verification rules (TASK-017) are unchanged.
- Only articles not yet assigned to an event are clustered; existing events are
  neither dissolved nor recomputed.

**Scope** (to be refined against the code before implementing):
`app/clustering/article_clusterer.py` and its use in `app/pipeline/generation.py`;
the LLM call goes through the `LLMProvider` abstraction; web titles are untrusted
input in the prompt (§10-11).

**Out of scope:** changing verification, ranking, importance, relevance filtering,
embeddings, regrouping events already persisted.

**Verification:** unit tests (grouping, a malformed or failing LLM answer, no
LLM call when there are no candidates); `pytest`, `ruff check`, `mypy app`; a real
run on a copy of the database with today's articles unassigned, comparing events
before/after and token usage.

**Changes:** `app/clustering/cluster_merger.py` (new), `app/pipeline/generation.py`
(`_merge_clusters`, `llm_provider` passed to `_analyze_pending_articles`),
`tests/test_cluster_merger.py`, `tests/test_pipeline_generation.py` (fake provider
answers the grouping call), `docs/ARCHITECTURE.md` §4.1b, `docs/PRD.md`.

**Design change during the task:** the first version linked candidates into
connected components and capped their size; on real data shared words chained almost
every title into one component (125 of 143 clusters had a link), which was discarded
whole, so no call was made. The rules now define a candidate graph, the LLM receives
every linked title and a group must be connected in that graph. A well-formed group
that is not connected is ignored on its own; a malformed response rejects everything.

**Verification results:**
- `pytest` 1031 passed; `ruff check` OK; `mypy app` OK.
- Real run on a copy of the database with today's 143 events dissolved (Gemini):
  143 articles -> 134 events with one LLM call (2,688 in / 74 out). Correct merges:
  Gemini 4 Argon (DeepMind, TechCrunch, Ars Technica, Reddit), "dots" (OpenAI,
  Wired), the lawsuit against OpenAI (Ars Technica, Wired), the White House pledge
  typo (Guardian, TechCrunch). One group ignored as unlinked.

**Flagged:**
- Title-only grouping is loose: one event merged the BBC "dots / safety worries"
  article with three articles about OpenAI safety delays (model rollout, IPO).
  The BBC "dots" article did not join the OpenAI "Introducing dots" event.
- On re-clustering the copy I had to reset `article.status` to `pending`; a real
  deployment never does this, since only unassigned articles are clustered.
- Merged events keep the verification rules of TASK-017, so multi-source events
  are now scored with more than one source; their effect on importance is visible
  in the data (events with 4 sources reached 6.5) and belongs to TASK-040.

## TASK-043 — Persist the composed edition

**Status:** DONE (awaiting approval/commit).

**Motivation:** the user wants a website showing the same news as the PDF
(2026-10-03). The database stored events, their generated content and the
edition row, but not which events made it into an edition nor how they were
laid out (Top Stories, section order, citations): that composition existed only
in memory between `assemble_edition` and `render_edition`.

**Decisions (user, 2026-10-03):**
- Work in two tasks: first persist the edition (this task), then the website
  (TASK-044).
- The website is a web app with a server reading the database (Flask), chosen
  over a statically generated site. Its design belongs to TASK-044.
- Store the composition as a JSON snapshot of the `Edition` on the `edition`
  row rather than a normalized `edition_event` table: it is exactly what the PDF
  was rendered from, it needs no recomposition by the reader, and later changes
  to the composition rules (e.g. TASK-041) never rewrite past editions.

**Scope:** migration `0004_edition_content.sql`, `EditionRecord.content`,
`EditionRepository.publish` (replaces `update_pdf_path`, whose only caller set
`published`), one line in `app/pipeline/generation.py`.

**Out of scope:** the website, any change to the composition or the PDF,
backfilling editions published before the migration.

**Verification:** `pytest`, `ruff check`, `mypy`; a generation test reads the
stored JSON back into an `Edition`.

**Changes:** `app/database/migrations/0004_edition_content.sql` (new),
`app/database/edition.py`, `app/database/edition_repository.py`,
`app/pipeline/generation.py`, `tests/test_edition_repository.py`,
`tests/test_pipeline_generation.py`, `docs/ARCHITECTURE.md` §3 and §4.14.

**Verification results:** `pytest` 1032 passed; `ruff check` OK; `mypy` OK.
No real run: the change does not touch an external service, and the generation
test exercises the whole publish path on a migrated database.

**Flagged:** editions published before this migration have `content = NULL`;
the website will list them without content (or link only the PDF) unless they
are regenerated.

## TASK-044 — Web app showing the editions

**Status:** DONE (awaiting approval/commit).

**Motivation:** the user wants the news of the PDF available on a website too
(2026-10-03), reading the editions saved to the database by TASK-043.

**Decisions (user, 2026-10-03):** a web app with a server reading the database
(Flask), chosen over a statically generated site. Defaults picked here: an
archive page plus one page per edition, the PDF downloadable from the page,
page chrome in the edition's language (the list page in `DEFAULT_LANGUAGE`),
Flask's built-in server through a new `ai-daily web` command.

**Scope:** `app/web/` (new: `server.py`, templates, stylesheet), the `web`
command in `app/cli/main.py`, `EditionRepository.get_by_number` and
`list_published`, the `flask` dependency.

**Out of scope:** public hosting and its security (WSGI server, HTTPS,
authentication), search, per-event pages, any change to the composition: the
site shows exactly what the PDF shows, so a Top Story also appears in its
section until TASK-041 changes the composition.

**Verification:** `pytest`, `ruff check`, `mypy`; the app served on a database
with two published editions and checked in a browser at desktop and phone width.

**Changes:** `app/web/__init__.py`, `app/web/server.py`,
`app/web/templates/{base,index,edition,_story}.html`, `app/web/static/style.css`,
`app/cli/main.py`, `app/database/edition_repository.py`, `tests/test_web.py`,
`pyproject.toml`, `uv.lock`, `README.md`, `docs/PRD.md` §36,
`docs/ARCHITECTURE.md` §1.2, §2 and §4.16.

**Verification results:** `pytest` 1041 passed; `ruff check` OK; `mypy` OK.
`ai-daily web` on a seeded database: `/` and `/editions/2` return 200, the PDF
route returns `application/pdf`; screenshots at 1280 px and 390 px show the
masthead, sections, callouts and sources laid out like the PDF.

**Flagged:**
- The masthead month names are duplicated from `app/newspaper/renderer.py`
  (private there); sharing them means touching the renderer, which TASK-042 is
  changing. Worth a small follow-up once TASK-042 lands.
- Flask's built-in server is fine locally; putting the site on the internet needs
  a hosting decision (separate task).

## TASK-045 — Website design

**Status:** DONE (awaiting approval/commit).

**Motivation:** the user rejected TASK-044's plain styling (2026-10-03) and asked
for a site designed like modern news sites.

**Decisions (user, 2026-10-03):** stay on Python + Jinja + CSS (server-rendered,
no JavaScript, no frontend build) over a Flask API with a React/Next.js or Astro
frontend.

**Scope:** `app/web/templates/`, `app/web/static/style.css`, page strings and two
template filters in `app/web/server.py`, `tests/test_web.py`.

**Out of scope:** any change to the stored edition, the composition or the PDF;
new product content (e.g. a visible verification status, which the PDF also does
not show).

**Changes:** front page with a lead Top Story, sticky section index, per-section
reading column, source count and reading time per story, labelled Developer
Impact / AI Senza Sbatti boxes, sources as linked chips, home page with the latest
edition's headlines and the archive, light/dark themes, phone layout. Google Fonts
(Newsreader, JetBrains Mono) with system fallbacks. `docs/ARCHITECTURE.md` §4.16.

**Verification results:** `pytest` 1042 passed; `ruff check` OK; `mypy` OK.
Screenshots on a seeded database at 1280 px (light and dark) and 390 px; no
horizontal overflow at 390 px (`scrollWidth` 390).

**Flagged:**
- Sources show the outlet name and date; the full URL is only the link target,
  unlike the PDF's citation lines.
- Google Fonts are fetched from Google's servers by each visitor; self-hosting the
  two fonts would avoid that if the site goes public.
- Top Stories still appear again in their section, as in the PDF, until TASK-041.

---

## Fix — CLI tests and the edition date (2026-10-03)

**Status:** DONE (awaiting approval/commit).

**Motivation:** four `tests/test_cli.py` tests (`generate` and `run`) built the
expected PDF name from `date.today()`, the machine's date, while the pipeline
names the PDF after today in `APP_TIMEZONE` (Europe/Rome). From midnight in Rome
to midnight on the machine clock (22:00-24:00 UTC in summer) the dates differ and
the four tests failed on `develop`. Found while verifying TASK-040.

**Scope:** `tests/test_cli.py` only: a `_edition_day()` helper returning
`datetime.now(APP_TIMEZONE).date()`. **Out of scope:** application code, the
existing formatting of the file.

**Verification results:** at 22:00 UTC on 2026-10-03, `uv run pytest` gave 4
failed / 1037 passed on `develop`, and 1041 passed with this fix;
`uv run ruff check .` OK; `uv run mypy` OK.

---

## TASK-039 — AI relevance filter

**Status:** DONE (awaiting approval/commit; real LLM run still to do, see Flagged).

**Motivation:** sources that are not dedicated to AI (NVIDIA, Microsoft Research,
BBC, ...) also publish unrelated items, and nothing filters them: the edition of
2026-10-01 printed a BMW Serie 3 review, a list of GeForce NOW games and an NVIDIA
fellowship announcement. AI Daily is a newspaper about AI (PRD §1-2: relevance
before quantity), so such events must not reach the edition.

**Decisions (user, 2026-10-03):**
- Approach: one LLM call over the titles of the day's clusters decides which are
  not about AI (option "LLM on titles"; keyword rules were considered and not
  adopted). Same pattern as TASK-038: titles are untrusted data, the response is
  only a list of item numbers, validated strictly.
- Defaults chosen by Claude, stated to the user: the filter runs in the analysis
  phase, after the cross-source merge and before events are persisted, so it runs
  once per article, not per language; the articles of a cluster judged not about
  AI are marked `discarded` (with `duplicate_of` NULL) and never become an event,
  so a later run neither re-clusters nor re-judges them; a failed call or a
  malformed answer keeps every cluster (fail open, CLAUDE.md §34), like the merge;
  when in doubt the model must keep the item.

**Scope:** a new `app/relevance/` stage (pure, in-memory, `LLMProvider`
abstraction); `ArticleRepository` gains a method to discard the rejected articles;
`app/pipeline/generation.py` calls the stage between `_merge_clusters` and
`_persist_event`; tests; `docs/ARCHITECTURE.md`, `docs/PRD.md`, `TODO.md`.

**Out of scope:** keyword or source-tier heuristics, ranking and tie-breaks
(TASK-040), re-judging events already persisted, changing verification.

**Verification:** unit tests (kept/rejected split, `NONE` answer, malformed or
out-of-range answer rejected, failing provider, untrusted titles presented as
data); pipeline tests (rejected articles discarded and absent from the edition,
fail-open on error); `uv run pytest`, `uv run ruff check .`, `uv run mypy`; a real
call on the 2026-10-01 titles when a `GEMINI_API_KEY` is available.

**Changes:** `app/relevance/__init__.py`, `app/relevance/ai_relevance_filter.py`
(new: `filter_ai_relevant`, `RelevanceSplit`, `AIRelevanceParseError`);
`app/database/article_repository.py` (`mark_not_relevant`, `list_clusterable`
docstring); `app/database/article.py` (docstring: meaning of `discarded` without
`duplicate_of`); `app/pipeline/generation.py` (`_filter_relevant`, called after
`_merge_clusters`); `tests/test_ai_relevance_filter.py` (new),
`tests/test_article_repository.py`, `tests/test_pipeline_generation.py` (the fake
provider records the analysis-phase calls in `analysis_requests`, apart from the
content generation calls); `docs/ARCHITECTURE.md` §2 and §4.1c, §4.14;
`docs/PRD.md` §7; `README.md`; `TODO.md`.

**Design note:** each title is put on one line (whitespace collapsed, `|` replaced),
so a title cannot forge further numbered items or titles in the prompt. This
matters more here than in the merge: a rejection discards the articles for good.

**Verification results:**
- `uv run pytest` 1052 passed; `uv run ruff check .` OK; `uv run mypy` OK
  (61 source files).
- Independent review of the diff in a fresh context: no correctness bug; its
  findings on prompt-line forging, stale `discarded` docstrings, a multi-line
  answer being accepted and a missing pipeline test for a provider error were
  fixed.

**Flagged:**
- The real LLM check on the 2026-10-01 titles was not run: this session has no
  `GEMINI_API_KEY` and no copy of the database. It should be run before relying
  on the prompt (`uv run ai-daily generate` on a copy of the database, then read
  the `Not about AI, discarded` log lines).
- A rejection is permanent: a real AI story judged not about AI is discarded with
  all its sources and is never judged again. Recoverable only by resetting the
  articles to `pending` by hand.
- `uv run ruff format --check .` reports 20 files that are not formatted on
  `develop` already; the new files are formatted and the others were not touched.

---

## TASK-040 — Ranking: break ties between equal importance scores

**Status:** DONE (awaiting approval/commit).

**Motivation:** importance factors take only two values each (TASK-024: 7.0 or
3.0), so many events share the same score: on 2026-10-01 seven events tied at
6.5. Among ties `_select_events` ordered by verification and then by event id,
and `assemble_edition` re-sorted by event id alone, so the Top Stories were picked
by arrival order in the database, and the two stages could disagree.

**Decisions (user, 2026-10-03):**
- Tie-break among equal `importance_score`: more distinct sources first (now
  meaningful after TASK-038), then better verification, then the most recent
  article, then event id. The score and its formula (TASK-013) are unchanged.
- Default chosen by Claude: one ordering for the whole edition. The pipeline
  passes each event's position in that ordering to `assemble_edition`
  (`EventForEdition.selection_rank`), which uses it after the score, so the 15
  selected events, the Top Stories and the sections all agree. Without a rank,
  `assemble_edition` keeps ordering ties by event id (approved decision D-011).

**Scope:** `app/pipeline/generation.py` (`_select_events` and the events it
builds), `app/editorial/edition.py` (`EventForEdition`, `_sort_key`), tests,
`docs/ARCHITECTURE.md`, `docs/PRD.md` §10, `TODO.md`.

**Out of scope:** the importance formula and its factors, Top Stories repeated in
the sections (TASK-041), relevance filtering (TASK-039).

**Verification:** unit tests (edition ordering with and without a rank; selection
ordering by source count, verification, recency, id); `uv run pytest`,
`uv run ruff check .`, `uv run mypy`.

**Changes:** `app/pipeline/generation.py` (`_select_events` takes the events'
articles, read once per event and also used for the TASK-036 eligibility check;
`_latest_published_timestamp`; `selection_rank` passed to `EventForEdition`);
`app/editorial/edition.py` (`EventForEdition.selection_rank`, optional, and
`_sort_key`); `tests/test_pipeline_generation.py`, `tests/test_edition.py`;
`docs/ARCHITECTURE.md` §4.14; `docs/PRD.md` §10; `TODO.md`.

**Verification results:**
- `uv run pytest` 1045 passed (21:58 UTC); `uv run ruff check .` OK; `uv run mypy`
  OK. After 22:00 UTC four `tests/test_cli.py` tests fail on `develop` too (see
  Flagged); the other 1041 pass.
- End-to-end test: two events with the same score, the two-source one created
  second, now leads the Top Stories (before this task the one-source event, with
  the lower id, did).
- Independent review of the diff: no blocking finding; the wording ("distinct",
  not "independent", sources), the count limited to cited articles, the optional
  rank and a stronger recency test were applied.

**Flagged:**
- "Distinct sources" counts outlets, not truly independent confirmations
  (CLAUDE.md §15): an outlet that copies another still counts. Same limit as the
  verification rules (TASK-017).
- Pre-existing, outside this task: `is_top_story` is given to the first three
  selected events even when one is `UNVERIFIED` or fails, so that event gets the
  long summary while `assemble_edition` keeps it out of the Top Stories and the
  fourth event is promoted with a short one. Worth a separate task.
- Pre-existing, outside this task: four `tests/test_cli.py` tests (`generate` and
  `run`) build the expected PDF name from `date.today()` (the machine's date),
  while the pipeline names it after today in `APP_TIMEZONE` (Europe/Rome). Between
  midnight in Rome and midnight on the machine clock (22:00-24:00 UTC in summer)
  the two dates differ and the tests fail, on `develop` as well. Worth a separate
  small fix (use `datetime.now(APP_TIMEZONE).date()` in the tests).

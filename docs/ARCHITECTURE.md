# ARCHITECTURE.md — AI Daily

Technical architecture proposal for the MVP, derived from [PRD.md](./PRD.md) and constrained by the rules in [../CLAUDE.md](../CLAUDE.md).

Status: **originally written as the MVP proposal; partially implemented (TASK-001 → TASK-028, see [../TODO.md](../TODO.md) for task status).** Where a component has been implemented, its section records the actual implementation (§2.1a, §4.1a, §4.2a, §4.3a, §4.8, §4.9, §4.10, §4.11, §4.12, §4.13, §4.14, §4.15); superseded or not adopted proposals are kept and marked as historical.

---

## 1. Stack and dependencies

### 1.1 Explicitly required by the PRD

| Area | Choice | Note |
|---|---|---|
| Language | Python 3.11+ | typed, consistent with CLAUDE.md §8 |
| PDF | `reportlab` | explicit (PRD §16); adopted (TASK-021, see §4.11) |
| DB | SQLite | explicit (PRD §20) |
| LLM | `anthropic`, `openai` (official SDKs) | behind an abstract interface (PRD §22) |
| Config | `.env` + `python-dotenv`, `config/sources.yaml` + `PyYAML` | PRD §6, §26 |
| Automation | GitHub Actions (cron) | PRD §27 |
| Notifications | Telegram Bot API (v0.3, post-MVP) | PRD §28 |

### 1.2 Minimal additional dependencies required

Not explicitly required by the PRD, but necessary to satisfy a concrete requirement. They must be confirmed/justified as required by CLAUDE.md §6.

| Requirement | Dependency | Why | Native alternative considered |
|---|---|---|---|
| RSS parsing (PRD §6) | `feedparser` | de facto standard | no sensible stdlib alternative |
| HTTP fetch (API/official pages) | `requests` | sync is sufficient for a daily batch job | stdlib `urllib`, but more cumbersome for headers/retry |
| Full article text (TASK-031) | `trafilatura` | extracts the article body from arbitrary HTML; RSS excerpts average 75-650 characters, too little for a complete summary. Used only for the events selected for the edition (§4.14). It pulls in `lxml` and other transitive packages | `beautifulsoup4` + a selector per source (rejected: one selector to maintain per site, breaks on layout changes) |
| Article language detection (TASK-008) | `langdetect` | detects the observed language of an article's normalized text (`Article.language`), seeded so that detection is deterministic | — |
| Content extraction from pages without RSS | `beautifulsoup4` + `lxml` — **proposed, not yet adopted** (no HTML collector is implemented) | necessary for the HTML scraping envisaged by PRD §6 | none |
| Title deduplication/clustering | `rapidfuzz` — **historical proposal, not adopted** (see §4.1/§4.1a) | originally proposed for fuzzy title matching | TASK-012 implemented clustering as deterministic exact-match on a normalized title; no fuzzy-matching dependency is used |
| CLI | `typer` (adopted, TASK-023) | typed signature consistent with CLAUDE.md §8; approved over the zero-dependency `argparse` alternative during TASK-023 FASE 0 -- see §4.13 | `argparse` |
| Typed data validation (config, models, LLM I/O) | `pydantic` | validates settings, `sources.yaml`, `config/labels.yaml`, database models, and the LLM request/response and summarization models; LLM output is plain text parsed by the consuming stage, not JSON (see §4.8) | dataclasses + manual validation |
| Lint | `ruff` | lint + formatting in a single tool | `flake8`+`black`+`isort` (more dependencies) |
| Type checking | `mypy` | explicitly required as a gate (PRD §35) | — |
| Tests | `pytest` (`pytest-cov` was proposed, not adopted) | PRD §25 | stdlib `unittest`, less ergonomic |
| HTTP mocking in tests | `responses` (adopted; `pytest-httpx` was the alternative) | avoids real network calls in collector tests/CI | — |
| PDF structural test assertions (TASK-021) | `pypdf` (dev-only, adopted) | parses a rendered PDF back into page/text structure for `tests/test_newspaper_renderer.py`; not used by any runtime code | `pdfminer.six` was considered, `pypdf` is lighter and sufficient for text-extraction assertions |

**Not introduced**: ORM (SQLAlchemy), Alembic, code/message bus, cache, microservices — consistent with CLAUDE.md §5 (avoid over-engineering). Data access via stdlib `sqlite3` + typed repositories; migrations as numbered SQL scripts applied at startup.

**Package manager**: `pyproject.toml` is required by the PRD (§21) but the tool is not specified. `uv` was proposed and has been adopted: `uv.lock` is committed and the README documents `uv sync` / `uv run`.

---

## 2. Module architecture

Follows the folder structure from PRD §21. Original pipeline → module mapping (proposal; the implementation status up to TASK-022 follows the block):

```
COLLECT              → app/collectors/       (RssCollector, ApiCollector, HtmlCollector)
NORMALIZE            → app/normalization/     (strip HTML, encoding, published_at, content hash)
FILTER               → app/filtering/         ("cheap" heuristics: source tier, recency, keywords — NO LLM)
DEDUPLICATE          → app/deduplication/     (near-dup title/content via rapidfuzz)
CLUSTER EVENTS       → app/deduplication/     (groups articles from different sources about the same event)
VERIFY               → app/verification/      (verification_status, hedging language)
CLASSIFY             → app/classification/    (primary + secondary category, event_type)
RANK                 → app/ranking/           (importance_score)
SUMMARIZE            → app/ai/                (event summary — LANGUAGE-DEPENDENT, see §5)
AI EXPLANATION        → app/ai/                (AI SENZA SBATTI / TERMINE DEL GIORNO — LANGUAGE-DEPENDENT)
EDITORIAL ASSEMBLY   → app/editorial/         (Top Stories, sections, What to Watch, labels — LANGUAGE-DEPENDENT)
PDF                  → app/newspaper/         (ReportLab rendering — LANGUAGE-DEPENDENT)
ORCHESTRATION         → app/pipeline/          (stage wiring, used by the CLI)
DATA ACCESS           → app/database/          (connection, migrations, repositories)
```

Implementation status (up to TASK-028):

| Stage / concern | Actual module | Status |
|---|---|---|
| COLLECT | `app/collectors/rss.py` | RSS only (`RssCollector`, TASK-007); no API or HTML collector |
| NORMALIZE | `app/normalization/` | implemented (TASK-008): HTML stripping, text normalization, `content_hash`, language detection |
| FILTER | `app/collectors/rss.py`, `app/database/article_repository.py` | **recency only** implemented (TASK-028, §4.15): the original proposal's source-tier and keyword heuristics remain not implemented, and no separate `app/filtering/` module was created |
| DEDUPLICATE | `app/deduplication/` | implemented (TASK-009) as exact duplicate detection on `content_hash`; the rapidfuzz near-duplicate proposal was not adopted |
| CLUSTER EVENTS | `app/clustering/` | implemented (TASK-012), see §4.1a; lives in `app/clustering/`, not `app/deduplication/` |
| VERIFY | `app/verification/` | implemented (TASK-017), deterministic, in-memory, see §4.3a; never produces `DEVELOPING`; no hedging-language detection |
| CLASSIFY | `app/pipeline/categories.py` | not implemented as specified (no LLM classifier); TASK-024 replaces it with deterministic category assignment from `Source.categories`, see §4.14 |
| RANK | `app/ranking/` | implemented (TASK-013), deterministic, see §4.2a |
| SUMMARIZE | `app/ai/event_summarizer.py` | implemented (TASK-015), in-memory, see §4.8 |
| AI EXPLANATION | `app/ai/concept_explainer.py` | implemented (TASK-016), in-memory, see §4.9; concept selection and technical-definition curation/validation are not part of it |
| DEVELOPER IMPACT (not in the original mapping) | `app/ai/developer_impact.py` | implemented (TASK-018), in-memory, one LLM call, see §4.10; not persisted |
| EDITORIAL ASSEMBLY | `app/editorial/` | implemented: `event_editorial.py` (TASK-019) assembles one event's `EditorialContent` per language; `edition.py` (TASK-020) composes an in-memory `Edition` from several `EditorialContent` (Top Stories, the nine category sections, What to Watch), see §4.6; `category`, `importance_score` and `future_date` are caller-supplied, since CLASSIFY and future-event extraction are not implemented |
| PDF | `app/newspaper/renderer.py` | implemented (TASK-021), pure, in-memory, see §4.11; renders an already-composed `Edition` to PDF bytes -- no persistence |
| SOURCE CITATIONS (not in the original mapping) | `app/newspaper/renderer.py` | implemented (TASK-022), pure, in-memory, see §4.12; renders `EditorialContent.articles` as a per-story citation sub-block |
| ORCHESTRATION | `app/pipeline/` | implemented (TASK-024), see §4.14; sequences CLUSTER → VERIFY → category → RANK → `Event` persistence → SUMMARIZE/Developer Impact → `event_content` → editorial assembly → PDF. `app/cli/` remains a thin adapter over it (§4.13) |
| LLM provider (not in the original mapping) | `app/llm/` | implemented (TASK-014), see §2.1a |
| Configuration and logging (not in the original mapping) | `app/config/`, `app/logging_config.py` | implemented (TASK-002, TASK-003, TASK-006) |
| DATA ACCESS | `app/database/` | connection, numbered SQL migrations, and models/repositories for `Source`, `Article`, `Event` (TASK-004, TASK-005, TASK-007, TASK-011), `EventContent` and `EditionRecord` (TASK-024, §4.14) |
| CLI (not in the original mapping) | `app/cli/` | implemented (TASK-023), see §4.13; wires `collect`/`process` to already-implemented stages, `generate`/`run` are explicit stubs |

Key architectural point (detailed in §5): the pipeline splits into an **analysis phase** (Collect → Rank), entirely **language-independent**, and a **generation phase** (Summarize → PDF), **language-dependent**. This split is not visible in the folder structure but in the behavior of the individual modules.

### 2.1 LLMProvider interface

Original proposal (**historical, not adopted** — superseded by the TASK-014 implementation in §2.1a): one provider method per AI use case.

```
class LLMProvider:
    def summarize(event, articles, verification_status, language) -> Summary
    def classify(event) -> ClassificationResult
    def explain(technical_definition, language) -> ConceptExplanation
    def rank(event, context) -> RankingSignal
```

Notes on the original proposal:

- `rank(event, context) -> RankingSignal` was the original proposal for LLM-assisted ranking. It is **historical, not adopted, and not implemented anywhere in the codebase**: importance ranking (TASK-013) is implemented as a deterministic formula outside `LLMProvider` — see §4.2a.
- `classify` and `rank` **do not receive `language`**: they produce structural data (category, score, internal/audit rationale) reusable for any output language. This is consistent with CLAUDE.md §35 (cost control): do not re-run classification/ranking per language. This principle still applies to the classification and ranking stages, independently of the provider interface.
- `summarize` and `explain` receive `language` and produce text intended for the reader. This still applies to the corresponding stages: event summarization (TASK-015, §4.8) takes the target language as input.
- `explain` receives an already-validated `technical_definition` (see §5.3) and only produces the simplification in the requested language — it does not generate the technical definition from scratch. This principle is implemented by TASK-016 (§4.9), as a standalone consumer of `complete()` — not as a provider method — the same pattern `summarize` follows in §2.1a.
- All implementations (`AnthropicProvider`, `OpenAIProvider`) return data structures validated with `pydantic`, independent of the provider.

#### 2.1a Actual implementation (TASK-014)

`app/llm/` exposes a single, provider-agnostic completion primitive instead of one method per use case:

```
LLMProvider.complete(request: CompletionRequest) -> CompletionResponse

CompletionRequest    messages: list[Message]          Message = role ("system" | "user" | "assistant") + content
CompletionResponse   text: str, usage: Usage | None   Usage = input_tokens, output_tokens
```

- `messages` must be non-empty; at most one `system` message is allowed and, if present, it must be first. No tools, structured output/JSON schema, temperature or other generation parameters are exposed.
- `AnthropicProvider` (official `anthropic` SDK, Messages API) sends the system message as the separate `system` parameter and always sends `max_tokens = 1024` (`DEFAULT_MAX_TOKENS`), which that API requires. `OpenAIProvider` (official `openai` SDK, Chat Completions API) passes the messages through unchanged and sends no `max_tokens`. `GeminiProvider` (official `google-genai` SDK, Gemini Developer API, added after TASK-014 to offer a free-tier option) maps `role="assistant"` to Gemini's `role="model"`, sends the system message as `GenerateContentConfig.system_instruction` (split out the same way Anthropic's `system` is), and sends no `max_tokens`-equivalent parameter. All three receive an already-constructed SDK client and wrap the SDK's API errors in `LLMProviderError`, so no vendor exception type reaches the rest of the application.
- Provider selection: `create_llm_provider(settings)` (`app/llm/factory.py`) builds the provider selected by `LLM_PROVIDER` (`anthropic`, `openai` or `gemini`) using `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`, and raises `ConfigurationError` if the key for the selected provider is missing. It is the only code that constructs a real SDK client.
- Pacing and retry (TASK-033): `RetryingProvider` (`app/llm/retrying_provider.py`) wraps any `LLMProvider`; the CLI applies it around the provider built by the factory. It spaces consecutive calls by at least `LLM_MIN_INTERVAL_SECONDS` (default 0 = off; 13 fits the Gemini free tier's 5 requests/minute) and retries up to 3 times when the provider raises an `LLMProviderError` with `retryable=True`, waiting the provider's `retry_after_seconds` hint or else 5/15/45 seconds; after that the error is raised unchanged. Only `GeminiProvider` marks errors retryable (HTTP 429 and 503); the Anthropic and OpenAI SDKs already retry transient errors themselves.
- Daily-quota errors (TASK-037): `GeminiProvider` marks a 429 as `retryable=False` when a `QuotaFailure` violation's `quotaId` contains `PerDay` (e.g. `GenerateRequestsPerDayPerProjectPerModel-FreeTier`), because waiting minutes cannot restore a per-day quota; `RetryingProvider` therefore raises it immediately. Per-minute 429s and 503s stay retryable. The run is not aborted: each remaining call still fails fast.
- `DEFAULT_GEMINI_MODEL` is `gemini-3.5-flash-lite` (TASK-035), a Flash-Lite model on the free tier of the Gemini Developer API -- the whole reason a third provider was added (Anthropic and OpenAI both require a paid API key; Gemini's free tier does not). It replaced `gemini-3.8-flash`, whose free tier allows only 20 requests per day (a per-model quota, observed in TASK-032). Free-tier limits are not published as fixed numbers and change over time; the live values are shown in Google AI Studio.
- `summarize`, `classify` and `explain` are not provider methods: each AI use case is a separate consumer that builds a `CompletionRequest` and interprets `CompletionResponse.text` itself. The first consumer is event summarization (TASK-015, §4.8). There is no `rank()`: ranking is deterministic (§4.2a).
- `CompletionResponse.usage` carries raw token counts for cost monitoring (CLAUDE.md §35); no cost or budget logic is implemented.
- Known limitation (technical debt, not addressed by TASK-015): `CompletionResponse` does not expose the provider's stop/finish reason, and `AnthropicProvider` always sends `max_tokens = 1024`, so a consumer cannot tell whether a response was cut off by the token limit.

---

## 3. Data model (SQLite)

Minimum entities from PRD §20, with the fields necessary to satisfy the verification, ranking and — following PRD addendum §38 — localization requirements.

**Source**
`id, name, type(rss|api|html), url, tier(1-4), categories, reliability_weight, is_active, last_fetched_at`

**Article**
`id, source_id→Source, event_id→Event (nullable), title, url(unique), published_at (nullable), fetched_at, raw_excerpt, normalized_text, content_hash, language, status(pending|processed|discarded|error), duplicate_of→Article (nullable)`

`Article.published_at` is nullable (widened from NOT NULL by TASK-007's
`0002_article_published_at_nullable.sql`): a feed entry with no publication
date must have that absence preserved, not an invented date (CLAUDE.md
§17, §41).

`Article.duplicate_of` was added by TASK-009's `0003_article_duplicate_of.sql`: `NULL` means the article is not a duplicate (not yet evaluated, or kept as canonical); otherwise it references the canonical article, and the duplicate is marked `status = 'discarded'` instead of being deleted, so the link to its source is never lost (CLAUDE.md §18).

`Article.language` is the language **observed** in the original content (any language, automatically detected) — it is purely informational and **does not constrain** the edition's language (PRD §38: "the source's language does not automatically determine the edition's language").

**Event** — *language-neutral*: represents the verified facts, shared across all languages
`id, verification_status(VERIFIED|PARTIALLY_VERIFIED|DEVELOPING|UNVERIFIED), confidence_score(0–10), importance_score(0–10), event_type(standard|research|developer_relevant), future_date(nullable, for What to Watch), created_at`

In the original module mapping (§2) `event_type` is assigned by CLASSIFY. Since TASK-024 it is derived deterministically from the event's assigned category (§4.14); the Developer Impact stage (§4.10) still does not use it.

**EventContent** — *language-specific*: the text generated for an event, per language
`event_id→Event, language, title, summary, structured_content(JSON — textual Developer Impact / Research breakdown)`
Composite primary key `(event_id, language)`. Intended to hold the output of the SUMMARIZE stage, one row per requested language. Allows the same `Event` (facts, verification, score) to be reused for `it` and `en` without re-running Verify/Classify/Rank.

Current status: written by `app/pipeline/generation.py` (TASK-024, §4.14) through `EventContentRepository`, one row per `(event_id, language)`. `structured_content` holds `{"developer_impact": {...}}` -- a `DeveloperImpact` (§4.10) minus its `usage` field -- or `NULL` when the event has no developer impact.

**Category** (static seed, the 10 categories from PRD §9)
`id, slug, canonical_name(English, for internal logs/debugging only)`
The name shown to the reader is **not** on this row: it is resolved from `config/labels.yaml` via `slug` + `Edition.language` (see §5.2). This avoids duplicating localized text in the DB for a small, fixed set of labels.

**EventCategory** (M:N, with a flag)
`event_id, category_id, is_primary`

**Concept** — *language-neutral*: the concept's identity
`id, slug, tags`

**ConceptTranslation** — *language-specific*: curated/generated content per language
`concept_id→Concept, language, technical_definition, simple_explanation, example, why_it_matters, one_liner, last_used_at`
Composite primary key `(concept_id, language)`. The `technical_definition` is curated/validated **per language** (see §5.3) — it is not an automatic translation of the fact-critical field.

**Edition**
`id, edition_number(sequential), date, language, pdf_path, status(draft|published|failed), concept_deep_dive_id→Concept, concept_term_id→Concept, stats(JSON), created_at`

`Edition.language` is the field that drives the entire generation phase. A single day can produce multiple `Edition` rows (one per language), all derived from the same `Event` rows.

Hierarchical relationship: `Source → Article → Event → EventContent (per language) → Edition (per language)`; `Event ↔ Category` via `EventCategory`; `Edition → Concept` (identity) resolved to text via `ConceptTranslation` at render time.

Current status: every table above exists since TASK-004's initial migration. `Source`, `Article`, `Event` (TASK-005, TASK-007, TASK-011), `EventContent` and `EditionRecord` (TASK-024) have models and repositories. No application code reads or writes `event_category`, `concept` or `concept_translation` yet, and `category` is only seeded: TASK-024 resolves an event's category deterministically from its sources' tags rather than through `event_category` (§4.14).

---

## 4. Critical components (design decisions not specified in the PRD)

### 4.1 Cross-source event clustering
No technical guidance in the PRD (§8). Original MVP proposal (**historical, not adopted** — superseded by the TASK-012 implementation in §4.1a): heuristic — title similarity (`rapidfuzz.token_sort_ratio`) + time window (~48h) + overlap of raw keywords/entities. No embeddings/ML in v0.1: cheaper, deterministic, testable.

#### 4.1a Actual implementation (TASK-012)

`app/clustering/article_clusterer.py` implements clustering as a deterministic exact match on a normalized title: HTML-unescape → Unicode NFKC normalize → casefold → replace punctuation with whitespace → collapse whitespace. Two articles are grouped together if and only if their normalized titles are identical and non-empty. No fuzzy matching, no semantic/embedding similarity, no LLM, no source tier/reliability weighting, and no time window are used.

`cluster_articles()` returns in-memory `ArticleCluster` objects only. It does not persist an `Event` row and does not write `Article.event_id`, which stays `NULL` throughout its execution (see §4.7).

### 4.2 Importance score
PRD §10 lists the factors but not their weights. Original proposal (**historical, not adopted** — superseded by the TASK-013 implementation in §4.2a): a hybrid score where the LLM (`rank()`) returns a score with a textual rationale (for audit), corrected by auditable deterministic modifiers (tier of the sources involved, number of independent sources, `event_type`). A purely LLM, unweighted score would be poorly reproducible.

#### 4.2a Actual implementation (TASK-013)

`app/ranking/event_ranker.py` computes `importance_score` as a deterministic, fixed-weight linear combination of the 8 qualitative factors from PRD §10, each supplied by the caller in the range `[0.0, 10.0]`:

```
importance_score =
    technological_impact     * 0.20 +
    economic_impact          * 0.15 +
    user_impact               * 0.15 +
    developer_relevance       * 0.10 +
    scientific_relevance      * 0.10 +
    regulatory_relevance      * 0.10 +
    source_authoritativeness  * 0.10 +
    novelty                   * 0.10
```

Weights sum to 1.00. No LLM call is involved — `LLMProvider.rank()` (§2.1) is not implemented anywhere in the codebase. `rank_events()` sorts events by `importance_score` descending, with `event_id` ascending as a tiebreak.

`regulatory_relevance` is this module's technical identifier for the PRD §10 factor "political/regulatory relevance"; the product requirement is unchanged, only the implementation name differs.

The formula is pure and in-memory: it does not persist an `Event` row and does not itself read `verification_status`, `confidence_score`, `event_type`, `Source.tier`, or `Source.reliability_weight` (see §4.7).

### 4.3 Verification status
Original proposal (**historical proposal, superseded in part** by the TASK-017 implementation in §4.3a): deterministic rule: `VERIFIED` if ≥1 direct Tier 1 source or ≥2 independent Tier 1/2 sources agree; `PARTIALLY_VERIFIED` if there is an authoritative source but details are missing; `DEVELOPING`/`UNVERIFIED` otherwise. The "no Tier 4 as sole confirmation" rule is hard-coded, not delegated to the LLM (CLAUDE.md §13, §15).

#### 4.3a Actual implementation (TASK-017)

`app/verification/event_verifier.py` implements the VERIFY stage as a pure, in-memory, deterministic function:

```
verify_cluster(articles: list[Article], sources: Mapping[int, Source]) -> VerificationResult

VerificationResult   verification_status, confidence_score (0.0–10.0), hedging_constraints: list[str]
```

- **Input is prepared by the caller.** `articles` are the articles of one candidate event (e.g. one `ArticleCluster`, §4.1a); `sources` maps `source_id` to `Source` and must cover every `article.source_id`. The stage does not open a database connection or repository, never calls an LLM and never reads article content: only `Source.tier` and `Source.reliability_weight` are used. `VerificationResult` is immutable and carries no `event_id`, since no `Event` exists yet (§4.7).
- **Reliability gate.** A source counts as evidence only if `reliability_weight >= MIN_RELIABILITY_WEIGHT` (`0.50`). A source below the gate contributes to neither `verification_status` nor `confidence_score`. If no eligible source remains, the result is `UNVERIFIED` with `confidence_score = 0.0`: a normal outcome, not an error.
- **Source counting.** Sources are counted by distinct `source_id`, never by article count: several articles from the same source count once (CLAUDE.md §16).
- **Status rule.** With n1, n2, n3 = the distinct eligible sources of Tier 1, 2 and 3:

  | Condition (evaluated in order) | `verification_status` |
  |---|---|
  | `n1 >= 1` or `n2 >= 2` | `VERIFIED` |
  | `n2 == 1` or `n3 >= 2` | `PARTIALLY_VERIFIED` |
  | otherwise | `UNVERIFIED` |

  Tier 4 sources never contribute to `VERIFIED` or `PARTIALLY_VERIFIED`, whatever their number (PRD §3). `DEVELOPING` remains a valid `VerificationStatus` value but is not produced: whether an event is still unfolding is not derivable from a tier/reliability snapshot, and no temporal proxy (e.g. `published_at` spread) is used.
- **Confidence score.** The formula is an approved architectural decision of TASK-017, not a formula from the PRD (PRD §4 only requires the field). It measures the structural strength of the sourcing evidence and is not a probability that the event is true:

  ```
  source_strength(s)  = TIER_BASE[s.tier] * s.reliability_weight        (eligible sources only)
  best                = max(source_strength(s))
  authoritative_extra = eligible Tier 1/2 sources, excluding the single source achieving `best`
  confidence_score    = min(10.0, best + authoritative_extra * CORROBORATION_BONUS_PER_SOURCE)

  TIER_BASE = {1: 10.0, 2: 7.0, 3: 4.0, 4: 1.0}
  CORROBORATION_BONUS_PER_SOURCE = 1.5
  ```
- **Hedging.** `hedging_constraints` is always `[]`: marker-based hedging detection (§4.4) is not implemented. The field exists so that the output shape already matches what SUMMARIZE (§4.8) and Developer Impact (§4.10) consume.
- **Determinism.** No I/O and no mutation of the inputs; the result is independent of the order of `articles` and of the iteration order of `sources`.
- **Errors.** `ValueError` if `articles` is empty; `KeyError` if some `article.source_id` is not a key of `sources`.
- **Persistence: none** (MODEL B, §4.7). The stage does not create or update an `Event` and does not read or write `Article.event_id`, `Article.status` or `Article.duplicate_of`.
- **Differences from the §4.3 proposal.** The `VERIFIED` source counts match the proposal, but agreement between sources is not checked; `PARTIALLY_VERIFIED` is defined by source counts rather than by "details missing"; a reliability gate is added; `DEVELOPING` is not produced; `confidence_score` has a defined formula.
- **Known limitations.** Independence between sources is approximated by distinct `source_id`: a source that republishes or copies another source's content is not detected (CLAUDE.md §15). Since article content is not read, whether the sources actually agree on the facts is not checked either.

### 4.4 Hedging language
Proposal (**not implemented yet**): dedicated module in `app/verification/` that detects uncertainty markers (reportedly, allegedly, sources say, rumor, leak, expected, may, could — **and the corresponding markers in both supported languages**, see §5.4) and passes the signal as an explicit constraint to the `summarize()` prompt.

Current status (TASK-015, TASK-017, TASK-018): marker-based hedging detection is **not implemented**. VERIFY (§4.3a) returns `hedging_constraints = []` in every case. Event summarization (§4.8) and Developer Impact (§4.10) accept `hedging_constraints` as opaque strings supplied by their caller and insert them verbatim into their prompts; neither detects nor interprets uncertainty markers. How these constraints will be produced has not been decided yet (see §6, item 4).

### 4.5 AI SENZA SBATTI — fact validation
Generating *and* validating a technical explanation every day via LLM is risky (risk of "self-validated" hallucination). Proposal: a knowledge base curated once — the ~15 concepts (PRD §11) have a `technical_definition` written/validated manually **for each supported language** (see §5.3), and the daily pipeline only runs the "Simplification" step (PRD §12) starting from that already-validated text.

Current status (TASK-016): the Simplification-step half of this proposal is implemented — see §4.9. `app/ai/concept_explainer.py` takes an already-validated `technical_definition` as caller-supplied input and only simplifies it; it never generates, validates or corroborates a technical definition itself. The curated-knowledge-base half of this proposal — how and where each concept's `technical_definition` is authored and validated per language, and which module selects the day's concept — is **not implemented** and remains open (see §6, ambiguities #1 and #6).

### 4.6 What to Watch
It is not specified whether items are extracted automatically or curated manually. Proposal: automatic extraction but with a high confidence threshold, only from Tier 1/2 sources, reusing the hedging module (§4.4) to discard speculative language. The `Event.future_date` field is language-neutral; the descriptive text lives in `EventContent` per language.

Current status (TASK-020): `app/editorial/edition.py` consumes `future_date` exactly as proposed here (language-neutral, caller-supplied), but implements only the selection rule -- an event with `future_date is not None` is included in What to Watch, with no other criterion. `verification_status`, `DEVELOPING`, `published_at` and `importance_score` are never used as an admission criterion (`UNVERIFIED` events are not excluded from What to Watch, unlike Top Stories -- see §4). Whether items are extracted automatically or curated manually, and how `future_date` is actually populated for a real `Event`, remains undecided: `EventForEdition.future_date` is caller-supplied and is never computed, parsed or inferred by this module.

### 4.7 Event lifecycle and persistence (current status)

`Event` is a real table in the database schema (`id, verification_status, confidence_score, importance_score, event_type, future_date, created_at`, defined since TASK-004's initial migration), and `EventRepository` (TASK-011) implements `create`/`get_by_id` against it. However, no pipeline code currently calls `EventRepository`: TASK-012 (clustering, §4.1a), TASK-013 (ranking, §4.2a), TASK-015 (summarization, §4.8), TASK-017 (verification, §4.3a) and TASK-018 (Developer Impact, §4.10) are all pure, in-memory functions. None of them persists an `Event` row or writes `Article.event_id`, which stays `NULL` throughout their execution, and neither TASK-015 nor TASK-018 writes `event_content`.

A persisted `Event` row is created only when all values required by the `Event` schema's mandatory columns are available. Code docstrings call this boundary **MODEL B**: until `VERIFY`, `CLASSIFY` and `RANK` have all produced real values, stages work on in-memory data only and never create or update an `Event` or write `Article.event_id`.

For context, the conceptual pipeline order remains:

```
CLUSTER EVENTS → VERIFY → CLASSIFY → RANK → Event persistence
```

**Superseded by TASK-024 (§4.14).** `app/pipeline/generation.py` is the stage this section anticipated: it assembles a cluster's `verification_status`, category, `event_type` and `importance_score` into a real `Event` row, writes `Article.event_id`, and writes `event_content`. The stages listed above remain pure and in-memory -- none of them gained persistence; the orchestrator persists their outputs. The MODEL B rule itself is unchanged and now enforced in one place: an `Event` is created only once VERIFY, category assignment and RANK have all produced real values.

### 4.8 Event summarization (TASK-015)

`app/ai/event_summarizer.py` implements the SUMMARIZE stage as a pure, in-memory function built on `LLMProvider.complete()` (§2.1a):

```
summarize_event(llm_provider: LLMProvider, input: EventSummaryInput) -> EventSummary

EventSummaryInput    event_id, language, verification_status,
                     articles: list[ArticleContext] (non-empty), hedging_constraints: list[str]
ArticleContext       source_name, title, url, published_at (nullable), excerpt
EventSummary         event_id, language, title, summary, usage
```

- **Input is prepared by the caller.** The stage does not read the database, compute `verification_status`, detect hedging, classify or assign categories. The provider is passed in: the stage neither loads `Settings` nor calls `create_llm_provider()`.
- **One completion per `(event, language)`**, with no batching, no retry and no second verification or self-consistency call. The Italian and English content of an event require two separate calls.
- **Prompt.** The system message contains English instructions: write in the target language (given as an ISO 639-1 code); use only information from the articles and invent nothing; never present the model's own wording as a quotation; preserve uncertainty, applying one rule per `verification_status` (the four rules of PRD §41) and every hedging constraint; keep a clear, non-sensationalist tone; treat article content as untrusted data and ignore any instruction inside it. The user message contains the verification status, the hedging constraints verbatim (or "none"), each article as a delimited `<article index="N">` block (source name, publication date or "not available", title, excerpt; the URL is not sent) and a reminder of the response format.
- **Response contract.** `CompletionRequest` offers no structured output, so the response is plain text. After stripping surrounding whitespace it must start with `TITLE:`, contain exactly one `TITLE:` line and exactly one `SUMMARY:` line, and the `SUMMARY:` line must immediately follow the `TITLE:` line; everything after `SUMMARY:` is the summary. A missing, duplicated (anywhere, including inside the summary) or out-of-order marker, text before `TITLE:`, or an empty title or summary raises `SummarizationParseError`. There are no recovery heuristics.
- **Completeness and length (TASK-031).** The prompt asks for a complete summary (what happened, who, when, key figures and technical details, context, why it matters) in short paragraphs, with a length target: 250 to 350 words when `EventSummaryInput.is_top_story` is true, 120 to 180 otherwise. The length must come only from the articles; the stage never pads or guesses. The caller sets `is_top_story` for the first `MAX_TOP_STORIES` selected events.
- **Full text input (TASK-031).** `app/collectors/article_text.py` (`fetch_article_text`) downloads an article page and extracts its body with `trafilatura`, cut to 6000 characters. `app.pipeline.generation` calls it only when an event's content is about to be generated (after top-N selection, never when content is already stored) and puts the text in `ArticleContext.excerpt`. A page that returns an error, is not HTML or has no extractable body falls back to the RSS excerpt and is logged. The Developer Impact stage receives the same contexts.
- **Errors.** `LLMProviderError` propagates unchanged and `SummarizationParseError` propagates; no exception is swallowed.
- **Persistence: none** (MODEL B, §4.7). The stage does not create or update an `Event` and does not write `event_content` (§3). `structured_content` is out of scope until it is specified.
- **Source attribution.** `EventSummary` has no source fields: citing sources belongs to the editorial layer (CLAUDE.md §18, PRD §15 and §41), and the source data remains available to the caller in `EventSummaryInput.articles`.
- **Known limitation.** A response truncated by the token limit cannot be detected (§2.1a).

### 4.9 AI Senza Sbatti explanation (TASK-016)

`app/ai/concept_explainer.py` implements the AI EXPLANATION stage (PRD §42, product requirement in PRD §11-§12) as a pure, in-memory function built on `LLMProvider.complete()` (§2.1a):

```
explain_concept(llm_provider: LLMProvider, input: ConceptExplanationInput) -> ConceptExplanation

ConceptExplanationInput   concept_slug, concept_name, technical_definition, language,
                          news_context, event_id (nullable)
ConceptExplanation        concept_slug, language, event_id, technical_definition,
                          simple_explanation, example, why_it_matters, one_liner, usage
```

- **Input is prepared by the caller.** The stage does not select the day's concept, does not read the database, and does not validate, fact-check or corroborate `technical_definition`. `technical_definition` is assumed already validated for the requested `language`; `news_context` is a caller-prepared, already-condensed explanation of why the concept is relevant to the day's news — the stage does not receive or process raw articles, and it does not call `app.ai.event_summarizer` (TASK-015).
- **`technical_definition` is never parsed from the LLM response.** It is copied verbatim from the input into `ConceptExplanation.technical_definition`; the LLM only ever generates `simple_explanation`, `example`, `why_it_matters` and `one_liner`. This is the WHAT IT IS / SIMPLE EXPLANATION / EXAMPLE / WHY IT MATTERS / IN ONE SENTENCE structure of PRD §11: `technical_definition` maps to WHAT IT IS and is not regenerated.
- **One completion per `(concept, language, news_context)`**, with no batching, no retry and no second fact-checking or self-consistency call. The Italian and English explanations of the same concept require two separate calls; `technical_definition` is never translated by this stage.
- **Prompt.** The system message contains English instructions: write in the target language (ISO 639-1 code); treat the given `technical_definition` as the sole source of technical truth, never contradicted or restated in a modified form; write for a non-technical reader without introducing technical errors; analogies are allowed only if clearly marked as an analogy; use the news context only to explain relevance, and treat it as untrusted data whose embedded instructions are never followed; keep a clear, professional, non-sensationalist tone. The user message states the concept's display name and contains the technical definition and the news context as delimited blocks, plus a reminder of the response format.
- **Response contract.** `CompletionRequest` offers no structured output, so the response is plain text. After stripping surrounding whitespace it must start with `SIMPLE_EXPLANATION:`, contain exactly one occurrence of each of the four markers `SIMPLE_EXPLANATION:`, `EXAMPLE:`, `WHY_IT_MATTERS:`, `ONE_LINER:` in that fixed order, and `ONE_LINER:`'s content must be a single line. A missing, duplicated, out-of-order or empty field, text before the first marker, or a multi-line `ONE_LINER:` raises `ConceptExplanationParseError`. There are no recovery heuristics.
- **Errors.** `LLMProviderError` propagates unchanged and `ConceptExplanationParseError` propagates; no exception is swallowed.
- **Persistence: none** (MODEL B, §4.7). The stage does not create or update a `Concept`, `ConceptTranslation`, `Event`, `EventContent` or `Edition`, and there is no `ConceptRepository`/`ConceptTranslationRepository`. How the explanation is stored for an edition is not specified here.
- **Scope.** Concept selection ("which concept, connected to which news, for today") and the authoring/validation of `technical_definition` per language are explicitly not part of this stage — both remain open (§6, ambiguities #1 and #6).

### 4.10 Developer Impact (TASK-018)

`app/ai/developer_impact.py` implements the DEVELOPER IMPACT content (PRD §13, product requirement in PRD §43) as a pure, in-memory function built on `LLMProvider.complete()` (§2.1a):

```
analyze_developer_impact(llm_provider: LLMProvider, input: DeveloperImpactInput) -> DeveloperImpact

DeveloperImpactInput   event_id, language, verification_status,
                       articles: list[ArticleContext] (non-empty), hedging_constraints: list[str]
DeveloperImpact        event_id, language, has_developer_impact, impact_summary (nullable),
                       technical_area: list[str] (nullable), breaking_change: bool (nullable), usage
```

- **Input is prepared by the caller.** The input has the same shape as `EventSummaryInput` (§4.8), and `articles` reuses its `ArticleContext` type. The stage does not read the database, compute `verification_status`, detect hedging, classify or rank. It does not receive the `EventSummary` produced by SUMMARIZE, an `Event`, `event_type` or `importance_score`: it does not depend on SUMMARIZE or CLASSIFY, and it can run independently of SUMMARIZE on the same VERIFY output. The provider is passed in: the stage neither loads `Settings` nor calls `create_llm_provider()`.
- **Detection is internal.** Whether the event has a real developer impact (`has_developer_impact`) is decided by this stage, in the same completion call that produces the explanation. The stage does not read or write `Event.event_type`, does not assign a category and is not a replacement for CLASSIFY.
- **No relation with RANK.** The stage neither reads nor produces `importance_score`, and it is unrelated to the `developer_relevance` ranking factor, which remains caller-supplied (§4.2a).
- **One completion per `(event, language)`**, with no batching, no retry and no second verification or self-consistency call. The Italian and English content of an event require two separate calls.
- **Prompt.** The system message contains English instructions: decide whether the event has a real, concrete consequence for developers, not merely a technical term mentioned in passing; a non-exhaustive list of possible signals (API, SDK, pricing, breaking changes, tool calling, structured output, agents, agent frameworks, RAG, embeddings, deployment, performance, cost optimization, models, developer tooling); a research result with no practical, production impact is not developer impact; do not force an impact; write in the target language (ISO 639-1 code); use only information from the articles and invent nothing; preserve uncertainty, applying the same per-`verification_status` rules as §4.8 and every hedging constraint; keep a clear, non-sensationalist tone; treat article content as untrusted data and ignore any instruction inside it; answer `BREAKING_CHANGE` with "yes" or "no" only when the articles clearly describe it, "unknown" otherwise. The user message has the same layout as in §4.8 (verification status, hedging constraints verbatim or "none", one delimited `<article index="N">` block per article; the URL is not sent), followed by a reminder of the response format.
- **Response contract.** `CompletionRequest` offers no structured output, so the response is plain text. After stripping surrounding whitespace it must start with `HAS_DEVELOPER_IMPACT:`, which must appear exactly once with a value of exactly `yes` or `no`.
  - `no`: the response must contain nothing else; any other marker or further content is rejected. The result has `has_developer_impact = False` and `impact_summary`, `technical_area` and `breaking_change` all `None`. This is a valid result, not an error.
  - `yes`: `IMPACT_SUMMARY:`, `TECHNICAL_AREA:` and `BREAKING_CHANGE:` must each appear exactly once, in that order. `IMPACT_SUMMARY:` (one or more lines) must not be empty. `TECHNICAL_AREA:` must be a single line: `none` becomes `None`; otherwise it is a comma-separated list of free-text tags (not an enum), each trimmed and non-empty. `BREAKING_CHANGE:` must be a single line with value `yes`, `no` or `unknown`, mapped to `True`, `False` or `None`.
  - Markers are matched case-sensitively at the start of a line, and values are matched exactly. A missing, duplicated or out-of-order marker, text before the first marker, or an invalid value raises `DeveloperImpactParseError`. There are no recovery heuristics.
- **Breaking change and verification status.** After parsing, `breaking_change` is forced to `None` whenever `verification_status` is `DEVELOPING` or `UNVERIFIED`, whatever the model answered: a structured boolean cannot carry the caution that free text can. This is the only post-parse correction. `has_developer_impact`, `impact_summary` and `technical_area` are not gated by `verification_status`; the caution required by the status is expressed in the text, through the prompt rules.
- **Output invariants.** `DeveloperImpact` validates that `impact_summary`, `technical_area` and `breaking_change` are all `None` when `has_developer_impact` is `False`, and that `impact_summary` is present when it is `True`.
- **Errors.** Invalid input raises `pydantic.ValidationError` when `DeveloperImpactInput` is built (e.g. empty `articles`, unsupported `language`). `LLMProviderError` propagates unchanged and `DeveloperImpactParseError` propagates; no exception is swallowed.
- **Persistence: none.** Implemented in-memory; persistence integration pending (MODEL B, §4.7). The stage does not create or update an `Event` and does not write `event_content`; how a `DeveloperImpact` would be stored in `event_content.structured_content` (§3) is not specified.
- **Limits.** No marker-based hedging detection (§4.4); no `EventContent` persistence; no dependency on CLASSIFY; no editorial integration and no localized `DEVELOPER IMPACT` label (PRD §40). As in §2.1a, a response truncated by the token limit cannot be detected as such: it is rejected only if it breaks the response contract.

### 4.11 PDF rendering (TASK-021)

`app/newspaper/renderer.py` implements the PDF stage (docs/PRD.md §16) as a pure, in-memory function built on ReportLab's `Platypus` layout engine:

```
render_edition(edition: Edition, *, metadata: NewspaperMetadata) -> bytes

NewspaperMetadata   edition_number (>=1), edition_date
```

- **Input is the already-final `Edition`.** The renderer performs no Top Stories/section/What to Watch selection, filtering, grouping or re-sorting: `edition.top_stories`, `edition.sections` (in their already-fixed canonical order) and `edition.what_to_watch` are rendered in exactly the order `app.editorial.edition.assemble_edition` (TASK-020) produced them. `Edition` is never mutated.
- **`NewspaperMetadata` is renderer-owned, not a field of `Edition`.** Edition numbering and the publication date are publication-time concerns, not editorial content; adding them to `Edition` would couple the editorial model (TASK-019/020) to the renderer. `NewspaperMetadata` is a frozen pydantic model defined in `renderer.py` itself (no separate module, per CLAUDE.md §37).
- **Layout.** Single-column A4, ~2cm uniform margins, Times-Roman/Times-Bold Base-14 fonts (page geometry and `ParagraphStyle` definitions live in `app/newspaper/styles.py`, pure data with no editorial logic). Page 1 holds the masthead (`AI DAILY`, the edition date and edition number) and Top Stories, followed by one explicit `PageBreak()`; page 2 onward flows the category sections and What to Watch using `Platypus`'s native pagination (`Paragraph`, `Spacer`, `HRFlowable`, `KeepTogether`) -- no manual page-breaking algorithm. A category section is rendered only when it has at least one entry; `section.label` is used exactly as supplied by `Edition`, never recomputed from the slug.
- **Modern styling pass.** `app/newspaper/styles.py` pairs Times-Roman/Times-Bold (serif: masthead title, story titles, body copy) with Helvetica/Helvetica-Bold (sans: section-heading bands, the masthead date line, citations, footer) -- both Base-14, no font embedding. A small palette (`ACCENT_COLOR` navy, `ACCENT_TINT` a light tint of it, `MUTED_COLOR` gray) is applied via `ParagraphStyle.backColor`/`borderColor`, not `HRFlowable` rules: the masthead title and every section heading (Top Stories, the nine categories, What to Watch) render as a full-width colored band (`backColor` paints behind the whole available line width, not just the text -- verified empirically, no `Table` needed); AI SENZA SBATTI/Developer Impact sub-blocks render as one rounded, tinted callout `Paragraph` per sub-block (`_build_callout` in `renderer.py`, joining every field with `<br/>` into a single styled `Paragraph`) instead of indented italic text. Deliberately not `reportlab.platypus.Table` for either the bands or the callout boxes: a `Table` row that does not fit in the remaining page space does not reliably split across pages and can raise `LayoutError`, whereas a styled `Paragraph` keeps ReportLab's native line-level splitting (verified: a callout with ~100 lines of content splits cleanly across pages where the equivalent `Table` raised `LayoutError`). `ParagraphStyle.borderPadding` is not counted by ReportLab's own `Paragraph.wrap()` when it reports the flowable's height to the frame (verified against ReportLab's source): every banded/boxed style therefore sets `spaceBefore`/`spaceAfter` comfortably larger than its `borderPadding`, or the background/border bleeds into the neighboring flowable. Body copy (`BODY_TEXT`, `STORY_TITLE`) stays plain black; fonts sizes beyond the pairing above, margins, page breaks and the `KeepTogether` grouping are unchanged, and sub-blocks are still distinguished purely by typography (no new label text, `config/labels.yaml` untouched).
- **AI SENZA SBATTI / Developer Impact.** Rendered from the data already present on `EditorialContent.developer_impact` / `.concept_explanation` (all already-generated fields, nothing invented), distinguished from the story summary purely by typography/indentation/rules -- no new semantic sub-headers were added and `config/labels.yaml` was not modified, since those sub-labels are not yet approved (docs/PRD.md §40 note). A `DeveloperImpact` whose `has_developer_impact` is `False` (a normal "no impact" outcome, docs/PRD.md §43) renders nothing.
- **Masthead-only static strings.** The edition-number label ("Edition No. {n}" / "Edizione n. {n}"), the footer page-number label ("Page {n}" / "Pagina {n}") and the edition-date month names are small, renderer-internal strings, not a new localization structure and not an addition to `config/labels.yaml` (which has no entries for these). Section headings (Top Stories, the nine categories, What to Watch) use the existing `config/labels.yaml` values via the same `app.config.labels.load_labels()`/`Labels.get()` primitive `app.editorial.edition` already uses, memoized the same way.
- **Not rendered.** No `verification_status` badge, label or color is rendered -- the wording already produced by earlier stages carries the required caution. No `Research` section exists, since no upstream model produces one. (Citation/source formatting, formerly listed here as TASK-022's responsibility, is now implemented -- see §4.12.)
- **Error handling.** `NewspaperRenderError` (`app/newspaper/errors.py`) wraps only genuine ReportLab rendering failures raised by `SimpleDocTemplate.build()` (ReportLab's own `LayoutError` and `PDFError`), following the same wrapping pattern as `LLMProviderError` (§2.1a). A bare `except Exception` is deliberately not used, so a programming error in this module's own flowable-building code still propagates and fails tests rather than being silently reclassified as a rendering error.
- **Unicode.** Base-14 Times-Roman/Times-Bold fonts were verified (not merely assumed) to render the full set of Italian accented characters (à, è, é, ì, ò, ù and their uppercase forms) correctly; no bundled Unicode font was needed.
- **Persistence: none.** The function returns `bytes` only -- it never writes to a filesystem path, never opens a database connection and is never given one. Where a generated PDF is written to disk or has its path recorded (`edition.pdf_path`, §3) is not decided by this stage and remains open (§6, ambiguity #8).

### 4.12 Source citations (TASK-022)

`app/newspaper/renderer.py` renders `EditorialContent.articles` (§3, `ArticleContext`, TASK-015) as a per-story citation sub-block, closing the scope boundary §4.11 left open. No new module, package or model was introduced: `ArticleContext`, `EditorialContent` and `Edition` are unchanged.

```
_is_renderable_link(url: str) -> bool
_build_citation_line(article: ArticleContext) -> str
_build_citations_block(articles: tuple[ArticleContext, ...], language: str) -> list[Flowable]
```

- **Placement.** `_build_citations_block` is the last sub-block appended in `_build_story_block`, after the summary and any Developer Impact / AI Senza Sbatti sub-blocks, inside the same `KeepTogether` group -- a story's citations never separate from its own content across a page break.
- **Fields.** Only `source_name`, `published_at` (rendered exactly as supplied, with no date parsing or reformatting, and omitted entirely when `None`) and `url` are shown. `ArticleContext.title` and `.excerpt` are never rendered: a citation is a factual reference, not a repetition of the article's own text or a quotation of the AI-generated summary (CLAUDE.md §18, docs/PRD.md §41).
- **Order and duplicates.** `articles` is rendered in exactly the order already present on `EditorialContent` -- one citation line per article, with no deduplication, reordering or aggregation by publisher or URL.
- **Empty articles.** `_build_citations_block` returns `[]` when `articles` is empty: no heading with nothing under it, mirroring the Developer Impact / AI Senza Sbatti sub-blocks (§4.11).
- **URL handling.** `_is_renderable_link` treats an absolute `http://`/`https://` string as safe to link; anything else (a relative path, another scheme, or malformed text) renders as plain text, never as a link, and never raises. `url` and `source_name` are untrusted, caller-supplied data (CLAUDE.md §10-11): a renderable `url` is wrapped in a ReportLab `<link href="...">` tag whose `href` attribute is escaped with `xml.sax.saxutils.quoteattr` (stdlib), and the visible text of every field is escaped with the module's existing `_escape` helper, so `&`, `"` or `<` in a URL or source name can never break `Paragraph`'s markup parsing or inject new markup.
- **Localization.** The heading uses a new `sources` key added to `config/labels.yaml` (`"Fonti:"` / `"Sources:"`), resolved the same way every other section heading already is (`app.config.labels.load_labels()`/`Labels.get()`, memoized). This key is additional to the 13 top-level section labels approved in docs/PRD.md §40 -- it is a sub-heading, not a top-level section.
- **Styling.** A new `CITATION_TEXT` `ParagraphStyle` (`app/newspaper/styles.py`) is small (8.5pt), plain (non-italic, non-bold, `Times-Roman`), and indented to match `SUB_BLOCK_BODY` -- deliberately distinct from `SUB_BLOCK_BODY` (italic), which is the existing visual signature of AI-generated sub-content (Developer Impact, AI Senza Sbatti), so citations read as a third, factual-reference register, distinguishable from AI-generated text (CLAUDE.md §18).
- **Test impact.** `tests/test_newspaper_renderer.py`'s `test_render_edition_never_renders_source_citations`, which asserted the pre-TASK-022 absence of citation rendering, was replaced by `test_render_edition_renders_source_citations` asserting the current (positive) behavior; a new `test_render_edition_never_renders_article_excerpt` preserves the still-true boundary that `.excerpt` is never reader-facing.
- **Persistence: none.** Pure, in-memory, consistent with every other stage in this module (MODEL B, §4.7).

### 4.13 CLI (TASK-023)

`app/cli/main.py` implements the `ai-daily` command (docs/PRD.md §32) with `typer` (§1.2), exposed via `[project.scripts]` in `pyproject.toml` (`ai-daily = "app.cli.main:app"`).

```
ai-daily collect   load_settings -> get_connection -> run_migrations
                   -> load_sources_config -> sync_sources -> RssCollector.collect_all
ai-daily process   load_settings -> get_connection -> run_migrations
                   -> normalize_pending_articles -> deduplicate_pending_articles
ai-daily generate  stub -- exit code 1, no DB connection opened
ai-daily run       stub -- exit code 1, no DB connection opened
```

- **Thin orchestration layer, not the pipeline orchestrator.** `collect` and `process` call the already-implemented, already-tested batch entry points (`RssCollector.collect_all` TASK-007, `normalize_pending_articles` TASK-008, `deduplicate_pending_articles` TASK-009) directly; no new domain logic was added anywhere outside `app/cli/`. This is not the `ORCHESTRATION`/`app/pipeline/` row of the §2 table: that row remains "not implemented" and refers to the future cluster→verify→classify→rank→`Event` persistence wiring (§4.7), which `app/cli/` does not attempt.
- **`generate`/`run` are deliberate stubs**, not a partial implementation. Both are registered `typer` commands (so `ai-daily --help` already shows the full PRD §32 surface) but exit immediately with a non-zero exit code and a message pointing to TASK-024 ("Full pipeline"); neither opens a database connection, loads `Settings`, nor calls any stage. This boundary exists because the stages they would need -- CLASSIFY, `Event`/`event_content` persistence integration, editorial assembly wired to real data, PDF rendering wired to a persisted `Edition` -- are undecided/unimplemented (§4.7, ambiguities #8-#9 in §6) and are TASK-024's scope, not TASK-023's (CLAUDE.md §2, one task at a time).
- **Bootstrap.** Every command runs through one `@app.callback()` (`main()`) that calls `configure_logging()` (TASK-003) exactly once before the command body executes. `collect`/`process` additionally call `load_settings()` (TASK-002) and open one `sqlite3.Connection` per invocation via `get_connection`/`run_migrations`, closed in a `finally` block.
- **Error handling.** `ConfigurationError`, `sqlite3.Error` and `OSError` -- the anticipated critical/infrastructure failure modes (a missing/invalid `config/sources.yaml`, an unreadable database) -- are caught in `collect`/`process`, reported with a one-line message on stderr, and turned into `typer.Exit(code=1)`. Any other exception is treated as an unanticipated programming error and is left to propagate with its traceback, consistent with CLAUDE.md §32 ("do not hide errors"); no blanket `except Exception` is used. Per-source failures inside `collect` (a single feed down or malformed) are unaffected: they remain `RssCollector`'s existing resilience behavior (TASK-007) and are reported in the command's summary line, not as a command failure.
- **No new CLI options.** Neither command takes flags yet (e.g. no `--language`, no `--sources-file`): TASK-023 FASE 0 deliberately scoped out speculative options, since `generate`/`run` -- the commands that would consume `--language` (§5.1) -- are stubs.
- **Testing.** `tests/test_cli.py` uses `typer.testing.CliRunner` against the real `app` object. Because `collect` and `process` each open their own `sqlite3.Connection` per `CliRunner.invoke()` call, tests use a file-based SQLite database (via `DATABASE_URL`) in a temporary, `monkeypatch.chdir`-isolated working directory with its own `config/sources.yaml`, rather than `sqlite:///:memory:` (which does not persist across separate connections/invocations the way the shared-fixture-connection pattern in `tests/test_rss_collector.py` does). HTTP is mocked with `responses`, already a dev dependency.
- **Persistence.** `collect`/`process` persist through the same repositories their underlying stages already use (`ArticleRepository`, `SourceRepository`); `app/cli/` itself contains no SQL and no new database schema. Since TASK-024 (§4.14) `generate`/`run` additionally persist `Event`, `event_content` and `edition` rows through `app/pipeline/`.

### 4.14 Full pipeline (TASK-024)

`app/pipeline/` is the `ORCHESTRATION` module of §2, and closes the MODEL B boundary described in §4.7: it is the first code that persists an `Event`, writes `Article.event_id` and writes `event_content`. It adds no domain logic to the stages it sequences -- the only logic it owns is what previously had no owner (category assignment, ranking factors, persistence sequencing).

```
ANALYSIS (language-neutral, no LLM, once per article)
    list_clusterable -> cluster_articles -> verify_cluster -> assign_category
    -> assign_event_type -> build_ranking_input -> compute_importance_score
    -> Event persisted -> Article.event_id + status='processed'

GENERATION (once per language, LLM-backed)
    list_by_created_date -> summarize_event + analyze_developer_impact
    -> event_content persisted -> assemble_editorial_content -> assemble_edition
    -> render_edition -> PDF file -> edition.pdf_path
```

- **Stage order.** The order above has no separate FILTER step: its recency requirement is folded into COLLECT and into `list_clusterable` rather than existing as its own stage (TASK-028, §4.15), and CLASSIFY is replaced by deterministic category assignment (below). The split point between the two phases is where docs/PRD.md §38 requires it: everything before `event_content` is language-neutral and is never recomputed per language, so generating a second language reuses the same `Event` rows.
- **Category assignment replaces CLASSIFY (approved TASK-024 decision).** `app/pipeline/categories.py` derives an event's `EditorialCategory` from the `categories` tags already configured for its sources (`config/sources.yaml`), with no LLM call and no new taxonomy: both sides of the mapping already existed. An event reported by several sources is resolved by counting each *distinct* source once (mirroring how VERIFY counts sources, §4.3a), highest count winning, ties broken by the canonical category order. `Event.event_type` is derived from the resulting category rather than from a second, independent heuristic. **Known limitation:** source tags describe the outlet, not the story, so this expresses "which desk would cover this", not "what this is about" -- a real CLASSIFY stage remains future work. The `other` fallback originally contemplated for TASK-024 does not exist: `EditorialCategory`, the `category` seed table and docs/PRD.md §40's approved labels are all a closed set of the same nine slugs, so an event with no mappable tag falls back to `big_tech_business`, the broadest of the nine, rather than introducing an unapproved tenth category and an unapproved reader-facing label.
- **Ranking factors (resolves ambiguity #9).** `app/pipeline/ranking_factors.py` supplies the eight caller-supplied factors `compute_importance_score` (§4.2a) deliberately does not compute. Six are tag-evidence factors scored `7.0` when an evidencing source tag is present and `3.0` when it is not -- two documented constants either side of the 5.0 midpoint, because source tags are weak, outlet-level evidence and do not justify the extremes of the range. `source_authoritativeness = max(TIER_AUTHORITY[tier] * reliability_weight)` over an event's distinct sources -- the authority of the single *most authoritative* source, computed with **no dependency on VERIFY** (`app.verification.event_verifier`) and no reference to `confidence_score`/`verification_status`; using the maximum rather than a sum means adding more (even weaker) corroborating sources never changes this factor. `novelty` compares the most recent parsable `published_at` against the edition date. An article with no publication date contributes nothing: absence stays unknown rather than counting as freshness (CLAUDE.md §17). `event_ranker.py` itself was not modified. `developer_relevance` is derived from source tags, never from the Developer Impact stage, which is language-dependent and explicitly unrelated to that factor (§4.10) -- ranking stays language-neutral (docs/PRD.md §38).
- **Correction (Post-Implementation Review, Finding 1 -- BLOCKER).** An earlier revision computed `source_authoritativeness` as `VerificationResult.confidence_score` directly. This silently violated two already-approved rules: `app.ranking.event_ranker`'s own module docstring ("`verification_status`, `confidence_score`, `event_type` and category play no part in this formula... this module does not receive them at all") and docs/PRD.md §10 ("Importance and verification are separate concerns... verification_status must not be used to artificially inflate or penalize the importance_score"). Since `confidence_score` is itself a deterministic function of an event's source set (§4.3a), two events with identical sources always produced identical `confidence_score` too -- so the coupling was not merely theoretical, it fired on every event. The corrected formula above removes `confidence_score` from `build_ranking_input`'s signature entirely (there is no longer any parameter through which a VERIFY result could reach ranking), and `tests/test_pipeline_ranking_factors.py::test_importance_score_is_independent_of_verification_confidence_score` demonstrates, using the real `verify_cluster`, that two source sets producing different `verification_status`/`confidence_score` (`PARTIALLY_VERIFIED`/`confidence_score=6.3` vs. `VERIFIED`/`confidence_score=7.8`, both from the same strongest source) now yield the identical `importance_score`.
- **Event persistence (resolves ambiguity #8).** One `Event` row per cluster, written only once VERIFY, category assignment and RANK have all produced real values, immediately followed by `ArticleRepository.assign_event`, which attaches the cluster's articles and moves them to `status = 'processed'` in a single transaction. Per-event boundaries only: a whole day's run is deliberately not wrapped in one transaction. An interrupted run can leave an `Event` with no articles, which is inert (no content, skipped by the generation phase); it can never leave an article attached to an event that does not exist. **Correction (Post-Implementation Review, Finding 2 -- MINOR):** the per-cluster loop (`_analyze_pending_articles`) now catches the one exception `assign_event` can raise (`ValueError`, a rowcount mismatch) around each cluster individually, logs it and moves on to the next cluster, instead of letting it escape uncaught -- previously this would have propagated past the CLI's known-clean `_CRITICAL_ERRORS` set and surfaced as a raw traceback, and would have aborted every other cluster in the same run. `sqlite3.Error`/`OSError` are not caught by this handler and still reach the CLI unchanged.
- **`event_content` and `structured_content`.** `EventContent`/`EventContentRepository` (`app/database/`) write one row per `(event_id, language)`. `structured_content`, whose shape §3 left unspecified, is now `{"developer_impact": {...}}` -- a `DeveloperImpact` minus its `usage` field, since token counts are per-call telemetry, not editorial content, and would make a rerun's row differ from the original. `None` means no Developer Impact was produced, which is a normal outcome (docs/PRD.md §43).
- **LLM usage logging (Post-Implementation Review, Finding 4 -- MINOR, corrected).** `CompletionResponse.usage` (input/output token counts, §2.1a) is logged with a structured `logger.info` line per LLM call (`stage`, `event_id`, `language`, token counts) rather than being silently discarded -- it is not written to `event_content` (not editorial content) and no new table or dependency was added, consistent with CLAUDE.md §35 ("monitor LLM consumption") without turning telemetry into a second persistence concern.
- **Rerun policy: no duplicates, no wasted LLM calls, no schema change.** An event's identity is carried by its articles' state, not by a new column: `list_clusterable` selects only `status = 'pending'` articles with a `content_hash`, and `assign_event` moves them out of that pool, so a second run finds nothing to cluster and creates no second `Event`. The generation phase composes the edition from `list_by_created_date`, so a rerun reproduces the same edition rather than an empty one, reusing the stored `event_content` instead of re-calling the LLM (CLAUDE.md §35). `event_content` is upserted on its `(event_id, language)` primary key, and an edition row is looked up by `(date, language)` before being created, so an edition keeps its original `edition_number`. **No migration was required**: every table and constraint this relies on already existed. **Correction (Post-Implementation Review, Finding 3 -- MINOR):** `Event.created_at` -- the only field `list_by_created_date` can key on, since `Event` has no separate "day" column -- is now stamped with `edition_day`'s date combined with the real wall-clock time, not plain `datetime.now()`. Previously, an event analyzed during a `generate_edition()` call whose `edition_date` differed from the real calendar day (a run straddling local midnight, or an explicit backfill date) was created with a `created_at` on the *real* day and then silently excluded from the edition composed for `edition_date`, with no error or warning. Not reachable through the CLI today (`generate`/`run` never pass an explicit `edition_date`, and no `--date` option exists), but a real defect in `generate_edition()`'s own contract; `tests/test_pipeline_generation.py::test_events_created_are_associated_with_the_generation_edition_date` reproduces the scenario (a frozen "now" five days after `edition_date`) and asserts the event is found.
- **No empty edition (TASK-034).** If the edition would contain no event -- there was none (empty database, nothing fresh) or every event failed -- `generate_edition` raises `EmptyEditionError` (carrying the per-event failures) before any rendering: no PDF is written and the edition row is marked `failed` (`EditionRepository.update_status`), unless that row is already `published`, which a rerun never downgrades. The CLI prints the error and exits with code 1, so `run` stops there. This replaces the TASK-024 behavior of publishing an empty edition. A rerun of the same day reuses the `failed` row and its edition number.
- **Error handling.** Per-event failures (`LLMProviderError`, the three parse errors, `ValueError`) are logged, listed in `GenerationResult.failed_events` and skipped, so one bad event never costs the whole edition (CLAUDE.md §34). Genuine infrastructure failures (`sqlite3.Error`, `OSError`) are deliberately not caught and reach the CLI, which reports them as exit code 1. No blanket `except Exception` is used anywhere.
- **`event_type` derivation (Post-Implementation Review, Finding 5 -- MINOR, resolved by documentation).** Verified during the review: `event_type` has no reader anywhere in the codebase besides its own persistence round-trip, and no PRD/ARCHITECTURE text defines how it should be assigned. `app/pipeline/categories.py:assign_event_type()`'s category-derived mapping is kept unchanged, now with this investigation recorded directly in its docstring, rather than introducing a second heuristic or a new taxonomy for a field with no real consumer.
- **PDF output.** `render_edition` (§4.11) is unchanged and still returns bytes; `app/pipeline/generation.py` writes them to `<database directory>/editions/<date>-<language>.pdf`, deriving the location from the already-configured `DATABASE_URL` rather than adding a setting, and records the path on the edition row. Re-running the same day and language deterministically overwrites that file, which is the documented rerun behavior rather than an accident.
- **`EditionRecord`/`EditionRepository`** (`app/database/edition.py`) were added because TASK-024 needs two things with no other source: a real, non-invented sequential `edition_number` for `NewspaperMetadata` (which requires `>= 1`), and somewhere to record `pdf_path`. Named `EditionRecord` to keep it distinct from `app.editorial.edition.Edition`, which is the in-memory composition and has no persistent identity.
- **Deliberately still empty.** `future_date` is always `None`: no deterministic signal identifies an announced future event, and §4.6 leaves this open, so What to Watch stays empty rather than being populated by guesswork. No `ConceptExplanation` is produced: concept selection and the curated technical definitions it consumes remain undecided (§6, ambiguities #1 and #6). `hedging_constraints` stays `[]`, matching what VERIFY returns (§4.4).
- **Event selection before the LLM (TASK-032).** `_select_events` keeps only the `MAX_EDITION_EVENTS = 15` best events of the day (CLAUDE.md §35) before the per-event LLM stage: `importance_score` descending, then verification status (`VERIFIED` before `PARTIALLY_VERIFIED`, `DEVELOPING`, `UNVERIFIED`), then `id`. `UNVERIFIED` events are not excluded, only ranked last on ties. The other events stay persisted without `event_content`. The selection is deterministic, so a rerun or another language of the same day picks the same events and reuses their stored content. An event is eligible only if at least one of its articles has text (TASK-036): feeds that carry only a title (e.g. Hugging Face, Google DeepMind) would otherwise fail `ArticleContext` validation and waste a slot, so such events are excluded before the selection (fetching their text is TASK-031). Articles without text are left out of the LLM context and the citations of an otherwise eligible event. A selected event that fails is not replaced by the next candidate.
- **`MAX_TOP_STORIES = 3`**, from the page-1 layout of docs/PRD.md §17; `assemble_edition` deliberately has no default (approved TASK-020 decision D-008), so the value is fixed by the orchestrator rather than invented inside the editorial layer.

### 4.15 Freshness window (TASK-028)

Implements the recency requirement of the PRD §7 FILTER stage (§2: originally proposed as a dedicated `app/filtering/` module alongside source-tier and keyword heuristics). Only recency is implemented; source-tier and keyword filtering remain future work, and no separate module was created for it (CLAUDE.md §5, §37) -- the two call sites below are small enough to live in the modules that already own the data they filter.

Root cause this addresses: no stage read `published_at` for inclusion/exclusion before TASK-028 -- `app.collectors.rss` persisted every feed entry regardless of age, `app.clustering.article_clusterer` explicitly never reads `published_at` (by design, §4.1a), and `Event.created_at` is stamped with `edition_day`, not derived from its articles' dates (§4.14) -- so a cold-start collection (a feed's entire historical archive, not just "yesterday") flowed unfiltered all the way into an edition. Observed in AI Daily's first real run (2026-09-16): 2310 articles collected in one `collect` invocation, many years old, all reaching the generated PDF.

- **Two enforcement points, not one.** `RssCollector` (`app/collectors/rss.py`) is the ingestion gate: an entry whose `published_at` is older than `lookback_days` before `reference_date` is never persisted as an `Article` at all -- the cheapest possible rejection point, and the one that actually reduces LLM cost (CLAUDE.md §35) by never letting stale content reach clustering. `ArticleRepository.list_clusterable` (`app/database/article_repository.py`) is a safety net applying the same rule again at analysis time, protecting against any article already sitting in the database from before this filter existed (exactly AI Daily's own first-run backlog) and against any future regression at the ingestion gate. Neither point alone would be sufficient: the gate alone leaves pre-existing backlog unprotected forever (articles already `status = 'pending'` are never re-collected, so `get_by_url` would never give the gate a second chance to reject them); the safety net alone would still let stale content be persisted and normalized before being discarded, wasting the collection and normalization work CLAUDE.md §35 asks to avoid.
- **Both are true safety nets against a single window definition, not two independent policies.** `Settings.news_lookback_days` (`app/config/settings.py`, default `DEFAULT_NEWS_LOOKBACK_DAYS = 2`, `.env` → `NEWS_LOOKBACK_DAYS`) is the one configured value both call sites receive from the CLI -- neither module defines its own default lookback that could silently drift from the other.
- **Comparison is by calendar date, not exact instant** (`(reference_date - published_date).days`), mirroring the precision `_novelty` (§4.14) already uses for the same `published_at` field -- deliberately not more precise than existing precedent already accepts. The boundary is inclusive: an article exactly `lookback_days` old is kept, one day older is not.
- **No second "now".** Both `reference_date` (`RssCollector`) and `edition_day` (`generate_edition`, unchanged) are computed as `datetime.now(APP_TIMEZONE).date()` -- the one expression this codebase already used for "today" (§4.14) -- each independently, at its own command's call site (`collect`/`generate`), since `collect` and `generate` are separate CLI invocations with no shared state today and adding one (e.g. a new `--date` threaded between them) was judged an unjustified scope increase for this task. Both `RssCollector.collect_all`/`collect_source` and `ArticleRepository.list_clusterable` take `reference_date`/`lookback_days` as **required** keyword arguments with no default of their own: the CLI is the only place that computes "now", so neither module can silently diverge from it or from its own tests.
- **Absence of `published_at` is never staleness** (CLAUDE.md §17): an entry/article with no usable publication date always passes both filters, at any `lookback_days` including `0`. This is the same principle `_novelty` (§4.14) already applies to the same field.
- **No retroactive cleanup.** Articles and events already persisted before this task (including AI Daily's own first-run backlog) are not touched: an already-`processed` article can never re-enter `list_clusterable` regardless of its age (§4.14's existing rerun guarantee), and no migration reclassifies or deletes existing rows. Re-running `collect`/`generate` today applies the new window only to articles collected/clustered from this point on.
- **No schema change.** `published_at` already existed and was already nullable (TASK-007); the safety net's `WHERE` clause reads it as-is, with no new column and no new index (acceptable at the article volumes observed so far; revisit if `list_clusterable`'s query becomes a measured hot path).

---

## 5. Localization (replaces the previous open ambiguity about language)

Reference: PRD §38.

### 5.1 Language configuration

- The language is **neither global nor hardcoded**: it is a parameter passed explicitly per run/edition.
- CLI (implemented, TASK-024, §4.14): `ai-daily generate --language it` (or `en`); if omitted, `Settings.default_language` is used (`.env` → `DEFAULT_LANGUAGE=it`, read and validated in `app/config/settings.py`). `ai-daily run` takes the same option and passes it through.
- Languages supported in the MVP: `it`, `en` — defined as a constant in code (`SUPPORTED_LANGUAGES = ("it", "en")` in `app/config/settings.py`); no dedicated configuration file is needed just for this (CLAUDE.md §5/§37: avoid unnecessary structures for a two-item list).
- To produce both editions for the same day, generation is invoked twice (once per language), reusing the same already-analyzed `Event` rows: **`ai-daily run` operates on one language per invocation**; producing both languages is a choice made by the external orchestration (e.g. a GitHub Actions workflow with two steps), not by the CLI itself. This decision was made for simplicity and to isolate failures per language; it is reversible (see ambiguity §6).

### 5.2 Section labels

- File `config/labels.yaml`, structured with two top-level keys (`it`, `en`), containing all the fixed strings shown in the PDF: section names (`TOP STORIES`, `AI SENZA SBATTI`, `TERMINE DEL GIORNO`, `WHAT TO WATCH`, the 10 category names, `Sources:`, footer text, etc.).
- The 13 top-level section names (internal key + `it`/`en` values) are approved and recorded in `PRD.md` §40 — that table is the source of truth for these `labels.yaml` entries.
- Loaded with the same `PyYAML` already used for `sources.yaml` — no new dependency.
- Loading, validation and the `Labels.get(key, language)` lookup primitive live in `app/config/labels.py` (TASK-002); resolving labels during editorial assembly will build on it in `app/editorial/`, which is not implemented yet. A dedicated `app/i18n/` package is not created just for this: it is a small responsibility that does not justify a new structure per CLAUDE.md §37.
- Adding a future language = adding a key to `labels.yaml`, not modifying the pipeline.

### 5.3 Curated content (Concept)

`ConceptTranslation.technical_definition` is **written/validated separately for each supported language**, not automatically translated by an LLM. Rationale: it is the field most critical to technical accuracy (PRD §12, CLAUDE.md §21); an automatic translation would reintroduce the risk of error precisely in the section designed to be pedagogically correct. Cost of this choice: ~15 concepts × 2 languages to curate instead of 15 — acceptable at this stage, to be confirmed (see ambiguity §6).

### 5.4 Components affected by localization

| Component | Impact |
|---|---|
| `Edition` (DB) | new `language` field, required |
| `EventContent` (DB, new entity) | text generated per event, one row per language |
| `ConceptTranslation` (DB, new entity) | curated/generated content per concept, one row per language |
| `Category` (DB) | stays slug-only; the displayed name is resolved from `labels.yaml` |
| Event summarization (`app/ai/event_summarizer.py`, TASK-015; originally proposed as `LLMProvider.summarize`) | receives `language` as input; the prompt instructions are in English and request output in the target language (§4.8) |
| AI SENZA SBATTI explanation (`app/ai/concept_explainer.py`, TASK-016; originally proposed as `LLMProvider.explain`) | receives `language`, simplifies a `technical_definition` already in the target language (§4.9) |
| Developer Impact (`app/ai/developer_impact.py`, TASK-018) | receives `language`; one generation per `(event, language)`, with English prompt instructions requesting output in the target language (§4.10) |
| Classification (not implemented) and ranking (`app/ranking/`, TASK-013); originally proposed as `LLMProvider.classify` / `LLMProvider.rank` | **not impacted** — remain language-neutral |
| `app/verification/` (VERIFY implemented by TASK-017, §4.3a; hedging-language detection not implemented) | VERIFY itself is **not impacted** (language-neutral); the uncertainty-detection patterns of the future hedging detection must be defined for both languages |
| `app/editorial/` | Top Stories/What to Watch selection reads `EventContent` in the edition's language; resolves labels from `config/labels.yaml` |
| `app/newspaper/` (PDF) | templates and typography must handle text in both languages (variable string length, potential text direction if non-Latin languages are added in the future) |
| CLI (`app/cli/`, TASK-023/TASK-024, §4.13, §4.14) | `collect`/`process` are language-neutral (unaffected); `generate`/`run` take `--language`, defaulting to `Settings.default_language`, and produce one language per invocation |
| `config/labels.yaml` (new file) | section labels for `it`/`en` |
| `.env.example` | new `DEFAULT_LANGUAGE` variable |
| Collectors, Normalize, Filter, Dedup, Cluster, Verify, Classify, Rank | **not impacted** — remain upstream of the language split |

---

## 6. Remaining ambiguities

1. **Curation vs. translation of concepts (§5.3)** — I assumed separate manual curation of `technical_definition` for `it`/`en`. If you prefer LLM-assisted translation with subsequent human review (faster to scale, less fine-grained control), this must be decided explicitly: it changes the authoring process, not the data schema. Still open after TASK-016 (§4.9), which only consumes an already-validated `technical_definition` supplied by its caller and does not implement curation, translation or storage of it.
2. **Behavior when a concept's translation is missing for the requested language** — I propose an explicit failure of the generation for that language (consistent with CLAUDE.md §34: "critical component → fail explicitly"), rather than silently skipping the AI SENZA SBATTI section. To be confirmed. Still open after TASK-016 — the stage has no way to detect a missing translation itself, since it never reads `ConceptTranslation`; this remains the responsibility of whichever future stage prepares `ConceptExplanationInput`.
3. **Multi-language generation in a single CLI invocation vs. separate invocations (§5.1)** — I chose "one language per invocation" for simplicity and failure isolation. If you prefer `ai-daily run` to generate all configured languages in a single command, it is a contained change but must be decided now because it affects the CLI's signature.
4. **Hedging-language detection in English and Italian (§4.4/§5.4)** — the PRD only lists markers in English; the Italian equivalents ("secondo alcune fonti", "si vocifera", "potrebbe", "sarebbe atteso", etc.) must be defined before hedging-language detection is implemented. Still open after TASK-015 and TASK-018, which only consume hedging constraints supplied by their caller (§4.8, §4.10), and after TASK-017, whose verification stage returns no hedging constraints (§4.3a, §4.4).
5. **Historical persistence on GitHub Actions** (an ambiguity already raised in the general architectural analysis, not specific to language) — runners are ephemeral; the PRD asks for historical preservation (§1.10) but does not indicate where `data/ai_daily.db` and the PDFs persist between runs. Not blocking for the MVP (local execution via CLI), but must be resolved before v0.2 (automation).
6. **Concept selection (PRD §11, §42)** — which module selects the concept connected to the day's news, and how it prepares the `ConceptExplanationInput.news_context` it hands to TASK-016 (§4.9), is not yet decided. TASK-016 explicitly receives the selected concept, its already-validated technical definition and its news context as caller-supplied input and does not implement selection itself; this is deferred to a future task.
7. **`DEVELOPING` status (PRD §4)** — the verification stage (§4.3a) never produces `DEVELOPING`: whether an event is still unfolding is not derivable from source tier/reliability, and no signal for it has been decided. Still open after TASK-017.
8. **Persistence integration of analysis and generation results (§4.7)** — **resolved by TASK-024 (§4.14)**: `app/pipeline/generation.py` persists the `Event`, writes `Article.event_id`, writes `event_content` (with `structured_content` now specified as `{"developer_impact": {...}}`), writes the PDF to `<database directory>/editions/<date>-<language>.pdf` and records it on an `edition` row's `pdf_path`. The in-memory `Edition`/`EditionSection` composition is still not persisted as such -- only the publication record is.
9. **`category`/`importance_score`/`future_date` sourcing for editorial assembly (§2, §4.6)** — **resolved for `category` and `importance_score` by TASK-024 (§4.14)**: `app/pipeline/categories.py` assigns the category deterministically from source tags and `app/pipeline/ranking_factors.py` supplies RANK's eight factors, both without an LLM. **`future_date` remains open**: no deterministic signal identifies an announced future event, so it stays `None` and What to Watch stays empty rather than being populated by guesswork (§4.6).

---

## 7. MVP implementation plan (increments)

Not substantively changed by the language decision, except Phase 5 (Summarize/AI Senza Sbatti) and Phase 6/7 (Editorial/PDF), which now explicitly include the language parameter. **Historical plan, kept for reference**: implementation has proceeded task by task (TASK-001 → TASK-021) rather than phase by phase, and the authoritative roadmap and task status are in [../TODO.md](../TODO.md). Some phase descriptions no longer match the implemented decisions (near-duplicate detection and clustering into `Event` in Phase 2, hedging detection in Phase 3, the provider interface and LLM-assisted ranking in Phase 4, `EventContent` persistence in Phase 5, `Edition` composition without DB persistence in Phase 6, PDF generation without persistence or citation formatting in Phase 7): see §2.1a, §4.1a, §4.2a, §4.3a, §4.6, §4.7, §4.8 and §4.11.

| Phase | Content | Exit criteria |
|---|---|---|
| 0 — Bootstrap | Folder scaffold, `pyproject.toml`, `.env.example`, `sources.yaml`, `config/labels.yaml` (it/en), DB schema, logging, CLI stub, CI | `ai-daily --help` works; lint/type/test pass |
| 1 — Collect & Normalize | RSS collector, normalization, `Source`/`Article` persistence | `ai-daily collect` populates real articles |
| 2 — Filter, Dedup, Cluster | Heuristic filter, near-dup, clustering into `Event` | duplicates removed on a known test set |
| 3 — Verification | `verification_status`/`confidence_score`, hedging (it/en) | table-driven tests on the rules |
| 4 — LLMProvider + Classify + Rank | Abstract interface, Anthropic/OpenAI providers, classify, rank | pipeline tested with a mocked provider |
| 5 — Summarize + AI Senza Sbatti | `EventContent` per language; `ConceptTranslation` curated per language + simplification | generated summaries respect hedging, in the requested language |
| 6 — Editorial Assembly | Top Stories, sections, What to Watch, `Edition` (with `language`), label resolution | coherent edition in the DB for a given language |
| 7 — PDF | ReportLab layout for both languages | readable PDF generated from real data |
| 8 — End-to-end | Complete `ai-daily run`, e2e tests with deterministic fixtures | PRD §35 DoD checklist satisfied (except automation) |
| 9 (v0.2, post-MVP) | GitHub Actions + historical persistence | out of MVP scope |

---

## 8. Repository Language Policy (technical implications)

Reference: CLAUDE.md §43, PRD.md §39.

This project draws a hard line between two independent language concerns:

1. **Repository / development language — always English.** Source code, identifiers, database schema (table/column names), enum values (`VERIFIED`, `PARTIALLY_VERIFIED`, `DEVELOPING`, `UNVERIFIED`), category slugs, concept slugs, CLI commands/help text, logs, error messages, comments, docstrings, and all project documentation (this file, `PRD.md`, `CLAUDE.md`, `README.md`, `TODO.md`) are English-only, regardless of `Edition.language`.

2. **Editorial output language — configurable per edition, `it` or `en`.** Only the content actually shown to the newspaper's reader is subject to `Edition.language`: `EventContent` rows, `ConceptTranslation` rows, and the *values* (not the keys) in `config/labels.yaml`.

Concrete implications for the data model and configuration already proposed in §3 and §5.2:

* `config/labels.yaml` **keys** (e.g. `top_stories`, `ai_senza_sbatti`, `termine_del_giorno` — full approved list in `PRD.md` §40) are English identifiers — repository language. Their **values** per language (`it`/`en`) are editorial content.
* `Category.slug` and `Concept.slug` are English identifiers and are never localized.
* `verification_status` / `event_type` values are internal English enums. If ever surfaced to the reader in the PDF (e.g. a "verified" badge), the reader-facing label is resolved through `config/labels.yaml`, not the raw enum value.
* Log lines and error messages produced by the pipeline are English even when the edition being generated is `it` — this was already the case in PRD §24's log example and requires no change.

No change to the module layout, data model, or MVP plan in §1–§7 was required by this policy: the architecture already separated English structural identifiers from generated, localized editorial text before this policy was formalized (§3, §5). This section makes that separation an explicit, binding rule rather than an implicit design choice.

Translation status: this file has been translated to English under the Repository Language Policy (2026-09-11), preserving structure, meaning, decisions and scope unchanged.

---

## 9. Application Timezone (decision — 2026-09-12)

**Application timezone: `Europe/Rome`.**

This is the timezone AI Daily uses whenever a wall-clock time or date is meaningful to the application — for example the daily schedule referenced in PRD §27 ("07:00"), log timestamps (PRD §24), and the date assigned to an `Edition` (PRD §20). It is a single, fixed timezone for the MVP; no per-user or per-locale timezone handling is planned.

Current status: the timezone is a fixed constant (`APP_TIMEZONE` / `APP_TIMEZONE_NAME` in `app/config/settings.py`, TASK-002), not an environment variable, and log timestamps are rendered in it by `app/logging_config.py` (TASK-003). Scheduling is not implemented yet; it belongs to the later GitHub Actions automation task.

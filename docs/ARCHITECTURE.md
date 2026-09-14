# ARCHITECTURE.md — AI Daily

Technical architecture proposal for the MVP, derived from [PRD.md](./PRD.md) and constrained by the rules in [../CLAUDE.md](../CLAUDE.md).

Status: **proposal, no code implemented yet.**

---

## 1. Stack and dependencies

### 1.1 Explicitly required by the PRD

| Area | Choice | Note |
|---|---|---|
| Language | Python 3.11+ | typed, consistent with CLAUDE.md §8 |
| PDF | `reportlab` | explicit (PRD §16) |
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
| Content extraction from pages without RSS | `beautifulsoup4` + `lxml` | necessary for the HTML scraping envisaged by PRD §6 | none |
| Title deduplication/clustering | `rapidfuzz` | lightweight fuzzy matching, no heavy ML dependency | stdlib `difflib`, slower and less accurate on short text |
| CLI | `typer` (proposed) | typed signature consistent with CLAUDE.md §8; `argparse` stdlib is the zero-dependency alternative | `argparse` |
| Typed data validation (config, LLM output) | `pydantic` | validates `sources.yaml`, `config/labels.yaml` and the LLM's JSON responses | dataclasses + manual validation |
| Lint | `ruff` | lint + formatting in a single tool | `flake8`+`black`+`isort` (more dependencies) |
| Type checking | `mypy` | explicitly required as a gate (PRD §35) | — |
| Tests | `pytest`, `pytest-cov` | PRD §25 | stdlib `unittest`, less ergonomic |
| HTTP mocking in tests | `responses` or `pytest-httpx` | avoids real network calls in collector tests/CI | — |

**Not introduced**: ORM (SQLAlchemy), Alembic, code/message bus, cache, microservices — consistent with CLAUDE.md §5 (avoid over-engineering). Data access via stdlib `sqlite3` + typed repositories; migrations as numbered SQL scripts applied at startup.

**Package manager**: `pyproject.toml` is required by the PRD (§21) but the tool is not specified. Proposal: `uv`. Reversible decision, to be confirmed.

---

## 2. Module architecture

Follows the folder structure from PRD §21. Pipeline → module mapping:

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

Key architectural point (detailed in §5): the pipeline splits into an **analysis phase** (Collect → Rank), entirely **language-independent**, and a **generation phase** (Summarize → PDF), **language-dependent**. This split is not visible in the folder structure but in the behavior of the individual modules.

### 2.1 LLMProvider interface

```
class LLMProvider:
    def summarize(event, articles, verification_status, language) -> Summary
    def classify(event) -> ClassificationResult
    def explain(technical_definition, language) -> ConceptExplanation
    def rank(event, context) -> RankingSignal
```

Notes:

- `classify` and `rank` **do not receive `language`**: they produce structural data (category, score, internal/audit rationale) reusable for any output language. This is consistent with CLAUDE.md §35 (cost control): do not re-run classification/ranking per language.
- `summarize` and `explain` receive `language` and produce text intended for the reader.
- `explain` receives an already-validated `technical_definition` (see §5.3) and only produces the simplification in the requested language — it does not generate the technical definition from scratch.
- All implementations (`AnthropicProvider`, `OpenAIProvider`) return data structures validated with `pydantic`, independent of the provider.

---

## 3. Data model (SQLite)

Minimum entities from PRD §20, with the fields necessary to satisfy the verification, ranking and — following PRD addendum §38 — localization requirements.

**Source**
`id, name, type(rss|api|html), url, tier(1-4), categories, reliability_weight, is_active, last_fetched_at`

**Article**
`id, source_id→Source, event_id→Event (nullable), title, url(unique), published_at (nullable), fetched_at, raw_excerpt, normalized_text, content_hash, language, status(pending|processed|discarded|error)`

`Article.published_at` is nullable (widened from NOT NULL by TASK-007's
`0002_article_published_at_nullable.sql`): a feed entry with no publication
date must have that absence preserved, not an invented date (CLAUDE.md
§17, §41).

`Article.language` is the language **observed** in the original content (any language, automatically detected) — it is purely informational and **does not constrain** the edition's language (PRD §38: "the source's language does not automatically determine the edition's language").

**Event** — *language-neutral*: represents the verified facts, shared across all languages
`id, verification_status(VERIFIED|PARTIALLY_VERIFIED|DEVELOPING|UNVERIFIED), confidence_score(0–10), importance_score(0–10), event_type(standard|research|developer_relevant), future_date(nullable, for What to Watch), created_at`

**EventContent** — *language-specific*: the text generated for an event, per language
`event_id→Event, language, title, summary, structured_content(JSON — textual Developer Impact / Research breakdown)`
Composite primary key `(event_id, language)`. Generated by the SUMMARIZE stage, one row per requested language. Allows the same `Event` (facts, verification, score) to be reused for `it` and `en` without re-running Verify/Classify/Rank.

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

---

## 4. Critical components (design decisions not specified in the PRD)

### 4.1 Cross-source event clustering
No technical guidance in the PRD (§8). MVP proposal: heuristic — title similarity (`rapidfuzz.token_sort_ratio`) + time window (~48h) + overlap of raw keywords/entities. No embeddings/ML in v0.1: cheaper, deterministic, testable. Should be validated against real data before being trusted in production.

### 4.2 Importance score
PRD §10 lists the factors but not their weights. Proposal: hybrid score — the LLM (`rank()`) returns a score with a textual rationale (for audit), corrected by auditable deterministic modifiers (tier of the sources involved, number of independent sources, `event_type`). A purely LLM, unweighted score would be poorly reproducible.

### 4.3 Verification status
Deterministic rule: `VERIFIED` if ≥1 direct Tier 1 source or ≥2 independent Tier 1/2 sources agree; `PARTIALLY_VERIFIED` if there is an authoritative source but details are missing; `DEVELOPING`/`UNVERIFIED` otherwise. The "no Tier 4 as sole confirmation" rule is hard-coded, not delegated to the LLM (CLAUDE.md §13, §15).

### 4.4 Hedging language
Dedicated module in `app/verification/` that detects uncertainty markers (reportedly, allegedly, sources say, rumor, leak, expected, may, could — **and the corresponding markers in both supported languages**, see §5.4) and passes the signal as an explicit constraint to the `summarize()` prompt.

### 4.5 AI SENZA SBATTI — fact validation
Generating *and* validating a technical explanation every day via LLM is risky (risk of "self-validated" hallucination). Proposal: a knowledge base curated once — the ~15 concepts (PRD §11) have a `technical_definition` written/validated manually **for each supported language** (see §5.3), and the daily pipeline only runs the "Simplification" step (PRD §12) starting from that already-validated text.

### 4.6 What to Watch
It is not specified whether items are extracted automatically or curated manually. Proposal: automatic extraction but with a high confidence threshold, only from Tier 1/2 sources, reusing the hedging module (§4.4) to discard speculative language. The `Event.future_date` field is language-neutral; the descriptive text lives in `EventContent` per language.

---

## 5. Localization (replaces the previous open ambiguity about language)

Reference: PRD §38.

### 5.1 Language configuration

- The language is **neither global nor hardcoded**: it is a parameter passed explicitly per run/edition.
- CLI: `ai-daily generate --language it` (or `en`); if omitted, a configured default is used (`.env` → `DEFAULT_LANGUAGE=it`).
- Languages supported in the MVP: `it`, `en` — defined as a constant in code (e.g. `SUPPORTED_LANGUAGES = ["it", "en"]`); no dedicated configuration file is needed just for this (CLAUDE.md §5/§37: avoid unnecessary structures for a two-item list).
- To produce both editions for the same day, generation is invoked twice (once per language), reusing the same already-analyzed `Event` rows: **`ai-daily run` operates on one language per invocation**; producing both languages is a choice made by the external orchestration (e.g. a GitHub Actions workflow with two steps), not by the CLI itself. This decision was made for simplicity and to isolate failures per language; it is reversible (see ambiguity §6).

### 5.2 Section labels

- File `config/labels.yaml`, structured with two top-level keys (`it`, `en`), containing all the fixed strings shown in the PDF: section names (`TOP STORIES`, `AI SENZA SBATTI`, `TERMINE DEL GIORNO`, `WHAT TO WATCH`, the 10 category names, `Sources:`, footer text, etc.).
- The 13 top-level section names (internal key + `it`/`en` values) are approved and recorded in `PRD.md` §40 — that table is the source of truth for these `labels.yaml` entries.
- Loaded with the same `PyYAML` already used for `sources.yaml` — no new dependency.
- Lookup function in `app/editorial/` (a dedicated `app/i18n/` package is not created just for this: it is a small responsibility that does not justify a new structure per CLAUDE.md §37).
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
| `LLMProvider.summarize` | receives `language`, localized prompt |
| `LLMProvider.explain` | receives `language`, simplifies a `technical_definition` already in the target language |
| `LLMProvider.classify`, `LLMProvider.rank` | **not impacted** — remain language-neutral |
| `app/verification/` (hedging language) | uncertainty-detection patterns must be defined for both languages |
| `app/editorial/` | Top Stories/What to Watch selection reads `EventContent` in the edition's language; resolves labels from `config/labels.yaml` |
| `app/newspaper/` (PDF) | templates and typography must handle text in both languages (variable string length, potential text direction if non-Latin languages are added in the future) |
| CLI (`app/pipeline/`) | new `--language` parameter on `generate`/`run` |
| `config/labels.yaml` (new file) | section labels for `it`/`en` |
| `.env.example` | new `DEFAULT_LANGUAGE` variable |
| Collectors, Normalize, Filter, Dedup, Cluster, Verify, Classify, Rank | **not impacted** — remain upstream of the language split |

---

## 6. Remaining ambiguities

1. **Curation vs. translation of concepts (§5.3)** — I assumed separate manual curation of `technical_definition` for `it`/`en`. If you prefer LLM-assisted translation with subsequent human review (faster to scale, less fine-grained control), this must be decided explicitly: it changes the authoring process, not the data schema.
2. **Behavior when a concept's translation is missing for the requested language** — I propose an explicit failure of the generation for that language (consistent with CLAUDE.md §34: "critical component → fail explicitly"), rather than silently skipping the AI SENZA SBATTI section. To be confirmed.
3. **Multi-language generation in a single CLI invocation vs. separate invocations (§5.1)** — I chose "one language per invocation" for simplicity and failure isolation. If you prefer `ai-daily run` to generate all configured languages in a single command, it is a contained change but must be decided now because it affects the CLI's signature.
4. **Hedging-language detection in English and Italian (§4.4/§5.4)** — the PRD only lists markers in English; the Italian equivalents ("secondo alcune fonti", "si vocifera", "potrebbe", "sarebbe atteso", etc.) must be defined before implementing the verification module.
5. **Historical persistence on GitHub Actions** (an ambiguity already raised in the general architectural analysis, not specific to language) — runners are ephemeral; the PRD asks for historical preservation (§1.10) but does not indicate where `data/ai_daily.db` and the PDFs persist between runs. Not blocking for the MVP (local execution via CLI), but must be resolved before v0.2 (automation).

---

## 7. MVP implementation plan (increments)

Not substantively changed by the language decision, except Phase 5 (Summarize/AI Senza Sbatti) and Phase 6/7 (Editorial/PDF), which now explicitly include the language parameter. Full list kept for reference; **no phase has been started yet**.

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

This section only records the decision. No timezone logic, scheduling, or runtime configuration has been implemented yet — that belongs to the tasks that actually need it (e.g. the Logging task, and the later GitHub Actions automation task).

# AI Daily

Automated AI News Intelligence & Learning Platform — a system that collects, verifies, analyzes and summarizes news about artificial intelligence and generates a digital newspaper in PDF format.

**Status: in development.** The pipeline now runs end to end: `ai-daily run` collects articles, processes them, clusters them into verified and ranked events, generates their content and produces a newspaper PDF (see [Usage](#usage)). Some stages of the product vision remain unimplemented — see [Architecture](#architecture). This README documents what actually exists today; see [TODO.md](TODO.md) for the roadmap and task status.

## Documentation

- [docs/PRD.md](docs/PRD.md) — product requirements
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — technical architecture
- [CLAUDE.md](CLAUDE.md) — permanent development rules
- [TODO.md](TODO.md) — roadmap and task status

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) as the package/dependency manager

## Installation

```bash
uv sync
```

This creates a local virtual environment and installs the runtime dependencies and the development tools (`pytest`, `ruff`, `mypy`) declared in `pyproject.toml`.

## Configuration

Copy the example environment file and fill in the values you need:

```bash
cp .env.example .env
```

See `.env.example` for the currently defined variables (LLM provider selection and API keys, database location, default edition language, the collection freshness window, Telegram credentials for a later phase). `.env` must never be committed.

`LLM_PROVIDER` selects `anthropic`, `openai` or `gemini`, with the matching `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` set. Gemini (Google AI Studio) has a free tier that needs no billing, unlike Anthropic and OpenAI. `LLM_MIN_INTERVAL_SECONDS` (default `0`) sets a minimum pause between LLM calls; use `13` on the Gemini free tier (5 requests per minute). Transient 429/503 errors from Gemini are retried automatically (up to 3 times).

## Development commands

```bash
uv run pytest        # run the test suite
uv run ruff check .  # lint
uv run mypy          # type checking (the app package, as configured in pyproject.toml)
```

## Usage

After `uv sync`, the `ai-daily` command is available (via `uv run ai-daily ...` or directly once the virtual environment is activated):

```bash
uv run ai-daily --help
```

Four commands are defined, per docs/PRD.md §32:

- `ai-daily collect` — syncs `config/sources.yaml` into the database and fetches every active RSS source (TASK-007), persisting new articles no older than `NEWS_LOOKBACK_DAYS` (TASK-028; an article with no publication date is always kept).
- `ai-daily process` — normalizes (TASK-008) and deduplicates (TASK-009) every `pending` article already collected.
- `ai-daily generate [--language it|en]` — turns the articles already collected and processed into one edition: clusters them into events, verifies and ranks them, persists the `Event` and its generated content, assembles the newspaper and writes the PDF. Defaults to `DEFAULT_LANGUAGE`; one invocation produces one language.
- `ai-daily run [--language it|en]` — the full pipeline in one command: `collect`, then `process`, then `generate`. Stops at the first stage that fails.

`generate` and `run` call the configured LLM provider (summarization and Developer Impact), so `LLM_PROVIDER` and the matching API key must be set. The PDF is written next to the database, as `<database directory>/editions/<date>-<language>.pdf` (for the default `DATABASE_URL`, `data/editions/`), and its path is recorded on the edition row.

Re-running `generate` for the same day is safe: articles already attached to an event are not clustered again, already-generated content is reused instead of calling the LLM again, and the edition keeps its number while its PDF is rewritten.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the technical architecture, including the actual implementation of each component built so far.

Implemented so far, wired together by `app/pipeline/` (TASK-024) and driven by the CLI:

- configuration (`.env` settings, `config/sources.yaml`, `config/labels.yaml`) and logging;
- SQLite schema, migrations and repositories for sources, articles, events, generated event content and editions;
- RSS collection, article normalization and deduplication;
- event clustering, deterministic event verification and deterministic importance ranking;
- the LLM provider abstraction (Anthropic, OpenAI, Gemini), in-memory event summarization, AI Senza Sbatti concept explanation and Developer Impact assessment;
- editorial content assembly and newspaper layout composition (Top Stories, category sections, What to Watch);
- PDF rendering (`app/newspaper/`, ReportLab): turns an already-composed `Edition` into a complete newspaper PDF (masthead, Top Stories, category sections, What to Watch, page numbers, per-story source citations);
- pipeline orchestration (`app/pipeline/`, TASK-024): sequences the stages above into one persisted run — `Event`, `Article.event_id`, generated content per language, and the edition's PDF — including deterministic category assignment and ranking factors;
- a CLI (`app/cli/`, the `ai-daily` command, TASK-023/TASK-024) exposing `collect`, `process`, `generate` and `run` (see [Usage](#usage)).

Not implemented yet: filtering, hedging-language detection, a real LLM classifier (categories are currently derived deterministically from each source's configured tags), concept selection and the AI SENZA SBATTI section, What to Watch population, and automation (scheduling, Telegram, archive).

## Language

The repository (code, configuration, docs) is English-only — see `CLAUDE.md` §43 for the full policy. AI Daily's generated editorial content supports Italian (`it`) and English (`en`), selected per edition: event summarization, AI Senza Sbatti concept explanation, Developer Impact assessment and PDF rendering already take the target language as input (`Edition.language` drives section labels, the masthead date and the footer page-number wording), while the other generation stages are not implemented yet.

## License

MIT — see [LICENSE](LICENSE).

## Troubleshooting

- If `uv sync` fails, verify that Python 3.11+ and uv are correctly installed and on your `PATH`.
- A `ConfigurationError` means that a configuration value is missing or invalid — for example an unsupported `DEFAULT_LANGUAGE`, or no API key set for the selected `LLM_PROVIDER`.

# AI Daily

Automated AI News Intelligence & Learning Platform — a system that collects, verifies, analyzes and summarizes news about artificial intelligence and generates a digital newspaper in PDF format.

**Status: in development.** Several pipeline components are implemented as standalone, tested modules (see [Architecture](#architecture)); they are not yet connected into an end-to-end pipeline, and there is no CLI or PDF output yet. This README documents what actually exists today; see [TODO.md](TODO.md) for the roadmap and task status.

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

See `.env.example` for the currently defined variables (LLM provider selection and API keys, database location, default edition language, Telegram credentials for a later phase). `.env` must never be committed.

## Development commands

```bash
uv run pytest        # run the test suite
uv run ruff check .  # lint
uv run mypy          # type checking (the app package, as configured in pyproject.toml)
```

## Usage

Not available yet. The `ai-daily` CLI (`collect` / `process` / `generate` / `run`) is planned in a later task (see TODO.md, Milestone 6) and is not implemented yet. The modules implemented so far are exercised through the test suite.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the technical architecture, including the actual implementation of each component built so far.

Implemented so far, as standalone and tested modules that are not yet connected into a pipeline:

- configuration (`.env` settings, `config/sources.yaml`, `config/labels.yaml`) and logging;
- SQLite schema, migrations and repositories for sources, articles and events;
- RSS collection, article normalization and deduplication;
- event clustering, deterministic event verification and deterministic importance ranking;
- the LLM provider abstraction (Anthropic, OpenAI), in-memory event summarization, AI Senza Sbatti concept explanation and Developer Impact assessment.

Not implemented yet: filtering, hedging-language detection, classification, concept selection, editorial assembly, PDF generation, CLI and automation.

## Language

The repository (code, configuration, docs) is English-only — see `CLAUDE.md` §43 for the full policy. AI Daily's generated editorial content supports Italian (`it`) and English (`en`), selected per edition: event summarization, AI Senza Sbatti concept explanation and Developer Impact assessment already take the target language as input, while the other generation stages are not implemented yet.

## License

MIT — see [LICENSE](LICENSE).

## Troubleshooting

- If `uv sync` fails, verify that Python 3.11+ and uv are correctly installed and on your `PATH`.
- A `ConfigurationError` means that a configuration value is missing or invalid — for example an unsupported `DEFAULT_LANGUAGE`, or no API key set for the selected `LLM_PROVIDER`.

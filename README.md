# AI Daily

Automated AI News Intelligence & Learning Platform — a system that collects, verifies, analyzes and summarizes news about artificial intelligence and generates a digital newspaper in PDF format.

**Status: early bootstrap.** No pipeline stage is implemented yet. This README documents what actually exists today; see [TODO.md](TODO.md) for the roadmap.

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

This creates a local virtual environment and installs the development dependencies (`pytest`, `ruff`, `mypy`) declared in `pyproject.toml`.

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
uv run mypy .         # type checking
```

## Usage

Not available yet. The `ai-daily` CLI (`collect` / `process` / `generate` / `run`) is planned in a later task (see TODO.md, Milestone 6) and is not implemented in this bootstrap.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full technical proposal. At this stage the repository contains only the project bootstrap: package scaffolding, dependency/tooling configuration, and this documentation — no collectors, database, verification, classification, ranking, LLM integration, or PDF generation yet.

## Language

The repository (code, configuration, docs) is English-only — see `CLAUDE.md` §43 for the full policy. AI Daily's generated editorial content will support both Italian (`it`) and English (`en`) per edition once the relevant pipeline stages exist.

## License

MIT — see [LICENSE](LICENSE).

## Troubleshooting

Nothing to troubleshoot yet — no functional code exists. If `uv sync` fails, verify that Python 3.11+ and uv are correctly installed and on your `PATH`.

# TODO.md

## Milestone 1 — Foundation

- [x] TASK-001 — Initialize the Python project
- [x] TASK-002 — Application configuration
- [x] TASK-003 — Logging
- [x] TASK-004 — Initial database model

## Milestone 2 — News Collection

- [x] TASK-005 — Source model
- [x] TASK-006 — sources.yaml
- [x] TASK-007 — RSS collector
- [x] TASK-008 — Article normalization

## Milestone 3 — News Intelligence

- [x] TASK-009 — Deduplication
- [x] TASK-010 — Source reliability
- [x] TASK-011 — Event persistence
- [x] TASK-012 — Cluster events
- [x] TASK-013 — Importance ranking
- [x] TASK-017 — Event verification

## Milestone 4 — AI

- [x] TASK-014 — LLM provider abstraction
- [x] TASK-015 — Summarization
- [x] TASK-016 — AI Senza Sbatti
- [x] TASK-018 — Developer Impact

## Milestone 5 — Newspaper

- [x] TASK-019 — Editorial model
- [x] TASK-020 — Newspaper layout
- [x] TASK-021 — PDF generator
- [x] TASK-022 — Sources and citations

## Milestone 6 — Automation

- [x] TASK-023 — CLI
- [x] TASK-024 — Full pipeline
- [ ] TASK-025 — GitHub Actions
- [x] CodeQL code scanning workflow (no task number; part of the security tooling, not the TASK-025 pipeline run)

## Milestone 7 — Delivery

- [ ] TASK-026 — Telegram
- [ ] TASK-027 — Archive

## Milestone 8 — Pipeline Quality

- [x] TASK-028 — Freshness & Date Window

## Milestone 9 — Review (details in `docs/TASK_LOG.md`)

- [x] TASK-029 — Switch to the free Gemini provider
- [x] TASK-030 — Measure LLM token usage of one edition
- [x] TASK-031 — Longer, richer story content
- [x] TASK-032 — Select candidate events before calling the LLM
- [x] TASK-033 — Rate-limit handling for the LLM provider
- [x] TASK-034 — Do not publish an empty edition
- [x] TASK-035 — Use a Gemini model with a larger free daily quota
- [x] TASK-036 — Events whose articles have no excerpt
- [x] TASK-037 — Fail fast on daily-quota errors
- [x] TASK-038 — Cross-source event clustering
- [x] TASK-039 — AI relevance filter
- [ ] TASK-040 — Ranking: break ties between equal importance scores
- [ ] TASK-041 — Do not repeat Top Stories in the sections
- [ ] TASK-042 — Human-readable source dates in citations
- [x] Fix — CLI tests expect the PDF date in `APP_TIMEZONE` (no task number)

## Milestone 10 — Website (details in `docs/TASK_LOG.md`)

- [x] TASK-043 — Persist the composed edition
- [x] TASK-044 — Web app showing the editions
- [x] TASK-045 — Website design

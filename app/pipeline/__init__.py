"""Pipeline orchestration (TASK-024).

The `ORCHESTRATION` module of docs/ARCHITECTURE.md §2: it sequences the
stages implemented by TASK-007 to TASK-022 into a real, persisted run and
owns nothing else. Domain logic stays in the stage modules
(`app/clustering/`, `app/verification/`, `app/ranking/`, `app/ai/`,
`app/editorial/`, `app/newspaper/`); the only logic added here is what had
no owner before: deterministic category assignment
(`app.pipeline.categories`), deterministic ranking factors
(`app.pipeline.ranking_factors`) and the persistence sequencing in
`app.pipeline.generation`.

`app/cli/` is a thin adapter over this package, not a second orchestrator
(docs/ARCHITECTURE.md §4.13, §4.14).
"""

from app.pipeline.generation import GenerationResult, generate_edition

__all__ = [
    "GenerationResult",
    "generate_edition",
]

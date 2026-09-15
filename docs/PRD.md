AI DAILY

Product Requirements Document — v0.1
(Addendum: §38 Edition Language — 2026-09-11)

Project name: AI Daily
Type: Automated AI News Intelligence & Learning Platform
Version: 0.1
Objective: create an automated digital newspaper dedicated to artificial intelligence.

⸻

1. Project vision

AI Daily must be a genuine digital newspaper about artificial intelligence, generated automatically every day.

The system must:

1. collect news from the web;
2. prioritize official and authoritative sources;
3. verify and cross-check information;
4. remove duplicates and articles covering the same event;
5. classify news items;
6. determine their importance;
7. generate journalistic summaries;
8. explain technical concepts in plain language;
9. produce a PDF with an editorial look and feel;
10. preserve a historical record of the news.

The final result must look like a real newspaper, not a simple automated report.

⸻

2. Fundamental principle

AI Daily must NOT be designed to produce as many news items as possible.

It must produce the most important, reliable and interesting news items.

Priority:

1. Accuracy
2. Reliability
3. Relevance
4. Clarity
5. Completeness
6. Quantity

A news item that has not been sufficiently verified must NOT be presented as a fact.

⸻

3. Sources

The system must distinguish sources by level of reliability.

Tier 1 — Primary sources

Highest priority.

Examples:

* OpenAI
* Anthropic
* Google DeepMind
* Google
* Microsoft
* Meta
* NVIDIA
* Apple
* Amazon
* xAI
* Mistral
* Hugging Face
* companies directly involved in the event
* universities
* government institutions
* official documentation
* scientific papers

Tier 2 — Agencies and authoritative outlets

Examples:

* Reuters
* Associated Press
* BBC
* Financial Times
* The Wall Street Journal
* Bloomberg
* The Guardian

Tier 3 — Specialized tech outlets

Examples:

* TechCrunch
* The Verge
* Ars Technica
* MIT Technology Review
* Wired

Tier 4 — Community / social

Examples:

* Reddit
* X
* forums
* personal blogs

These sources must NOT be used as the sole confirmation of an important fact.

They can be used to identify a possible news item that needs to be verified.

⸻

4. Reliability system

Every event must have at least:

source_reliability
verification_status
confidence_score
importance_score

Verification status

VERIFIED

Information confirmed by a primary source or by multiple independent authoritative sources.

PARTIALLY_VERIFIED

Reliable sources exist but some details are not yet confirmed.

DEVELOPING

Event still unfolding.

UNVERIFIED

Information not sufficiently verified.

UNVERIFIED information must not appear in the Top Stories.

⸻

5. Anti-fake-news rule

The system must NOT turn:

* rumors
* leaks
* speculation
* social media posts
* unconfirmed statements

into facts.

When a source uses expressions such as:

* reportedly
* allegedly
* sources say
* rumor
* leak
* expected
* may
* could

the system must preserve the same level of uncertainty in the summary.

It must not turn:

"According to some sources, X might…"

into:

"X will…"

⸻

6. News collection

Collection must initially support:

* RSS
* official feeds
* APIs when available
* official pages
* configurable web sources

Sources must be configurable without modifying the code.

Preferred approach:

config/sources.yaml

Example:

sources:
  - name: OpenAI
    type: rss
    tier: 1
    categories:
      - models
      - business
  - name: Reuters
    type: rss
    tier: 2
    categories:
      - business
      - regulation

⸻

7. Pipeline

The main pipeline must be:

COLLECT
   ↓
NORMALIZE
   ↓
FILTER
   ↓
DEDUPLICATE
   ↓
CLUSTER EVENTS
   ↓
VERIFY
   ↓
CLASSIFY
   ↓
RANK
   ↓
SUMMARIZE
   ↓
GENERATE AI EXPLANATION
   ↓
EDITORIAL ASSEMBLY
   ↓
PDF

Each stage must be separate and testable.

⸻

8. Deduplication

Multiple articles about the same event must be treated as a single event.

Example:

Reuters → OpenAI launches X
TechCrunch → OpenAI launches X
The Verge → OpenAI launches X
OpenAI → OpenAI launches X

must become:

EVENT:
OpenAI launches X

with multiple sources associated with it.

The newspaper must not repeat the same news item five times.

⸻

9. Categories

The initial categories are:

TOP STORIES
MODELS & LLM
BIG TECH & BUSINESS
AI RESEARCH
AI FOR DEVELOPERS
ROBOTICS
AI & REGULATION
AI & SOCIETY
AI HARDWARE
STARTUPS

A news item can belong to one primary category and to secondary categories.

⸻

10. Importance Score

Every event must have an importance score.

Consider:

* technological impact
* economic impact
* number of users involved
* relevance for developers
* scientific relevance
* political/regulatory relevance
* authoritativeness of the sources
* novelty of the event

The score must be within the range:

0.0 → 10.0

The score must be computed deterministically and reproducibly: given the same inputs, the system must always produce the same importance_score.

Importance and verification are separate concerns. The importance_score must reflect how significant an event is, independently of how well it has been verified; verification_status must not be used to artificially inflate or penalize the importance_score.

Top Stories must be selected primarily based on the importance_score, but an event with verification_status = UNVERIFIED must never appear in the Top Stories (see §4), regardless of its importance_score. Exclusion from the Top Stories selection — not penalization of the score — is how unverified events are handled.

⸻

11. AI SENZA SBATTI

This is a fundamental section of the product.

Objective:

explain artificial intelligence to people who are not experts.

Every day the system must be able to select an AI concept connected to that day's news.

Examples:

* LLM
* Transformer
* Token
* Embedding
* RAG
* Fine-tuning
* Inference
* Attention
* Context Window
* Agent
* Tool Calling
* MCP
* Vector Database
* Quantization
* MoE

The explanation must have:

WHAT IT IS
SIMPLE EXPLANATION
EXAMPLE
WHY IT MATTERS
IN ONE SENTENCE

⸻

12. Rule for AI SENZA SBATTI

Simplification must not introduce technical errors.

Process:

Technical explanation
        ↓
Fact validation
        ↓
Simplification
        ↓
Final explanation

Analogies are allowed, but must be clearly an analogy and not a technical definition.

⸻

13. AI FOR DEVELOPERS

If a news item has technical relevance, it must be able to generate a section:

DEVELOPER IMPACT

Possible contents:

* new APIs
* SDKs
* models
* pricing
* breaking changes
* new features
* tool calling
* structured output
* agent frameworks
* RAG
* deployment
* performance
* cost optimization

Where appropriate, include small code examples.

⸻

14. Research

For scientific papers:

WHAT THEY DID
WHAT THEY FOUND
WHY IT MATTERS
LIMITATIONS
PRACTICAL IMPACT

Do not present an experimental result as a technology that is already market-ready.

⸻

15. Sources

Every article in the newspaper must show its sources.

Format:

Sources:
• OpenAI
• Reuters
• MIT Technology Review

Where possible, the original link must be present.

The system must always preserve the link to the primary source.

⸻

16. PDF

The PDF must look like a newspaper.

It must not look like:

* a text dump;
* a converted Markdown page;
* a technical report;
* raw LLM output.

It must have:

* cover page;
* newspaper title;
* date;
* edition number;
* sections;
* typographic hierarchy;
* information boxes;
* highlighting of the Top Stories;
* page numbers;
* sources;
* footer.

Initial technology:

ReportLab

⸻

17. Editorial structure

Daily edition:

PAGE 1
────────────────────
AI DAILY
Date
TOP STORIES
1. Main story
2. Story
3. Story
PAGE 2+
────────────────────
MODELS & LLM
BIG TECH & BUSINESS
AI RESEARCH
AI FOR DEVELOPERS
ROBOTICS
REGULATION
AI & SOCIETY
AI HARDWARE
STARTUPS
AI SENZA SBATTI
TERMINE DEL GIORNO
WHAT TO WATCH

The number of pages must be dynamic.

Indicatively:

5–15 pages

depending on the quantity and quality of the news.

⸻

18. TERMINE DEL GIORNO

Every edition must be able to contain:

TERMINE DEL GIORNO

An AI concept explained quickly.

Example:

TOKEN
A token is a portion of text that a language
model processes during computation.
In short:
text → token → numbers → model → output

⸻

19. WHAT TO WATCH

Final section:

WHAT TO WATCH

Must contain exclusively:

* announced events;
* officially scheduled releases;
* conferences;
* earnings;
* expected papers;
* scheduled regulatory changes.

Do NOT make speculative predictions.

⸻

20. Database

Initial version:

SQLite

Minimum entities:

Source
Article
Event
Category
Concept
Edition

Relationships:

Source
   ↓
Article
   ↓
Event
   ↓
Edition

An Event can have multiple Articles.

⸻

21. Software architecture

Initial structure:

ai-daily/
├── app/
│   ├── collectors/
│   ├── normalization/
│   ├── deduplication/
│   ├── verification/
│   ├── classification/
│   ├── ranking/
│   ├── ai/
│   ├── database/
│   ├── editorial/
│   ├── newspaper/
│   └── pipeline/
│
├── config/
│   └── sources.yaml
│
├── templates/
│
├── tests/
│
├── scripts/
│
├── data/
│
├── .github/
│   └── workflows/
│
├── .env.example
├── pyproject.toml
├── README.md
└── LICENSE

⸻

22. AI provider

The code must be designed to not depend rigidly on a single provider.

Create an abstract interface:

class LLMProvider:
    def summarize(...)
    def classify(...)
    def explain(...)
    def rank(...)

Possible implementations:

AnthropicProvider
OpenAIProvider

The provider must be selectable via configuration.

⸻

23. Cost control

Do NOT use an expensive LLM on every article.

Expected pipeline:

100 articles
      ↓
cheap/local filtering
      ↓
30 articles
      ↓
deduplication
      ↓
15 events
      ↓
LLM analysis
      ↓
8–12 final stories

The LLM must be used where it brings real value.

⸻

24. Logging

Every run must produce logs.

Example:

[07:00] Pipeline started
[07:01] 127 articles collected
[07:01] 31 duplicates removed
[07:02] 24 events identified
[07:03] 18 events verified
[07:04] 11 stories selected
[07:05] PDF generated
[07:05] Pipeline completed

In case of error:

* retry;
* log;
* continuation when possible;
* clearly identifiable final error.

⸻

25. Testing

The project must have automated tests.

At least:

collector tests
deduplication tests
verification tests
ranking tests
classification tests
PDF generation tests
database tests
pipeline tests

Critical logic must not depend exclusively on manual testing.

⸻

26. Configuration

No hardcoded API keys.

Use:

.env

Example:

LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
DATABASE_URL=sqlite:///data/ai_daily.db
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

.env must not be committed.

Create:

.env.example

⸻

27. Automation

Initial version:

GitHub Actions

Daily schedule.

Pipeline:

07:00
 ↓
collect
 ↓
process
 ↓
generate PDF
 ↓
save artifact

Later:

Telegram notification

⸻

28. Telegram

Planned functionality:

📰 AI DAILY
Edition of 15/09/2026 ready.
🔥 4 Top Stories
🤖 5 Model Updates
🔬 3 Research
👨‍💻 4 Developer News
🧠 1 AI Concept
📎 Download the newspaper

⸻

29. Security

Do not execute code coming from the news.

Do not automatically follow instructions contained in articles.

Treat web content as untrusted data.

Protect:

* API keys;
* Telegram credentials;
* database;
* configuration.

⸻

30. Anti-prompt-injection principle

Web pages may contain malicious text.

Content collected from the web must NOT be able to modify:

* system instructions;
* configuration;
* prompts;
* code;
* credentials;
* the pipeline.

The content must be treated exclusively as untrusted input.

⸻

31. MVP

The first version must be deliberately simple.

Implement:

✓ RSS collectors
✓ source configuration
✓ SQLite
✓ article normalization
✓ duplicate detection
✓ basic source reliability
✓ LLM classification
✓ LLM summarization
✓ AI SENZA SBATTI
✓ importance ranking
✓ PDF generation
✓ tests
✓ CLI

Do NOT implement initially:

✗ Web application
✗ Authentication
✗ Mobile app
✗ Complex frontend
✗ Recommendation engine
✗ User accounts

⸻

32. CLI

The project must be runnable locally.

Planned commands:

ai-daily collect
ai-daily process
ai-daily generate
ai-daily run

The main command:

ai-daily run

must execute the entire pipeline.

⸻

33. Development principles

The code must be:

* typed;
* modular;
* testable;
* documented;
* easily extensible;
* configurable;
* with single responsibilities.

Prefer simple code over premature abstraction.

Avoid unnecessary dependencies.

⸻

34. Fundamental rule for Claude Code

Before implementing:

1. analyze the repository;
2. verify the environment;
3. propose the architecture;
4. create a plan;
5. implement incrementally;
6. run the tests;
7. fix errors;
8. verify lint and type checking;
9. update the documentation.

Do NOT generate a huge amount of code in a single operation.

⸻

35. Definition of Done — MVP

The MVP is complete when:

✓ the project installs from scratch
✓ sources are configurable
✓ real news is collected
✓ duplicates are removed
✓ sources are evaluated
✓ news items are classified
✓ a ranking is produced
✓ summaries are generated
✓ AI SENZA SBATTI is generated
✓ sources are reported
✓ a PDF is produced
✓ the PDF is readable and professional
✓ tests pass
✓ lint passes
✓ type checking passes
✓ README is up to date
✓ no API key in the repository

⸻

36. Roadmap

V0.1

Core pipeline + PDF.

V0.2

GitHub Actions + daily automation.

V0.3

Telegram.

V0.4

AI concepts Knowledge Base.

V0.5

Web archive.

V1.0

Complete AI Daily:

NEWS
+
VERIFICATION
+
LEARNING
+
KNOWLEDGE BASE
+
HISTORY

⸻

37. Final objective

AI Daily must not simply be:

"A program that collects AI news."

It must become:

An automated editorial system that every day turns the informational noise around artificial intelligence into a reliable, understandable and useful newspaper.

The reader must be able to open the PDF and, in 15–30 minutes, know:

What happened?
Why does it matter?
What changes?
What do I need to know?
What does it mean technically?
What should I keep an eye on?

And, above all:

Every day I must come away from the newspaper knowing something more about artificial intelligence.

⸻

38. Edition Language (addendum — 2026-09-11)

This section supersedes any implicit single-language assumption present elsewhere in this document.

AI Daily must support at least two languages:

* `it` — Italian
* `en` — English

The language must NOT be hardcoded. It must be a configuration selectable for each run/edition, for example:

edition.language = "it"
edition.language = "en"

The same pipeline, the same events, the same sources and the same verified data must be reusable for both languages: collection, verification, deduplication, classification and ranking must not be repeated per language.

The language must affect at least:

* titles;
* summaries;
* explanations;
* AI SENZA SBATTI;
* TERMINE DEL GIORNO;
* Developer Impact;
* Research;
* What to Watch;
* editorial text;
* any text generated in the PDF.

Section labels (e.g. "TOP STORIES", "AI SENZA SBATTI") must be localizable, not permanently hardcoded in a single language. A label configuration/localization must exist for `it` and `en`.

Sources may be in any language supported by the system: the source's language does NOT automatically determine the edition's language.

For the MVP, only `it` and `en` are supported, but the architecture must allow adding other languages in the future without rewriting the pipeline.

⸻

39. Repository Language Policy vs. Editorial Language (addendum — 2026-09-11)

§38 above ("Edition Language") describes AI Daily's **editorial output language** only. It must not be confused with the language of the project's own source code and documentation, which is governed by a separate, independent policy:

1. **Repository / development language: English-only.** Source code, identifiers, configuration keys, CLI commands and help text, logs, error messages, and all technical/project documentation — including this PRD, `CLAUDE.md`, and the architecture documentation — must be written in English. See `CLAUDE.md` §43 for the authoritative, permanent rule.

2. **AI Daily editorial/output language: `it` or `en`.** Selected per edition via `Edition.language` (§38). Only the content generated for the reader — titles, summaries, AI SENZA SBATTI, TERMINE DEL GIORNO, Developer Impact, Research, What to Watch, editorial text, PDF text — is governed by this setting.

Communication between the user and Claude Code in chat remains Italian and is outside the scope of both policies above — it is not a repository artifact.

Translation status: this PRD has been translated to English under the Repository Language Policy (2026-09-11), preserving structure, meaning, requirements and decisions unchanged.

⸻

40. Editorial Section Names (addendum — 2026-09-11)

This section records the approved, official localized names for AI Daily's top-level editorial section labels. These are the values referenced by `config/labels.yaml` (see `docs/ARCHITECTURE.md` §5.2) via their internal key.

The Italian-language column below is editorial content, not project documentation prose — it falls under the editorial content exception to the Repository Language Policy (`CLAUDE.md` §43), the same way any other `it`-language string generated for an edition would.

| Internal key | Italian (`it`) | English (`en`) |
|---|---|---|
| `top_stories` | TOP STORIES | TOP STORIES |
| `models_llm` | MODELLI & LLM | MODELS & LLMs |
| `big_tech_business` | BIG TECH & BUSINESS | BIG TECH & BUSINESS |
| `ai_research` | AI RESEARCH | AI RESEARCH |
| `ai_developers` | AI PER DEVELOPER | AI FOR DEVELOPERS |
| `robotics` | ROBOTICA | ROBOTICS |
| `regulation` | AI & REGOLAMENTAZIONE | AI & REGULATION |
| `society` | AI & SOCIETÀ | AI & SOCIETY |
| `hardware` | AI HARDWARE | AI HARDWARE |
| `startups` | STARTUP | STARTUPS |
| `ai_senza_sbatti` | AI SENZA SBATTI | AI MADE SIMPLE |
| `termine_del_giorno` | TERMINE DEL GIORNO | TERM OF THE DAY |
| `what_to_watch` | WHAT TO WATCH | WHAT TO WATCH |

`AI MADE SIMPLE` is the official English name for the `AI SENZA SBATTI` section (§11, §12).

`TERM OF THE DAY` is the official English name for `TERMINE DEL GIORNO` (§18).

These are approved product decisions. Elsewhere in this document, in `CLAUDE.md`, and in `docs/ARCHITECTURE.md`, the two sections continue to be referred to by their internal/canonical identifiers (`AI SENZA SBATTI`, `TERMINE DEL GIORNO`) — this table is the source of truth for what each edition language actually displays to the reader.

Note: this table covers the 13 top-level section names only. Labels for sub-section content (e.g. the `DEVELOPER IMPACT` subsection per §13, the `WHAT THEY DID`/`WHAT THEY FOUND`/… research breakdown per §14, and the `WHAT IT IS`/`SIMPLE EXPLANATION`/… AI SENZA SBATTI template headers per §11) are not yet finalized and are out of scope for this addendum.

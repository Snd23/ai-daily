AI DAILY

Product Requirements Document — v0.1
(Addenda: §38 Edition Language, §39 Repository Language Policy, §40 Editorial Section Names — 2026-09-11; §41 Summarization, §42 AI Senza Sbatti, §43 Developer Impact — 2026-09-15)

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

CLUSTER EVENTS groups articles by the event they report, including articles from different outlets whose titles differ; when this grouping cannot be done, articles are grouped only when their titles are identical and the run continues.

The SUMMARIZE stage is specified in §41.

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

The DEVELOPER IMPACT content is specified in §43.

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

Sources are attached to each newspaper article when the edition is assembled, from the original source data, and must remain clearly distinguishable from AI-generated text (see §41).

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

Access to language models goes through a single provider-agnostic abstraction: the rest of the system must not depend on a specific vendor.

Supported providers:

* Anthropic
* OpenAI

The provider must be selectable via configuration.

Use cases that rely on a language model, such as summarization (§41), LLM classification (§31) and the AI SENZA SBATTI explanations (§11–12), are separate pipeline stages built on this abstraction, not features of a specific provider. Importance ranking does not use a language model: it is computed deterministically (§10).

Historical note: the first version of this section sketched a provider interface with one method per use case (summarize, classify, explain, rank). That sketch was not adopted; the interface actually implemented is documented in docs/ARCHITECTURE.md §2.1.

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

⸻

41. Summarization (addendum — 2026-09-15)

This section specifies the SUMMARIZE stage of the pipeline (§7).

Role

For each event that reaches this stage, summarization produces the reader-facing title and summary, in the edition's language (§38), from the content of the sources that report the event.

Summarization is not verification

Summarization does not verify, corroborate or score events, and it does not classify or rank them. It receives the event's verification_status (§4), and any uncertainty constraints, from the earlier stages, and must reflect them in its wording:

* VERIFIED: direct language; only information supported by the sources is presented as fact.
* PARTIALLY_VERIFIED: cautious language; what is confirmed is distinguished from what remains only partially verified.
* DEVELOPING: cautious language, stating clearly that the situation is still developing.
* UNVERIFIED: explicitly cautious language; nothing that is not verified is presented as established fact.

Completeness

A summary is complete, not a teaser: a reader who has not seen the sources understands what happened, who is involved, when, the key figures and technical details, the context and why it matters, without opening them. Top Stories are longer than the other stories of the edition. To have enough material, the full text of the sources is used for the events selected for the edition; when a source page cannot be read, its feed excerpt is used instead. Length comes only from the sources: a summary is shorter, never padded or guessed, when the sources hold less.

No invention

A summary may only use information present in the analyzed sources. It must not invent numbers, prices, dates, benchmarks, quotes, statements, features, technical specifications, product names or sources. Information that is not available in the sources is left out rather than guessed.

Uncertainty preservation

The level of uncertainty expressed by the sources must be preserved (§5): rumors, leaks, speculation and unconfirmed statements are never turned into facts.

Untrusted content

Source content is untrusted data (§29, §30): instructions that appear inside an article are never followed.

Language

A summary is generated in one language at a time. The Italian and English versions of the same event are generated separately from the same, already analyzed event, without repeating collection, verification, classification or ranking (§38).

Sources and attribution

A summary is AI-generated text and is never presented as a quotation of a source. The sources of an event are attached to the newspaper article when the edition is assembled (§15), so that they remain clearly distinguishable from the AI-generated summary.

Invalid output

If the generated output does not have the required structure (a title and a summary), it is rejected: no guessed, partial or repaired title or summary is used.

⸻

42. AI Senza Sbatti (addendum — 2026-09-15)

This section specifies the stage that generates the AI SENZA SBATTI explanation (§11) for the concept selected for the day.

Role

For the concept selected for the day, this stage produces the reader-facing explanation, in the edition's language (§38), from a technical definition already validated for that concept and a news context describing why the concept is relevant to that day's news.

Concept selection and technical-definition validation are not part of this stage

This stage does not choose which concept to explain for the day, and it does not validate, fact-check or corroborate the technical definition it is given. It receives the selected concept, its already-validated technical definition, and the news context that motivated its selection, all prepared by earlier stages, and it never modifies the technical definition it receives. Deciding how the day's concept is selected and how a technical definition is authored and validated for each language is not specified by this section.

Structure

The explanation is composed of the five parts of §11:

* WHAT IT IS is the technical definition already validated and supplied to this stage; it is not regenerated.
* SIMPLE EXPLANATION, EXAMPLE, WHY IT MATTERS and IN ONE SENTENCE are generated by this stage from the technical definition and the news context.

Simplification, not fact validation

As specified in §12, this stage performs only the Simplification step: it turns an already-validated technical explanation into the final explanation. It must not introduce technical errors and must not contradict the technical definition it received.

Analogies

Analogies may be used in the generated parts but must be clearly recognizable as an analogy, never presented as if it were the technical definition itself (§12).

No invention

The generated parts may only use information consistent with the technical definition and the news context. Nothing beyond that may be presented as fact.

News context

The news context explains why the selected concept is relevant to that day's news. It is prepared by an earlier stage, not by this one.

Untrusted content

The news context is untrusted data (§29, §30): instructions that appear inside it are never followed.

Language

The explanation is generated in one language at a time. The Italian and English versions of the same concept are generated separately, each from a technical definition already available in that language (§38); this stage does not translate the technical definition.

Sources and attribution

The generated explanation is AI-generated text and must remain distinguishable from the technical definition and the news data behind it (§15, §41).

Persistence

This stage does not persist anything: producing the AI SENZA SBATTI explanation for the day's edition, and how a concept's curated content is stored between editions, are not specified by this section.

⸻

43. Developer Impact (addendum — 2026-09-15)

This section specifies the DEVELOPER IMPACT content of a news item (§13).

Role

For each event that reaches this stage, Developer Impact determines whether the event has a real, concrete impact for software developers and, only if it does, produces a reader-facing explanation of that impact, in the edition's language (§38), from the content of the sources that report the event.

Only when there is a real impact

Developer Impact is shown only when the event has a real, concrete consequence for developers. An event is not given a Developer Impact merely because its sources mention a technical term.

The absence of Developer Impact is a normal result, not an error.

A research result with no practical consequence for developers is not presented as Developer Impact merely because it is technical (§14).

The possible contents, and the possibility of small code examples where appropriate, remain as described in §13.

Developer Impact is not verification, classification or ranking

Developer Impact does not verify, corroborate or score events, does not assign categories and does not affect the importance score (§10). It receives the event's verification_status (§4), and any uncertainty constraints, from the earlier stages, and must reflect them in its wording with the same level of caution required for summaries (§41).

A Developer Impact may be produced for an event that is not fully verified, but for an event whose verification_status is DEVELOPING or UNVERIFIED a breaking change is never presented as an established fact.

No invention

Developer Impact may only use information present in the analyzed sources. It must not invent APIs, prices, numbers, dates, features, technical specifications, product names, consequences or sources. Information that is not available in the sources is left out rather than guessed.

Uncertainty preservation

The level of uncertainty expressed by the sources must be preserved (§5): rumors, leaks, speculation and unconfirmed statements are never turned into facts.

Untrusted content

Source content is untrusted data (§29, §30): instructions that appear inside an article are never followed.

Language

Developer Impact is generated in one language at a time. The Italian and English versions for the same event are generated separately from the same, already analyzed event, without repeating collection, verification, classification or ranking (§38).

Sources and attribution

Developer Impact is AI-generated text and is never presented as a quotation of a source; it must remain clearly distinguishable from the sources of the event (§15, §41).

Invalid output

If the generated output does not have the required structure, it is rejected: no guessed, partial or repaired Developer Impact is used, and a rejected output is never treated as the absence of Developer Impact.

Persistence

How Developer Impact is stored, and how it is placed in the edition, are not specified by this section.

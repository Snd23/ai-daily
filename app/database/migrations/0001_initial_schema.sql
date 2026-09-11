-- Initial database schema (TASK-004).
--
-- Implements the data model from docs/ARCHITECTURE.md section 3, derived
-- from docs/PRD.md section 20 (minimum entities) and section 38 (per
-- language editorial content).
--
-- Conventions used throughout this file:
--   - Timestamp columns are TEXT, ISO-8601, stored in UTC.
--   - edition.date is a calendar date (TEXT, format YYYY-MM-DD), not a
--     timestamp.
--   - Booleans are INTEGER with a CHECK restricting them to 0 or 1.
--   - List-shaped or free-form structured values (source.categories,
--     concept.tags, event_content.structured_content, edition.stats) are
--     stored as TEXT containing JSON, encoded/decoded by the application.
--   - Enumerated TEXT columns get a CHECK against the documented values.
--   - Foreign keys are declared here but only enforced when the connection
--     has run "PRAGMA foreign_keys = ON" (see app/database/connection.py).

CREATE TABLE source (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('rss', 'api', 'html')),
    url TEXT NOT NULL,
    tier INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 4),
    categories TEXT NOT NULL,
    reliability_weight REAL NOT NULL,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    last_fetched_at TEXT
);

CREATE TABLE event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_status TEXT NOT NULL CHECK (
        verification_status IN ('VERIFIED', 'PARTIALLY_VERIFIED', 'DEVELOPING', 'UNVERIFIED')
    ),
    confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0.0 AND 10.0),
    importance_score REAL NOT NULL CHECK (importance_score BETWEEN 0.0 AND 10.0),
    event_type TEXT NOT NULL CHECK (event_type IN ('standard', 'research', 'developer_relevant')),
    future_date TEXT,
    created_at TEXT NOT NULL
);

-- source_id is required: every article comes from a source. event_id is
-- nullable because clustering into an Event happens after collection.
CREATE TABLE article (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES source (id),
    event_id INTEGER REFERENCES event (id),
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    raw_excerpt TEXT NOT NULL,
    normalized_text TEXT,
    content_hash TEXT,
    language TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'processed', 'discarded', 'error')
    )
);

-- Static seed table (rows inserted below): the displayed name per language
-- is resolved from config/labels.yaml via slug, not stored here.
CREATE TABLE category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    canonical_name TEXT NOT NULL
);

CREATE TABLE event_category (
    event_id INTEGER NOT NULL REFERENCES event (id),
    category_id INTEGER NOT NULL REFERENCES category (id),
    is_primary INTEGER NOT NULL CHECK (is_primary IN (0, 1)),
    PRIMARY KEY (event_id, category_id)
);

CREATE TABLE concept (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    tags TEXT NOT NULL
);

-- technical_definition is curated per language, not machine-translated
-- (docs/ARCHITECTURE.md section 5.3).
CREATE TABLE concept_translation (
    concept_id INTEGER NOT NULL REFERENCES concept (id),
    language TEXT NOT NULL CHECK (language IN ('it', 'en')),
    technical_definition TEXT NOT NULL,
    simple_explanation TEXT NOT NULL,
    example TEXT NOT NULL,
    why_it_matters TEXT NOT NULL,
    one_liner TEXT NOT NULL,
    last_used_at TEXT,
    PRIMARY KEY (concept_id, language)
);

-- One row per (event, language): lets the same verified Event be reused
-- for both editorial languages without re-running verify/classify/rank.
CREATE TABLE event_content (
    event_id INTEGER NOT NULL REFERENCES event (id),
    language TEXT NOT NULL CHECK (language IN ('it', 'en')),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    structured_content TEXT,
    PRIMARY KEY (event_id, language)
);

-- pdf_path and the two concept references are nullable: an Edition exists
-- in status 'draft' before the PDF and the curated concepts are attached.
CREATE TABLE edition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edition_number INTEGER NOT NULL UNIQUE,
    date TEXT NOT NULL,
    language TEXT NOT NULL CHECK (language IN ('it', 'en')),
    pdf_path TEXT,
    status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'failed')),
    concept_deep_dive_id INTEGER REFERENCES concept (id),
    concept_term_id INTEGER REFERENCES concept (id),
    stats TEXT,
    created_at TEXT NOT NULL
);

-- Static seed: the 10 categories from PRD.md section 9, with the approved
-- internal keys and English canonical names from PRD.md section 40.
INSERT INTO category (slug, canonical_name) VALUES
    ('top_stories', 'TOP STORIES'),
    ('models_llm', 'MODELS & LLM'),
    ('big_tech_business', 'BIG TECH & BUSINESS'),
    ('ai_research', 'AI RESEARCH'),
    ('ai_developers', 'AI FOR DEVELOPERS'),
    ('robotics', 'ROBOTICS'),
    ('regulation', 'AI & REGULATION'),
    ('society', 'AI & SOCIETY'),
    ('hardware', 'AI HARDWARE'),
    ('startups', 'STARTUPS');

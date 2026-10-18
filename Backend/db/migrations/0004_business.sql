-- 0004: business (BOM sessions, rows, match runs, candidates, review decisions). See docs/LCA/spec/04-ERD.md.
-- Candidates are stored per de-duplicated query (query_key = sha256(norm_text)), not per row (spec/08 section 4).
BEGIN;

-- One uploaded BOM = one session. project_id is the session id (12 alphanumerics). Deleted 24h after creation (CASCADE).
CREATE TABLE bom_project (
    project_id  text PRIMARY KEY CHECK (project_id ~ '^[A-Za-z0-9]{12}$'),
    name        text,
    source_file text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL
);
CREATE INDEX bom_project_expires_idx ON bom_project (expires_at);

-- One BOM line. raw_* are the original strings (never modified); clean_* is the normalized copy.
CREATE TABLE bom_item (
    item_id            bigserial PRIMARY KEY,
    project_id         text NOT NULL REFERENCES bom_project ON DELETE CASCADE,
    row_no             integer NOT NULL,         -- Row.id (1-based within the session)
    source_row         integer NOT NULL,         -- line/row number in the uploaded file (header counted, 1-based)
    raw_name           text NOT NULL,
    raw_spec           text NOT NULL,
    raw_unit           text NOT NULL,
    raw_qty            text NOT NULL,
    clean_name         text NOT NULL,
    clean_spec         text NOT NULL,
    clean_unit         text,                     -- canonical unit or NULL
    clean_unit_display text NOT NULL,
    clean_qty          double precision,         -- NULL when unreadable
    norm_text          text NOT NULL,            -- search query (no dictionary yet)
    query_key          text NOT NULL,            -- sha256(norm_text)
    parsed_attrs       jsonb NOT NULL DEFAULT '{}',
    issues             jsonb NOT NULL DEFAULT '[]',
    target_status      text NOT NULL,
    target_reason      text NOT NULL DEFAULT '',
    UNIQUE (project_id, row_no)
);

-- One matching run. A session reads its latest run (re-matching comes later).
CREATE TABLE match_run (
    run_id             text PRIMARY KEY,
    project_id         text NOT NULL REFERENCES bom_project ON DELETE CASCADE,
    config             jsonb NOT NULL DEFAULT '{}',
    model_versions     jsonb NOT NULL DEFAULT '{}',
    dictionary_version text,
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz
);
CREATE INDEX match_run_project_idx ON match_run (project_id, started_at);

-- Top-N candidates per de-duplicated query. Vetoed candidates are kept (vetoed=true) with the rule id.
CREATE TABLE match_candidate (
    run_id       text NOT NULL REFERENCES match_run ON DELETE CASCADE,
    query_key    text NOT NULL,
    rank         integer NOT NULL CHECK (rank >= 1),
    dataset_id   text NOT NULL REFERENCES lci_dataset,
    rank_tfidf   integer,                         -- NULL when outside that list's top 100
    rank_dense   integer,
    score_tfidf  real,
    score_dense  real,
    score_rrf    real NOT NULL,
    vetoed       boolean NOT NULL DEFAULT false,
    veto_rule_id text,
    confidence   text NOT NULL,
    PRIMARY KEY (run_id, query_key, rank)
);

-- Approval / rejection / exclusion / manual selection history. Append-only trigger comes with T9b; unused for now.
CREATE TABLE review_decision (
    decision_id   bigserial PRIMARY KEY,
    item_id       bigint NOT NULL REFERENCES bom_item ON DELETE CASCADE,
    run_id        text REFERENCES match_run ON DELETE CASCADE,
    dataset_id    text REFERENCES lci_dataset,
    action        text NOT NULL,
    thickness_mm  real,
    density_kg_m3 real,
    note          text,
    actor         text,
    decided_at    timestamptz NOT NULL DEFAULT now()
);

COMMIT;

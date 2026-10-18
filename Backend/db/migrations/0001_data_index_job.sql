-- 0001: dataset / index / job   (see docs/LCA/spec/04-ERD.md, "PostgreSQL" section)
-- Keep this file ASCII-only: piping non-ASCII through Windows PowerShell corrupts it.
-- Applied in a single transaction. Never edit an applied file; add a new number instead.
BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- National LCI DB datasets. List values are loaded first; XML-derived values stay NULL when there is no XML.
CREATE TABLE lci_dataset (
    dataset_id       text PRIMARY KEY CHECK (dataset_id ~ '^list-[0-9]+$'),  -- 'list-' || list_sn, never changes
    list_sn          integer NOT NULL UNIQUE,                                -- lci_database_sn of the list (API list_row)
    ilcd_uuid        uuid UNIQUE,                                            -- filled after reading the XML
    name_ko          text NOT NULL,
    name_en          text,
    category         text NOT NULL,                                          -- 16 categories
    developer        text,
    dev_year         integer,
    version          text,
    has_xml          boolean NOT NULL DEFAULT false,
    reference_year   integer,
    valid_until      integer,
    geography        text,
    tech_description text,
    lci_method       text,
    allocation       text,
    cutoff           text,
    dataset_type     text,
    ref_flow_name    text,
    ref_flow_unit    text,
    license_type     text,
    source_file      text,                                                   -- downloaded ZIP / Excel file name
    source_hash      text,                                                   -- content hash; same hash = skip re-reading
    loaded_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT lci_dataset_id_matches_sn CHECK (dataset_id = 'list-' || list_sn)
);
CREATE INDEX lci_dataset_name_ko_idx ON lci_dataset (name_ko);               -- duplicate-name grouping
CREATE INDEX lci_dataset_category_idx ON lci_dataset (category);

-- Index versions: only a successful one becomes active. Exactly one active at a time.
CREATE TABLE index_version (
    version_id  text PRIMARY KEY,
    model_name  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    active      boolean NOT NULL DEFAULT false,
    stats       jsonb NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX index_version_one_active ON index_version (active) WHERE active;

-- Which search text (hash) each dataset uses in each version.
CREATE TABLE index_version_item (
    version_id  text NOT NULL REFERENCES index_version ON DELETE CASCADE,
    dataset_id  text NOT NULL REFERENCES lci_dataset,
    text_hash   text NOT NULL,
    PRIMARY KEY (version_id, dataset_id)
);
CREATE INDEX index_version_item_hash_idx ON index_version_item (text_hash);

-- Embeddings keyed by content. Same text + model is never computed twice. No ANN index (exact search, spec/08).
CREATE TABLE text_embedding (
    text_hash   text NOT NULL,
    model_name  text NOT NULL,
    vector      vector(1024) NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (text_hash, model_name)
);

-- Background jobs (A09 ingest, A01 match). The worker takes rows with FOR UPDATE SKIP LOCKED.
CREATE TABLE job (
    job_id       text PRIMARY KEY,
    kind         text NOT NULL CHECK (kind IN ('ingest', 'match')),
    state        text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'succeeded', 'failed')),
    params       jsonb NOT NULL DEFAULT '{}',   -- inputs (session id, options)
    stages       jsonb NOT NULL DEFAULT '[]',   -- [{name, state, done, total, started_at, finished_at}]
    result       jsonb NOT NULL DEFAULT '{}',
    error        jsonb,                         -- {detail, code}; 'interrupted' for jobs left running at restart
    created_at   timestamptz NOT NULL DEFAULT now(),
    started_at   timestamptz,
    finished_at  timestamptz
);
CREATE INDEX job_queue_idx ON job (created_at) WHERE state = 'queued';

COMMIT;

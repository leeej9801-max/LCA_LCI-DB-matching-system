-- 0003: evaluation (gold set, labels, eval runs, per-row results). See docs/LCA/spec/04-ERD.md.
-- Numbering: 0003 eval / 0004 business (T9) / 0005 knowledge (decided 2026-10-18).
BEGIN;

-- One gold set version. sha256 of the CSV file makes re-loading the same file idempotent.
CREATE TABLE gold_set (
    gold_id     text PRIMARY KEY,
    name        text NOT NULL,
    version     text NOT NULL,
    sha256      text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

-- One labelled BOM line. is_no_match = 1 <=> expected_dataset_id IS NULL.
CREATE TABLE gold_label (
    label_id            bigserial PRIMARY KEY,
    gold_id             text NOT NULL REFERENCES gold_set ON DELETE CASCADE,
    bom_text            text NOT NULL,
    spec                text,
    unit                text,
    expected_dataset_id text REFERENCES lci_dataset,
    is_no_match         integer NOT NULL CHECK (is_no_match IN (0, 1)),
    hard_pair_group     text,
    product             text,                 -- demo product tag (no product names in code)
    input_style         text NOT NULL,        -- notation style tag (abbreviation, english, typo ...)
    label_source        text CHECK (label_source IN ('pool', 'manual')),
    split               text NOT NULL CHECK (split IN ('dev', 'test')),
    source              text,                 -- public source memo
    note                text,
    CHECK ((is_no_match = 1) = (expected_dataset_id IS NULL)),
    UNIQUE (gold_id, bom_text)
);
CREATE INDEX gold_label_gold_idx ON gold_label (gold_id);

-- One evaluation run = one case (one ablation line).
CREATE TABLE eval_run (
    eval_id        text PRIMARY KEY,
    gold_id        text NOT NULL REFERENCES gold_set,
    config         jsonb NOT NULL DEFAULT '{}',
    model_versions jsonb NOT NULL DEFAULT '{}',
    started_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE eval_result (
    eval_id              text NOT NULL REFERENCES eval_run ON DELETE CASCADE,
    label_id             bigint NOT NULL REFERENCES gold_label,
    predicted_dataset_id text REFERENCES lci_dataset,
    gold_rank            integer,             -- strict rank of the expected dataset (NULL: not in top 100 or no-match row)
    confidence           real,                -- top-1 score as given by the case (RRF is not a probability)
    top1_ok              integer NOT NULL CHECK (top1_ok IN (0, 1)),
    top3_ok              integer NOT NULL CHECK (top3_ok IN (0, 1)),
    rejected             integer NOT NULL CHECK (rejected IN (0, 1)),
    top_ids              jsonb NOT NULL DEFAULT '[]',   -- top 10 [{dataset_id, score}]
    top1_name_ok         integer CHECK (top1_name_ok IN (0, 1)),
    PRIMARY KEY (eval_id, label_id)
);

COMMIT;

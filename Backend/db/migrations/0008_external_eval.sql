-- 0008: external evaluation results (E2). Candidates are exported to a file, scored outside (Colab: rerank / judge),
-- and imported back so the same evaluation code computes the metrics. See docs/LCA/spec/04-ERD.md.
-- Numbering: 0007 gold label type / 0008 external eval; the knowledge tables move after this.
BEGIN;

-- One exported candidate file. sha256 = hash of the file bytes. split = 'test' records that the test split was opened.
CREATE TABLE eval_export (
    export_id   text PRIMARY KEY,
    gold_id     text NOT NULL REFERENCES gold_set,
    split       text NOT NULL CHECK (split IN ('dev', 'test')),
    base_case   text NOT NULL,          -- case that produced the candidates, e.g. C2+D+V
    top         integer NOT NULL CHECK (top > 0),
    sha256      text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- One imported external run (a reranker or a judge) computed on one export.
CREATE TABLE eval_external_run (
    run_id        text PRIMARY KEY,
    export_id     text NOT NULL REFERENCES eval_export,
    kind          text NOT NULL CHECK (kind IN ('rerank', 'judge')),
    model         text NOT NULL,
    params        jsonb NOT NULL DEFAULT '{}',
    prompt_sha256 text,
    structure     text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    imported_at   timestamptz NOT NULL DEFAULT now()
);

-- Per-row external result. ranking and picked_dataset_id only use ids from the exported candidates (checked on import).
CREATE TABLE eval_external_result (
    run_id            text NOT NULL REFERENCES eval_external_run ON DELETE CASCADE,
    label_id          bigint NOT NULL REFERENCES gold_label,
    ranking           jsonb NOT NULL DEFAULT '[]',   -- [[dataset_id, score], ...]
    decision          text CHECK (decision IN ('pick', 'none')),
    picked_dataset_id text REFERENCES lci_dataset,
    reason            text,
    confidence        text,
    latency_ms        integer,
    PRIMARY KEY (run_id, label_id)
);

COMMIT;

-- 0002: dataset extras (reference flow amount, system boundary) and dataset_issue
BEGIN;

ALTER TABLE lci_dataset
    ADD COLUMN ref_flow_amount numeric,   -- reference flow amount as in the source (1000 kg, 1 ton ...)
    ADD COLUMN system_boundary text;      -- raw text, e.g. 'Cradle to gate'

-- Data problems found while loading. Raw values are kept in lci_dataset; this table only records them.
CREATE TABLE dataset_issue (
    issue_id    bigserial PRIMARY KEY,
    dataset_id  text NOT NULL REFERENCES lci_dataset ON DELETE CASCADE,
    code        text NOT NULL,
    severity    text NOT NULL CHECK (severity IN ('info', 'warning')),
    message     text NOT NULL,
    detail      jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, code)
);
CREATE INDEX dataset_issue_code_idx ON dataset_issue (code);

COMMIT;

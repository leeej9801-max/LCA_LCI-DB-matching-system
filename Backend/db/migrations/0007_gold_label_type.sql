-- 0007: label kinds and accept sets on gold_label (F3). Old rows keep NULL and mean "one correct id = expected_dataset_id".
-- Numbering: 0006 role / 0007 gold label type; the knowledge tables (planned 0007) move to the next number.
BEGIN;

ALTER TABLE gold_label
    ADD COLUMN label_type text CHECK (label_type IN ('exact', 'proxy', 'none')),
    ADD COLUMN a_accept   text[],   -- item level: ids that count as right (first one = expected_dataset_id)
    ADD COLUMN s_accept   text[],   -- strict level: may be empty (proxy: nothing is strictly right); NULL = old row
    ADD COLUMN decided_by text;     -- who decided the label (claude / user / user+claude), for the report header

COMMIT;

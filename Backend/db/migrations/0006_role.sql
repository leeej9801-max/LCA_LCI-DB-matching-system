-- 0006: dataset role on lci_dataset, and the optional role/part number columns on bom_item. See docs/LCA/spec/04-ERD.md.
-- Numbering: 0006 role / 0007 knowledge (decided 2026-10-18, T13). Values are English codes (this file is ASCII only);
-- the API shows Korean labels (app/roles.py LABEL).
BEGIN;

-- NULL until app.roles apply (or the ingest) fills it. The ingest fails if any row is still NULL after loading.
ALTER TABLE lci_dataset
    ADD COLUMN role text CHECK (role IN ('material', 'process', 'combined', 'transport', 'waste', 'utility'));

-- input_role: what the user wrote in the BOM "role" column (material / process), NULL when empty or unknown.
ALTER TABLE bom_item
    ADD COLUMN input_role text CHECK (input_role IN ('material', 'process')),
    ADD COLUMN part_no    text;

COMMIT;

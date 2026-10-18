-- 0005: review state on bom_item, richer review_decision, append-only guard. See docs/LCA/spec/04-ERD.md.
-- Numbering: 0005 review / 0006 knowledge (decided 2026-10-18, T9b).
BEGIN;

-- Current state of each BOM line. selected_manual IS NULL means "nobody touched the selection yet":
-- the API then shows the top candidate as the default selection (computed when reading, not stored here).
ALTER TABLE bom_item
    ADD COLUMN selected_id            text REFERENCES lci_dataset,
    ADD COLUMN selected_manual        boolean,
    ADD COLUMN override_thickness_mm  numeric,
    ADD COLUMN override_density_kg_m3 numeric,
    ADD COLUMN override_unit_mass_kg  numeric,
    ADD COLUMN review_status          text NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected', 'excluded')),
    ADD COLUMN review_note            text NOT NULL DEFAULT '',
    ADD COLUMN explanation            jsonb;

-- Rows created before 0005: excluded target rows start as 'excluded' (target_status = U&'\C81C\C678' is the Korean word for "excluded").
UPDATE bom_item SET review_status = 'excluded' WHERE target_status = U&'\C81C\C678';

-- Every A03 request leaves one line, including rejected ones (outcome = 'rejected').
ALTER TABLE review_decision
    ADD COLUMN unit_mass_kg numeric,
    ADD COLUMN from_status  text,
    ADD COLUMN to_status    text,
    ADD COLUMN outcome      text NOT NULL DEFAULT 'applied' CHECK (outcome IN ('applied', 'rejected')),
    ADD COLUMN payload      jsonb NOT NULL DEFAULT '{}',
    ADD COLUMN reason       text;

-- Append-only: UPDATE is always refused. DELETE is allowed only as part of the ON DELETE CASCADE that starts from
-- deleting the bom_project (24h cleanup): by then the project row is gone, whichever cascade path (bom_item or match_run) arrives first.
CREATE FUNCTION review_decision_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'review_decision is append-only: UPDATE is not allowed' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF EXISTS (SELECT 1 FROM bom_item i JOIN bom_project p USING (project_id) WHERE i.item_id = OLD.item_id) THEN
        RAISE EXCEPTION 'review_decision is append-only: DELETE only via bom_project cascade' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN OLD;
END;
$$;

CREATE TRIGGER review_decision_no_update BEFORE UPDATE ON review_decision
    FOR EACH ROW EXECUTE FUNCTION review_decision_append_only();
CREATE TRIGGER review_decision_no_delete BEFORE DELETE ON review_decision
    FOR EACH ROW EXECUTE FUNCTION review_decision_append_only();

COMMIT;

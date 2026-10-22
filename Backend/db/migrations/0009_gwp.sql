-- 0009: climate change impact results (emission factors) read from the national LCI DB XML (LCIAResults).
-- Values are per 1 reference unit (the LCIA amount divided by ref_flow_amount). NULL = the dataset has no result (never filled with 0 or with another dataset's value).
BEGIN;

ALTER TABLE lci_dataset
    ADD COLUMN gwp_total    numeric,  -- "Climate change" (kg CO2 eq per 1 reference unit)
    ADD COLUMN gwp_fossil   numeric,  -- "Climate change-Fossil"
    ADD COLUMN gwp_biogenic numeric,  -- "Climate change-Biogenic"
    ADD COLUMN gwp_luluc    numeric,  -- "Climate change-Land use and land use change"
    ADD COLUMN gwp_method   text;     -- method name and version, e.g. 'Climate change (04.00.016)'

COMMIT;

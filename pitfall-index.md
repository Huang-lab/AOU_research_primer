# Pitfall Index

Every **Pitfall** callout from the 27 Reference pages, grouped by failure
mode. Use this as a pre-submission checklist: scan each category before
running a final analysis to confirm you have not fallen into a
silent-wrong-answer trap.

Each entry links back to the Reference page where the full explanation,
code fix, and context live.

---

## Missing denominator / survivors-only bias

- **Carrier-status query returns carriers only; non-carriers are absent.**
  Computing rates on the raw result gives 100%. Left-join back to the full
  cohort and zero-fill.
  [Source](reference/genomics/query-carrier-status.md)

- **INNER JOIN on `visit_occurrence_id` silently drops clinical events.**
  The foreign key is frequently NULL in AoU data. Use LEFT JOIN when the
  goal is to retain all events.
  [Source](reference/visits/query-visit-occurrence.md)

- **Not filtering by observation period inflates apparent health.**
  Participants with short EHR windows appear condition-free because their
  data is simply sparse, biasing case-control comparisons.
  [Source](reference/data-quality/filter-by-observation-period.md)

- **Controls without a pseudo-index date produce undefined temporal features.**
  You cannot compute windowed features for controls if they have no index
  date; any case-control comparison will be silently biased.
  [Source](reference/temporal-windowing/apply-index-date-window.md)

- **Counting raw `visit_occurrence` rows without stratifying by visit type.**
  A single ER visit plus follow-ups looks like higher utilization than
  fewer but more severe visits.
  [Source](reference/visits/query-visit-occurrence.md)

- **Not excluding participants who develop the condition after study period.**
  Controls who later become cases contaminate the control group.
  [Source](reference/cohort-definition/build-matched-controls.md)

---

## Temporal leakage

- **Off-by-one on the window boundary: `<=` includes day 0.**
  Using `<= index_date` leaks the diagnosis-day event into baseline
  features. Use strict `<`.
  [Source](reference/temporal-windowing/apply-index-date-window.md)

- **Auditing leakage at the cohort level instead of per-participant.**
  One clean participant can mask another whose features include
  post-diagnosis data. Compare each person's max event date to their own
  index date.
  [Source](reference/temporal-windowing/audit-temporal-leakage.md)

- **Relying on the absence of obvious future dates.**
  Same-day events (e.g., confirmatory tests) do not show up as "future"
  but may still be consequent to the index event. Decide on a policy and
  enforce strict `<`.
  [Source](reference/temporal-windowing/audit-temporal-leakage.md)

- **Including the target variable or its proxies in the feature matrix.**
  A cancer-specific drug or staging lab is definitionally linked to the
  outcome and produces meaningless SHAP importance.
  [Source](reference/statistical-modeling/build-shap-feature-matrix.md)

---

## Ancestry confounding

- **Using self-reported race as a proxy for genetic ancestry.**
  Race categories do not capture continuous admixture. Use pre-computed
  ancestry PCs instead.
  [Source](reference/demographics-ancestry/compute-ancestry-pcs.md)

- **Not adjusting for enough PCs.**
  AoU's diverse population typically requires 10-16 PCs. Using 3-4 leaves
  residual confounding.
  [Source](reference/demographics-ancestry/compute-ancestry-pcs.md)

- **Not including enough PCs in regression (same issue, modeling context).**
  Carrier-status odds ratios are biased if ancestry variation is not fully
  absorbed. Use at least 10 PCs; 16 is standard.
  [Source](reference/statistical-modeling/pc-adjusted-regression.md)

- **Including both self-reported race AND PCs as covariates.**
  They are collinear. Including both inflates standard errors and does not
  improve confounding control. Use PCs alone for genetic analyses.
  [Source](reference/statistical-modeling/pc-adjusted-regression.md)

- **Matching controls on self-reported race/ethnicity instead of PCs.**
  Self-reported categories are coarse and do not reflect genetic
  population structure.
  [Source](reference/cohort-definition/build-matched-controls.md)

---

## Vocabulary / hierarchy errors

- **Querying `condition_source_concept_id` instead of `condition_concept_id`.**
  Source concepts are non-standard and skip OMOP's vocabulary mapping.
  [Source](reference/cohort-definition/define-case-cohort-by-condition.md)

- **Filtering on exact `condition_concept_id` without `concept_ancestor`.**
  Misses all descendant SNOMED codes beneath the target concept.
  [Source](reference/cohort-definition/define-case-cohort-by-condition.md)

- **Excluding by exact `concept_id` without descendant expansion.**
  Same hierarchy issue applied to exclusion criteria.
  [Source](reference/cohort-definition/exclude-by-condition-history.md)

- **Querying exact `drug_concept_id` for a specific product.**
  Misses most exposures. Use `concept_ancestor` to roll up to the
  ingredient level.
  [Source](reference/medications/query-drug-exposures.md)

- **Procedures coded in both CPT4 and SNOMED; querying only one misses the other.**
  Use `concept_ancestor` to capture the full hierarchy, or query both
  `procedure_concept_id` and `procedure_source_concept_id`.
  [Source](reference/procedures/query-procedure-occurrence.md)

- **Mixing parent and child codes inflates prevalence.**
  A participant matching both a parent and child concept gets counted
  twice.
  [Source](reference/conditions-phenotypes/build-multi-code-phenotype.md)

- **Code lists from published algorithms may not match your CDR.**
  Concept IDs and mappings can differ across OMOP vocabularies and CDR
  versions.
  [Source](reference/conditions-phenotypes/build-multi-code-phenotype.md)

- **Exact-match filtering on ClinVar `clinical_significance_string`.**
  ClinVar uses compound slash/comma-separated strings. `= 'Pathogenic'`
  misses `Pathogenic/Likely pathogenic` and others. Use `LIKE '%athogenic%'`.
  [Source](reference/genomics/filter-clinvar-plp.md)

- **`LIKE '%Pathogenic%'` silently includes "Conflicting classifications".**
  Variants with conflicting submissions are not definitive P/LP calls.
  Add `NOT LIKE '%Conflicting%'`.
  [Source](reference/genomics/filter-clinvar-plp.md)

- **Compound ClinVar strings can contain both "Pathogenic" and "Benign".**
  Entries like "Pathogenic/Likely benign" match `LIKE '%Pathogenic%'` but
  are not clean P/LP. Add `NOT LIKE '%enign%'`.
  [Source](reference/genomics/filter-clinvar-plp.md)

- **ClinVar annotations change between CDR releases.**
  A VUS in v7 may be reclassified as Pathogenic in v8. Document your CDR
  version and re-run when upgrading.
  [Source](reference/genomics/filter-clinvar-plp.md)

- **`cb_variant_to_person.person_ids` is an ARRAY, not a scalar.**
  Using it as `vp.person_id` silently fails or returns wrong results. You
  must use `UNNEST(person_ids) AS person_id`.
  [Source](reference/genomics/query-carrier-status.md)

- **`pca_features` is a string, not a native array.**
  Calling `.tolist()` directly gives strings, not lists. Parse with
  `ast.literal_eval()` first.
  [Source](reference/demographics-ancestry/compute-ancestry-pcs.md)

- **Assuming column names from old code or documentation.**
  Genomics schemas change across CDR releases. Always verify with
  `INFORMATION_SCHEMA` before writing queries.
  [Source](reference/genomics/discover-genomics-tables.md)

- **Join key for variant tables changes across CDR releases.**
  If a genomics query returns zero rows, verify the join key exists with
  `INFORMATION_SCHEMA`.
  [Source](reference/genomics/query-carrier-status.md)

- **Survey answers stored in `value_as_concept_id`, not `value_as_number`.**
  Querying only `value_as_number` for categorical questions returns all
  NULLs.
  [Source](reference/surveys/query-survey-responses.md)

- **Only standard concepts (`standard_concept = 'S'`) match clinical records.**
  Source vocabularies (ICD10CM, ICD9CM) in the concept table return zero
  patients when used in `WHERE condition_concept_id = ...`.
  [Source](reference/cohort-definition/discover-omop-concepts.md)

- **Secondary cancer concepts name the DESTINATION, not the origin.**
  "Secondary malignant neoplasm of lung" = metastasis IN the lung. A
  breast cancer patient with lung mets may contaminate a lung primary cohort.
  [Source](reference/cohort-definition/define-case-cohort-by-condition.md)

- **AlphaMissense uses `chr1` format; AoU uses bare `1`.**
  Coordinate mismatch when matching variants. Strip `chr` prefix or add it.
  [Source](reference/genomics/integrate-alphamissense.md)

---

## Unit / encoding errors

- **Same lab test reported in different units.**
  Mixing mg/dL and mmol/L (or similar) without conversion corrupts
  aggregations.
  [Source](reference/labs-measurements/query-lab-measurements.md)

- **Biologically implausible outliers left in lab values.**
  Extreme values from data-entry errors or device malfunctions skew means
  and model training.
  [Source](reference/labs-measurements/query-lab-measurements.md)

- **Rows with NULL `value_as_number` silently corrupt lab aggregations.**
  SQL `AVG()` ignores NULLs but `COUNT(*)` includes them, producing
  inconsistent denominators.
  [Source](reference/labs-measurements/query-lab-measurements.md)

- **Inconsistent categorical encoding across features.**
  One-hot vs. ordinal encoding produces incomparable SHAP values. Choose
  one strategy for all categoricals.
  [Source](reference/statistical-modeling/build-shap-feature-matrix.md)

- **NaN handling varies by model framework.**
  XGBoost treats NaN as a learnable split; scikit-learn raises errors.
  Decide and document your imputation strategy.
  [Source](reference/statistical-modeling/build-shap-feature-matrix.md)

- **`race` and `ethnicity` are concept IDs, not strings.**
  Using them without joining to the concept table produces opaque integer
  columns.
  [Source](reference/demographics-ancestry/extract-demographic-features.md)

- **`year_of_birth` alone gives +/- 1 year error.**
  Without month/day, computed age can be off by a full year.
  [Source](reference/demographics-ancestry/extract-demographic-features.md)

- **`procedure_datetime` is sometimes NULL when `procedure_date` is populated.**
  Filtering on `procedure_datetime` silently excludes those records.
  [Source](reference/procedures/query-procedure-occurrence.md)

---

## Provenance mixing

- **Mixing EHR and survey conditions without distinguishing source.**
  Self-reported conditions have different sensitivity/specificity than EHR
  diagnoses, biasing prevalence and associations.
  [Source](reference/data-quality/distinguish-ehr-survey-sources.md)

- **Physical measurements mixed with EHR lab results in the `measurement` table.**
  AoU enrollment measurements follow different protocols than EHR vitals.
  Filter by `measurement_type_concept_id` or include source as a
  covariate.
  [Source](reference/data-quality/distinguish-ehr-survey-sources.md)

- **Ignoring `condition_type_concept_id`.**
  This field distinguishes primary diagnoses, billing codes, and
  self-reported conditions. Ignoring it mixes provenance silently.
  [Source](reference/conditions-phenotypes/query-condition-occurrence.md)

- **Longitudinal surveys contribute multiple rows per participant per question.**
  Without date filtering, `COUNT(*)` and row-level analyses are inflated.
  [Source](reference/surveys/query-survey-responses.md)

- **`observation_period_start_date` does not mean first healthcare contact.**
  It reflects the earliest event in AoU's data, which depends on
  contributing EHR systems. Do not use for incidence calculations without
  acknowledging left-truncation.
  [Source](reference/data-quality/filter-by-observation-period.md)

---

## Cost / resource traps

- **Dry-run estimates are upper bounds, not guarantees.**
  Actual execution may scan less (caching, pruning) or more (plan
  changes, table growth). Treat as order-of-magnitude guidance.
  [Source](reference/cost-awareness/dry-run-query.md)

- **Not catching the `Forbidden` exception when `maximum_bytes_billed` is exceeded.**
  The error propagates as an opaque 403. Always wrap capped queries in
  `try/except`.
  [Source](reference/cost-awareness/cap-query-cost.md)

- **Dataproc clusters have NO autostop.**
  Unlike Jupyter environments, Dataproc clusters do not auto-pause or
  auto-stop when idle. A forgotten cluster at $0.12/hr (minimum) or
  $0.73/hr (with workers) burns credits continuously. Delete the cluster
  manually after each session.
  [Source](reference/cost-awareness/optimize-compute-costs.md)

- **`WORKSPACE_CDR` is None in Dataproc, producing a confusing 403.**
  `os.environ.get("WORKSPACE_CDR")` returns `None` in Dataproc, which
  produces queries against `None.table_name`. BigQuery returns `403
  Forbidden` instead of a clear error. Always provide a manual fallback
  string and print the CDR value before running queries.
  [Source](reference/cost-awareness/optimize-compute-costs.md)

---

## Other

- **Absolute date filters are meaningless in the Registered Tier.**
  Dates are shifted per-participant by a random offset. Only relative
  date arithmetic (intervals between events) is valid.
  [Source](reference/conditions-phenotypes/query-condition-occurrence.md)

- **Using absolute date thresholds in Registered Tier for exclusions.**
  Same date-shift issue applied to exclusion logic.
  [Source](reference/cohort-definition/exclude-by-condition-history.md)

- **`drug_exposure_end_date` is unreliable for duration calculations.**
  Many records have imputed or NULL end dates. Use `days_supply` or
  define duration from dispensing logic.
  [Source](reference/medications/query-drug-exposures.md)

- **Drugs with dual indications contaminate cohorts in general biobanks.**
  Denosumab = Xgeva (oncology) AND Prolia (osteoporosis). ~80% of drug-
  only patients in AoU have osteoporosis, not cancer.
  [Source](reference/medications/query-drug-exposures.md)

- **Hardcoded paths break across compute environments.**
  `/home/jupyter/` paths fail on Dataproc (`/home/dataproc/`). Use
  `os.getcwd()` or relative paths.
  [Source](reference/environment/choose-compute-environment.md)

- **`WORKSPACE_CDR` is None in Dataproc environments.**
  Queries using `os.environ["WORKSPACE_CDR"]` raise `KeyError`. Set
  CDR string manually.
  [Source](reference/environment/choose-compute-environment.md)

- **Dataproc files are NOT persistent.**
  Local disk is wiped on cluster stop/destroy. Sync to GCS before
  shutdown.
  [Source](reference/environment/choose-compute-environment.md)

- **GCS ancestry file path changed in Workbench 2.0.**
  `gs://fc-aou-datasets-controlled` → `gs://vwb-aou-datasets-controlled`.
  Filename is now `echo_v4_r2.ancestry_preds.tsv`.
  [Source](reference/demographics-ancestry/compute-ancestry-pcs.md)

- **`sex_male` covariate causes singular matrix for sex-specific cancers.**
  Near-zero variance when nearly all participants share the same sex.
  Drop `sex_male` for ovarian/prostate analyses.
  [Source](reference/statistical-modeling/pc-adjusted-regression.md)

- **Too many race dummy columns cause convergence failures.**
  `pd.get_dummies(df['race'])` on 11 categories creates sparse columns.
  Collapse to 4 clean categories.
  [Source](reference/statistical-modeling/pc-adjusted-regression.md)

- **All covariates must be float for statsmodels.**
  Pandas nullable `Int64` vs numpy `int64` causes `isin()` mismatches
  and silent failures. Cast to float before fitting.
  [Source](reference/statistical-modeling/build-shap-feature-matrix.md)

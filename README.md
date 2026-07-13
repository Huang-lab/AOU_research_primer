# All of Us Query Documentation

**[Live docs →](https://mohibul-07.github.io/AOU_Documentation/)**

Task-based reference for querying the All of Us Researcher Workbench CDR.
Each page answers one "how do I do X" question with exact code, parameters,
and inline **Pitfall** warnings for silent-wrong-answer traps.

Audience: fluent in SQL and pandas. No language basics here.

## How to use this

**Looking up a specific task?** Find it in the Reference index below.
**Building a full pipeline?** See the [Guides](#guides) below — they chain
Reference pages into end-to-end workflows with the connective reasoning
between steps.

**Callout key:**
- **Pitfall** — something that produces a wrong answer silently. Inline,
  at the point of danger. The most important callout in the doc.
- **Note** — clarifying aside, not critical to correctness.
- **Version note** — behavior that differs by CDR release.

---

## Reference

### Cohort Definition

- [Define a case cohort by condition codes](reference/cohort-definition/define-case-cohort-by-condition.md)
  — Identify participants with specific conditions using SNOMED concept
  hierarchies.
- [Build matched controls](reference/cohort-definition/build-matched-controls.md)
  — Age/sex-matched controls with anti-join exclusion of case-condition
  participants.
- [Exclude participants by condition history](reference/cohort-definition/exclude-by-condition-history.md)
  — Remove participants with prior diagnoses using date-aware anti-joins.

### Demographics & Ancestry

- [Extract demographic features](reference/demographics-ancestry/extract-demographic-features.md)
  — Age, sex, race/ethnicity from the person table with concept joins.
- [Compute genetic ancestry principal components](reference/demographics-ancestry/compute-ancestry-pcs.md)
  — Access pre-computed PCs for population stratification adjustment.

### Conditions & Phenotypes

- [Query condition occurrence with date constraints](reference/conditions-phenotypes/query-condition-occurrence.md)
  — Pull conditions within temporal windows, with provenance filtering.
- [Build a phenotype from multiple condition codes](reference/conditions-phenotypes/build-multi-code-phenotype.md)
  — Combine SNOMED/ICD codes into binary phenotype columns.

### Labs & Measurements

- [Query lab measurements by LOINC code](reference/labs-measurements/query-lab-measurements.md)
  — Pull from measurement with unit normalization and plausibility bounds.

### Medications

- [Query drug exposure history](reference/medications/query-drug-exposures.md)
  — Ingredient-level queries via concept_ancestor with duration handling.

### Temporal Windowing

- [Apply pre/post-index-date windowing](reference/temporal-windowing/apply-index-date-window.md)
  — Filter clinical events to windows relative to per-participant index
  dates.
- [Audit a feature matrix for temporal leakage](reference/temporal-windowing/audit-temporal-leakage.md)
  — Per-participant validation that no post-index data leaked into features.

### Genomics

- [Query carrier status for a gene panel](reference/genomics/query-carrier-status.md)
  — Variant-to-person carrier lookup with non-carrier zero-fill.
- [Filter variants to ClinVar P/LP](reference/genomics/filter-clinvar-plp.md)
  — ClinVar significance filtering with compound-string handling.
- [Discover genomics table schemas](reference/genomics/discover-genomics-tables.md)
  — INFORMATION_SCHEMA queries to verify table/column names across CDR
  versions.

### Cost Awareness

- [Dry-run a query to estimate cost](reference/cost-awareness/dry-run-query.md)
  — Estimate bytes processed without execution.
- [Cap query cost before execution](reference/cost-awareness/cap-query-cost.md)
  — Set maximum_bytes_billed to abort expensive queries.

### Surveys

- [Query survey responses](reference/surveys/query-survey-responses.md)
  — Pull and decode responses from AoU survey modules (The Basics, COPE,
  SDOH, etc.).

### Procedures

- [Query procedure occurrence](reference/procedures/query-procedure-occurrence.md)
  — Procedure lookups by CPT4/SNOMED with concept_ancestor rollup.

### Visits

- [Query visit occurrence](reference/visits/query-visit-occurrence.md)
  — Visit counting, utilization metrics, and encounter-level event anchoring.

### Data Quality

- [Filter participants by observation period](reference/data-quality/filter-by-observation-period.md)
  — Require minimum EHR coverage before including a participant.
- [Distinguish EHR from survey data sources](reference/data-quality/distinguish-ehr-survey-sources.md)
  — Use type_concept_id to separate EHR, survey, and physical measurement
  provenance.

### Statistical Modeling

- [Build a SHAP-ready feature matrix](reference/statistical-modeling/build-shap-feature-matrix.md)
  — Wide-format matrix assembly with leakage and encoding guardrails.
- [Run PC-adjusted logistic regression](reference/statistical-modeling/pc-adjusted-regression.md)
  — Logistic regression with ancestry PCs as covariates.

---

## Glossary

[Glossary](glossary.md) — CDR, Registered/Controlled Tier, index date,
carrier, P/LP, FDR, dry run, OMOP CDM, concept_id, and more. Linked from
every page that uses these terms.

## Pitfall Index

[Pitfall Index](pitfall-index.md) — every Pitfall callout from all 23
Reference pages, grouped by failure mode (missing denominator, temporal
leakage, ancestry confounding, vocabulary errors, unit/encoding errors,
provenance mixing, cost traps). Use as a pre-submission checklist.

## Template

[Reference page template](TEMPLATE.md) — the fixed structure every
Reference page follows.

---

## Guides

End-to-end workflows that chain Reference pages into complete pipelines.
Each Guide shows the pipeline shape and connective reasoning; full code
lives on the linked Reference pages.

- [Build a genomic case-control cohort from scratch](guides/build-genomic-case-control-cohort.md)
  — 12-step pipeline from condition definition through analysis-ready
  dataframe with carrier status, demographics, and ancestry PCs.
- [Add a properly-windowed lab feature to an existing cohort](guides/add-windowed-lab-feature.md)
  — 7-step pipeline: concept lookup, temporal query, unit normalization,
  plausibility bounds, aggregation, merge, and leakage audit.
- [Estimate and cap the cost of a large query](guides/estimate-and-cap-query-cost.md)
  — Dry-run, evaluate, optimize, cap, execute. The shortest Guide but
  the one that saves the most money.
- [Take case/control pairs to FDR-corrected results](guides/case-control-to-fdr-results.md)
  — Per-gene regression, p-value collection, Benjamini-Hochberg
  correction, results table with carrier counts.

---

*23 Reference pages · 4 Guides · Phases 1–3 complete · Built from AoU
domain knowledge, to be validated against project CDR.*

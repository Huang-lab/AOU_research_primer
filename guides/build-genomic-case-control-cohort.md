# Guide: Build a Genomic Case-Control Cohort from Scratch

## Purpose

End-to-end pipeline for constructing an analysis-ready case-control cohort for a
germline predisposition study on the All of Us Researcher Workbench. The result
is a single dataframe with demographics, ancestry PCs, and carrier status for a
gene panel, with matched controls and all temporal boundaries enforced.

---

## Prerequisites

- A Researcher Workbench workspace with CDR access
- A Jupyter notebook (Python 3) in the workspace
- Familiarity with the condition, gene panel, and study design you intend to use

```python
import os
import pandas as pd
from google.cloud import bigquery

CDR = os.environ["WORKSPACE_CDR"]
client = bigquery.Client()
```

---

## Pipeline Overview

```
Step 1  Define cases by condition
  │
Step 2  Set index dates (first diagnosis)
  │
Step 3  Exclude participants with confounding condition history
  │
Step 4  Build age/sex-matched controls
  │
Step 5  Assign pseudo-index dates to controls
  │
Step 6  Filter both groups by minimum observation period
  │
Step 7  Extract demographics
  │
Step 8  Pull ancestry PCs
  │
Step 9  Query carrier status for gene panel
  │
Step 10 Filter to ClinVar P/LP (if clinical-risk analysis)
  │
Step 11 Left-join carriers to full cohort, zero-fill non-carriers
  │
Step 12 Merge all features into analysis-ready dataframe
```

---

## Step 1: Define Cases by Condition

**Reference:** [define-case-cohort-by-condition](../references/define-case-cohort-by-condition.md)

Identify participants with at least one record of the study condition. The
Reference page covers concept set construction, descendant expansion, and the
choice between `condition_occurrence` and `condition_era`.

```python
case_condition_concept_ids = [4112853, 36684828, 4188544]  # breast cancer concepts

cases_sql = f"""
SELECT DISTINCT person_id
FROM `{CDR}.condition_occurrence`
WHERE condition_concept_id IN ({','.join(str(c) for c in case_condition_concept_ids)})
"""
cases_df = client.query(cases_sql).to_dataframe()
```

Output: a dataframe of `person_id` values, feeding into Step 2 for index dates.
Every downstream step depends on this set.

---

## Step 2: Set Index Dates for Cases

**Reference:** [apply-index-date-window](../references/apply-index-date-window.md)
(index date computation section)

The index date anchors all temporal reasoning. For a predisposition study, use
the date of first diagnosis:

```python
index_date_sql = f"""
SELECT person_id, MIN(condition_start_date) AS index_date
FROM `{CDR}.condition_occurrence`
WHERE condition_concept_id IN ({','.join(str(c) for c in case_condition_concept_ids)})
GROUP BY person_id
"""
case_index_df = client.query(index_date_sql).to_dataframe()
cases_df = cases_df.merge(case_index_df, on="person_id")
```

Output: cases enriched with `index_date`. Steps 3 and 6 both depend on this
date -- without it you cannot determine whether a confounding diagnosis came
*before* the study condition.

---

## Step 3: Exclude Participants with Prior Confounding Condition

**Reference:** [exclude-by-condition-history](../references/exclude-by-condition-history.md)

For a breast cancer study, exclude participants with prior ovarian cancer (shared
genetic risk factors make attribution ambiguous):

```python
confounding_concept_ids = [4091466]  # ovarian cancer

exclusion_sql = f"""
SELECT DISTINCT co.person_id
FROM `{CDR}.condition_occurrence` co
JOIN (SELECT person_id, index_date FROM case_index) ci
  ON co.person_id = ci.person_id
WHERE co.condition_concept_id IN ({','.join(str(c) for c in confounding_concept_ids)})
  AND co.condition_start_date < ci.index_date
"""
exclude_df = client.query(exclusion_sql).to_dataframe()
cases_df = cases_df[~cases_df["person_id"].isin(exclude_df["person_id"])]
```

**Why this comes before matching (Step 4):** If you match controls first and then
remove cases, you break the matched pairs. Always finalize the case set before
building controls.

---

## Step 4: Build Age/Sex-Matched Controls

**Reference:** [build-matched-controls](../references/build-matched-controls.md)

Controls are participants who never had the study condition, matched to cases on
age and sex. The Reference page covers the matching algorithm, caliper selection,
and handling unmatched cases.

```python
matched_controls_df = build_matched_controls(
    cases_df=cases_df,
    condition_concept_ids=case_condition_concept_ids,
    cdr=CDR, client=client,
    ratio=5, age_caliper=2,  # 5:1 ratio, 2-year caliper
)
```

Output: controls dataframe with `person_id` and `matched_case_id`. This comes
after exclusion because the matching pool must already exclude cases and
confounded participants -- otherwise you may match against someone who is later
removed, breaking the pair.

---

## Step 5: Assign Pseudo-Index Dates to Controls

Controls do not have a natural index date (they were never diagnosed). For
temporal features to be comparable between groups, each control must receive a
pseudo-index date. The standard approach is to assign the index date of the
matched case.

```python
# Each control inherits their matched case's index date
controls_df = matched_controls_df.merge(
    cases_df[["person_id", "index_date"]].rename(
        columns={"person_id": "matched_case_id"}
    ),
    on="matched_case_id",
)

# Combine into a single cohort
cases_df["case_control"] = 1
controls_df["case_control"] = 0

cohort_df = pd.concat([
    cases_df[["person_id", "index_date", "case_control"]],
    controls_df[["person_id", "index_date", "case_control"]],
], ignore_index=True)

print(f"Combined cohort: {len(cohort_df)}")
```

> **Pitfall: Not propagating index dates to controls.**
> If you skip this step and later extract temporal features (lab values, medication
> history), controls will have no temporal anchor. Every feature that uses "pre-index"
> logic will fail silently -- either returning all data (no filter applied) or no
> data (NULL comparison). Always verify that `cohort_df["index_date"].isna().sum() == 0`
> before proceeding.

---

## Step 6: Filter by Minimum Observation Period

**Reference:** [filter-by-observation-period](../references/filter-by-observation-period.md)

Require minimum observation time before index date to ensure that absent records
reflect genuine absence, not missing data.

```python
min_obs_days = 365

obs_filter_sql = f"""
SELECT person_id
FROM `{CDR}.observation_period` op
JOIN cohort c ON op.person_id = c.person_id
WHERE DATE_DIFF(c.index_date, op.observation_period_start_date, DAY) >= {min_obs_days}
"""
obs_eligible = client.query(obs_filter_sql).to_dataframe()
cohort_df = cohort_df[cohort_df["person_id"].isin(obs_eligible["person_id"])]
```

> **Pitfall: Running carrier queries before the observation filter.**
> Steps 8-10 scan the most expensive tables in the CDR. If Step 6 drops 10,000
> participants after you already queried their variants, you paid for gigabytes
> of unnecessary scans. Always finalize the cohort first.

---

## Step 7: Extract Demographics

**Reference:** [extract-demographic-features](../references/extract-demographic-features.md)

Pull age, sex at birth, and race/ethnicity. For large cohorts, use a temp table
instead of an IN-list (see Reference page).

```python
person_ids_str = ','.join(str(p) for p in cohort_df["person_id"])

demo_sql = f"""
SELECT person_id,
    DATE_DIFF(CURRENT_DATE(), birth_datetime, YEAR) AS age,
    sex_at_birth_concept_id, race_concept_id, ethnicity_concept_id
FROM `{CDR}.person`
WHERE person_id IN ({person_ids_str})
"""
demo_df = client.query(demo_sql).to_dataframe()
```

The Reference page covers concept-to-label mapping and handling of
skip/prefer-not-to-answer responses. This step comes after the cohort is
finalized to avoid re-running it if the cohort changes.

---

## Step 8: Pull Ancestry Principal Components

**Reference:** [compute-ancestry-pcs](../references/compute-ancestry-pcs.md)

Ancestry PCs are essential confounders in any genetic association. The AoU
genomic data includes pre-computed PCs (see Reference for exact table path).

```python
n_pcs = 10
ancestry_sql = f"""
SELECT person_id,
    {', '.join(f'pca_component_{i} AS PC{i}' for i in range(1, n_pcs + 1))}
FROM `{CDR}.ancestry_pcs`
WHERE person_id IN ({person_ids_str})
"""
pcs_df = client.query(ancestry_sql).to_dataframe()
```

> **Pitfall: Participants missing from the ancestry PC table.**
> Not every participant has genomic data. EHR-only participants will be silently
> dropped on inner join. Decide early whether to restrict the cohort to WGS
> participants (at Step 1 or Step 6).

---

## Step 9: Query Carrier Status for Gene Panel

**Reference:** [query-carrier-status](../references/query-carrier-status.md)

The core genomic query. The Reference page covers variant table structure, gene
symbol filtering, and consequence filtering.

```python
gene_panel = ["BRCA1", "BRCA2", "PALB2", "ATM", "CHEK2", "TP53"]

# Returns ONLY participants who carry a variant -- see Step 11 for zero-fill
carrier_df = query_carrier_status(
    person_ids=cohort_df["person_id"].tolist(),
    genes=gene_panel, cdr=CDR, client=client,
)
```

**Critical: the result contains only carriers.** Non-carriers are absent
entirely. The zero-fill happens in Step 11.

---

## Step 10: Filter to ClinVar P/LP Variants (Conditional)

**Reference:** [filter-clinvar-plp](../references/filter-clinvar-plp.md)

If the study is focused on clinically actionable risk (as opposed to discovery),
restrict to variants classified as Pathogenic or Likely Pathogenic in ClinVar.

```python
# Only run this step if doing clinical-risk analysis
if clinical_risk_mode:
    carrier_df = filter_to_clinvar_plp(
        carrier_df=carrier_df,
        cdr=CDR,
        client=client,
    )
    print(f"Carriers after ClinVar P/LP filter: {len(carrier_df)}")
    print(f"P/LP breakdown by gene:\n{carrier_df['gene_symbol'].value_counts()}")
```

**Why this is a separate step rather than a filter in Step 9:** Keeping the two
steps separate lets you run the analysis both ways (all qualifying variants vs.
P/LP only) without re-querying the expensive genomic tables. You query once in
Step 9 and filter in Python in Step 10.

See the Reference page for the Pitfall about ClinVar version lag and VUS
reclassification.

---

## Step 11: Left-Join Carriers to Full Cohort, Zero-Fill Non-Carriers

This is where the most common carrier-status bug is introduced. The carrier
query returns only carriers; a naive inner join silently drops everyone else.

```python
# Pivot to one row per person, one column per gene
carrier_pivot = carrier_df.pivot_table(
    index="person_id", columns="gene_symbol",
    values="variant_id", aggfunc="count",
).reset_index()
carrier_pivot.columns = ["person_id"] + [
    f"carrier_{gene}" for gene in carrier_pivot.columns[1:]
]

# LEFT join and zero-fill -- both are critical
cohort_df = cohort_df.merge(carrier_pivot, on="person_id", how="left")
carrier_cols = [c for c in cohort_df.columns if c.startswith("carrier_")]
cohort_df[carrier_cols] = cohort_df[carrier_cols].fillna(0).astype(int)
```

> **Pitfall: Carrier-status result is carriers-only.**
> See the [query-carrier-status](../references/query-carrier-status.md) Pitfall.
> If you forget `how="left"` or `fillna(0)`, downstream regression will either
> fail (NaN values) or silently exclude non-carriers.

---

## Step 12: Merge All Features into Analysis-Ready Dataframe

Bring together demographics (Step 7), ancestry PCs (Step 8), and carrier status
(Step 11):

```python
analysis_df = cohort_df.merge(demo_df, on="person_id", how="left")
analysis_df = analysis_df.merge(pcs_df, on="person_id", how="left")

# Verify
assert analysis_df["person_id"].is_unique, "Duplicate person_ids"
assert analysis_df["index_date"].notna().all(), "Missing index dates"
print(f"Final: {len(analysis_df)} rows, missing:\n{analysis_df.isna().sum()}")
```

The output is ready for [case-control-to-fdr-results](./case-control-to-fdr-results.md).

---

## Pipeline-Level Pitfalls Summary

1. **Genomic queries before cohort is final** -- Steps 9-10 scan the most
   expensive tables in the CDR. Finalize the cohort (Steps 1-6) first; see the
   inline Pitfall at Step 6 for the cost implications.

2. **Missing index dates on controls** -- Step 5 solves this. Verify with
   `assert cohort_df["index_date"].notna().all()` before any temporal feature
   extraction.

3. **Carrier zero-fill at the merge** -- Step 9 returns carriers only (see the
   [query-carrier-status](../references/query-carrier-status.md) Pitfall). The
   `how="left"` and `fillna(0)` in Step 11 are structural requirements, not
   optional cleanup.

---

## What Comes Next

With the analysis-ready dataframe in hand, proceed to:

- [case-control-to-fdr-results](./case-control-to-fdr-results.md) for running
  PC-adjusted logistic regression across the gene panel and applying FDR correction
- [add-windowed-lab-feature](./add-windowed-lab-feature.md) if you want to add
  clinical features (e.g., HbA1c, BMI) before running the regression
- [estimate-and-cap-query-cost](./estimate-and-cap-query-cost.md) if you want to
  estimate the cost of the genomic queries before running them (do this before
  Step 9)

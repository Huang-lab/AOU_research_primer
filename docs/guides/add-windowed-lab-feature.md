# Guide: Add a Properly-Windowed Lab Feature to an Existing Cohort

## Purpose

You already have a cohort dataframe with `person_id` and `index_date` columns.
Now you want to add a lab measurement (e.g., HbA1c, LDL cholesterol, serum
creatinine) as a feature for downstream analysis. This guide walks through the
full pipeline for doing so safely, with correct temporal windowing, unit
handling, outlier removal, and post-merge verification.

Getting a lab value is straightforward. Getting a lab value that does not
introduce temporal leakage, unit-mixing artifacts, or implausible outliers into
your analysis is not. This guide exists because each of those failure modes is
silent -- the query runs, the numbers look reasonable at a glance, and the
problem only surfaces when results are irreproducible or nonsensical.

---

## Prerequisites

- A cohort dataframe (`cohort_df`) with at least `person_id` and `index_date` columns
- The LOINC code or concept name for the lab measurement you want
- A decision on the temporal window (e.g., 365 days before index date)
- A decision on the aggregation strategy (most recent, mean, median, etc.)

```python
import os
import pandas as pd
import numpy as np
from google.cloud import bigquery

CDR = os.environ["WORKSPACE_CDR"]
client = bigquery.Client()
```

---

## Pipeline Overview

```
Step 1  Identify LOINC code and find concept_id
  │
Step 2  Query measurements within pre-index window
  │
Step 3  Normalize units
  │
Step 4  Apply plausibility bounds (remove outliers)
  │
Step 5  Aggregate to one value per participant
  │
Step 6  Left-join to cohort and handle missingness
  │
Step 7  Audit for temporal leakage
```

---

## Step 1: Identify the LOINC Code and Find Its concept_id

**Reference:** [query-lab-measurements](../reference/labs-measurements/query-lab-measurements.md)
(concept lookup section)

Before querying measurements, you need the OMOP `measurement_concept_id` that
corresponds to your lab test. The Reference page covers how to search the concept
table and handle cases where multiple concept IDs map to the same clinical test.

```python
# Example: HbA1c
lab_name = "HbA1c"
loinc_code = "4548-4"  # Hemoglobin A1c/Hemoglobin.total in Blood

concept_lookup_sql = f"""
SELECT concept_id, concept_name, concept_code, vocabulary_id
FROM `{CDR}.concept`
WHERE concept_code = '{loinc_code}'
  AND vocabulary_id = 'LOINC'
"""
concept_df = client.query(concept_lookup_sql).to_dataframe()
print(concept_df)

measurement_concept_id = concept_df.iloc[0]["concept_id"]
```

If you are working with a less common lab, you may need to search by name rather
than LOINC code. See the Reference page for partial-match searching and the
distinction between standard and non-standard concepts.

**Why this is a separate step:** Using the wrong concept ID is an unrecoverable
error. If you pick the concept for "Hemoglobin" instead of "Hemoglobin A1c",
every downstream step runs correctly on the wrong data. Always verify the concept
name matches your intent before proceeding.

---

## Step 2: Query Measurements Within the Pre-Index Window

**Reference:** [apply-index-date-window](../reference/temporal-windowing/apply-index-date-window.md)
and [query-lab-measurements](../reference/labs-measurements/query-lab-measurements.md)

This is where temporal windowing and measurement extraction combine. The query
must join the measurement table to your cohort on `person_id` and filter by date
relative to each participant's individual index date.

```python
window_days = 365  # look back up to 1 year before index date

lab_sql = f"""
SELECT
    m.person_id,
    m.measurement_date,
    m.value_as_number,
    m.unit_concept_id,
    m.measurement_concept_id
FROM `{CDR}.measurement` m
JOIN cohort c ON m.person_id = c.person_id
WHERE m.measurement_concept_id = {measurement_concept_id}
  AND m.value_as_number IS NOT NULL
  AND m.measurement_date < c.index_date
  AND m.measurement_date >= DATE_SUB(c.index_date, INTERVAL {window_days} DAY)
"""
lab_raw_df = client.query(lab_sql).to_dataframe()
print(f"Raw measurements: {len(lab_raw_df)} rows for "
      f"{lab_raw_df['person_id'].nunique()} participants")
```

The `cohort` reference in the SQL above assumes you have uploaded your cohort as
a temporary table or are using a CTE. See the Reference page for the full
pattern.

**Why the date filter uses strict inequality (`<`) for index date:** The index
date itself is the date of diagnosis. A lab drawn on the same day as diagnosis
is ambiguous -- it may have been drawn as part of the diagnostic workup (i.e.,
because the clinician already suspected the condition). Using `<` rather than
`<=` is the conservative choice that avoids this ambiguity.

---

## Step 3: Handle Unit Normalization

**Reference:** [query-lab-measurements](../reference/labs-measurements/query-lab-measurements.md)
(unit Pitfall)

Lab values in the OMOP CDR can be recorded in different units for the same test.
HbA1c, for example, can appear as a percentage (e.g., 6.5%) or in mmol/mol
(e.g., 48 mmol/mol). Mixing these without conversion produces meaningless
aggregates.

```python
# Check what units are present
unit_dist = lab_raw_df.groupby("unit_concept_id").agg(
    count=("value_as_number", "count"),
    mean=("value_as_number", "mean"),
    median=("value_as_number", "median"),
    min=("value_as_number", "min"),
    max=("value_as_number", "max"),
).reset_index()
print(unit_dist)
```

If multiple units are present, convert to a single target unit. For HbA1c:

```python
# IFCC (mmol/mol) to NGSP (%): % = (mmol/mol * 0.0915) + 2.15
MMOL_MOL_CONCEPT_ID = 8753  # example; verify in your CDR

needs_conversion = lab_raw_df["unit_concept_id"] == MMOL_MOL_CONCEPT_ID
lab_raw_df.loc[needs_conversion, "value_as_number"] = (
    lab_raw_df.loc[needs_conversion, "value_as_number"] * 0.0915 + 2.15
)
```

See the Reference page for the full unit Pitfall, including how to identify
the correct unit concept IDs and conversion factors for common lab tests.

**Why this comes before outlier removal:** Plausibility bounds depend on units.
An HbA1c of 48 is an outlier in percent-space but perfectly normal in mmol/mol.
If you remove outliers before normalizing units, you will incorrectly discard
valid measurements.

---

## Step 4: Apply Plausibility Bounds

**Reference:** [query-lab-measurements](../reference/labs-measurements/query-lab-measurements.md)
(outlier Pitfall)

Lab databases contain implausible values: data entry errors, instrument
malfunctions, unit-conversion bugs upstream. Remove these before aggregating.

```python
# HbA1c plausibility bounds (in %)
lower_bound = 3.0   # physiologically impossible below this
upper_bound = 20.0  # beyond any clinically observed value

pre_filter_count = len(lab_raw_df)
lab_clean_df = lab_raw_df[
    (lab_raw_df["value_as_number"] >= lower_bound) &
    (lab_raw_df["value_as_number"] <= upper_bound)
].copy()

dropped = pre_filter_count - len(lab_clean_df)
print(f"Dropped {dropped} implausible values "
      f"({dropped / pre_filter_count * 100:.1f}%)")
```

!!! pitfall "Aggregating BEFORE filtering outliers"
    If you compute the mean first and remove outliers afterward, the damage is already done. A single glucose value of 9999 mg/dL (a data entry error) will inflate a participant's mean even if you would have removed it in a later step. Always filter outliers BEFORE aggregation. The correct order is: normalize units (Step 3) -> remove outliers (Step 4) -> aggregate (Step 5).


---

## Step 5: Aggregate to One Value per Participant

Most analyses need a single value per participant. The choice of aggregation
function depends on the clinical question:

| Strategy | When to use |
|---|---|
| Most recent (pre-index) | When current status matters (e.g., HbA1c for diabetes control) |
| Mean | When average exposure matters (e.g., average LDL over time) |
| Median | When the distribution is skewed or has residual outliers |
| Max / Min | When peak or nadir matters (e.g., max creatinine for AKI) |

```python
# Most recent pre-index value
lab_agg_df = (
    lab_clean_df
    .sort_values("measurement_date")
    .groupby("person_id")
    .last()
    .reset_index()
    [["person_id", "value_as_number", "measurement_date"]]
    .rename(columns={
        "value_as_number": f"{lab_name}_value",
        "measurement_date": f"{lab_name}_date",
    })
)
print(f"Aggregated to {len(lab_agg_df)} participants")
```

!!! pitfall "Taking the "most recent" value without confirming it is pre-index"
    If Step 2's date filter was correct, this is safe -- every value in `lab_clean_df` is already pre-index. But if you skipped Step 2's date filtering (perhaps querying all measurements and planning to filter later), the "most recent" value might be a post-diagnosis measurement. That value is causally downstream of the condition and will introduce temporal leakage. Always verify your date filter is applied BEFORE aggregation.


---

## Step 6: Left-Join to Cohort and Handle Missingness

Not every participant will have a lab measurement in the window. The join must
be a left join so that participants without lab data are retained with a missing
value rather than silently dropped.

```python
cohort_df = cohort_df.merge(lab_agg_df, on="person_id", how="left")

n_missing = cohort_df[f"{lab_name}_value"].isna().sum()
pct_missing = n_missing / len(cohort_df) * 100
print(f"Participants with {lab_name}: {len(cohort_df) - n_missing}")
print(f"Participants without {lab_name}: {n_missing} ({pct_missing:.1f}%)")
```

How to handle missingness depends on your analysis plan:

```python
# Option A: Exclude participants without the lab value
# (only if missingness is low and plausibly random)
cohort_complete = cohort_df.dropna(subset=[f"{lab_name}_value"])

# Option B: Impute with median (simple, preserves sample size)
median_val = cohort_df[f"{lab_name}_value"].median()
cohort_df[f"{lab_name}_value"] = cohort_df[f"{lab_name}_value"].fillna(median_val)

# Option C: Add a missingness indicator and impute
# (best for models that can learn from missingness patterns)
cohort_df[f"{lab_name}_missing"] = cohort_df[f"{lab_name}_value"].isna().astype(int)
cohort_df[f"{lab_name}_value"] = cohort_df[f"{lab_name}_value"].fillna(median_val)
```

**Important:** Before choosing an imputation strategy, check whether missingness
is differential between cases and controls:

```python
missing_by_group = cohort_df.groupby("case_control")[f"{lab_name}_value"].apply(
    lambda x: x.isna().mean()
)
print(f"Missingness by group:\n{missing_by_group}")
```

If missingness is significantly higher in one group, imputation may introduce
bias. Consider whether the lab test is ordered more often in the presence of
symptoms (i.e., informative missingness).

---

## Step 7: Audit for Temporal Leakage

**Reference:** [audit-temporal-leakage](../reference/temporal-windowing/audit-temporal-leakage.md)

This step is not optional. It is the verification that Steps 2-6 actually
respected the temporal boundary. The audit checks that no measurement date in
the final dataframe falls on or after the index date.

```python
# Direct audit: check dates
if f"{lab_name}_date" in cohort_df.columns:
    leakage = cohort_df[
        cohort_df[f"{lab_name}_date"] >= cohort_df["index_date"]
    ]
    if len(leakage) > 0:
        print(f"TEMPORAL LEAKAGE DETECTED: {len(leakage)} rows have "
              f"{lab_name} measurements on or after index date")
        print(leakage[["person_id", "index_date", f"{lab_name}_date"]].head(10))
    else:
        print(f"Temporal audit passed: no {lab_name} values on or after index date")

# Full audit using the Reference page's approach
audit_result = audit_temporal_leakage(
    df=cohort_df,
    date_columns=[f"{lab_name}_date"],
    index_date_column="index_date",
)
```

!!! pitfall "Not auditing after the merge"
    Step 7 is the verification, not an optional quality check. If you skip it, you are trusting that the SQL in Step 2, the aggregation in Step 5, and the merge in Step 6 all worked correctly. Bugs in any of those steps will silently introduce temporal leakage. The audit takes seconds to run and catches errors that would invalidate months of downstream work.


See the Reference page for the full audit approach, including how to handle
cases where the measurement date column was dropped during aggregation.

---

## Pipeline-Level Pitfalls Summary

1. **Wrong step ordering: aggregate before filtering outliers.** The correct
   order is: normalize units -> remove outliers -> aggregate. A single glucose
   of 9999 mg/dL corrupts the mean even if you "would have" removed it later.

2. **"Most recent" without date confirmation.** If Step 2's date filter was
   incorrectly written, `groupby().last()` may select a post-diagnosis value.
   Verify after Step 5:
   ```python
   merged_check = lab_agg_df.merge(cohort_df[["person_id", "index_date"]], on="person_id")
   assert (merged_check[f"{lab_name}_date"] < merged_check["index_date"]).all()
   ```

3. **Skipping the temporal audit.** Step 7 catches bugs in all preceding steps.
   It runs in seconds. The alternative is discovering temporal leakage during
   peer review.

---

## Repeating for Multiple Lab Features

To add several labs (HbA1c, LDL, creatinine), wrap Steps 1-7 in a function and
call it once per lab. Each call is independent and runs its own temporal audit,
so a leakage bug in one lab does not go undetected because a different lab
passed.

```python
lab_specs = [
    # (LOINC, name, window_days, lower_bound, upper_bound)
    ("4548-4", "HbA1c", 365, 3.0, 20.0),
    ("2093-3", "LDL", 365, 10.0, 500.0),
    ("2160-0", "Creatinine", 365, 0.1, 25.0),
]

for loinc, name, window, lo, hi in lab_specs:
    cohort_df = add_lab_feature(cohort_df, loinc, name, window, lo, hi)
```

---

## What Comes Next

- If building a feature matrix for regression or machine learning, see
  [build-shap-feature-matrix](../reference/statistical-modeling/build-shap-feature-matrix.md) for
  encoding and scaling guidance
- If proceeding to statistical analysis, see
  [case-control-to-fdr-results](./case-control-to-fdr-results.md)
- If the lab feature query is expensive, estimate cost first with
  [estimate-and-cap-query-cost](./estimate-and-cap-query-cost.md)

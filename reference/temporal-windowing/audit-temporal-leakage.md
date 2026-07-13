# Audit a feature matrix for temporal leakage

Validate that no feature was computed from data occurring on or after the index date when it should only use pre-index data.

## Prerequisites

- A feature matrix DataFrame with `person_id`, feature columns, and an `index_date` column
- The source event data with per-event dates, or the ability to re-query it
- Python 3, `pandas`, optionally `google-cloud-bigquery`

**Tier:** N/A (operates on already-extracted data)
**CDR versions:** All

## Reference

Temporal leakage occurs when information from the future (relative to the prediction point) contaminates features used for prediction. In AoU research, the most common form is including clinical events that occurred on or after the index date in "baseline" features. Leakage produces models that appear highly accurate during development but fail on prospective data.

Leakage sources in AoU data, ranked by how easily they hide:

| Source | Why it hides | Detection |
|---|---|---|
| Same-day events (day 0) | The diagnosis and a related lab may share a date | Check `max(event_date) >= index_date` per person |
| Medication started after preliminary workup | Drug prescribed between suspicion and formal dx date | Check `drug_exposure_start_date` vs `index_date` |
| Backward-filled dates | EHR systems sometimes backdate orders to encounter date | Compare `event_date` to `event_datetime` if available |
| Concept hierarchy leakage | A descendant concept of the target condition used as a feature | Concept set audit, not date-based |

## Usage

### Step 1: Prepare the audit inputs

Assume you have a feature matrix and the raw event data used to build it:

```python
import pandas as pd
import numpy as np

# feature_matrix: one row per person_id, columns are features + index_date
# events_df: the raw event-level data with person_id, event_date, concept_id

# Example structure
print(feature_matrix.columns.tolist())
# ['person_id', 'index_date', 'n_labs_365d', 'mean_hba1c', 'n_conditions', ...]

print(events_df.columns.tolist())
# ['person_id', 'event_date', 'concept_id', 'value', 'source_table']
```

### Step 2: Per-participant date audit

Check that no participant has events at or after their index date in the feature source data:

```python
# Merge events with index dates
audit_df = events_df.merge(
    feature_matrix[["person_id", "index_date"]],
    on="person_id",
    how="inner",
)

# Flag events that violate the temporal boundary
audit_df["is_leaking"] = audit_df["event_date"] >= audit_df["index_date"]

# Per-participant summary
leak_summary = (
    audit_df.groupby("person_id")["is_leaking"]
    .agg(["sum", "count"])
    .rename(columns={"sum": "n_leaking_events", "count": "n_total_events"})
)
leak_summary["leak_rate"] = (
    leak_summary["n_leaking_events"] / leak_summary["n_total_events"]
)

n_affected = (leak_summary["n_leaking_events"] > 0).sum()
print(f"Participants with leaking events: {n_affected:,} "
      f"/ {len(leak_summary):,}")
```

> **Pitfall: auditing at the cohort level instead of per-participant.** Do not check only `events_df["event_date"].max() < index_dates.min()`. One participant with clean dates can mask another whose features include post-diagnosis data. The audit must be per-participant, comparing each person's `max(event_date)` to their own `index_date`.

### Step 3: Identify same-day events

```python
# Same-day events are the most common subtle leak
day_zero = audit_df[
    audit_df["event_date"] == audit_df["index_date"]
]
print(f"Same-day (day-0) events: {len(day_zero):,}")
print("Source tables involved:")
print(day_zero["source_table"].value_counts())
```

> **Pitfall: relying on the absence of obvious future dates.** Leakage is often subtle. A lab drawn on the same day as diagnosis or a medication started in response to a preliminary finding both occur on day 0 and will not show up as "future" dates. Your boundary must be strict `< index_date` (not `<=`), and you need an explicit policy on same-day events. If any same-day events exist, decide whether they are causally prior to the index event (e.g., a routine lab drawn before the diagnosis was made) or consequent to it (e.g., a confirmatory test ordered because of the diagnosis). When in doubt, exclude them.

### Step 4: Automated assertion for pipelines

```python
def assert_no_temporal_leakage(
    events: pd.DataFrame,
    index_dates: pd.DataFrame,
    event_date_col: str = "event_date",
    strict: bool = True,
) -> None:
    """Raise AssertionError if any event date >= index_date.

    Parameters
    ----------
    events : DataFrame with person_id and event_date_col
    index_dates : DataFrame with person_id and index_date
    event_date_col : name of the date column in events
    strict : if True, day-0 events also trigger failure
    """
    merged = events.merge(index_dates[["person_id", "index_date"]],
                          on="person_id")
    if strict:
        violations = merged[merged[event_date_col] >= merged["index_date"]]
    else:
        violations = merged[merged[event_date_col] > merged["index_date"]]

    if len(violations) > 0:
        n_people = violations["person_id"].nunique()
        sample = violations.head(5)[
            ["person_id", event_date_col, "index_date"]
        ]
        raise AssertionError(
            f"Temporal leakage detected: {len(violations):,} events "
            f"from {n_people:,} participants violate the boundary.\n"
            f"Sample:\n{sample.to_string(index=False)}"
        )
    print("Temporal leakage audit passed.")


# Use in your pipeline
assert_no_temporal_leakage(events_df, feature_matrix)
```

> **Pitfall — a passing date audit does not rule out concept-hierarchy leakage.** If your model AUC is suspiciously high (>0.95) despite clean temporal boundaries, leakage may be through the concept hierarchy rather than dates. A feature concept that is a descendant (or ancestor) of the target condition concept encodes the outcome directly. For example, if the target is "Type 2 diabetes" and a feature includes "diabetic nephropathy" (a descendant), the feature is definitionally linked to the label. Check whether any feature concept is in the `concept_ancestor` tree of the target condition.

### Step 5: SQL-level audit (run before extracting features)

If you want to catch leakage at the BigQuery level before pulling data into pandas:

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

audit_sql = f"""
WITH idx AS (
    SELECT person_id, MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_concept_id = 201826
    GROUP BY person_id
),
events AS (
    SELECT person_id, measurement_date AS event_date
    FROM `{CDR}.measurement`
)
SELECT
    e.person_id,
    MAX(e.event_date) AS max_event_date,
    idx.index_date,
    CASE
        WHEN MAX(e.event_date) >= idx.index_date THEN 'LEAK'
        ELSE 'OK'
    END AS status
FROM events e
JOIN idx USING (person_id)
GROUP BY e.person_id, idx.index_date
HAVING MAX(e.event_date) >= idx.index_date
LIMIT 100
"""
leaks = client.query(audit_sql).to_dataframe()
print(f"Participants with potential leakage: {len(leaks):,}")
```

## Variations

### Automated leakage check as a pandas assertion

Integrate the assertion into your feature-building pipeline so it runs automatically:

```python
# In your feature pipeline
features = build_baseline_features(cohort_df, events_df)

# Gate: fail the pipeline if leakage is detected
assert_no_temporal_leakage(
    events_df, cohort_df, event_date_col="event_date", strict=True
)

# Only reached if audit passes
features.to_parquet("features_clean.parquet")
```

### Column-level audit for wide feature matrices

When the feature matrix is already built and you no longer have the raw events, audit indirectly by checking feature values against known temporal constraints:

```python
# If a feature should be zero for participants diagnosed after
# a certain date, verify that
recent_dx = feature_matrix[
    feature_matrix["index_date"] > "2022-01-01"
]
# A feature counting "events in 2023" should be zero for these
# participants if their index date is in 2023
suspect = recent_dx[recent_dx["n_events_2023"] > 0]
if len(suspect) > 0:
    print(f"WARNING: {len(suspect)} participants have 2023 events "
          f"despite 2023 index dates")
```

### Multi-table audit

Run the date check across all OMOP event tables simultaneously:

```python
event_tables = {
    "condition_occurrence": "condition_start_date",
    "measurement": "measurement_date",
    "drug_exposure": "drug_exposure_start_date",
    "procedure_occurrence": "procedure_date",
    "observation": "observation_date",
}

for table, date_col in event_tables.items():
    table_events = pd.read_gbq(
        f"SELECT person_id, {date_col} AS event_date "
        f"FROM `{CDR}.{table}`",
        progress_bar_type=None,
    )
    try:
        assert_no_temporal_leakage(
            table_events, feature_matrix, strict=True
        )
        print(f"  {table}: PASS")
    except AssertionError as e:
        print(f"  {table}: FAIL -- {e}")
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| Assertion fires on every participant | The feature query likely used `<=` instead of `<` for the boundary. Fix the extraction query and rebuild. |
| `merge` produces more rows than expected | Duplicate `person_id` in `index_dates` (multiple observation periods). Deduplicate to one index date per person before auditing. |

## Cost note

This page is mostly Python/pandas operating on already-extracted data. The optional SQL audit in Step 5 scans event tables, but the `HAVING` clause limits output. Cost is low.

## See also

- [Apply pre/post-index-date temporal windowing](apply-index-date-window.md) -- the feature extraction step this page audits
- [Build a SHAP-ready feature matrix](../statistical-modeling/build-shap-feature-matrix.md) -- where clean features are assembled for modeling

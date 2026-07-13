# Apply pre/post-index-date temporal windowing

Filter clinical events to a time window relative to each participant's index date (e.g., baseline features from -365 to -1 days before diagnosis; outcomes from +1 to +365 days after).

## Prerequisites

- A defined cohort with `person_id` values
- An index-date query (typically: first `condition_start_date` for the case-defining condition)
- Python 3, `google-cloud-bigquery`, `pandas`

**Tier:** Registered or Controlled (depending on tables accessed)
**CDR versions:** v7+

## Reference

The **index date** is the per-participant anchor from which all temporal features are measured. In case-control studies, this is usually the first occurrence of the case-defining condition. Every clinical event is then classified as pre-index, post-index, or excluded based on its date relative to this anchor.

Window boundaries are defined as a `(lower_days, upper_days)` offset from the index date:

| Window purpose | Lower bound | Upper bound | Typical use |
|---|---|---|---|
| Baseline features | -365 | -1 | Comorbidities, labs before diagnosis |
| Peri-index | -7 | +7 | Events around the diagnosis encounter |
| Short-term outcome | +1 | +90 | 90-day readmission, early response |
| Long-term outcome | +1 | +365 | 1-year survival, sustained remission |

## Usage

### Step 1: Compute the index date per participant

```python
import os
import pandas as pd
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

# Index date = first diagnosis of Type 2 Diabetes (concept 201826)
index_sql = f"""
SELECT
    person_id,
    MIN(condition_start_date) AS index_date
FROM `{CDR}.condition_occurrence`
WHERE condition_concept_id = 201826
GROUP BY person_id
"""
index_df = client.query(index_sql).to_dataframe()
print(f"Participants with index date: {len(index_df):,}")
```

### Step 2: Pull events and apply the window in SQL

```python
# Baseline labs: -365 to -1 days before index date
baseline_labs_sql = f"""
WITH idx AS (
    SELECT person_id, MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_concept_id = 201826
    GROUP BY person_id
)
SELECT
    m.person_id,
    m.measurement_concept_id,
    m.value_as_number,
    m.measurement_date,
    idx.index_date,
    DATE_DIFF(m.measurement_date, idx.index_date, DAY) AS days_from_index
FROM `{CDR}.measurement` m
JOIN idx USING (person_id)
WHERE m.measurement_date >= DATE_SUB(idx.index_date, INTERVAL 365 DAY)
  AND m.measurement_date < idx.index_date
"""
baseline_labs = client.query(baseline_labs_sql).to_dataframe()
```

!!! pitfall "off-by-one on the window boundary"
    The filter above uses `< idx.index_date`, not `<= idx.index_date`. This is deliberate. If you use `<=`, day 0 (the index date itself) is included in the "pre-diagnosis" window. For a condition-based index date, the diagnosis event falls on day 0 -- including it in baseline features leaks the outcome into the feature set. Always use strict inequality (`<`) for the boundary adjacent to the index date.


### Step 3: Post-index outcome window

```python
# Outcome events: +1 to +365 days after index date
outcome_sql = f"""
WITH idx AS (
    SELECT person_id, MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_concept_id = 201826
    GROUP BY person_id
)
SELECT
    co.person_id,
    co.condition_concept_id,
    co.condition_start_date,
    DATE_DIFF(co.condition_start_date, idx.index_date, DAY) AS days_from_index
FROM `{CDR}.condition_occurrence` co
JOIN idx USING (person_id)
WHERE co.condition_start_date > idx.index_date
  AND co.condition_start_date <= DATE_ADD(idx.index_date, INTERVAL 365 DAY)
"""
outcomes = client.query(outcome_sql).to_dataframe()
```

### Step 4: Assign pseudo-index dates to controls

!!! pitfall "controls have no natural index date"
    If you skip this step, temporal features for controls are undefined -- you cannot compute "number of lab tests in the 365 days before index" for someone who has no index. Any comparison between cases and controls will be silently biased or will error. You must assign a pseudo-index date to every control.


```python
import numpy as np

# Get observation periods for controls
control_obs_sql = f"""
SELECT
    person_id,
    observation_period_start_date AS obs_start,
    observation_period_end_date AS obs_end
FROM `{CDR}.observation_period`
WHERE person_id IN UNNEST(@control_ids)
"""
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ArrayQueryParameter("control_ids", "INT64", control_person_ids)
    ]
)
control_obs = client.query(control_obs_sql, job_config=job_config).to_dataframe()

# Assign a random date within each control's observation period
rng = np.random.default_rng(seed=42)
control_obs["obs_days"] = (
    control_obs["obs_end"] - control_obs["obs_start"]
).dt.days
control_obs["pseudo_index_date"] = control_obs.apply(
    lambda r: r["obs_start"] + pd.Timedelta(
        days=rng.integers(0, max(r["obs_days"], 1))
    ),
    axis=1,
)
```

An alternative is to assign each control the same index date as their matched case (in a matched case-control design). This preserves calendar-time alignment, which matters if secular trends affect the features.

## Variations

### Symmetric windows for exposure studies

For exposure assessments where you need events both before and after a reference point:

```python
# Symmetric +-90 day window around an exposure date
symmetric_sql = f"""
WITH exposure AS (
    SELECT person_id, MIN(drug_exposure_start_date) AS exposure_date
    FROM `{CDR}.drug_exposure`
    WHERE drug_concept_id = 1322184  -- metformin
    GROUP BY person_id
)
SELECT
    m.person_id,
    m.measurement_concept_id,
    m.value_as_number,
    DATE_DIFF(m.measurement_date, e.exposure_date, DAY) AS days_from_exposure,
    CASE
        WHEN m.measurement_date < e.exposure_date THEN 'pre'
        WHEN m.measurement_date > e.exposure_date THEN 'post'
        ELSE 'day_zero'
    END AS period
FROM `{CDR}.measurement` m
JOIN exposure e USING (person_id)
WHERE m.measurement_date BETWEEN
    DATE_SUB(e.exposure_date, INTERVAL 90 DAY)
    AND DATE_ADD(e.exposure_date, INTERVAL 90 DAY)
"""
```

### Landmark analysis windows

In survival analysis, a landmark time avoids immortal-time bias. Only participants who survive (or remain event-free) to the landmark are included, and prediction starts from that point:

```python
# Landmark at 90 days post-index: only include participants alive at day 90
landmark_sql = f"""
WITH idx AS (
    SELECT person_id, MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_concept_id = 201826
    GROUP BY person_id
),
landmark AS (
    SELECT idx.person_id, idx.index_date,
           DATE_ADD(idx.index_date, INTERVAL 90 DAY) AS landmark_date
    FROM idx
    -- Exclude participants who died before the landmark
    LEFT JOIN `{CDR}.death` d ON idx.person_id = d.person_id
    WHERE d.death_date IS NULL
       OR d.death_date > DATE_ADD(idx.index_date, INTERVAL 90 DAY)
)
SELECT *
FROM landmark
"""
```

### Cascading windows for temporal feature engineering

Split the pre-index period into multiple non-overlapping windows to capture recency effects:

```python
# Multiple baseline windows: 0-30, 31-90, 91-365 days before index
cascade_sql = f"""
WITH idx AS (
    SELECT person_id, MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_concept_id = 201826
    GROUP BY person_id
)
SELECT
    m.person_id,
    m.measurement_concept_id,
    CASE
        WHEN DATE_DIFF(idx.index_date, m.measurement_date, DAY)
             BETWEEN 1 AND 30 THEN 'recent_30d'
        WHEN DATE_DIFF(idx.index_date, m.measurement_date, DAY)
             BETWEEN 31 AND 90 THEN 'mid_90d'
        WHEN DATE_DIFF(idx.index_date, m.measurement_date, DAY)
             BETWEEN 91 AND 365 THEN 'distant_365d'
    END AS time_window,
    AVG(m.value_as_number) AS avg_value,
    COUNT(*) AS n_measurements
FROM `{CDR}.measurement` m
JOIN idx USING (person_id)
WHERE m.measurement_date >= DATE_SUB(idx.index_date, INTERVAL 365 DAY)
  AND m.measurement_date < idx.index_date
GROUP BY m.person_id, m.measurement_concept_id, time_window
"""
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `JOIN` returns zero rows | The index-date CTE matched no participants. Verify the `condition_concept_id` returns rows independently before joining. |
| `DATE_DIFF` returns NULL | Either `measurement_date` or `index_date` is NULL. Add `WHERE m.measurement_date IS NOT NULL` to the event query. |
| Query runs but returns far fewer rows than expected | The window may be too narrow, or many participants lack events in the window. Check the distribution of `days_from_index` before filtering. |

## Cost note

Cost depends on the event table scanned. `measurement` and `condition_occurrence` are among the largest OMOP tables. The index-date CTE is evaluated once and is small. For large cohorts, consider materializing the index-date table first to avoid re-scanning the condition table in every query.

## See also

- [Audit temporal leakage](audit-temporal-leakage.md) -- validate that your windowed features are leak-free
- [Build a SHAP-ready feature matrix](../statistical-modeling/build-shap-feature-matrix.md) -- assemble windowed features into a model-ready format

# Filter participants by observation period

Use the `observation_period` table to require minimum EHR data coverage before including a participant in your analysis.

## Prerequisites

- Researcher Workbench notebook environment with BigQuery access
- `os.environ["WORKSPACE_CDR"]` set to your CDR dataset

## Tier

Registered Tier (observation period metadata) / Controlled Tier (when joined to EHR tables)

## CDR versions

All CDR versions (v5+). The `observation_period` table structure is stable across versions.

## Reference

The `observation_period` table defines the time span during which a participant's data is considered reliably captured. Each row represents a contiguous period of data availability.

| Column | Description |
|---|---|
| `observation_period_id` | Unique row identifier |
| `person_id` | Participant identifier |
| `observation_period_start_date` | Start of the data coverage window |
| `observation_period_end_date` | End of the data coverage window |
| `period_type_concept_id` | How the period was derived |

In AoU, the observation period is typically computed from the earliest to latest recorded clinical event for each participant. A participant may have multiple observation periods if there are significant gaps in their data.

**Why this matters:** Without filtering on observation period, participants with only a single visit or a few months of recorded data are included alongside participants with years of longitudinal records. Sparse-data participants appear to have no conditions, no medications, and no labs -- not because they are healthy, but because their data is insufficient. This biases any analysis that interprets absence of records as absence of disease.

## Usage

### Inspect observation period distribution

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

obs_period_sql = f"""
SELECT
    person_id,
    observation_period_start_date,
    observation_period_end_date,
    DATE_DIFF(observation_period_end_date,
              observation_period_start_date, DAY) AS coverage_days
FROM `{CDR}.observation_period`
ORDER BY coverage_days DESC
"""
obs_df = client.query(obs_period_sql).to_dataframe()

print(f"Total participants with obs period: {obs_df.person_id.nunique():,}")
print(f"Coverage (days) summary:")
print(obs_df['coverage_days'].describe())
```

!!! pitfall "Pitfall"
    Not filtering by observation period at all is one of the most common sources of bias in AoU analyses. Participants with only a single visit or a few months of data will have sparse features that appear as "no conditions" or "no labs" when the data is simply insufficient. This inflates the apparent health of your cohort and systematically biases case-control comparisons -- controls look healthier than they are because their short observation windows never captured their real diagnoses.


### Require minimum coverage before inclusion

Filter to participants with at least 1 year (365 days) of data:

```python
MIN_COVERAGE_DAYS = 365

cohort_with_coverage_sql = f"""
WITH adequate_coverage AS (
    SELECT
        person_id,
        observation_period_start_date AS obs_start,
        observation_period_end_date AS obs_end,
        DATE_DIFF(observation_period_end_date,
                  observation_period_start_date, DAY) AS coverage_days
    FROM `{CDR}.observation_period`
    WHERE DATE_DIFF(observation_period_end_date,
                    observation_period_start_date, DAY) >= {MIN_COVERAGE_DAYS}
)
SELECT
    co.person_id,
    co.condition_concept_id,
    c.concept_name AS condition_name,
    co.condition_start_date,
    ac.obs_start,
    ac.obs_end,
    ac.coverage_days
FROM `{CDR}.condition_occurrence` co
JOIN adequate_coverage ac USING (person_id)
JOIN `{CDR}.concept` c
    ON co.condition_concept_id = c.concept_id
WHERE co.condition_start_date BETWEEN ac.obs_start AND ac.obs_end
ORDER BY co.person_id, co.condition_start_date
"""
filtered_df = client.query(cohort_with_coverage_sql).to_dataframe()
print(f"Participants with >= {MIN_COVERAGE_DAYS}d coverage: "
      f"{filtered_df.person_id.nunique():,}")
```

!!! pitfall "Pitfall"
    Do not treat `observation_period_start_date` as if it means "first contact with the healthcare system." It reflects the earliest recorded event in AoU's data for that person, which depends on which EHR systems contributed data and how far back those systems exported records. A participant whose observation period starts in 2018 may have been receiving care since 2005 at a system that did not contribute data to AoU. Do not use this date for incidence calculations or "time since first healthcare contact" analyses without acknowledging this left-truncation.


### Apply observation period filter to a study cohort

Template pattern for requiring coverage around an index date:

```python
LOOKBACK_DAYS = 365
FOLLOWUP_DAYS = 180

study_cohort_sql = f"""
WITH index_dates AS (
    SELECT
        person_id,
        MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence` co
    JOIN `{CDR}.concept_ancestor` ca
        ON co.condition_concept_id = ca.descendant_concept_id
    WHERE ca.ancestor_concept_id = 201826  -- Type 2 diabetes
    GROUP BY person_id
),
eligible AS (
    SELECT
        ix.person_id,
        ix.index_date,
        op.observation_period_start_date AS obs_start,
        op.observation_period_end_date AS obs_end
    FROM index_dates ix
    JOIN `{CDR}.observation_period` op USING (person_id)
    WHERE DATE_SUB(ix.index_date, INTERVAL {LOOKBACK_DAYS} DAY)
              >= op.observation_period_start_date
        AND DATE_ADD(ix.index_date, INTERVAL {FOLLOWUP_DAYS} DAY)
              <= op.observation_period_end_date
)
SELECT
    person_id,
    index_date,
    obs_start,
    obs_end,
    DATE_DIFF(index_date, obs_start, DAY) AS pre_index_days,
    DATE_DIFF(obs_end, index_date, DAY) AS post_index_days
FROM eligible
ORDER BY person_id
"""
eligible_df = client.query(study_cohort_sql).to_dataframe()
print(f"Eligible participants: {eligible_df.person_id.nunique():,}")
print(eligible_df[['pre_index_days', 'post_index_days']].describe())
```

## Variations

### 1. Require continuous enrollment analog (overlap with study window)

Ensure a participant's observation period fully covers your study window:

```python
STUDY_START = '2020-01-01'
STUDY_END = '2022-12-31'

enrollment_sql = f"""
SELECT
    person_id,
    observation_period_start_date,
    observation_period_end_date,
    DATE_DIFF(observation_period_end_date,
              observation_period_start_date, DAY) AS coverage_days
FROM `{CDR}.observation_period`
WHERE observation_period_start_date <= '{STUDY_START}'
    AND observation_period_end_date >= '{STUDY_END}'
"""
enrolled_df = client.query(enrollment_sql).to_dataframe()
print(f"Participants with continuous coverage "
      f"{STUDY_START} to {STUDY_END}: {enrolled_df.person_id.nunique():,}")
```

### 2. Compute data density (events per year of observation)

Distinguish participants with genuine low utilization from those with sparse data:

```python
density_sql = f"""
WITH coverage AS (
    SELECT
        person_id,
        DATE_DIFF(observation_period_end_date,
                  observation_period_start_date, DAY) / 365.25
            AS obs_years
    FROM `{CDR}.observation_period`
    WHERE DATE_DIFF(observation_period_end_date,
                    observation_period_start_date, DAY) >= 365
),
event_counts AS (
    SELECT person_id, COUNT(*) AS n_conditions
    FROM `{CDR}.condition_occurrence`
    GROUP BY person_id
)
SELECT
    cov.person_id,
    ROUND(cov.obs_years, 1) AS observation_years,
    COALESCE(ec.n_conditions, 0) AS total_conditions,
    ROUND(COALESCE(ec.n_conditions, 0) / cov.obs_years, 1)
        AS conditions_per_year
FROM coverage cov
LEFT JOIN event_counts ec USING (person_id)
ORDER BY conditions_per_year
"""
density_df = client.query(density_sql).to_dataframe()
print(density_df.describe())
```

### 3. Handle multiple observation periods per participant

Some participants have gaps that produce multiple periods. Merge them or take the longest:

```python
merged_periods_sql = f"""
WITH ranked AS (
    SELECT
        person_id,
        observation_period_start_date,
        observation_period_end_date,
        DATE_DIFF(observation_period_end_date,
                  observation_period_start_date, DAY) AS coverage_days,
        ROW_NUMBER() OVER (
            PARTITION BY person_id
            ORDER BY DATE_DIFF(observation_period_end_date,
                               observation_period_start_date, DAY) DESC
        ) AS rn
    FROM `{CDR}.observation_period`
)
SELECT
    person_id,
    observation_period_start_date AS longest_start,
    observation_period_end_date AS longest_end,
    coverage_days
FROM ranked
WHERE rn = 1
"""
longest_df = client.query(merged_periods_sql).to_dataframe()
longest_df.head()
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| A participant in your cohort has no row in `observation_period` | Survey-only participants may lack an observation period if they have no EHR events. Join with `LEFT JOIN` and handle NULLs. |
| `coverage_days` is 0 for many participants | These participants have only a single recorded event (start = end). Filter them out with `HAVING coverage_days > 0`. |
| Observation period dates extend into the future | Data quality issue in the source EHR. Cap `observation_period_end_date` at the CDR build date or current date. |

## Deep dive

The observation period in AoU is not analogous to "continuous enrollment" in claims data. Claims databases define enrollment by active insurance coverage; AoU derives observation periods from the span of recorded clinical events. This distinction matters:

- **Left truncation:** A participant's true healthcare history predates their AoU observation period if their earlier care was at a non-contributing institution.
- **Right censoring:** The observation period ends at the last recorded event, not at a known disenrollment date. Absence of events after the end date could mean the participant left the AoU data network, died, or simply had no healthcare encounters.
- **Gaps:** Unlike claims, there is no monthly enrollment indicator. A 5-year observation period does not guarantee continuous data -- the participant may have had a 2-year gap with care at a non-contributing provider.

For study designs that require true continuous enrollment (e.g., new-user cohort studies), supplement observation period filtering with data density checks (Variation 2) to ensure the observation window contains meaningful data.

## Cost note

The `observation_period` table is small (one or a few rows per participant). Queries against it alone are inexpensive. It is an ideal first-pass filter to apply via CTE before joining to large clinical tables.

## See also

- [Query visit occurrence](../visits/query-visit-occurrence.md) -- for computing observation spans from actual visit records
- [Distinguish EHR from survey data sources](../data-quality/distinguish-ehr-survey-sources.md) -- observation period applies primarily to EHR data
- [Query survey responses](../surveys/query-survey-responses.md) -- survey-only participants may lack observation periods

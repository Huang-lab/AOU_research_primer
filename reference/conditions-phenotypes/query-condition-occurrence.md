# Query condition occurrence with date constraints

Pull conditions from `condition_occurrence` within a date window relative to an index date (e.g., enrollment, first diagnosis, or procedure date).

## Prerequisites

- Researcher Workbench notebook environment
- `pandas`, `google-cloud-bigquery` installed (default in AoU environment)

## Tier availability

| Feature | Registered Tier | Controlled Tier |
|---|---|---|
| `condition_occurrence` | Yes | Yes |
| Exact dates (`condition_start_date`) | Shifted (per-participant random offset) | Real dates |
| Date arithmetic (relative intervals) | Valid (shift is consistent within participant) | Valid |

## CDR versions

All CDR versions (v5+). The `condition_occurrence` table follows the OMOP CDM standard.

---

## Reference

### Key tables

| Table | Purpose |
|---|---|
| `condition_occurrence` | One row per condition record. Contains diagnosis dates, provenance, and SNOMED concept IDs. |
| `concept` | Maps `condition_concept_id` to human-readable condition names (SNOMED standard vocabulary). |
| `concept_ancestor` | Hierarchical relationships between concepts. Used to query a parent concept and capture all descendant conditions. |

### Key columns on `condition_occurrence`

| Column | Type | Notes |
|---|---|---|
| `person_id` | INT64 | Participant identifier |
| `condition_concept_id` | INT64 | Standard SNOMED concept ID for the condition |
| `condition_start_date` | DATE | Date the condition was recorded. Shifted in Registered Tier. |
| `condition_end_date` | DATE | Often NULL or unreliable |
| `condition_type_concept_id` | INT64 | Provenance: EHR (32817), claim (32810), self-report, etc. |
| `condition_source_value` | STRING | Source code as recorded (e.g., ICD-10 code string like "E11.9") |
| `condition_source_concept_id` | INT64 | Concept ID for the source vocabulary code |
| `condition_status_concept_id` | INT64 | Preliminary, confirmed, resolved, etc. |

---

## Usage

### Basic: conditions within an absolute date window

This pattern works when you need conditions within a calendar period (e.g., all diagnoses in 2020). This is meaningful only in the Controlled Tier where dates are real.

```python
import os
import pandas as pd
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

condition_query = f"""
SELECT
    co.person_id,
    co.condition_concept_id,
    c.concept_name          AS condition_name,
    co.condition_start_date,
    co.condition_type_concept_id
FROM `{CDR}.condition_occurrence` co
JOIN `{CDR}.concept` c
    ON co.condition_concept_id = c.concept_id
WHERE co.condition_concept_id = 201826  -- Type 2 diabetes (SNOMED)
  AND co.condition_start_date BETWEEN '2018-01-01' AND '2022-12-31'
"""

conditions_df = client.query(condition_query).to_dataframe()
```

> **Pitfall -- absolute date filters are meaningless in the Registered Tier.**
> In the Registered Tier, all dates in `condition_occurrence` are shifted by a random per-participant offset (up to +/- 365 days). A filter like `condition_start_date BETWEEN '2020-01-01' AND '2020-12-31'` does NOT select conditions that actually occurred in 2020 -- it selects conditions whose shifted dates happen to land in that range. The shift is consistent *within* a participant (so relative date differences are preserved), but absolute calendar positions are meaningless. Use relative dates instead.

### Recommended: conditions relative to an index date

This pattern works correctly in both tiers because the per-participant date shift cancels out in relative differences.

```python
# Step 1: Define an index date per participant
# Example: first recorded Type 2 diabetes diagnosis
index_query = f"""
SELECT
    person_id,
    MIN(condition_start_date) AS index_date
FROM `{CDR}.condition_occurrence`
WHERE condition_concept_id = 201826  -- Type 2 diabetes
GROUP BY person_id
"""

index_df = client.query(index_query).to_dataframe()
```

```python
# Step 2: Pull all conditions within 365 days before the index
relative_query = f"""
WITH index_dates AS (
    SELECT person_id, MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_concept_id = 201826
    GROUP BY person_id
)
SELECT
    co.person_id,
    c.concept_name              AS condition_name,
    co.condition_start_date,
    DATE_DIFF(co.condition_start_date,
              idx.index_date, DAY) AS days_from_index,
    co.condition_type_concept_id
FROM `{CDR}.condition_occurrence` co
JOIN index_dates idx
    ON co.person_id = idx.person_id
JOIN `{CDR}.concept` c
    ON co.condition_concept_id = c.concept_id
WHERE DATE_DIFF(co.condition_start_date,
                idx.index_date, DAY) BETWEEN -365 AND 0
"""

pre_index_df = client.query(relative_query).to_dataframe()
```

> **Pitfall -- ignoring `condition_type_concept_id`.**
> The `condition_type_concept_id` column tells you *where* the diagnosis came from: EHR problem lists (32817), billing claims (32810), self-reported survey responses, or other sources. These have very different levels of clinical validation. An EHR-confirmed diagnosis of diabetes is not the same as a self-reported one. If you combine all provenance types without accounting for the difference, you get a heterogeneous phenotype that mixes clinician-verified conditions with unvalidated self-reports. At minimum, filter to EHR sources for clinical phenotyping, or include `condition_type_concept_id` as a covariate. Always report which provenance types you included.

---

## Variations

### 1. Pre-index-date conditions only (comorbidity history)

Useful for building baseline comorbidity profiles (e.g., Charlson comorbidity index).

```python
history_query = f"""
WITH index_dates AS (
    SELECT person_id, MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_concept_id = 201826
    GROUP BY person_id
)
SELECT
    co.person_id,
    co.condition_concept_id,
    c.concept_name AS condition_name,
    DATE_DIFF(co.condition_start_date,
              idx.index_date, DAY) AS days_before_index
FROM `{CDR}.condition_occurrence` co
JOIN index_dates idx ON co.person_id = idx.person_id
JOIN `{CDR}.concept` c ON co.condition_concept_id = c.concept_id
WHERE co.condition_start_date < idx.index_date
  AND co.condition_type_concept_id = 32817  -- EHR only
"""
```

### 2. Post-index-date conditions only (incident outcomes)

Useful for survival analysis and outcome studies. Exclude conditions that existed before the index date to find *new* diagnoses.

```python
outcome_query = f"""
WITH index_dates AS (
    SELECT person_id, MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_concept_id = 201826
    GROUP BY person_id
),
-- Exclude anyone with the outcome before index
prevalent AS (
    SELECT DISTINCT co.person_id
    FROM `{CDR}.condition_occurrence` co
    JOIN index_dates idx ON co.person_id = idx.person_id
    WHERE co.condition_concept_id = 4329847  -- Myocardial infarction
      AND co.condition_start_date < idx.index_date
)
SELECT
    co.person_id,
    co.condition_start_date,
    DATE_DIFF(co.condition_start_date,
              idx.index_date, DAY) AS days_to_event
FROM `{CDR}.condition_occurrence` co
JOIN index_dates idx ON co.person_id = idx.person_id
WHERE co.condition_concept_id = 4329847
  AND co.condition_start_date >= idx.index_date
  AND co.person_id NOT IN (SELECT person_id FROM prevalent)
ORDER BY co.person_id
"""
```

### 3. Including descendant conditions via `concept_ancestor`

Capture all conditions under a SNOMED hierarchy node (e.g., all types of diabetes, not just the exact code).

```python
hierarchy_query = f"""
SELECT
    co.person_id,
    co.condition_concept_id,
    c.concept_name AS condition_name,
    co.condition_start_date
FROM `{CDR}.condition_occurrence` co
JOIN `{CDR}.concept_ancestor` ca
    ON co.condition_concept_id = ca.descendant_concept_id
JOIN `{CDR}.concept` c
    ON co.condition_concept_id = c.concept_id
WHERE ca.ancestor_concept_id = 201820  -- Diabetes mellitus (parent)
"""
```

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Query returns zero rows for a known-common condition | Verify the `condition_concept_id` exists in your CDR version. Query `concept` with the SNOMED code to confirm: `SELECT * FROM concept WHERE concept_id = 201826`. |
| Unexpected duplicate rows per person per date | Multiple condition records can exist for the same condition on the same date from different sources (EHR + claim). Add `DISTINCT` or group by `condition_type_concept_id`. |
| `condition_end_date` is NULL for most rows | Expected behavior. Many EHR systems do not reliably populate end dates. Do not use `condition_end_date` for duration calculations without first checking completeness. |
| Date filter returns different counts than expected in Registered Tier | Dates are shifted. Absolute date filters do not correspond to real calendar dates. Use relative date patterns. |

---

## Cost note

The `condition_occurrence` table is one of the larger OMOP tables in AoU (tens of millions of rows). Filtering by `condition_concept_id` or joining on a cohort's `person_id` list in a CTE significantly reduces bytes scanned. Avoid `SELECT *` without filters.

---

## See also

- [build-multi-code-phenotype.md](build-multi-code-phenotype.md) -- Combining multiple condition codes into a single phenotype
- [query-lab-measurements.md](../labs-measurements/query-lab-measurements.md) -- Adding lab values to condition-based cohorts
- [extract-demographic-features.md](../demographics-ancestry/extract-demographic-features.md) -- Joining demographics to conditions

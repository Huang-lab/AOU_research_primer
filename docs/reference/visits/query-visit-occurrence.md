# Query visit occurrence and aggregate by encounter

Pull from `visit_occurrence` to count visits, compute healthcare utilization, or anchor clinical events to encounters.

## Prerequisites

- Researcher Workbench notebook environment with BigQuery access
- `os.environ["WORKSPACE_CDR"]` set to your CDR dataset

## Tier

Controlled Tier (visit records derive from EHR data)

## CDR versions

All CDR versions (v5+). The `visit_occurrence` table structure is stable across versions.

## Reference

The `visit_occurrence` table records encounters between a participant and the healthcare system. Each row represents one visit with a start/end date and a visit type.

Standard visit type concept IDs:

| `visit_concept_id` | Visit type |
|---|---|
| 9201 | Inpatient Visit |
| 9202 | Outpatient Visit |
| 9203 | Emergency Room Visit |
| 9204 | Non-hospital institution visit |
| 581477 | Emergency Room and Inpatient Visit |
| 38004515 | Telehealth Visit |
| 44818518 | Office Visit |

Key columns:

| Column | Description |
|---|---|
| `visit_occurrence_id` | Unique visit identifier; FK target for clinical tables |
| `visit_concept_id` | Standard concept for visit type |
| `visit_start_date` / `visit_end_date` | Visit date range |
| `visit_start_datetime` / `visit_end_datetime` | Visit timestamp range (may be NULL) |
| `visit_type_concept_id` | Provenance of the visit record (EHR, claim, etc.) |

## Usage

### Count visits by type per participant

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

visit_counts_sql = f"""
SELECT
    vo.person_id,
    c.concept_name AS visit_type,
    COUNT(*) AS visit_count,
    MIN(vo.visit_start_date) AS first_visit,
    MAX(vo.visit_start_date) AS last_visit
FROM `{CDR}.visit_occurrence` vo
JOIN `{CDR}.concept` c
    ON vo.visit_concept_id = c.concept_id
GROUP BY vo.person_id, c.concept_name
ORDER BY vo.person_id, visit_count DESC
"""
visits_df = client.query(visit_counts_sql).to_dataframe()
visits_df.head(20)
```

!!! pitfall "Pitfall"
    Counting raw `visit_occurrence` rows as a measure of healthcare utilization without stratifying by visit type produces misleading results. A single ER visit followed by 3 outpatient follow-ups registers as 4 visits -- appearing as "higher utilization" than a participant with 2 ER visits and no follow-up. If your analysis compares utilization across groups, always stratify by `visit_concept_id` or define utilization as a weighted composite that accounts for visit severity.


### Join clinical events to visits

Anchor diagnoses, labs, or procedures to specific encounters:

```python
events_with_visits_sql = f"""
SELECT
    co.person_id,
    co.condition_start_date,
    cond.concept_name AS condition_name,
    vo.visit_concept_id,
    visit_type.concept_name AS visit_type,
    vo.visit_start_date,
    vo.visit_end_date
FROM `{CDR}.condition_occurrence` co
LEFT JOIN `{CDR}.visit_occurrence` vo
    ON co.visit_occurrence_id = vo.visit_occurrence_id
LEFT JOIN `{CDR}.concept` cond
    ON co.condition_concept_id = cond.concept_id
LEFT JOIN `{CDR}.concept` visit_type
    ON vo.visit_concept_id = visit_type.concept_id
WHERE co.condition_concept_id = 201826  -- Type 2 diabetes
ORDER BY co.person_id, co.condition_start_date
LIMIT 50
"""
events_df = client.query(events_with_visits_sql).to_dataframe()
events_df.head(20)
```

!!! pitfall "Pitfall"
    The `visit_occurrence_id` foreign key in clinical tables (`condition_occurrence`, `procedure_occurrence`, `measurement`, etc.) is frequently NULL in AoU data. An INNER JOIN on `visit_occurrence_id` silently drops every clinical event that lacks a visit link. Always use a LEFT JOIN when your goal is to retain all clinical events and optionally enrich them with visit context. Check the NULL rate before relying on visit-linked analyses:


```python
null_check_sql = f"""
SELECT
    COUNTIF(visit_occurrence_id IS NULL) AS null_visit_fk,
    COUNT(*) AS total_rows,
    ROUND(COUNTIF(visit_occurrence_id IS NULL) / COUNT(*) * 100, 1)
        AS pct_null
FROM `{CDR}.condition_occurrence`
"""
client.query(null_check_sql).to_dataframe()
```

### Summarize visit patterns across the cohort

```python
cohort_summary_sql = f"""
SELECT
    c.concept_name AS visit_type,
    COUNT(*) AS total_visits,
    COUNT(DISTINCT vo.person_id) AS unique_patients,
    ROUND(COUNT(*) / COUNT(DISTINCT vo.person_id), 1)
        AS avg_visits_per_patient
FROM `{CDR}.visit_occurrence` vo
JOIN `{CDR}.concept` c
    ON vo.visit_concept_id = c.concept_id
GROUP BY c.concept_name
ORDER BY total_visits DESC
"""
summary_df = client.query(cohort_summary_sql).to_dataframe()
summary_df
```

## Variations

### 1. Compute observation period length from first to last visit

Derive actual data span per participant from visit records rather than the `observation_period` table:

```python
obs_span_sql = f"""
SELECT
    person_id,
    MIN(visit_start_date) AS first_visit_date,
    MAX(visit_start_date) AS last_visit_date,
    DATE_DIFF(MAX(visit_start_date),
              MIN(visit_start_date), DAY) AS span_days,
    COUNT(*) AS total_visits
FROM `{CDR}.visit_occurrence`
GROUP BY person_id
HAVING COUNT(*) >= 2
ORDER BY span_days DESC
"""
span_df = client.query(obs_span_sql).to_dataframe()
span_df.describe()
```

### 2. Inpatient-only event filtering

Restrict clinical events to those that occurred during an inpatient stay:

```python
inpatient_events_sql = f"""
SELECT
    co.person_id,
    co.condition_start_date,
    cond.concept_name AS condition_name,
    vo.visit_start_date AS admission_date,
    vo.visit_end_date AS discharge_date,
    DATE_DIFF(vo.visit_end_date, vo.visit_start_date, DAY)
        AS length_of_stay
FROM `{CDR}.condition_occurrence` co
JOIN `{CDR}.visit_occurrence` vo
    ON co.visit_occurrence_id = vo.visit_occurrence_id
JOIN `{CDR}.concept` cond
    ON co.condition_concept_id = cond.concept_id
WHERE vo.visit_concept_id IN (9201, 581477)  -- Inpatient, ER+Inpatient
ORDER BY co.person_id, vo.visit_start_date
"""
inpatient_df = client.query(inpatient_events_sql).to_dataframe()
inpatient_df.head(20)
```

Note: this variation uses an INNER JOIN intentionally -- events without a visit link cannot be confirmed as inpatient, so excluding them is correct here.

### 3. Identify ER-to-inpatient escalation

Find ER visits that escalated to inpatient admissions:

```python
er_escalation_sql = f"""
WITH er_visits AS (
    SELECT person_id, visit_occurrence_id,
           visit_start_date AS er_date
    FROM `{CDR}.visit_occurrence`
    WHERE visit_concept_id = 9203  -- ER
),
ip_visits AS (
    SELECT person_id, visit_start_date AS admit_date,
           visit_end_date AS discharge_date
    FROM `{CDR}.visit_occurrence`
    WHERE visit_concept_id IN (9201, 581477)  -- Inpatient
)
SELECT
    er.person_id,
    er.er_date,
    ip.admit_date,
    ip.discharge_date,
    DATE_DIFF(ip.admit_date, er.er_date, DAY) AS days_er_to_admit
FROM er_visits er
JOIN ip_visits ip
    ON er.person_id = ip.person_id
    AND ip.admit_date BETWEEN er.er_date
        AND DATE_ADD(er.er_date, INTERVAL 1 DAY)
ORDER BY er.person_id, er.er_date
"""
escalation_df = client.query(er_escalation_sql).to_dataframe()
escalation_df.head()
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `visit_concept_id = 0` in many rows | Visit type was not mapped to a standard concept. Check `visit_source_concept_id` and `visit_source_value` for the original code. |
| Length-of-stay calculation returns negative values | `visit_end_date` can precede `visit_start_date` in rare data quality issues. Add `HAVING DATE_DIFF(...) >= 0` or filter in post-processing. |
| JOIN on `visit_occurrence_id` returns far fewer rows than expected | The FK is NULL for many clinical records. Use LEFT JOIN and check NULL rate (see pitfall above). |

## Cost note

The `visit_occurrence` table is moderate in size. Queries that join it to large clinical tables (`condition_occurrence`, `measurement`) can become expensive. Filter the clinical table first, then join to visits, rather than scanning all visits and then filtering.

## See also

- [Query procedure occurrence](../procedures/query-procedure-occurrence.md) -- for procedure events anchored to visits
- [Filter by observation period](../data-quality/filter-by-observation-period.md) -- for requiring minimum data coverage
- [Distinguish EHR from survey data sources](../data-quality/distinguish-ehr-survey-sources.md) -- visits are EHR-derived records

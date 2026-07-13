# Distinguish EHR from survey data sources

Determine the provenance of a record in AoU -- whether it originated from EHR, surveys, physical measurements, wearables, or genomics -- and filter accordingly.

## Prerequisites

- Researcher Workbench notebook environment with BigQuery access
- `os.environ["WORKSPACE_CDR"]` set to your CDR dataset

## Tier

Registered Tier (survey data) / Controlled Tier (EHR data)

## CDR versions

All CDR versions (v5+). Type concept IDs are stable; specific values may expand as new data sources are added.

## Reference

AoU integrates data from multiple sources into the same OMOP tables. A "diabetes" record in `condition_occurrence` could be an EHR ICD-10 diagnosis or a self-reported survey response. A "blood pressure" measurement in `measurement` could be from an EHR lab panel or a physical measurement taken at an AoU enrollment visit. These have fundamentally different provenance, sensitivity, and specificity.

The primary mechanism for distinguishing source is the `*_type_concept_id` column present in every clinical table:

| Table | Type column | Key type concept IDs |
|---|---|---|
| `condition_occurrence` | `condition_type_concept_id` | 32817 (EHR), 32883 (Survey) |
| `measurement` | `measurement_type_concept_id` | 32817 (EHR), 32883 (Survey), 44818701 (Physical Measurement) |
| `observation` | `observation_type_concept_id` | 32817 (EHR), 32883 (Survey) |
| `drug_exposure` | `drug_type_concept_id` | 32817 (EHR), 32838 (EHR prescription) |
| `procedure_occurrence` | `procedure_type_concept_id` | 32817 (EHR) |

Common type concept IDs across tables:

| `type_concept_id` | Meaning |
|---|---|
| 32817 | EHR |
| 32838 | EHR prescription |
| 32883 | Survey |
| 44818701 | Patient reported / Physical Measurement |
| 32846 | EHR problem list |
| 32840 | EHR chief complaint |

Additional signals for provenance:

- `observation_source_value` for survey records often contains the survey module prefix (e.g., `TheBasics_`, `OverallHealth_`)
- Physical measurements taken at AoU enrollment have specific `measurement_concept_id` values and a `measurement_type_concept_id` of 44818701
- The `cb_search_all_events` table (Cohort Builder) includes a `is_standard` flag that can help distinguish source mappings

## Usage

### Audit provenance distribution for a condition

Check how records for a given condition split across data sources:

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

provenance_sql = f"""
SELECT
    type_c.concept_id AS type_concept_id,
    type_c.concept_name AS source_type,
    COUNT(*) AS record_count,
    COUNT(DISTINCT co.person_id) AS patient_count
FROM `{CDR}.condition_occurrence` co
JOIN `{CDR}.concept_ancestor` ca
    ON co.condition_concept_id = ca.descendant_concept_id
JOIN `{CDR}.concept` type_c
    ON co.condition_type_concept_id = type_c.concept_id
WHERE ca.ancestor_concept_id = 201826  -- Type 2 diabetes
GROUP BY type_c.concept_id, type_c.concept_name
ORDER BY record_count DESC
"""
prov_df = client.query(provenance_sql).to_dataframe()
prov_df
```

> **Pitfall:** Mixing EHR-derived and survey-derived conditions without accounting for provenance creates a heterogeneous case definition. Self-reported conditions from surveys have different sensitivity and specificity than EHR diagnoses -- a participant who self-reports "diabetes" on a survey may have prediabetes, gestational diabetes, or a misunderstanding of their diagnosis. An EHR ICD-10 code for T2DM has been assigned by a clinician. A "diabetes" phenotype that mixes both sources without distinguishing them will have inconsistent case ascertainment, biasing prevalence estimates and weakening associations in downstream analyses.

### Separate EHR from survey conditions

```python
EHR_TYPE_IDS = [32817, 32846, 32840, 32838]

ehr_only_sql = f"""
SELECT
    co.person_id,
    co.condition_start_date,
    c.concept_name AS condition_name,
    type_c.concept_name AS source_type
FROM `{CDR}.condition_occurrence` co
JOIN `{CDR}.concept` c
    ON co.condition_concept_id = c.concept_id
JOIN `{CDR}.concept` type_c
    ON co.condition_type_concept_id = type_c.concept_id
WHERE co.condition_type_concept_id IN ({','.join(str(x) for x in EHR_TYPE_IDS)})
    AND co.condition_concept_id IN (
        SELECT descendant_concept_id
        FROM `{CDR}.concept_ancestor`
        WHERE ancestor_concept_id = 201826  -- Type 2 diabetes
    )
ORDER BY co.person_id, co.condition_start_date
"""
ehr_conditions_df = client.query(ehr_only_sql).to_dataframe()
print(f"EHR-only diabetes patients: "
      f"{ehr_conditions_df.person_id.nunique():,}")
```

### Audit measurement provenance

Identify which measurements come from EHR labs vs. AoU physical measurements:

```python
measurement_sources_sql = f"""
SELECT
    m.measurement_concept_id,
    mc.concept_name AS measurement_name,
    type_c.concept_id AS type_concept_id,
    type_c.concept_name AS source_type,
    COUNT(*) AS record_count,
    COUNT(DISTINCT m.person_id) AS patient_count
FROM `{CDR}.measurement` m
JOIN `{CDR}.concept` mc
    ON m.measurement_concept_id = mc.concept_id
JOIN `{CDR}.concept` type_c
    ON m.measurement_type_concept_id = type_c.concept_id
WHERE m.measurement_concept_id IN (
    3004249,   -- Systolic blood pressure
    3012888,   -- Diastolic blood pressure
    3023314,   -- Heart rate
    3038553    -- BMI
)
GROUP BY 1, 2, 3, 4
ORDER BY measurement_name, record_count DESC
"""
meas_sources_df = client.query(measurement_sources_sql).to_dataframe()
meas_sources_df
```

> **Pitfall:** Physical measurements (height, weight, blood pressure, heart rate) taken at AoU enrollment visits are stored in the same `measurement` table as EHR lab results. These measurements follow different protocols -- AoU enrollment measurements are taken by trained staff using standardized equipment and procedures, while EHR vitals vary by clinical setting, equipment, and staff training. Mixing them in aggregate statistics (e.g., mean systolic BP) produces inconsistent results. Filter by `measurement_type_concept_id` to separate them, or include the source as a covariate.

## Variations

### 1. EHR-only cohort filtering

Create a reusable CTE that restricts an entire analysis to EHR-derived records:

```python
ehr_cohort_sql = f"""
WITH ehr_conditions AS (
    SELECT person_id, condition_concept_id, condition_start_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_type_concept_id IN (32817, 32846, 32840)
),
ehr_measurements AS (
    SELECT person_id, measurement_concept_id,
           value_as_number, measurement_date
    FROM `{CDR}.measurement`
    WHERE measurement_type_concept_id = 32817
),
ehr_drugs AS (
    SELECT person_id, drug_concept_id, drug_exposure_start_date
    FROM `{CDR}.drug_exposure`
    WHERE drug_type_concept_id IN (32817, 32838)
)
-- Example: T2DM patients with HbA1c labs and metformin
SELECT DISTINCT ec.person_id
FROM ehr_conditions ec
JOIN `{CDR}.concept_ancestor` ca
    ON ec.condition_concept_id = ca.descendant_concept_id
    AND ca.ancestor_concept_id = 201826   -- T2DM
JOIN ehr_measurements em
    ON ec.person_id = em.person_id
    AND em.measurement_concept_id = 3004410  -- HbA1c
JOIN ehr_drugs ed
    ON ec.person_id = ed.person_id
    AND ed.drug_concept_id IN (
        SELECT descendant_concept_id
        FROM `{CDR}.concept_ancestor`
        WHERE ancestor_concept_id = 1503297  -- Metformin
    )
"""
ehr_cohort_df = client.query(ehr_cohort_sql).to_dataframe()
print(f"EHR-confirmed T2DM on metformin with HbA1c: "
      f"{ehr_cohort_df.person_id.nunique():,}")
```

### 2. Survey-only phenotyping

Use survey responses exclusively for conditions that may not appear in EHR (e.g., self-reported mental health):

```python
survey_pheno_sql = f"""
SELECT
    o.person_id,
    question.concept_name AS question_text,
    answer.concept_name AS answer_text,
    o.observation_date
FROM `{CDR}.observation` o
JOIN `{CDR}.concept` question
    ON o.observation_concept_id = question.concept_id
LEFT JOIN `{CDR}.concept` answer
    ON o.value_as_concept_id = answer.concept_id
WHERE o.observation_type_concept_id = 32883  -- Survey
    AND o.observation_source_value LIKE 'OverallHealth_%'
    AND LOWER(question.concept_name) LIKE '%depression%'
ORDER BY o.person_id
"""
survey_df = client.query(survey_pheno_sql).to_dataframe()
survey_df.head(20)
```

### 3. Compare EHR vs. survey concordance

Measure agreement between self-reported and EHR-diagnosed conditions:

```python
concordance_sql = f"""
WITH ehr_cases AS (
    SELECT DISTINCT person_id
    FROM `{CDR}.condition_occurrence`
    WHERE condition_type_concept_id IN (32817, 32846)
        AND condition_concept_id IN (
            SELECT descendant_concept_id
            FROM `{CDR}.concept_ancestor`
            WHERE ancestor_concept_id = 201826
        )
),
survey_cases AS (
    SELECT DISTINCT person_id
    FROM `{CDR}.condition_occurrence`
    WHERE condition_type_concept_id = 32883
        AND condition_concept_id IN (
            SELECT descendant_concept_id
            FROM `{CDR}.concept_ancestor`
            WHERE ancestor_concept_id = 201826
        )
)
SELECT
    COUNTIF(e.person_id IS NOT NULL AND s.person_id IS NOT NULL)
        AS both_sources,
    COUNTIF(e.person_id IS NOT NULL AND s.person_id IS NULL)
        AS ehr_only,
    COUNTIF(e.person_id IS NULL AND s.person_id IS NOT NULL)
        AS survey_only,
    COUNTIF(e.person_id IS NULL AND s.person_id IS NULL)
        AS neither
FROM `{CDR}.person` p
LEFT JOIN ehr_cases e USING (person_id)
LEFT JOIN survey_cases s USING (person_id)
"""
concordance_df = client.query(concordance_sql).to_dataframe()
concordance_df
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `condition_type_concept_id = 0` for many records | Type concept was not populated in the source data. These records have unknown provenance; decide whether to include or exclude them from your analysis and document the decision. |
| All measurements appear as a single type | Your CDR version may use a different set of type concept IDs. Run `SELECT DISTINCT measurement_type_concept_id` to see what values exist. |
| Survey conditions not appearing in `condition_occurrence` | In some CDR versions, self-reported conditions from surveys are stored only in `observation`, not `condition_occurrence`. Query `observation` with `observation_type_concept_id = 32883`. |

## Deep dive

The distinction between EHR and survey data in AoU has implications beyond simple filtering:

**Phenotype validity.** EHR diagnoses reflect clinical judgment but are influenced by billing incentives and documentation practices. Survey responses reflect participant perception but are subject to recall bias and health literacy. Neither is ground truth. Robust phenotyping algorithms in AoU often require concordance between both sources (e.g., self-reported diabetes AND at least one EHR ICD-10 code AND an HbA1c >= 6.5%).

**Temporality.** Survey responses capture point-in-time self-reports (date = survey completion date). EHR diagnoses capture when a clinician recorded the condition (which may lag true onset). Mixing these in time-to-event analyses requires careful handling of each source's temporal semantics.

**Missing data patterns.** Not all participants contribute both EHR and survey data. Restricting to EHR-only excludes participants without linked EHR records, introducing selection bias. Restricting to survey-only limits you to the questions that were asked, with no ability to capture incident conditions between survey waves.

## Cost note

No additional cost -- this is a filter applied to existing queries. Adding a `WHERE *_type_concept_id IN (...)` clause does not increase scan size because the filter is applied during the scan. Joining to `concept` for the type label adds negligible overhead.

## See also

- [Query survey responses](../surveys/query-survey-responses.md) -- for pulling survey-specific data
- [Filter by observation period](../data-quality/filter-by-observation-period.md) -- observation periods are computed from EHR events; survey-only participants may lack them
- [Query visit occurrence](../visits/query-visit-occurrence.md) -- visits are EHR-derived; use visit context to confirm provenance

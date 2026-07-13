# Query survey responses

Pull participant answers from AoU survey modules and map concept IDs to human-readable response values.

## Prerequisites

- Researcher Workbench notebook environment with BigQuery access
- `os.environ["WORKSPACE_CDR"]` set to your CDR dataset

## Tier

Registered Tier (all survey modules) / Controlled Tier (for linked EHR)

## CDR versions

- CDR v7+: surveys available in both `observation` and the denormalized `ds_survey` table
- CDR v5--v6: use `observation` only; `ds_survey` not yet available

## Reference

AoU surveys are stored as OMOP **observation** records. Each survey question is a distinct `observation_concept_id`, and each answer is encoded in one of several value columns depending on the question type:

| Question type | Value column | Example |
|---|---|---|
| Categorical (most questions) | `value_as_concept_id` | Race, insurance status |
| Free-text | `value_as_string` | ZIP code, free-response |
| Numeric | `value_as_number` | Number of cigarettes per day |

Survey modules are identified by the `observation_source_value` prefix or by joining to the `cb_criteria` table. Key modules:

| Module | Observation source prefix |
|---|---|
| The Basics | `TheBasics_` |
| Overall Health | `OverallHealth_` |
| Lifestyle | `Lifestyle_` |
| Healthcare Access | `HealthcareAccess_` |
| COPE (COVID) | `cope_` |
| Social Determinants of Health | `sdoh_` |

The newer `ds_survey` table pre-joins questions and answers with readable strings, but it is only available in CDR v7+.

## Usage

### Find survey question concept IDs

Look up concept IDs for a specific question by keyword:

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

find_questions_sql = f"""
SELECT
    observation_concept_id,
    observation_source_value,
    concept.concept_name AS question_text,
    COUNT(DISTINCT person_id) AS respondent_count
FROM `{CDR}.observation` o
JOIN `{CDR}.concept` concept
    ON o.observation_concept_id = concept.concept_id
WHERE LOWER(concept.concept_name) LIKE '%income%'
    AND observation_concept_id != 0
GROUP BY 1, 2, 3
ORDER BY respondent_count DESC
LIMIT 20
"""
question_df = client.query(find_questions_sql).to_dataframe()
question_df
```

### Pull responses for a specific question

Once you have the `observation_concept_id`, retrieve responses with readable answer labels:

```python
QUESTION_CONCEPT_ID = 1585375  # Annual household income

survey_sql = f"""
SELECT
    o.person_id,
    o.observation_date,
    o.value_as_concept_id,
    answer.concept_name AS answer_text,
    o.value_as_number
FROM `{CDR}.observation` o
LEFT JOIN `{CDR}.concept` answer
    ON o.value_as_concept_id = answer.concept_id
WHERE o.observation_concept_id = {QUESTION_CONCEPT_ID}
ORDER BY o.person_id
"""
responses_df = client.query(survey_sql).to_dataframe()
responses_df.head(10)
```

!!! pitfall "Pitfall"
    Most survey questions store categorical answers in `value_as_concept_id`, not `value_as_number`. If you query only `value_as_number` for a categorical question, every row comes back NULL and your downstream analysis silently operates on an empty series. Always check `value_as_concept_id` first, and join to `concept` to decode the answer label.


### Pull responses using ds_survey (CDR v7+)

The `ds_survey` table provides pre-joined, human-readable survey data:

```python
ds_survey_sql = f"""
SELECT
    person_id,
    survey_datetime,
    survey AS module_name,
    question,
    answer
FROM `{CDR}.ds_survey`
WHERE LOWER(question) LIKE '%income%'
ORDER BY person_id
LIMIT 100
"""
ds_df = client.query(ds_survey_sql).to_dataframe()
ds_df.head(10)
```

!!! pitfall "Longitudinal surveys (COPE, SDOH) were administered at multiple time points"
    If you do not filter by `observation_date` (or `survey_datetime` in `ds_survey`), a single participant can contribute multiple rows for the same question. Aggregations like `COUNT(DISTINCT person_id)` are fine, but `COUNT(*)` or any row-level analysis will be inflated. Always decide whether you want the earliest, latest, or all responses and filter accordingly.


## Variations

### 1. Pivot survey responses into one-row-per-participant format

```python
pivot_sql = f"""
WITH labeled AS (
    SELECT
        o.person_id,
        o.observation_source_value AS question_code,
        COALESCE(answer.concept_name,
                 CAST(o.value_as_number AS STRING),
                 o.value_as_string) AS answer_value
    FROM `{CDR}.observation` o
    LEFT JOIN `{CDR}.concept` answer
        ON o.value_as_concept_id = answer.concept_id
    WHERE o.observation_source_value IN (
        'Race_WhatRaceEthnicity',
        'TheBasics_Employment',
        'TheBasics_EducationLevel'
    )
)
SELECT *
FROM labeled
PIVOT (
    MAX(answer_value)
    FOR question_code IN (
        'Race_WhatRaceEthnicity' AS race,
        'TheBasics_Employment'   AS employment,
        'TheBasics_EducationLevel' AS education
    )
)
"""
pivoted_df = client.query(pivot_sql).to_dataframe()
pivoted_df.head()
```

### 2. Filter to a specific survey module

```python
module_sql = f"""
SELECT
    o.person_id,
    o.observation_date,
    question.concept_name AS question_text,
    COALESCE(answer.concept_name,
             CAST(o.value_as_number AS STRING)) AS answer
FROM `{CDR}.observation` o
JOIN `{CDR}.concept` question
    ON o.observation_concept_id = question.concept_id
LEFT JOIN `{CDR}.concept` answer
    ON o.value_as_concept_id = answer.concept_id
WHERE o.observation_source_value LIKE 'Lifestyle_%'
ORDER BY o.person_id, o.observation_date
"""
lifestyle_df = client.query(module_sql).to_dataframe()
lifestyle_df.head(20)
```

### 3. Get the most recent response per participant for longitudinal surveys

```python
latest_response_sql = f"""
WITH ranked AS (
    SELECT
        o.person_id,
        o.observation_date,
        o.value_as_concept_id,
        answer.concept_name AS answer_text,
        ROW_NUMBER() OVER (
            PARTITION BY o.person_id
            ORDER BY o.observation_date DESC
        ) AS rn
    FROM `{CDR}.observation` o
    LEFT JOIN `{CDR}.concept` answer
        ON o.value_as_concept_id = answer.concept_id
    WHERE o.observation_concept_id = 1333015  -- COPE question
)
SELECT person_id, observation_date, answer_text
FROM ranked
WHERE rn = 1
"""
latest_df = client.query(latest_response_sql).to_dataframe()
latest_df.head()
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Unrecognized name: ds_survey` | Your CDR version predates v7. Use the `observation` table instead. |
| Query returns zero rows for a known question | The `observation_concept_id` may differ between CDR versions. Re-run the concept lookup query against your current CDR. |
| `value_as_concept_id` is 0 for many rows | The answer concept was not mapped. Check `value_as_string` or `value_source_concept_id` for the raw response. |

## Deep dive

Survey data in OMOP is inherently denormalized: one row per question-response pair. For analyses that require a wide participant-level table (e.g., regression inputs), pivoting in SQL is cleaner than post-hoc reshaping in pandas for large cohorts, because BigQuery handles the memory. However, PIVOT syntax requires hard-coded column names. For dynamic question sets, query the question codes first, then template the PIVOT clause in Python.

The `ds_survey` table exists precisely to simplify this workflow -- it pre-joins question text, answer text, and survey module into a single flat table. If your CDR supports it, prefer `ds_survey` for exploratory work and fall back to `observation` + `concept` joins when you need concept IDs for programmatic filtering.

## Cost note

The `observation` table is one of the largest tables in the CDR (hundreds of millions of rows spanning surveys, labs, and other observations). Always filter by `observation_concept_id` or `observation_source_value` rather than scanning the full table. Using `ds_survey` is more efficient for survey-only queries because it contains only survey records.

## See also

- [Query condition occurrence](../conditions-phenotypes/query-condition-occurrence.md) -- for EHR-derived diagnoses as opposed to self-reported survey conditions
- [Distinguish EHR from survey data sources](../data-quality/distinguish-ehr-survey-sources.md) -- for separating survey-reported conditions from EHR diagnoses
- [Filter by observation period](../data-quality/filter-by-observation-period.md) -- for ensuring sufficient data coverage before analysis

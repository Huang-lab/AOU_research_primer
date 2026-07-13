# Query procedure occurrence

Pull procedure records from the OMOP `procedure_occurrence` table filtered by CPT4 or SNOMED concept IDs.

## Prerequisites

- Researcher Workbench notebook environment with BigQuery access
- `os.environ["WORKSPACE_CDR"]` set to your CDR dataset

## Tier

Controlled Tier (procedure records derive from EHR data)

## CDR versions

All CDR versions (v5+). The `procedure_occurrence` table structure is stable across versions.

## Reference

The `procedure_occurrence` table stores one row per procedure performed on a participant. Procedures are coded in multiple vocabularies:

| Vocabulary | `vocabulary_id` | Use case |
|---|---|---|
| CPT4 | `CPT4` | Standard US billing codes (office visits, surgeries, imaging) |
| SNOMED | `SNOMED` | Clinical terminology, used as OMOP standard concepts |
| HCPCS | `HCPCS` | Medicare/Medicaid billing (DME, ambulance, some drugs) |
| ICD10PCS | `ICD10PCS` | Inpatient procedure coding |

OMOP maps source codes to **standard concepts** (typically SNOMED). The `procedure_concept_id` column holds the standard concept; `procedure_source_concept_id` holds the original source vocabulary code.

Key columns:

| Column | Description |
|---|---|
| `procedure_concept_id` | Standard (SNOMED) concept for the procedure |
| `procedure_source_concept_id` | Source vocabulary concept (often CPT4) |
| `procedure_date` | Date of the procedure (always populated) |
| `procedure_datetime` | Timestamp (may be NULL) |
| `procedure_type_concept_id` | Provenance: how the record was captured |
| `visit_occurrence_id` | FK to the visit (may be NULL) |

## Usage

### Find procedure concept IDs

Search the concept table by keyword to identify relevant concept IDs:

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

find_procedures_sql = f"""
SELECT
    c.concept_id,
    c.concept_name,
    c.vocabulary_id,
    c.concept_code,
    c.standard_concept
FROM `{CDR}.concept` c
WHERE c.domain_id = 'Procedure'
    AND LOWER(c.concept_name) LIKE '%colonoscopy%'
    AND c.standard_concept = 'S'
ORDER BY c.concept_name
LIMIT 20
"""
proc_concepts_df = client.query(find_procedures_sql).to_dataframe()
proc_concepts_df
```

### Pull procedure records with descendant concepts

Use `concept_ancestor` to capture all specific procedure variants under a parent concept:

```python
COLONOSCOPY_CONCEPT_ID = 4249893  # Colonoscopy (SNOMED)

procedure_sql = f"""
SELECT
    po.person_id,
    po.procedure_date,
    po.procedure_concept_id,
    c.concept_name AS procedure_name,
    src.concept_name AS source_name,
    src.vocabulary_id AS source_vocabulary
FROM `{CDR}.procedure_occurrence` po
JOIN `{CDR}.concept_ancestor` ca
    ON po.procedure_concept_id = ca.descendant_concept_id
JOIN `{CDR}.concept` c
    ON po.procedure_concept_id = c.concept_id
LEFT JOIN `{CDR}.concept` src
    ON po.procedure_source_concept_id = src.concept_id
WHERE ca.ancestor_concept_id = {COLONOSCOPY_CONCEPT_ID}
ORDER BY po.person_id, po.procedure_date
"""
procedures_df = client.query(procedure_sql).to_dataframe()
procedures_df.head(10)
```

> **Pitfall:** Procedures are coded in both CPT4 and SNOMED. If you query only `procedure_concept_id` (SNOMED standard) without using `concept_ancestor`, you will miss procedures that were mapped from CPT4 to a different SNOMED descendant than the one you specified. Always use `concept_ancestor` to capture the full hierarchy, or query both `procedure_concept_id` and `procedure_source_concept_id` with their respective vocabularies.

### Filter by date safely

```python
date_filtered_sql = f"""
SELECT
    po.person_id,
    po.procedure_date,
    c.concept_name AS procedure_name
FROM `{CDR}.procedure_occurrence` po
JOIN `{CDR}.concept_ancestor` ca
    ON po.procedure_concept_id = ca.descendant_concept_id
JOIN `{CDR}.concept` c
    ON po.procedure_concept_id = c.concept_id
WHERE ca.ancestor_concept_id = {COLONOSCOPY_CONCEPT_ID}
    AND po.procedure_date BETWEEN '2020-01-01' AND '2023-12-31'
ORDER BY po.person_id, po.procedure_date
"""
dated_df = client.query(date_filtered_sql).to_dataframe()
dated_df.head()
```

> **Pitfall:** Some `procedure_occurrence` records have a populated `procedure_date` but a NULL `procedure_datetime`. If you filter with `WHERE procedure_datetime BETWEEN ...`, those records are silently excluded. Always filter on `procedure_date` (the DATE column) unless you specifically need sub-day precision, and verify that `procedure_datetime` is not NULL before using it.

## Variations

### 1. Count procedure frequency per participant

```python
frequency_sql = f"""
SELECT
    po.person_id,
    COUNT(*) AS procedure_count,
    MIN(po.procedure_date) AS first_procedure,
    MAX(po.procedure_date) AS last_procedure,
    DATE_DIFF(MAX(po.procedure_date),
              MIN(po.procedure_date), DAY) AS span_days
FROM `{CDR}.procedure_occurrence` po
JOIN `{CDR}.concept_ancestor` ca
    ON po.procedure_concept_id = ca.descendant_concept_id
WHERE ca.ancestor_concept_id = {COLONOSCOPY_CONCEPT_ID}
GROUP BY po.person_id
ORDER BY procedure_count DESC
"""
freq_df = client.query(frequency_sql).to_dataframe()
freq_df.describe()
```

### 2. Procedures within a temporal window relative to an index date

Useful for pre/post analyses around a diagnosis or treatment start:

```python
window_sql = f"""
WITH index_dates AS (
    -- Example: first T2DM diagnosis as index
    SELECT
        person_id,
        MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence` co
    JOIN `{CDR}.concept_ancestor` ca
        ON co.condition_concept_id = ca.descendant_concept_id
    WHERE ca.ancestor_concept_id = 201826  -- Type 2 diabetes
    GROUP BY person_id
)
SELECT
    po.person_id,
    ix.index_date,
    po.procedure_date,
    DATE_DIFF(po.procedure_date, ix.index_date, DAY) AS days_from_index,
    c.concept_name AS procedure_name
FROM `{CDR}.procedure_occurrence` po
JOIN index_dates ix USING (person_id)
JOIN `{CDR}.concept` c
    ON po.procedure_concept_id = c.concept_id
WHERE po.procedure_date BETWEEN
    DATE_SUB(ix.index_date, INTERVAL 365 DAY)
    AND DATE_ADD(ix.index_date, INTERVAL 365 DAY)
ORDER BY po.person_id, po.procedure_date
"""
window_df = client.query(window_sql).to_dataframe()
window_df.head(20)
```

### 3. Cross-walk between source and standard concepts

Inspect how source codes map to standard concepts for a set of procedures:

```python
crosswalk_sql = f"""
SELECT
    src.concept_id AS source_concept_id,
    src.concept_code AS source_code,
    src.vocabulary_id AS source_vocab,
    src.concept_name AS source_name,
    std.concept_id AS standard_concept_id,
    std.concept_name AS standard_name,
    COUNT(DISTINCT po.person_id) AS patient_count
FROM `{CDR}.procedure_occurrence` po
JOIN `{CDR}.concept` src
    ON po.procedure_source_concept_id = src.concept_id
JOIN `{CDR}.concept` std
    ON po.procedure_concept_id = std.concept_id
WHERE std.concept_id IN (
    SELECT descendant_concept_id
    FROM `{CDR}.concept_ancestor`
    WHERE ancestor_concept_id = {COLONOSCOPY_CONCEPT_ID}
)
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY patient_count DESC
"""
xwalk_df = client.query(crosswalk_sql).to_dataframe()
xwalk_df
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| Query returns zero rows for a valid concept ID | The concept may be non-standard. Check `standard_concept = 'S'` in the concept table. Use `concept_relationship` to find the standard mapping. |
| `procedure_concept_id = 0` in many rows | Source codes could not be mapped to a standard concept. Check `procedure_source_concept_id` and `procedure_source_value` for the original code. |
| `BadRequest: 400 Syntax error` on `BETWEEN` with dates | Ensure date literals are quoted strings: `'2020-01-01'`, not bare integers. |

## Cost note

The `procedure_occurrence` table is moderate in size (tens of millions of rows). Filtering by `procedure_concept_id` or joining through `concept_ancestor` on specific ancestor IDs keeps scans manageable. Avoid `SELECT *` without a WHERE clause.

## See also

- [Query visit occurrence](../visits/query-visit-occurrence.md) -- for anchoring procedures to specific encounters
- [Filter by observation period](../data-quality/filter-by-observation-period.md) -- for ensuring participants have adequate data coverage around the procedure window
- [Distinguish EHR from survey data sources](../data-quality/distinguish-ehr-survey-sources.md) -- procedures are EHR-derived; confirms provenance

# Define a case cohort by condition codes

Query `condition_occurrence` with SNOMED standard concepts and `concept_ancestor` to identify all participants diagnosed with a target condition, including descendant codes.

## Prerequisites

| Requirement | Details |
|---|---|
| Workspace CDR | `os.environ["WORKSPACE_CDR"]` set by the AoU environment |
| BigQuery client | `google.cloud.bigquery.Client()` |
| Familiarity | OMOP CDM `condition_occurrence`, `concept`, `concept_ancestor` tables |

**Tier:** Registered Tier or Controlled Tier
**CDR versions:** C2022Q4R9 and later

---

## Reference

### Key tables and columns

| Table | Column | Role |
|---|---|---|
| `condition_occurrence` | `person_id` | Participant identifier |
| `condition_occurrence` | `condition_concept_id` | Standard (SNOMED) concept for the condition |
| `condition_occurrence` | `condition_source_concept_id` | Source vocabulary concept (e.g., ICD-10-CM) |
| `condition_occurrence` | `condition_start_date` | Date condition was recorded |
| `concept` | `concept_id`, `concept_name`, `vocabulary_id` | Concept metadata |
| `concept_ancestor` | `ancestor_concept_id`, `descendant_concept_id` | Standard-vocabulary hierarchy traversal |
| `cb_search_all_events` | `person_id`, `concept_id` | Cohort Builder denormalized lookup (faster scans) |

### How concept mapping works in AoU

Source EHR data arrives in ICD-10-CM, ICD-9-CM, or other source vocabularies. The ETL maps these to standard SNOMED concepts and stores the result in `condition_concept_id`. The original source code is preserved in `condition_source_concept_id`. Querying by the standard concept captures all source codes that map to the same clinical meaning.

---

## Usage

### Step 1 — Identify your target concept

Look up the SNOMED concept for your condition of interest. For example, type 2 diabetes mellitus is SNOMED concept `201826`.

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

concept_sql = f"""
SELECT concept_id, concept_name, vocabulary_id, concept_code
FROM `{CDR}.concept`
WHERE concept_name LIKE '%Type 2 diabetes mellitus%'
  AND vocabulary_id = 'SNOMED'
  AND standard_concept = 'S'
  AND domain_id = 'Condition'
ORDER BY concept_name
LIMIT 20
"""
client.query(concept_sql).to_dataframe()
```

### Step 2 — Pull cases using `concept_ancestor` for descendant inclusion

Use `concept_ancestor` to capture the target concept and all its descendant SNOMED codes. This is the correct general pattern for condition-based cohort definitions.

```python
TARGET_ANCESTOR_CONCEPT_ID = 201826  # Type 2 diabetes mellitus

cases_sql = f"""
SELECT DISTINCT co.person_id
FROM `{CDR}.condition_occurrence` AS co
JOIN `{CDR}.concept_ancestor` AS ca
  ON co.condition_concept_id = ca.descendant_concept_id
WHERE ca.ancestor_concept_id = {TARGET_ANCESTOR_CONCEPT_ID}
"""
cases_df = client.query(cases_sql).to_dataframe()
print(f"Case count: {len(cases_df)}")
```

> **Pitfall — querying `condition_source_concept_id` instead of `condition_concept_id`.**
> Source concept IDs retain the original vocabulary (ICD-10-CM, ICD-9-CM, etc.). If you filter on `condition_source_concept_id`, you capture only participants whose EHR happened to use that specific source code. Participants whose records were coded in a different source vocabulary but map to the same SNOMED standard concept are silently excluded. Always query `condition_concept_id` (the standard concept) unless you have a specific reason to restrict to a single source vocabulary.

> **Pitfall — filtering on an exact `condition_concept_id` without using `concept_ancestor`.**
> SNOMED is hierarchical. A top-level concept like "Malignant neoplasm of colon" (concept `4089661`) has dozens of site-specific children (ascending colon, transverse colon, sigmoid colon, etc.). Filtering `WHERE condition_concept_id = 4089661` returns only records coded at that exact level. Records coded to child concepts are silently missed, undercounting your cohort — often dramatically. Always join through `concept_ancestor` to capture the full descendant tree.

### Step 3 — Verify the descendant tree

Before committing to a cohort, inspect which descendant concepts are included.

```python
descendants_sql = f"""
SELECT c.concept_id, c.concept_name, c.concept_code,
       ca.min_levels_of_separation, ca.max_levels_of_separation
FROM `{CDR}.concept_ancestor` AS ca
JOIN `{CDR}.concept` AS c
  ON ca.descendant_concept_id = c.concept_id
WHERE ca.ancestor_concept_id = {TARGET_ANCESTOR_CONCEPT_ID}
  AND c.standard_concept = 'S'
ORDER BY ca.min_levels_of_separation, c.concept_name
"""
descendants_df = client.query(descendants_sql).to_dataframe()
print(f"Descendant concepts included: {len(descendants_df)}")
descendants_df.head(20)
```

Review this list for unwanted concepts. If a descendant is too broad or clinically irrelevant, exclude it explicitly:

```python
EXCLUDE_CONCEPT_IDS = [1234567, 7654321]  # hypothetical unwanted descendants

cases_filtered_sql = f"""
SELECT DISTINCT co.person_id
FROM `{CDR}.condition_occurrence` AS co
JOIN `{CDR}.concept_ancestor` AS ca
  ON co.condition_concept_id = ca.descendant_concept_id
WHERE ca.ancestor_concept_id = {TARGET_ANCESTOR_CONCEPT_ID}
  AND co.condition_concept_id NOT IN UNNEST({EXCLUDE_CONCEPT_IDS})
"""
cases_filtered_df = client.query(cases_filtered_sql).to_dataframe()
```

---

## Variations

### 1. Use `cb_search_all_events` for faster lookups

The Cohort Builder denormalized table `cb_search_all_events` pre-joins conditions, measurements, and other domains into a flat table. It already includes descendant roll-up for concepts that are flagged in `cb_criteria`. This can be significantly faster for large-scale lookups because it avoids the `concept_ancestor` join at query time.

```python
cb_cases_sql = f"""
SELECT DISTINCT person_id
FROM `{CDR}.cb_search_all_events`
WHERE concept_id IN (
    SELECT descendant_id
    FROM `{CDR}.cb_criteria_ancestor`
    WHERE ancestor_id IN (
        SELECT concept_id
        FROM `{CDR}.cb_criteria`
        WHERE domain_id = 'CONDITION'
          AND is_standard = 1
          AND concept_id = {TARGET_ANCESTOR_CONCEPT_ID}
    )
)
"""
cb_cases_df = client.query(cb_cases_sql).to_dataframe()
```

Note: The `cb_` tables mirror the logic of the Researcher Workbench Cohort Builder UI. Their descendant expansion may differ slightly from a raw `concept_ancestor` join if AoU has applied custom roll-up rules. Compare counts from both approaches if precision matters.

### 2. Require N minimum occurrences for case confirmation

For conditions where a single EHR entry may reflect rule-out coding or miscoding, require at least N distinct records (or distinct dates) before classifying someone as a case.

```python
MIN_OCCURRENCES = 2

confirmed_cases_sql = f"""
SELECT person_id
FROM `{CDR}.condition_occurrence` AS co
JOIN `{CDR}.concept_ancestor` AS ca
  ON co.condition_concept_id = ca.descendant_concept_id
WHERE ca.ancestor_concept_id = {TARGET_ANCESTOR_CONCEPT_ID}
GROUP BY person_id
HAVING COUNT(DISTINCT condition_start_date) >= {MIN_OCCURRENCES}
"""
confirmed_df = client.query(confirmed_cases_sql).to_dataframe()
```

Use `COUNT(DISTINCT condition_start_date)` rather than `COUNT(*)` to avoid inflated counts from same-day duplicate records.

### 3. Combine ICD and SNOMED criteria for maximum capture

In rare cases you may need to query both standard and source concepts — for example, when a source ICD-10-CM code maps to a SNOMED concept that is overly broad or you need to enforce that a specific ICD code was literally used.

```python
ICD10_SOURCE_CONCEPT_ID = 44836914  # E11 — Type 2 diabetes mellitus (ICD-10-CM)

combined_sql = f"""
SELECT DISTINCT person_id
FROM `{CDR}.condition_occurrence`
WHERE condition_concept_id IN (
    SELECT descendant_concept_id
    FROM `{CDR}.concept_ancestor`
    WHERE ancestor_concept_id = {TARGET_ANCESTOR_CONCEPT_ID}
)
   OR condition_source_concept_id = {ICD10_SOURCE_CONCEPT_ID}
"""
combined_df = client.query(combined_sql).to_dataframe()
```

This approach should be the exception, not the default. The standard concept path alone is correct for the vast majority of analyses.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Not found: Table ... condition_occurrence` | `WORKSPACE_CDR` is not set or points to a non-existent dataset. Verify with `print(os.environ["WORKSPACE_CDR"])`. |
| Query returns zero rows for a common condition | The concept ID may not be a standard concept (`standard_concept != 'S'`), or it may be a source concept ID rather than a SNOMED standard concept ID. Query the `concept` table to verify. |
| `concept_ancestor` join returns fewer rows than expected | The ancestor concept may have `min_levels_of_separation = 0` only (i.e., it is a leaf node with no descendants). Check the descendant tree as shown in Step 3. |
| `Resources exceeded` during query | Add a `LIMIT` clause during development or reduce the scope of the `concept_ancestor` join. See Cost note below. |

---

## Cost note

`condition_occurrence` is a moderate-size table (~hundreds of millions of rows in recent CDR versions). The `concept_ancestor` join is lightweight since it is a relatively small vocabulary table. The main cost driver is the scan of `condition_occurrence`. For iterative development, test your concept logic against the `concept` and `concept_ancestor` tables first (very cheap), then run the full cohort query once you have confirmed the correct concept set.

---

> **Pitfall — secondary cancer concepts name the DESTINATION site, not the origin.** "Secondary malignant neoplasm of lung" (OMOP 36714927) means a metastasis found IN the lung — it says nothing about where the primary cancer was. A breast cancer patient with lung metastases will also have a "malignant neoplasm of lung" code, and could be pulled into a Lung primary cohort. When building cancer cohorts, either exclude secondary neoplasm concepts (ancestor 432851) or cross-reference against each patient's primary diagnosis to avoid contamination.

## See also

- [Build matched controls for a case cohort](build-matched-controls.md) — find age/sex-matched controls for the cohort defined here
- [Exclude participants by condition history](exclude-by-condition-history.md) — remove participants with prior diagnoses from a study cohort
- [Discover OMOP concepts by name or hierarchy](discover-omop-concepts.md) — find concept IDs by searching names and expanding hierarchies

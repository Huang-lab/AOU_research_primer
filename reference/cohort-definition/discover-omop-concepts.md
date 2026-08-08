# Discover OMOP concepts by name or hierarchy

Find concept IDs for conditions, drugs, or measurements by searching concept names and expanding through the OMOP concept hierarchy.

## Prerequisites

- Workspace with CDR access
- Python 3, `google-cloud-bigquery`, `pandas`

**Tier:** Registered or Controlled
**CDR versions:** All

## Reference

OMOP concepts are the standardized vocabulary entries that link clinical events to a shared ontology. Every `condition_occurrence`, `drug_exposure`, and `measurement` row references a `concept_id`. To query clinical data, you first need the correct concept IDs.

Key tables:

| Table | Purpose |
|---|---|
| `concept` | Master vocabulary table: concept_id, name, code, vocabulary_id, standard_concept |
| `concept_ancestor` | Hierarchy: ancestor_concept_id → descendant_concept_id with levels of separation |
| `concept_relationship` | Direct relationships: Maps To, Is a, etc. |

> **Pitfall — only standard concepts match clinical records.** In `condition_occurrence`, the `condition_concept_id` column contains only standard SNOMED concepts (`standard_concept = 'S'`). Source vocabularies (ICD10CM, ICD9CM, Nebraska Lexicon, CIEL) are in the `concept` table for cross-reference but will return zero patients if used directly in a `WHERE condition_concept_id = ...` filter.

## Usage

### Step 1: Search concepts by name

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

concept_sql = f"""
SELECT c.concept_id, c.concept_name, c.concept_code,
       c.vocabulary_id, c.standard_concept,
       COUNT(DISTINCT co.person_id) AS n_patients
FROM `{CDR}.concept` c
JOIN `{CDR}.condition_occurrence` co
    ON c.concept_id = co.condition_concept_id
WHERE c.domain_id = 'Condition'
AND (
    LOWER(c.concept_name) LIKE '%breast%cancer%'
    OR LOWER(c.concept_name) LIKE '%malignant%breast%'
)
GROUP BY c.concept_id, c.concept_name, c.concept_code,
         c.vocabulary_id, c.standard_concept
HAVING n_patients >= 10
ORDER BY n_patients DESC
"""
results = client.query(concept_sql).to_dataframe()
print(results.to_string(index=False))
```

### Step 2: Expand via concept hierarchy

Use `concept_ancestor` to include all descendant concepts of a top-level ancestor:

```python
hierarchy_sql = f"""
SELECT DISTINCT co.person_id
FROM `{CDR}.condition_occurrence` co
JOIN `{CDR}.concept_ancestor` ca
    ON co.condition_concept_id = ca.descendant_concept_id
WHERE ca.ancestor_concept_id IN (
    432851,   -- Secondary malignant neoplastic disease
    4158910   -- Secondary malignant neoplasm of unknown site
)
"""
patients = client.query(hierarchy_sql).to_dataframe()
print(f"Patients: {len(patients):,}")
```

> **Pitfall — secondary cancer concepts name the DESTINATION, not the origin.** "Secondary malignant neoplasm of lung" means a metastasis found IN the lung, not a lung primary that metastasized. A breast cancer patient with lung metastases will also have a "malignant neoplasm of lung" code — and could be incorrectly pulled into a Lung primary cohort.

### Step 3: Resolve multi-match patients

When a participant matches multiple condition groups (e.g., both Breast and Ovarian cancer concepts), assign by earliest diagnosis:

```python
for pid in multi_match_ids:
    for cancer_type, concept_ids in concept_groups.items():
        concept_str = ",".join(map(str, concept_ids))
        date_sql = f"""
        SELECT MIN(condition_start_date) AS first_dx
        FROM `{CDR}.condition_occurrence`
        WHERE person_id = {pid}
        AND condition_concept_id IN ({concept_str})
        """
        first_dx = client.query(date_sql).to_dataframe()["first_dx"][0]
        # Assign to whichever cancer_type has the earliest first_dx
```

## Variations

### Search drug concepts

```python
drug_concept_sql = f"""
SELECT c.concept_id, c.concept_name, c.vocabulary_id,
       COUNT(DISTINCT de.person_id) AS n_patients
FROM `{CDR}.concept` c
JOIN `{CDR}.drug_exposure` de
    ON c.concept_id = de.drug_concept_id
WHERE LOWER(c.concept_name) LIKE '%metformin%'
GROUP BY c.concept_id, c.concept_name, c.vocabulary_id
HAVING n_patients >= 10
ORDER BY n_patients DESC
"""
```

### Search measurement concepts

```python
lab_concept_sql = f"""
SELECT c.concept_id, c.concept_name, c.concept_code,
       c.vocabulary_id,
       COUNT(DISTINCT m.person_id) AS n_patients
FROM `{CDR}.concept` c
JOIN `{CDR}.measurement` m
    ON c.concept_id = m.measurement_concept_id
WHERE LOWER(c.concept_name) LIKE '%hemoglobin a1c%'
GROUP BY c.concept_id, c.concept_name, c.concept_code, c.vocabulary_id
HAVING n_patients >= 10
ORDER BY n_patients DESC
"""
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| Query returns 0 patients for a valid concept | The concept is a source (non-standard) concept. Check `standard_concept` — only `'S'` concepts appear in clinical tables. |
| Too many irrelevant results | Name search is broad. Add `AND c.vocabulary_id = 'SNOMED'` to restrict to standard vocabulary. |
| Hierarchy expansion returns unexpected concepts | `concept_ancestor` includes all descendants at any depth. Check `min_levels_of_separation` and `max_levels_of_separation` to filter by hierarchy depth. |

## Cost note

Concept table queries are cheap (small table). Hierarchy expansion with `concept_ancestor` adds one join but is still low cost. The most expensive part is the `COUNT(DISTINCT person_id)` aggregation on large clinical tables.

## See also

- [Define a case cohort by condition codes](define-case-cohort-by-condition.md) — use discovered concepts to build cohorts
- [Query drug exposure history](../medications/query-drug-exposures.md) — drug-level queries using concept IDs
- [Discover genomics table schemas](../genomics/discover-genomics-tables.md) — schema discovery for genomics tables

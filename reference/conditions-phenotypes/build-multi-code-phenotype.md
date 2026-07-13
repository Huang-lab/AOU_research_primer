# Build a phenotype from multiple condition codes

Combine multiple SNOMED or ICD condition codes into a single binary phenotype column, handling "any of these codes" and "all of these codes" logic.

## Prerequisites

- Researcher Workbench notebook environment
- `pandas`, `google-cloud-bigquery` installed (default in AoU environment)
- A validated code list for your phenotype (from published phenotyping algorithms, PheKB, or manual curation)

## Tier availability

| Feature | Registered Tier | Controlled Tier |
|---|---|---|
| `condition_occurrence` | Yes | Yes |
| Standard concept IDs | Yes | Yes |
| Source ICD codes | Yes | Yes |

## CDR versions

All CDR versions (v5+). Concept IDs are stable across versions, but the vocabulary version may add or retire codes. Always validate your code list against the active CDR.

---

## Reference

### Key tables

| Table | Purpose |
|---|---|
| `condition_occurrence` | Source of condition records per participant |
| `concept` | Maps concept IDs to names, vocabulary, and domain |
| `concept_ancestor` | SNOMED hierarchy for rolling up child codes to parent concepts |
| `concept_relationship` | Maps between vocabularies (e.g., ICD-10-CM to SNOMED) |

### Phenotyping patterns

| Pattern | SQL logic | Use case |
|---|---|---|
| Any-of (OR) | `condition_concept_id IN (id1, id2, ...)` | Broad phenotype: any qualifying diagnosis |
| All-of (AND) | Count distinct codes per person, require count = N | Strict phenotype: must have each specified code |
| N-of-M | Count distinct codes per person, require count >= N | Moderate specificity: at least N of M codes present |

---

## Usage

### Step 1: Validate your code list against the CDR

Before building any phenotype, confirm that every concept ID in your list actually exists and has records in your CDR.

```python
import os
import pandas as pd
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

# Example: codes for a hypertension phenotype
hypertension_codes = [316866, 4028741, 320128, 315295, 4185932]

code_list = ", ".join(str(c) for c in hypertension_codes)

validation_query = f"""
SELECT
    c.concept_id,
    c.concept_name,
    c.standard_concept,
    c.vocabulary_id,
    COUNT(DISTINCT co.person_id) AS participant_count
FROM `{CDR}.concept` c
LEFT JOIN `{CDR}.condition_occurrence` co
    ON c.concept_id = co.condition_concept_id
WHERE c.concept_id IN ({code_list})
GROUP BY c.concept_id, c.concept_name,
         c.standard_concept, c.vocabulary_id
ORDER BY participant_count DESC
"""

validation_df = client.query(validation_query).to_dataframe()
print(validation_df.to_string(index=False))
```

> **Pitfall -- code lists from published algorithms may not match your CDR.**
> OMOP concept IDs are vocabulary-version-dependent. A concept ID from a 2019 PheKB algorithm may have been deprecated, remapped, or simply absent from the vocabulary version bundled with your AoU CDR release. If a code in your list has zero matches, it is silently excluded from your phenotype -- no error, just undercounting. Always run this validation step and investigate any zero-count codes before proceeding.

### Step 2: Any-of phenotype (OR logic)

Flag participants who have *at least one* of the specified conditions.

```python
any_of_query = f"""
SELECT DISTINCT person_id
FROM `{CDR}.condition_occurrence`
WHERE condition_concept_id IN ({code_list})
"""

cases_df = client.query(any_of_query).to_dataframe()
print(f"Participants with any hypertension code: {len(cases_df):,}")
```

> **Pitfall -- mixing parent and child codes inflates prevalence.**
> If your code list includes SNOMED code 316866 (Hypertensive disorder) *and* its child 320128 (Essential hypertension), every participant with essential hypertension is counted once already by code 320128. Adding the parent 316866 is redundant if that participant also has a record under the parent code -- but the `DISTINCT person_id` handles deduplication at the person level. The real problem is different: if you are using the `concept_ancestor` table to expand a parent code to all descendants (see Variation 1 below) *and* your code list already contains some of those descendants, you silently double the weight of those concepts in any frequency-based analysis. Always check whether your codes are at the same hierarchical level: `SELECT ancestor_concept_id, descendant_concept_id FROM concept_ancestor WHERE descendant_concept_id IN ({code_list}) AND ancestor_concept_id IN ({code_list}) AND ancestor_concept_id != descendant_concept_id`.

### Step 3: All-of phenotype (AND logic)

Flag participants who have *every one* of the specified conditions (useful for complex phenotypes requiring multiple diagnostic criteria).

```python
# Require all codes present for a multi-criteria phenotype
# Example: require both diabetes AND chronic kidney disease
required_codes = [201826, 46271022]  # T2DM, CKD stage 3
n_required = len(required_codes)
required_list = ", ".join(str(c) for c in required_codes)

all_of_query = f"""
SELECT person_id
FROM `{CDR}.condition_occurrence`
WHERE condition_concept_id IN ({required_list})
GROUP BY person_id
HAVING COUNT(DISTINCT condition_concept_id) = {n_required}
"""

strict_cases_df = client.query(all_of_query).to_dataframe()
print(f"Participants with ALL codes: {len(strict_cases_df):,}")
```

### Step 4: Create binary phenotype column and merge into cohort

```python
# Full cohort from cb_search_person
cohort_query = f"""
SELECT person_id FROM `{CDR}.cb_search_person`
"""
cohort_df = client.query(cohort_query).to_dataframe()

# Merge: 1 = case, 0 = control
cohort_df["hypertension"] = cohort_df["person_id"].isin(
    cases_df["person_id"]
).astype(int)

print(f"Cases: {cohort_df['hypertension'].sum():,}")
print(f"Controls: {(cohort_df['hypertension'] == 0).sum():,}")
print(f"Prevalence: {cohort_df['hypertension'].mean():.3%}")
```

> **Pitfall — prevalence inflated by high-level parent concepts.** If your code list includes a broad ancestor concept (e.g., "Hypertensive disorder" 316866), it may map to dozens of descendant conditions you did not intend to capture. The prevalence will be silently inflated because your phenotype is broader than you think. Inspect the descendant tree with `concept_ancestor` to verify what each code in your list actually covers.

> **Pitfall — prevalence deflated by invalid or non-standard concept IDs.** Concept IDs from published algorithms or older CDR versions may not exist in the current CDR vocabulary, or may be non-standard (`standard_concept != 'S'`). These codes silently match zero records, undercounting your phenotype. Run the Step 1 validation query and check `standard_concept = 'S'` in the `concept` table for any codes with zero participants.

---

## Variations

### 1. Including descendant codes via `concept_ancestor`

Expand a single parent SNOMED concept to capture the entire subtree. Useful when you want "all forms of diabetes" without manually listing every code.

```python
ancestor_query = f"""
SELECT DISTINCT co.person_id
FROM `{CDR}.condition_occurrence` co
JOIN `{CDR}.concept_ancestor` ca
    ON co.condition_concept_id = ca.descendant_concept_id
WHERE ca.ancestor_concept_id = 201820  -- Diabetes mellitus (parent)
"""

diabetes_any_df = client.query(ancestor_query).to_dataframe()
print(f"Participants with any diabetes descendant: "
      f"{len(diabetes_any_df):,}")
```

Check what codes you are pulling in:

```python
descendant_query = f"""
SELECT
    ca.descendant_concept_id,
    c.concept_name,
    ca.min_levels_of_separation
FROM `{CDR}.concept_ancestor` ca
JOIN `{CDR}.concept` c
    ON ca.descendant_concept_id = c.concept_id
WHERE ca.ancestor_concept_id = 201820
ORDER BY ca.min_levels_of_separation
"""

descendants_df = client.query(descendant_query).to_dataframe()
print(f"Total descendant codes: {len(descendants_df)}")
```

### 2. Requiring temporal co-occurrence (two codes within N days)

For phenotypes that require evidence of two related conditions within a time window (e.g., two diabetes codes within 90 days to reduce false positives from single coding errors).

```python
cooccurrence_query = f"""
WITH diabetes_records AS (
    SELECT
        person_id,
        condition_concept_id,
        condition_start_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_concept_id IN (201826, 443238, 4193704)
)
SELECT DISTINCT a.person_id
FROM diabetes_records a
JOIN diabetes_records b
    ON  a.person_id = b.person_id
    AND a.condition_concept_id != b.condition_concept_id
    AND ABS(DATE_DIFF(a.condition_start_date,
                      b.condition_start_date, DAY)) <= 90
"""

temporal_df = client.query(cooccurrence_query).to_dataframe()
print(f"Participants with 2 different diabetes codes "
      f"within 90 days: {len(temporal_df):,}")
```

### 3. Using source ICD codes when standard mapping is insufficient

Sometimes you need a specific ICD-10-CM code that maps to a broad SNOMED concept. Use `condition_source_concept_id` and `concept` to query at the source vocabulary level.

```python
icd_query = f"""
SELECT DISTINCT co.person_id
FROM `{CDR}.condition_occurrence` co
JOIN `{CDR}.concept` c
    ON co.condition_source_concept_id = c.concept_id
WHERE c.vocabulary_id = 'ICD10CM'
  AND c.concept_code IN ('E11.9', 'E11.65', 'E11.21')
"""

icd_cases_df = client.query(icd_query).to_dataframe()
```

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `concept_ancestor` join makes query very slow | The `concept_ancestor` table has hundreds of millions of rows. Filter it in a CTE or subquery rather than joining the full table. |
| Duplicate participants after joining multiple code sets | Use `DISTINCT person_id` at the final step. Multiple condition records per person for the same concept are expected. |

---

## Cost note

Queries scanning `condition_occurrence` filtered by a small set of `condition_concept_id` values are moderately expensive (the table has tens of millions of rows, but BigQuery pushes the predicate down efficiently on this column). Joining through `concept_ancestor` adds cost proportional to the hierarchy depth. Expect 100 MB-2 GB per query depending on the number of concepts.

---

## See also

- [query-condition-occurrence.md](query-condition-occurrence.md) -- Date-constrained condition queries and provenance filtering
- [query-lab-measurements.md](../labs-measurements/query-lab-measurements.md) -- Adding lab-based criteria to phenotypes
- [query-drug-exposures.md](../medications/query-drug-exposures.md) -- Adding medication criteria to phenotype definitions

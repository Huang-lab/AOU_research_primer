# Exclude participants by condition history

Remove participants from a study cohort who have a prior diagnosis of a specified condition, using an anti-join on `condition_occurrence` with descendant expansion and an optional date constraint.

## Prerequisites

| Requirement | Details |
|---|---|
| Workspace CDR | `os.environ["WORKSPACE_CDR"]` set by the AoU environment |
| BigQuery client | `google.cloud.bigquery.Client()` |
| Starting cohort | A set of `person_id` values to filter |
| Familiarity | OMOP CDM `condition_occurrence`, `concept_ancestor`; the distinction between Registered and Controlled Tier date handling |

**Tier:** Registered Tier or Controlled Tier
**CDR versions:** C2022Q4R9 and later

---

## Reference

### Key tables and columns

| Table | Column | Role |
|---|---|---|
| `condition_occurrence` | `person_id` | Participant identifier |
| `condition_occurrence` | `condition_concept_id` | Standard (SNOMED) concept for the condition |
| `condition_occurrence` | `condition_start_date` | Date the condition was first recorded |
| `concept_ancestor` | `ancestor_concept_id`, `descendant_concept_id` | Hierarchy traversal for descendant inclusion |

### Anti-join pattern

The anti-join removes rows from a base cohort where a matching row exists in a second table. In BigQuery SQL, the cleanest pattern is `LEFT JOIN ... WHERE right.key IS NULL` or `WHERE person_id NOT IN (subquery)`. Both produce identical results; the `NOT IN` form is more readable for simple exclusions, while the `LEFT JOIN` form is preferable when you need to carry forward columns from the exclusion table (e.g., the date that triggered exclusion).

### Date shifting in Registered Tier

In the Registered Tier, all dates are shifted by a random offset (up to +/- 1 year) that is consistent within a participant but varies across participants. This means:

- **Relative ordering within a participant is preserved**: "condition A happened before condition B" remains valid.
- **Absolute calendar dates are meaningless**: a `condition_start_date` of 2019-03-15 in Registered Tier does not correspond to the real-world date of March 15, 2019.
- **Cross-participant date comparisons are invalid**: you cannot assume that two participants with the same shifted date had events at the same real-world time.

The Controlled Tier uses actual dates.

---

## Usage

### Step 1 — Define the exclusion condition and descendant set

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

# Exclude participants with any history of malignant neoplasm of colon
EXCLUSION_ANCESTOR_CONCEPT_ID = 4089661  # Malignant neoplasm of colon (SNOMED)
```

### Step 2 — Apply the exclusion (any-time history)

This removes any participant who has ever had a record for the exclusion condition or any of its descendant concepts.

```python
# cohort_person_ids: list of person_ids from your starting cohort

exclusion_sql = f"""
WITH exclusion_ids AS (
    SELECT DISTINCT co.person_id
    FROM `{CDR}.condition_occurrence` AS co
    JOIN `{CDR}.concept_ancestor` AS ca
      ON co.condition_concept_id = ca.descendant_concept_id
    WHERE ca.ancestor_concept_id = {EXCLUSION_ANCESTOR_CONCEPT_ID}
)
SELECT person_id
FROM UNNEST({cohort_person_ids}) AS person_id
WHERE person_id NOT IN (SELECT person_id FROM exclusion_ids)
"""
filtered_df = client.query(exclusion_sql).to_dataframe()
print(f"Before exclusion: {len(cohort_person_ids)}")
print(f"After exclusion:  {len(filtered_df)}")
print(f"Excluded:         {len(cohort_person_ids) - len(filtered_df)}")
```

!!! pitfall "excluding by exact concept_id without descendant expansion"
    If you write `WHERE condition_concept_id = 4089661` instead of joining through `concept_ancestor`, you only exclude participants whose records are coded at the exact "Malignant neoplasm of colon" level. Participants coded with site-specific children (e.g., "Malignant neoplasm of ascending colon", "Malignant neoplasm of sigmoid colon") pass through the filter and remain in your cohort. This silently includes participants who should have been excluded, contaminating your study population. Always use `concept_ancestor` for condition-based exclusions.


### Step 3 — Apply the exclusion with a date constraint (pre-index-date only)

For incident-event studies, you typically want to exclude participants with a condition diagnosis *before* a defined index date, but not those diagnosed after.

```python
INDEX_DATE = "2020-01-01"  # study enrollment or index date

pre_index_exclusion_sql = f"""
WITH exclusion_ids AS (
    SELECT DISTINCT co.person_id
    FROM `{CDR}.condition_occurrence` AS co
    JOIN `{CDR}.concept_ancestor` AS ca
      ON co.condition_concept_id = ca.descendant_concept_id
    WHERE ca.ancestor_concept_id = {EXCLUSION_ANCESTOR_CONCEPT_ID}
      AND co.condition_start_date < '{INDEX_DATE}'
)
SELECT person_id
FROM UNNEST({cohort_person_ids}) AS person_id
WHERE person_id NOT IN (SELECT person_id FROM exclusion_ids)
"""
filtered_df = client.query(pre_index_exclusion_sql).to_dataframe()
```

!!! pitfall "using absolute date thresholds in Registered Tier"
    In Registered Tier, `condition_start_date` values are shifted by a per-participant random offset. The filter `condition_start_date < '2020-01-01'` does not mean "before January 2020 in the real world" — it means "before that date in shifted time," which differs for every participant. This silently produces an exclusion set that is neither clinically nor temporally coherent. In Registered Tier, use relative date logic (e.g., "condition occurred before the participant's earliest measurement date") rather than absolute calendar cutoffs. Only the Controlled Tier supports meaningful absolute date filtering.


### Relative date approach for Registered Tier

```python
# Exclude conditions that occurred before each participant's study entry
# (defined here as their first measurement date)
relative_exclusion_sql = f"""
WITH participant_entry AS (
    SELECT person_id, MIN(measurement_date) AS entry_date
    FROM `{CDR}.measurement`
    WHERE person_id IN UNNEST({cohort_person_ids})
    GROUP BY person_id
),
exclusion_ids AS (
    SELECT DISTINCT co.person_id
    FROM `{CDR}.condition_occurrence` AS co
    JOIN `{CDR}.concept_ancestor` AS ca
      ON co.condition_concept_id = ca.descendant_concept_id
    JOIN participant_entry AS pe
      ON co.person_id = pe.person_id
    WHERE ca.ancestor_concept_id = {EXCLUSION_ANCESTOR_CONCEPT_ID}
      AND co.condition_start_date < pe.entry_date
)
SELECT person_id
FROM UNNEST({cohort_person_ids}) AS person_id
WHERE person_id NOT IN (SELECT person_id FROM exclusion_ids)
"""
filtered_relative_df = client.query(relative_exclusion_sql).to_dataframe()
```

---

## Variations

### 1. Exclude by any-time history vs. pre-index-date history

The two approaches serve different study designs:

| Approach | Use case | Query pattern |
|---|---|---|
| Any-time exclusion | You want participants who have never had the condition, period | No date filter on `condition_start_date` |
| Pre-index exclusion | You want to exclude prevalent cases but allow incident cases after enrollment | `AND condition_start_date < index_date` |

The any-time approach is simpler and appropriate for control-group construction. The pre-index approach is essential for incidence studies where the outcome is the condition itself.

### 2. Exclude by multiple conditions simultaneously

To exclude participants with a history of any condition in a list:

```python
EXCLUSION_ANCESTORS = [4089661, 4112853, 201826]  # colon cancer, lung cancer, T2D

multi_exclusion_sql = f"""
WITH exclusion_ids AS (
    SELECT DISTINCT co.person_id
    FROM `{CDR}.condition_occurrence` AS co
    JOIN `{CDR}.concept_ancestor` AS ca
      ON co.condition_concept_id = ca.descendant_concept_id
    WHERE ca.ancestor_concept_id IN UNNEST({EXCLUSION_ANCESTORS})
)
SELECT person_id
FROM UNNEST({cohort_person_ids}) AS person_id
WHERE person_id NOT IN (SELECT person_id FROM exclusion_ids)
"""
```

This produces a single scan of `condition_occurrence` with multiple ancestor roots, which is more efficient than running separate exclusion queries.

### 3. Use `LEFT JOIN` pattern for auditability

When you need to know *why* a participant was excluded (which condition, what date), the `LEFT JOIN` pattern is preferable:

```python
audit_sql = f"""
WITH cohort AS (
    SELECT person_id FROM UNNEST({cohort_person_ids}) AS person_id
),
exclusion_hits AS (
    SELECT DISTINCT co.person_id,
           co.condition_concept_id,
           c.concept_name,
           MIN(co.condition_start_date) AS earliest_date
    FROM `{CDR}.condition_occurrence` AS co
    JOIN `{CDR}.concept_ancestor` AS ca
      ON co.condition_concept_id = ca.descendant_concept_id
    JOIN `{CDR}.concept` AS c
      ON co.condition_concept_id = c.concept_id
    WHERE ca.ancestor_concept_id = {EXCLUSION_ANCESTOR_CONCEPT_ID}
    GROUP BY co.person_id, co.condition_concept_id, c.concept_name
)
SELECT ch.person_id,
       eh.condition_concept_id AS excluded_by_concept,
       eh.concept_name AS excluded_by_name,
       eh.earliest_date AS excluded_by_date
FROM cohort AS ch
LEFT JOIN exclusion_hits AS eh
  ON ch.person_id = eh.person_id
ORDER BY ch.person_id
"""
audit_df = client.query(audit_sql).to_dataframe()

# Participants to keep: those with NULL exclusion columns
kept = audit_df[audit_df["excluded_by_concept"].isna()]["person_id"].unique()
excluded = audit_df[audit_df["excluded_by_concept"].notna()]
print(f"Kept: {len(kept)}, Excluded: {len(excluded['person_id'].unique())}")
```

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Exclusion removes zero participants | The `EXCLUSION_ANCESTOR_CONCEPT_ID` may not exist in `concept_ancestor` as an ancestor, or it may be a non-standard concept. Verify with `SELECT * FROM concept WHERE concept_id = <id>` and confirm `standard_concept = 'S'`. |
| Exclusion removes far too many participants | The ancestor concept is too broad. For example, using "Disorder of digestive system" instead of "Malignant neoplasm of colon" will exclude participants with any GI condition. Inspect the descendant tree with a `concept_ancestor` query before applying the exclusion. |
| `condition_start_date` comparison produces unexpected results | In Registered Tier, dates are shifted. Absolute date comparisons are not clinically meaningful. Switch to relative date logic. |
| `Resources exceeded` on large cohorts with `IN UNNEST(...)` | For cohorts >10,000 person_ids, upload the cohort to a temporary BigQuery table and join rather than inlining the array. |

---

## Cost note

The cost profile is moderate, driven by the `condition_occurrence` table scan. The `concept_ancestor` join adds negligible cost. When excluding by multiple ancestor concepts (Variation 2), the cost is essentially the same as a single-ancestor exclusion because the scan happens once. For iterative development, test the exclusion logic against a small sample first by adding `AND co.person_id IN UNNEST(<small_sample>)` to the exclusion CTE.

---

## See also

- [Define a case cohort by condition codes](define-case-cohort-by-condition.md) — the descendant-expansion pattern used here originates from cohort definition
- [Build matched controls for a case cohort](build-matched-controls.md) — uses this exclusion pattern to ensure controls are condition-free

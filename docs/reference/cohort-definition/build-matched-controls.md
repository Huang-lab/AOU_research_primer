# Build matched controls for a case cohort

Given a set of case `person_id`s, select control participants matched on age and sex (optionally genetic ancestry PCs), excluding anyone with the case-defining condition.

## Prerequisites

| Requirement | Details |
|---|---|
| Workspace CDR | `os.environ["WORKSPACE_CDR"]` set by the AoU environment |
| BigQuery client | `google.cloud.bigquery.Client()` |
| Case cohort | A table or DataFrame of `person_id` values defining your cases |
| Familiarity | OMOP CDM `person` table, `condition_occurrence`, anti-join patterns in SQL |

**Tier:** Registered Tier or Controlled Tier (Controlled Tier required if using genomic data for ancestry-based matching)
**CDR versions:** C2022Q4R9 and later

---

## Reference

### Key tables and columns

| Table | Column | Role |
|---|---|---|
| `person` | `person_id` | Participant identifier |
| `person` | `year_of_birth` | Birth year for age matching |
| `person` | `sex_at_birth_concept_id` | Biological sex for matching |
| `person` | `gender_concept_id` | Gender identity (distinct from sex at birth) |
| `person` | `race_concept_id` | Self-reported race |
| `person` | `ethnicity_concept_id` | Self-reported ethnicity |
| `condition_occurrence` | `person_id`, `condition_concept_id` | Used to exclude participants who have the case-defining condition |
| `concept_ancestor` | `ancestor_concept_id`, `descendant_concept_id` | Descendant expansion for exclusion condition |

### Matching strategy overview

The core pattern is:

1. Join cases to `person` to get demographics.
2. Query all participants from `person` who are NOT in the case set.
3. Anti-join against `condition_occurrence` (with descendant expansion) to further exclude anyone who has ever had the case-defining condition but was not already in your case set.
4. Match on `year_of_birth` and `sex_at_birth_concept_id`.
5. Sample controls at the desired ratio per case.

---

## Usage

### Step 1 — Load case demographics

Assume your case cohort exists as a Python list or DataFrame. Upload it to BigQuery as a temporary table for efficient joins.

```python
import os
import pandas as pd
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]
DATASET = os.environ["WORKSPACE_CDR"].rsplit(".", 1)[0]  # project.dataset

# case_person_ids: list of int person_ids from your case-definition step
# Example: case_person_ids = cases_df["person_id"].tolist()

case_demo_sql = f"""
SELECT p.person_id, p.year_of_birth, p.sex_at_birth_concept_id
FROM `{CDR}.person` AS p
WHERE p.person_id IN UNNEST({case_person_ids})
"""
case_demo_df = client.query(case_demo_sql).to_dataframe()
print(f"Cases with demographics: {len(case_demo_df)}")
```

For large case lists (>10,000), upload to a temporary table instead of using `IN UNNEST()`:

```python
temp_table_id = f"{DATASET}._temp_cases"
client.load_table_from_dataframe(
    pd.DataFrame({"person_id": case_person_ids}),
    temp_table_id,
    job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
).result()
```

### Step 2 — Select matched controls with anti-join exclusion

This query finds controls matched on exact birth year and sex at birth, excluding both the case participants and any participant who has the case-defining condition (including descendants).

```python
TARGET_ANCESTOR_CONCEPT_ID = 201826  # Same concept used to define cases
MATCH_RATIO = 5  # 5 controls per case

controls_sql = f"""
WITH case_ids AS (
    SELECT person_id FROM UNNEST({case_person_ids}) AS person_id
),
condition_exclusions AS (
    SELECT DISTINCT co.person_id
    FROM `{CDR}.condition_occurrence` AS co
    JOIN `{CDR}.concept_ancestor` AS ca
      ON co.condition_concept_id = ca.descendant_concept_id
    WHERE ca.ancestor_concept_id = {TARGET_ANCESTOR_CONCEPT_ID}
),
case_demographics AS (
    SELECT p.person_id, p.year_of_birth, p.sex_at_birth_concept_id
    FROM `{CDR}.person` AS p
    INNER JOIN case_ids AS ci ON p.person_id = ci.person_id
),
eligible_controls AS (
    SELECT p.person_id, p.year_of_birth, p.sex_at_birth_concept_id,
           RAND() AS rand_val
    FROM `{CDR}.person` AS p
    WHERE p.person_id NOT IN (SELECT person_id FROM case_ids)
      AND p.person_id NOT IN (SELECT person_id FROM condition_exclusions)
),
ranked AS (
    SELECT ec.person_id AS control_person_id,
           cd.person_id AS case_person_id,
           ROW_NUMBER() OVER (
               PARTITION BY cd.person_id ORDER BY ec.rand_val
           ) AS match_rank
    FROM case_demographics AS cd
    JOIN eligible_controls AS ec
      ON cd.year_of_birth = ec.year_of_birth
     AND cd.sex_at_birth_concept_id = ec.sex_at_birth_concept_id
)
SELECT case_person_id, control_person_id, match_rank
FROM ranked
WHERE match_rank <= {MATCH_RATIO}
ORDER BY case_person_id, match_rank
"""
controls_df = client.query(controls_sql).to_dataframe()
print(f"Matched controls: {controls_df['control_person_id'].nunique()}")
```

!!! pitfall "Pitfall"
    matching on self-reported race/ethnicity instead of genetic ancestry principal components. The `person` table contains `race_concept_id` and `ethnicity_concept_id`, which reflect self-reported categories. These do not capture genetic admixture or within-group population structure. If you match cases and controls on `race_concept_id` for a genetic analysis (GWAS, PRS, etc.), residual population stratification will confound your results — and the confounding is silent because the analysis runs without error. For genetic studies, match on or adjust for the first N ancestry principal components (PCs) from the genomic data instead. See the AoU genomic data documentation for extracting ancestry PCs.


!!! pitfall "not excluding participants who develop the condition after the study period"
    The `condition_exclusions` CTE above removes anyone who *ever* had the condition. If your study has an index date and you want to identify incident cases, a control who develops the condition after the index date is not truly disease-free — they are a future case. For prevalent vs. incident designs, add a date constraint: restrict the exclusion query to `condition_start_date <= @index_date` for prevalent exclusion, or decide whether to censor future cases rather than exclude them. Without this consideration, your control group is contaminated with participants who are phenotypically similar to cases, attenuating effect estimates silently.


### Step 3 — Verify match balance

After matching, confirm that the distributions of matching variables are balanced.

```python
verify_sql = f"""
SELECT 'case' AS cohort, year_of_birth, sex_at_birth_concept_id, COUNT(*) AS n
FROM `{CDR}.person`
WHERE person_id IN UNNEST({case_person_ids})
GROUP BY year_of_birth, sex_at_birth_concept_id

UNION ALL

SELECT 'control' AS cohort, p.year_of_birth, p.sex_at_birth_concept_id, COUNT(*) AS n
FROM `{CDR}.person` AS p
WHERE p.person_id IN (
    SELECT control_person_id FROM UNNEST(@control_ids) AS control_person_id
)
GROUP BY year_of_birth, sex_at_birth_concept_id
ORDER BY cohort, year_of_birth
"""
# Alternatively, verify from the DataFrames directly:
print("Cases by sex:", case_demo_df["sex_at_birth_concept_id"].value_counts().to_dict())
ctrl_demo = controls_df.merge(
    client.query(f"""
        SELECT person_id, year_of_birth, sex_at_birth_concept_id
        FROM `{CDR}.person`
        WHERE person_id IN UNNEST({controls_df['control_person_id'].tolist()})
    """).to_dataframe(),
    left_on="control_person_id", right_on="person_id"
)
print("Controls by sex:", ctrl_demo["sex_at_birth_concept_id"].value_counts().to_dict())
```

---

## Variations

### 1. 1:1 matching vs N:1 matching

The query above performs N:1 matching (multiple controls per case). For 1:1 matching, set `MATCH_RATIO = 1`. If controls are scarce in some strata, some cases may have fewer than N matches. Check for this:

```python
match_counts = controls_df.groupby("case_person_id").size()
print(f"Cases with fewer than {MATCH_RATIO} controls: "
      f"{(match_counts < MATCH_RATIO).sum()}")
```

If many cases are under-matched, consider relaxing the birth-year match to a +/- 2 year window:

```python
# Replace exact year match with:
#   AND ec.year_of_birth BETWEEN cd.year_of_birth - 2 AND cd.year_of_birth + 2
```

### 2. Match on age at index date rather than birth year

If your study has a defined index date (e.g., date of first diagnosis for each case), match on age at that date rather than birth year to avoid bias from calendar-time effects.

```python
# Assumes case_index_dates is a list of dicts: [{"person_id": ..., "index_date": ...}]
age_match_sql = f"""
WITH case_info AS (
    SELECT person_id, index_date,
           EXTRACT(YEAR FROM index_date) - year_of_birth AS age_at_index
    FROM `{CDR}.person`
    WHERE person_id IN UNNEST({case_person_ids})
)
-- Then match controls whose age at the case's index_date falls within +/- 1 year
"""
```

### 3. Greedy 1:1 matching without replacement in Python

For more sophisticated matching (e.g., propensity score, caliper-based), perform the matching in pandas after pulling demographics for cases and the eligible control pool.

```python
from scipy.spatial.distance import cdist
import numpy as np

# Pull demographics for eligible pool
pool_sql = f"""
SELECT person_id, year_of_birth, sex_at_birth_concept_id
FROM `{CDR}.person`
WHERE person_id NOT IN UNNEST({case_person_ids})
  AND person_id NOT IN (
      SELECT DISTINCT person_id
      FROM `{CDR}.condition_occurrence` AS co
      JOIN `{CDR}.concept_ancestor` AS ca
        ON co.condition_concept_id = ca.descendant_concept_id
      WHERE ca.ancestor_concept_id = {TARGET_ANCESTOR_CONCEPT_ID}
  )
"""
pool_df = client.query(pool_sql).to_dataframe()

# Greedy nearest-neighbor match (1:1, without replacement)
matched_controls = []
used = set()
for _, case_row in case_demo_df.iterrows():
    candidates = pool_df[
        (pool_df["sex_at_birth_concept_id"] == case_row["sex_at_birth_concept_id"])
        & (~pool_df["person_id"].isin(used))
    ].copy()
    if candidates.empty:
        continue
    candidates["age_diff"] = abs(candidates["year_of_birth"] - case_row["year_of_birth"])
    best = candidates.nsmallest(1, "age_diff").iloc[0]
    matched_controls.append({"case_person_id": case_row["person_id"],
                             "control_person_id": best["person_id"]})
    used.add(best["person_id"])

matched_df = pd.DataFrame(matched_controls)
print(f"Matched pairs: {len(matched_df)}")
```

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Many cases have zero matched controls | The matching criteria are too strict for sparse strata (e.g., very old or very young participants with a rare sex_at_birth value). Relax the birth-year window or switch to caliper matching. |
| `IN UNNEST(...)` fails with `Array element count exceeds the maximum` | The person_id list exceeds BigQuery's inline array limit (~10,000). Upload to a temporary table and join instead. |
| Control count is much larger than expected | The anti-join is not working — verify that `condition_exclusions` uses `concept_ancestor` with the correct ancestor concept. A common error is omitting the ancestor join, which excludes only the exact concept and lets through participants coded with descendant concepts. |
| `RAND()` gives different results each run | This is expected. For reproducibility, use `FARM_FINGERPRINT(CAST(person_id AS STRING))` as a deterministic pseudo-random sort key. |

---

## Cost note

The `person` table is small (~hundreds of thousands of rows) and scans are very cheap. The main cost in this workflow comes from the `condition_occurrence` scan in the `condition_exclusions` CTE, which is moderate. The `RAND()`-based ranking and `ROW_NUMBER()` window function add compute cost proportional to the number of eligible controls per stratum but do not increase bytes scanned.

---

## See also

- [Define a case cohort by condition codes](define-case-cohort-by-condition.md) — build the case cohort that feeds into this matching step
- [Exclude participants by condition history](exclude-by-condition-history.md) — anti-join pattern for removing participants with prior diagnoses

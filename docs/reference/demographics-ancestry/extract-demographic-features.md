# Extract demographic features

Pull age, sex at birth, race, and ethnicity for a cohort from the AoU `person` and `cb_search_person` tables.

## Prerequisites

- Researcher Workbench notebook environment
- `pandas`, `google-cloud-bigquery` installed (default in AoU environment)

## Tier availability

| Feature | Registered Tier | Controlled Tier |
|---|---|---|
| `year_of_birth` | Yes | Yes |
| `date_of_birth` | No | Yes |
| Sex at birth | Yes | Yes |
| Race / ethnicity concept IDs | Yes | Yes |

## CDR versions

All CDR versions (v5+). Column names are stable across versions.

---

## Reference

### Key tables

| Table | Purpose |
|---|---|
| `person` | Core OMOP person table. One row per participant. Contains `year_of_birth`, `date_of_birth` (Controlled), `gender_concept_id`, `race_concept_id`, `ethnicity_concept_id`. |
| `cb_search_person` | Cohort Builder denormalized table. Pre-joined demographic strings: `sex_at_birth`, `race`, `ethnicity`, `age_at_cdr`. Fastest for simple lookups. |
| `concept` | OMOP vocabulary table. Maps concept IDs to human-readable `concept_name` strings. |
| `observation` | Stores multi-select survey responses including multiple race selections. |

### Key columns on `person`

| Column | Type | Notes |
|---|---|---|
| `person_id` | INT64 | Unique participant identifier |
| `year_of_birth` | INT64 | Always available |
| `date_of_birth` | DATE | Controlled Tier only; NULL in Registered |
| `gender_concept_id` | INT64 | Maps to sex at birth (AoU uses gender_concept_id for sex at birth) |
| `race_concept_id` | INT64 | Single primary race; may be 0 if participant selected multiple or declined |
| `ethnicity_concept_id` | INT64 | Hispanic/Latino or Not Hispanic/Latino |

---

## Usage

### Quick approach: `cb_search_person`

The Cohort Builder table provides pre-resolved strings, saving you joins.

```python
import os
import pandas as pd
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

demo_query = f"""
SELECT
    person_id,
    sex_at_birth,
    race,
    ethnicity,
    age_at_cdr,
    dob
FROM `{CDR}.cb_search_person`
LIMIT 10
"""

demo_df = client.query(demo_query).to_dataframe()
demo_df.head()
```

### Full approach: `person` table with concept joins

Use this when you need concept IDs for programmatic filtering or when `cb_search_person` does not include a column you need.

```python
demo_query = f"""
SELECT
    p.person_id,
    p.year_of_birth,
    p.date_of_birth,
    gc.concept_name  AS sex_at_birth,
    rc.concept_name  AS race,
    ec.concept_name  AS ethnicity
FROM `{CDR}.person` p
LEFT JOIN `{CDR}.concept` gc
    ON p.gender_concept_id = gc.concept_id
LEFT JOIN `{CDR}.concept` rc
    ON p.race_concept_id = rc.concept_id
LEFT JOIN `{CDR}.concept` ec
    ON p.ethnicity_concept_id = ec.concept_id
"""

person_df = client.query(demo_query).to_dataframe()
```

!!! pitfall "`race` and `ethnicity` are concept IDs, not strings"
    If you query `person.race_concept_id` directly, you get integers like `8516` (Black or African American) or `0` (No matching concept). You *must* join to `concept` for readable labels. Worse, many participants selected multiple races in the AoU survey — those additional selections are stored in the `observation` table, not `person`. If you rely on `person.race_concept_id` alone, you will undercount multi-racial participants and misclassify them as whichever single race the ETL chose as primary.


### Computing age

#### Registered Tier: approximate age from `year_of_birth`

```python
import datetime

current_year = datetime.date.today().year

person_df["age_approx"] = current_year - person_df["year_of_birth"]
```

!!! pitfall "`year_of_birth` alone gives +/- 1 year error"
    A participant born in December 1990 is a different age than one born in January 1990, but both show `year_of_birth = 1990`. This matters for pediatric cohorts (age 17 vs 18 changes eligibility), age-stratified analyses with narrow bins, and any study where age cutoffs are inclusion criteria. In the Controlled Tier, use `date_of_birth` for exact age.


#### Controlled Tier: exact age from `date_of_birth`

```python
person_df["age_exact"] = person_df["date_of_birth"].apply(
    lambda dob: (datetime.date.today() - dob).days / 365.25
    if pd.notnull(dob) else None
)
```

---

## Variations

### 1. Multi-race handling via the observation table

The AoU survey allows participants to select multiple race categories. These are stored as separate rows in `observation` with `observation_source_concept_id = 1586140` (Race).

```python
race_query = f"""
SELECT
    o.person_id,
    c.concept_name AS race_selection
FROM `{CDR}.observation` o
JOIN `{CDR}.concept` c
    ON o.value_source_concept_id = c.concept_id
WHERE o.observation_source_concept_id = 1586140
ORDER BY o.person_id
"""

multi_race_df = client.query(race_query).to_dataframe()

# Pivot to one row per person with comma-separated races
race_agg = (
    multi_race_df
    .groupby("person_id")["race_selection"]
    .apply(lambda x: ", ".join(sorted(x)))
    .reset_index()
    .rename(columns={"race_selection": "all_races"})
)
```

### 2. Controlled vs Registered tier date precision

When writing code that must work in both tiers, check for `date_of_birth` availability:

```python
demo_query = f"""
SELECT
    person_id,
    year_of_birth,
    date_of_birth,
    CASE
        WHEN date_of_birth IS NOT NULL
            THEN DATE_DIFF(CURRENT_DATE(), date_of_birth, DAY) / 365.25
        ELSE EXTRACT(YEAR FROM CURRENT_DATE()) - year_of_birth
    END AS age
FROM `{CDR}.person`
"""

person_df = client.query(demo_query).to_dataframe()
```

### 3. Using `cb_search_person` with filters

```python
filtered_query = f"""
SELECT person_id, sex_at_birth, race, ethnicity, age_at_cdr
FROM `{CDR}.cb_search_person`
WHERE age_at_cdr BETWEEN 18 AND 65
  AND sex_at_birth = 'Female'
"""

filtered_df = client.query(filtered_query).to_dataframe()
```

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `date_of_birth` returns all NULLs | You are in the Registered Tier. This column is only populated in the Controlled Tier CDR. |
| `race_concept_id` is 0 for many participants | The participant either declined to answer, selected "None of these," or selected multiple races (primary race could not be determined). Query the `observation` table for the full set of race responses. |
| `cb_search_person` table not found | Your CDR environment variable may be pointing to a raw OMOP dataset that lacks Cohort Builder tables. Verify `WORKSPACE_CDR` is set correctly. |
| Query returns no rows | The `WORKSPACE_CDR` variable is not set or points to an empty/invalid dataset. Run `echo $WORKSPACE_CDR` in a terminal cell to verify. |

---

## Cost note

The `person` and `cb_search_person` tables are small (one row per participant, ~400K-800K rows depending on CDR version). Queries are inexpensive and typically process under 100 MB.

---

## See also

- [compute-ancestry-pcs.md](compute-ancestry-pcs.md) — Genetic ancestry principal components for population stratification
- [query-condition-occurrence.md](../conditions-phenotypes/query-condition-occurrence.md) — Joining demographics to clinical conditions

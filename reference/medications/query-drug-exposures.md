# Query drug exposure history

Pull drug exposures from the `drug_exposure` table by ingredient-level concept IDs, using `concept_ancestor` to capture all formulations, generics, and combination products.

## Prerequisites

- Researcher Workbench notebook environment
- `pandas`, `google-cloud-bigquery` installed (default in AoU environment)

## Tier availability

| Feature | Registered Tier | Controlled Tier |
|---|---|---|
| `drug_exposure` | Yes | Yes |
| `drug_exposure_start_date` | Shifted | Real dates |
| `drug_exposure_end_date` | Shifted (often NULL) | Real (often NULL) |
| `days_supply` | Yes | Yes |
| `quantity` | Yes | Yes |

## CDR versions

All CDR versions (v5+). The `drug_exposure` table follows the OMOP CDM standard. RxNorm vocabulary updates across versions may affect concept mappings.

---

## Reference

### Key tables

| Table | Purpose |
|---|---|
| `drug_exposure` | One row per drug prescription, dispensing, or administration record. |
| `concept` | Maps `drug_concept_id` to drug names, vocabulary (RxNorm), and concept class (Ingredient, Clinical Drug, Branded Drug, etc.). |
| `concept_ancestor` | Hierarchical relationships in RxNorm. An Ingredient is the ancestor of all its Clinical Drugs, Branded Drugs, and dose forms. |

### Key columns on `drug_exposure`

| Column | Type | Notes |
|---|---|---|
| `person_id` | INT64 | Participant identifier |
| `drug_concept_id` | INT64 | Standard concept ID (RxNorm). Usually at the Clinical Drug or Branded Drug level. |
| `drug_exposure_start_date` | DATE | When the exposure began. Shifted in Registered Tier. |
| `drug_exposure_end_date` | DATE | Often NULL or populated with defaults (start_date + 1 day). |
| `days_supply` | INT64 | Days of medication supplied. May be NULL. |
| `quantity` | FLOAT64 | Amount dispensed (e.g., number of pills). May be NULL. |
| `drug_type_concept_id` | INT64 | Provenance: prescription written (38000177), dispensed (38000175), EHR admin (32817), etc. |
| `drug_source_value` | STRING | Source code string (e.g., NDC code) |
| `sig` | STRING | Prescription instructions (free text, often NULL) |
| `route_concept_id` | INT64 | Route of administration (oral, injectable, topical, etc.) |

### RxNorm hierarchy (simplified)

```
Ingredient (e.g., metformin)
  └── Clinical Drug Form (metformin Oral Tablet)
        └── Clinical Drug (metformin 500 MG Oral Tablet)
              └── Branded Drug (Glucophage 500 MG Oral Tablet)
```

---

## Usage

### Step 1: Find the ingredient concept ID

```python
import os
import pandas as pd
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

# Find metformin's ingredient-level concept ID
ingredient_query = f"""
SELECT
    concept_id,
    concept_name,
    concept_class_id,
    vocabulary_id,
    standard_concept
FROM `{CDR}.concept`
WHERE vocabulary_id = 'RxNorm'
  AND concept_class_id = 'Ingredient'
  AND LOWER(concept_name) = 'metformin'
  AND standard_concept = 'S'
"""

ingredient_df = client.query(ingredient_query).to_dataframe()
print(ingredient_df.to_string(index=False))
# metformin ingredient concept_id = 1503297
```

> **Pitfall — querying a single brand or dose form silently undercounts exposures.** If your concept is a Clinical Drug (e.g., "metformin 500 MG Oral Tablet") or Branded Drug (e.g., "Glucophage") rather than an Ingredient, the `concept_ancestor` join captures only descendants of that specific formulation. Participants on other dose forms, generics, or combination products are silently missing. Always verify that your starting concept has `concept_class_id = 'Ingredient'` before querying.

### Step 2: Query by ingredient using `concept_ancestor`

This captures every formulation, dose, brand, and generic under the ingredient.

```python
METFORMIN_INGREDIENT_ID = 1503297

drug_query = f"""
SELECT
    de.person_id,
    de.drug_concept_id,
    c.concept_name            AS drug_name,
    c.concept_class_id,
    de.drug_exposure_start_date,
    de.drug_exposure_end_date,
    de.days_supply,
    de.quantity,
    de.drug_type_concept_id
FROM `{CDR}.drug_exposure` de
JOIN `{CDR}.concept_ancestor` ca
    ON de.drug_concept_id = ca.descendant_concept_id
JOIN `{CDR}.concept` c
    ON de.drug_concept_id = c.concept_id
WHERE ca.ancestor_concept_id = {METFORMIN_INGREDIENT_ID}
"""

metformin_df = client.query(drug_query).to_dataframe()
print(f"Total exposure records: {len(metformin_df):,}")
print(f"Unique participants: {metformin_df['person_id'].nunique():,}")
```

> **Pitfall -- querying by exact `drug_concept_id` for a specific product misses most exposures.**
> If you search for `drug_concept_id = 1503297` directly (the ingredient concept) in `drug_exposure`, you will get very few or zero results because most records are stored at the Clinical Drug or Branded Drug level (e.g., "metformin 500 MG Oral Tablet", concept_id 1502809). Searching for a single brand name like "Glucophage" misses all generic prescriptions, extended-release formulations, and combination products (e.g., metformin/sitagliptin). Always use `concept_ancestor` to roll up from the ingredient level, capturing the entire RxNorm subtree. This is the single most common medication query mistake in OMOP-based research.

Check what drug forms you are capturing:

```python
form_counts = (
    metformin_df
    .groupby(["concept_class_id", "drug_name"])
    .agg(records=("person_id", "size"),
         participants=("person_id", "nunique"))
    .sort_values("participants", ascending=False)
    .head(15)
)
print(form_counts.to_string())
```

### Step 3: Assess `drug_exposure_end_date` completeness

> **Pitfall -- `drug_exposure_end_date` is unreliable for duration calculations.**
> In many AoU source systems, `drug_exposure_end_date` is either NULL, set equal to `drug_exposure_start_date`, or populated with a default (start_date + 1 day). Before using end dates to calculate exposure duration, check the actual data.

```python
total = len(metformin_df)
null_end = metformin_df["drug_exposure_end_date"].isna().sum()
same_day = (
    metformin_df["drug_exposure_start_date"]
    == metformin_df["drug_exposure_end_date"]
).sum()

print(f"Total records: {total:,}")
print(f"NULL end_date: {null_end:,} ({null_end/total:.1%})")
print(f"Same-day start=end: {same_day:,} ({same_day/total:.1%})")
print(f"days_supply populated: "
      f"{metformin_df['days_supply'].notna().sum():,} "
      f"({metformin_df['days_supply'].notna().mean():.1%})")
```

When `drug_exposure_end_date` is unreliable, use `days_supply` to estimate exposure duration (when available):

```python
metformin_df["estimated_end"] = metformin_df.apply(
    lambda row: (
        row["drug_exposure_start_date"]
        + pd.Timedelta(days=row["days_supply"])
    ) if pd.notnull(row["days_supply"]) else pd.NaT,
    axis=1,
)
```

---

## Variations

### 1. Binary ever/never exposure

Create a simple binary indicator for cohort-level analysis.

```python
ever_exposed_query = f"""
SELECT DISTINCT de.person_id
FROM `{CDR}.drug_exposure` de
JOIN `{CDR}.concept_ancestor` ca
    ON de.drug_concept_id = ca.descendant_concept_id
WHERE ca.ancestor_concept_id = {METFORMIN_INGREDIENT_ID}
"""

exposed_df = client.query(ever_exposed_query).to_dataframe()

# Merge into full cohort
cohort_query = f"""
SELECT person_id FROM `{CDR}.cb_search_person`
"""
cohort_df = client.query(cohort_query).to_dataframe()

cohort_df["metformin_ever"] = cohort_df["person_id"].isin(
    exposed_df["person_id"]
).astype(int)

print(f"Ever exposed: {cohort_df['metformin_ever'].sum():,} "
      f"({cohort_df['metformin_ever'].mean():.2%})")
```

### 2. Temporal exposure windows relative to index date

Determine whether a participant was exposed during a specific time period (e.g., 90 days before an outcome).

```python
window_query = f"""
WITH index_dates AS (
    SELECT person_id, MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_concept_id = 201826  -- T2DM diagnosis
    GROUP BY person_id
)
SELECT DISTINCT de.person_id
FROM `{CDR}.drug_exposure` de
JOIN `{CDR}.concept_ancestor` ca
    ON de.drug_concept_id = ca.descendant_concept_id
JOIN index_dates idx
    ON de.person_id = idx.person_id
WHERE ca.ancestor_concept_id = {METFORMIN_INGREDIENT_ID}
  AND DATE_DIFF(de.drug_exposure_start_date,
                idx.index_date, DAY) BETWEEN -90 AND 0
"""

pre_index_exposed = client.query(window_query).to_dataframe()
print(f"Exposed 90 days before index: {len(pre_index_exposed):,}")
```

### 3. Concurrent medication detection (polypharmacy)

Find participants taking multiple medications of interest simultaneously.

```python
# Define ingredients of interest
medications = {
    1503297: "metformin",
    1529331: "atorvastatin",
    1332418: "amlodipine",
    1308216: "lisinopril",
}
med_ids = ", ".join(str(k) for k in medications.keys())

polypharm_query = f"""
WITH ingredient_exposures AS (
    SELECT DISTINCT
        de.person_id,
        ca.ancestor_concept_id AS ingredient_id
    FROM `{CDR}.drug_exposure` de
    JOIN `{CDR}.concept_ancestor` ca
        ON de.drug_concept_id = ca.descendant_concept_id
    WHERE ca.ancestor_concept_id IN ({med_ids})
)
SELECT
    person_id,
    COUNT(DISTINCT ingredient_id) AS n_medications,
    ARRAY_AGG(DISTINCT ingredient_id) AS medication_ids
FROM ingredient_exposures
GROUP BY person_id
HAVING COUNT(DISTINCT ingredient_id) >= 2
ORDER BY n_medications DESC
"""

polypharm_df = client.query(polypharm_query).to_dataframe()
polypharm_df["medications"] = polypharm_df["medication_ids"].apply(
    lambda ids: ", ".join(medications.get(i, str(i)) for i in ids)
)

print(f"Participants on 2+ medications: {len(polypharm_df):,}")
print(polypharm_df["n_medications"].value_counts().sort_index())
```

For truly concurrent exposure (overlapping dates), add temporal overlap logic:

```python
concurrent_query = f"""
WITH exposures AS (
    SELECT
        de.person_id,
        ca.ancestor_concept_id AS ingredient_id,
        de.drug_exposure_start_date,
        COALESCE(
            de.drug_exposure_end_date,
            DATE_ADD(de.drug_exposure_start_date,
                     INTERVAL COALESCE(de.days_supply, 30) DAY)
        ) AS exposure_end
    FROM `{CDR}.drug_exposure` de
    JOIN `{CDR}.concept_ancestor` ca
        ON de.drug_concept_id = ca.descendant_concept_id
    WHERE ca.ancestor_concept_id IN ({med_ids})
)
SELECT DISTINCT
    a.person_id,
    a.ingredient_id AS med_a,
    b.ingredient_id AS med_b
FROM exposures a
JOIN exposures b
    ON  a.person_id = b.person_id
    AND a.ingredient_id < b.ingredient_id
    AND a.drug_exposure_start_date <= b.exposure_end
    AND b.drug_exposure_start_date <= a.exposure_end
"""

concurrent_df = client.query(concurrent_query).to_dataframe()
```

---

> **Pitfall — drugs with dual indications contaminate cohorts in general biobanks.** Bone-modifying agents are a key example: denosumab is sold as Xgeva (120 mg, oncology) AND Prolia (60 mg, osteoporosis); zoledronic acid is Zometa (4 mg, oncology) AND Reclast (5 mg, osteoporosis). In All of Us (a general population biobank), ~80% of patients on these drugs have osteoporosis, not cancer. Using drug exposure alone as a cancer treatment proxy is unreliable — always cross-reference against a confirmed cancer diagnosis.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Zero results when querying by ingredient concept_id directly | Records are stored at the Clinical Drug or Branded Drug level, not the Ingredient level. Use `concept_ancestor` to capture all descendants. |
| `concept_ancestor` join returns unexpected drugs | A combination product (e.g., metformin/sitagliptin) has multiple ingredient ancestors. If you query metformin, you will also capture combo products. This is usually correct but verify. |
| Query is very slow | The `drug_exposure` table is large. Always filter by `concept_ancestor` in a CTE or subquery rather than scanning the full table. Add a cohort `person_id` filter when possible. |

---

## Cost note

The `drug_exposure` table is large (tens to hundreds of millions of rows). Joining through `concept_ancestor` is efficient because BigQuery pushes the `ancestor_concept_id` predicate into the join. Expect 500 MB-3 GB per ingredient-level query. For multi-medication analyses, combine all ingredient IDs into a single query rather than running separate queries per drug.

---

## See also

- [query-lab-measurements.md](../labs-measurements/query-lab-measurements.md) -- Linking lab results to drug exposures (e.g., HbA1c trajectory on metformin)
- [query-condition-occurrence.md](../conditions-phenotypes/query-condition-occurrence.md) -- Pairing conditions with medication history
- [build-multi-code-phenotype.md](../conditions-phenotypes/build-multi-code-phenotype.md) -- Multi-code phenotyping patterns applicable to drug code lists

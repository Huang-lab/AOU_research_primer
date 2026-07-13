# Query lab measurements by LOINC code

Pull laboratory measurements from the `measurement` table by mapping LOINC codes to OMOP concept IDs, with proper unit handling and plausibility filtering.

## Prerequisites

- Researcher Workbench notebook environment
- `pandas`, `google-cloud-bigquery` installed (default in AoU environment)
- The LOINC code(s) for the lab test(s) you want to query

## Tier availability

| Feature | Registered Tier | Controlled Tier |
|---|---|---|
| `measurement` table | Yes | Yes |
| `measurement_date` | Shifted | Real dates |
| `value_as_number` | Yes | Yes |
| `unit_concept_id` | Yes | Yes |

## CDR versions

All CDR versions (v5+). The `measurement` table follows the OMOP CDM standard. LOINC-to-concept mappings may change across vocabulary versions.

---

## Reference

### Key tables

| Table | Purpose |
|---|---|
| `measurement` | One row per lab result / vital sign / clinical measurement. Contains numeric values, units, and dates. |
| `concept` | Maps `measurement_concept_id` to LOINC names and codes. Also maps `unit_concept_id` to unit strings. |

### Key columns on `measurement`

| Column | Type | Notes |
|---|---|---|
| `person_id` | INT64 | Participant identifier |
| `measurement_concept_id` | INT64 | Standard OMOP concept ID (mapped from LOINC) |
| `measurement_date` | DATE | Date of measurement. Shifted in Registered Tier. |
| `value_as_number` | FLOAT64 | Numeric result. NULL for qualitative-only results. |
| `value_as_concept_id` | INT64 | Concept ID for qualitative results (e.g., "Positive", "Negative") |
| `unit_concept_id` | INT64 | OMOP concept ID for the unit of measure |
| `unit_source_value` | STRING | Original unit string from the source system |
| `range_low` | FLOAT64 | Lab-reported reference range lower bound |
| `range_high` | FLOAT64 | Lab-reported reference range upper bound |
| `measurement_type_concept_id` | INT64 | Provenance (EHR, self-report, etc.) |
| `measurement_source_value` | STRING | Source code as recorded (often the LOINC code string) |

---

## Usage

### Step 1: Find the concept ID for your LOINC code

```python
import os
import pandas as pd
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

# Example: HbA1c (LOINC 4548-4)
loinc_lookup_query = f"""
SELECT
    concept_id,
    concept_name,
    concept_code,
    vocabulary_id,
    standard_concept
FROM `{CDR}.concept`
WHERE vocabulary_id = 'LOINC'
  AND concept_code = '4548-4'
"""

loinc_df = client.query(loinc_lookup_query).to_dataframe()
print(loinc_df.to_string(index=False))
# Note the concept_id for use in subsequent queries
```

If you are unsure of the exact LOINC code, search by name:

```python
search_query = f"""
SELECT concept_id, concept_name, concept_code
FROM `{CDR}.concept`
WHERE vocabulary_id = 'LOINC'
  AND LOWER(concept_name) LIKE '%hemoglobin a1c%'
  AND standard_concept = 'S'
  AND domain_id = 'Measurement'
"""
client.query(search_query).to_dataframe()
```

### Step 2: Pull measurements with proper filtering

```python
# Using the concept_id found above (e.g., 3004410 for HbA1c)
HBA1C_CONCEPT_ID = 3004410

lab_query = f"""
SELECT
    m.person_id,
    m.measurement_date,
    m.value_as_number,
    m.unit_concept_id,
    uc.concept_name AS unit_name,
    m.range_low,
    m.range_high
FROM `{CDR}.measurement` m
LEFT JOIN `{CDR}.concept` uc
    ON m.unit_concept_id = uc.concept_id
WHERE m.measurement_concept_id = {HBA1C_CONCEPT_ID}
  AND m.value_as_number IS NOT NULL
"""

hba1c_df = client.query(lab_query).to_dataframe()
print(f"Total rows: {len(hba1c_df):,}")
print(f"Unique participants: {hba1c_df['person_id'].nunique():,}")
```

> **Pitfall -- rows with NULL `value_as_number` silently corrupt aggregations.**
> The `measurement` table contains rows where `value_as_number` is NULL. These arise from qualitative-only results (e.g., "Positive"), text comments logged as measurements, cancelled/errored lab orders, and results below the detection limit. If you omit the `value_as_number IS NOT NULL` filter and then compute `AVG(value_as_number)`, BigQuery ignores NULLs in aggregate functions -- but `pandas` operations like `.mean()` on a column with NaN values behave differently depending on context. More critically, your denominator (row count) will include NULL rows, making frequency calculations wrong. Always filter explicitly.

### Step 3: Check and handle unit heterogeneity

```python
unit_dist = hba1c_df.groupby("unit_name").agg(
    count=("value_as_number", "size"),
    mean=("value_as_number", "mean"),
    median=("value_as_number", "median"),
    min=("value_as_number", "min"),
    max=("value_as_number", "max"),
).reset_index()

print(unit_dist.to_string(index=False))
```

> **Pitfall -- same lab test in different units.**
> HbA1c can appear as a percentage (e.g., 6.5%) or in mmol/mol (e.g., 48 mmol/mol). Glucose can appear as mg/dL or mmol/L. If you aggregate `value_as_number` across units, your mean, median, and distribution are garbage. Always check `unit_concept_id` distribution first. Convert to a common unit before any analysis:

```python
# Example: convert HbA1c mmol/mol to percent
# IFCC (mmol/mol) to NGSP (%): % = (mmol/mol / 10.929) + 2.15
MMOL_MOL_UNIT = 8554  # unit_concept_id for mmol/mol

hba1c_df["value_pct"] = hba1c_df.apply(
    lambda row: (row["value_as_number"] / 10.929) + 2.15
    if row["unit_concept_id"] == MMOL_MOL_UNIT
    else row["value_as_number"],
    axis=1,
)
```

### Step 4: Apply clinical plausibility bounds

> **Pitfall -- biologically implausible outliers.**
> AoU measurement data contains values that are clearly erroneous: glucose values of 9999, HbA1c of 0.0 or 99.9, negative lab values for tests that cannot be negative. These arise from data entry errors, unit mismatch at the source, and sentinel values used by EHR systems. A single glucose value of 9999 mg/dL will dramatically skew your mean. Always define and apply clinical plausibility bounds before computing any summary statistics.

```python
# Clinical plausibility bounds for HbA1c (%)
HBAIC_LOW = 3.0
HBAIC_HIGH = 20.0

before_filter = len(hba1c_df)
hba1c_df = hba1c_df[
    hba1c_df["value_pct"].between(HBAIC_LOW, HBAIC_HIGH)
]
after_filter = len(hba1c_df)

print(f"Removed {before_filter - after_filter:,} implausible values "
      f"({(before_filter - after_filter)/before_filter:.2%})")
print(f"Final: mean={hba1c_df['value_pct'].mean():.2f}, "
      f"median={hba1c_df['value_pct'].median():.2f}")
```

Common plausibility bounds (adjust for your study):

| Lab test | Plausible low | Plausible high | Unit |
|---|---|---|---|
| HbA1c | 3.0 | 20.0 | % |
| Glucose (fasting) | 20 | 600 | mg/dL |
| Creatinine | 0.1 | 25.0 | mg/dL |
| eGFR | 1 | 200 | mL/min/1.73m2 |
| Total cholesterol | 50 | 500 | mg/dL |
| LDL cholesterol | 10 | 400 | mg/dL |
| BMI | 10 | 80 | kg/m2 |

---

## Variations

### 1. Most recent measurement per participant

Useful for cross-sectional analyses where you need one value per person.

```python
latest_query = f"""
WITH ranked AS (
    SELECT
        person_id,
        value_as_number,
        measurement_date,
        unit_concept_id,
        ROW_NUMBER() OVER (
            PARTITION BY person_id
            ORDER BY measurement_date DESC
        ) AS rn
    FROM `{CDR}.measurement`
    WHERE measurement_concept_id = {HBA1C_CONCEPT_ID}
      AND value_as_number IS NOT NULL
)
SELECT person_id, value_as_number, measurement_date, unit_concept_id
FROM ranked
WHERE rn = 1
"""

latest_df = client.query(latest_query).to_dataframe()
```

### 2. All measurements within a time window relative to index

```python
windowed_query = f"""
WITH index_dates AS (
    SELECT person_id, MIN(condition_start_date) AS index_date
    FROM `{CDR}.condition_occurrence`
    WHERE condition_concept_id = 201826  -- T2DM
    GROUP BY person_id
)
SELECT
    m.person_id,
    m.value_as_number,
    m.measurement_date,
    DATE_DIFF(m.measurement_date,
              idx.index_date, DAY) AS days_from_index
FROM `{CDR}.measurement` m
JOIN index_dates idx ON m.person_id = idx.person_id
WHERE m.measurement_concept_id = {HBA1C_CONCEPT_ID}
  AND m.value_as_number IS NOT NULL
  AND DATE_DIFF(m.measurement_date,
                idx.index_date, DAY) BETWEEN -180 AND 180
"""

windowed_df = client.query(windowed_query).to_dataframe()
```

### 3. Multiple lab tests in a single query

Pull several labs at once and pivot into a wide-format dataframe.

```python
# concept_id mapping
labs = {
    3004410: "hba1c",
    3000963: "glucose",
    3016723: "creatinine",
    3007070: "total_cholesterol",
}
lab_ids = ", ".join(str(k) for k in labs.keys())

multi_lab_query = f"""
SELECT
    m.person_id,
    m.measurement_concept_id,
    m.value_as_number,
    m.measurement_date
FROM `{CDR}.measurement` m
WHERE m.measurement_concept_id IN ({lab_ids})
  AND m.value_as_number IS NOT NULL
"""

multi_df = client.query(multi_lab_query).to_dataframe()
multi_df["lab_name"] = multi_df["measurement_concept_id"].map(labs)
```

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| LOINC code returns no concept_id | The LOINC code may not exist in the CDR's vocabulary version, or you may have the wrong format (use `4548-4` not `LOINC:4548-4`). Search by name as a fallback. |
| Very few results for a common lab | You may be using a non-standard concept_id. Check `standard_concept = 'S'` in the concept table. AoU maps source codes to standard OMOP concepts. |
| `value_as_number` and `value_as_concept_id` are both NULL | These are rows with results stored only as free text in `value_source_value`. They cannot be used in numeric analyses. |
| `range_low` and `range_high` are NULL | Not all source labs report reference ranges. This is expected. Do not rely on these columns being populated. |

---

## Cost note

The `measurement` table is the largest table in the AoU CDR (hundreds of millions of rows). Filtering by `measurement_concept_id` is essential -- a full table scan processes 10+ GB. Joining with a cohort CTE on `person_id` further reduces cost. For iterative work, cache the filtered result in a pandas dataframe rather than re-running the query.

---

## See also

- [query-condition-occurrence.md](../conditions-phenotypes/query-condition-occurrence.md) -- Pairing lab results with condition diagnoses
- [query-drug-exposures.md](../medications/query-drug-exposures.md) -- Linking medication exposures to lab trajectories
- [extract-demographic-features.md](../demographics-ancestry/extract-demographic-features.md) -- Adding demographics to lab-based cohorts

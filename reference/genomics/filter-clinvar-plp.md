# Filter variants to ClinVar Pathogenic/Likely Pathogenic

Add a ClinVar clinical significance filter to variant queries, restricting results to Pathogenic (P) and Likely Pathogenic (LP) classifications.

## Prerequisites

- Controlled-tier workspace access
- A variant query to which the filter will be added (see [Query carrier status for a gene panel](query-carrier-status.md))
- Python 3, `google-cloud-bigquery`, `pandas`

**Tier:** Controlled
**CDR versions:** v7+ (ClinVar annotations are updated with each CDR release)

## Reference

ClinVar classifications are stored in the `cb_variant_attribute` table (or a related annotations table, depending on CDR version) in a `clinical_significance` string column. The values in this column are not simple enumerations -- they are free-text compound strings drawn from ClinVar's submission summaries.

Common `clinical_significance` values in AoU data:

| Value | Contains "Pathogenic"? |
|---|---|
| `Pathogenic` | Yes |
| `Likely pathogenic` | Yes |
| `Pathogenic/Likely pathogenic` | Yes |
| `Pathogenic, risk factor` | Yes |
| `Pathogenic, drug response` | Yes |
| `Uncertain significance` | No |
| `Benign` | No |
| `Likely benign` | No |
| `Benign/Likely benign` | No |
| `Conflicting classifications of pathogenicity` | Yes (substring match!) |

## Usage

### Step 1: Explore the actual classification values

Before filtering, inspect what values exist in your CDR:

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

# See distinct clinical_significance values and their counts
explore_sql = f"""
SELECT
    clinical_significance,
    COUNT(*) AS n_variants
FROM `{CDR}.cb_variant_attribute`
WHERE clinical_significance IS NOT NULL
GROUP BY clinical_significance
ORDER BY n_variants DESC
LIMIT 50
"""
sig_values = client.query(explore_sql).to_dataframe()
print(sig_values.to_string(index=False))
```

### Step 2: Apply the P/LP filter with LIKE

```python
plp_sql = f"""
SELECT
    va.vid,
    va.clinical_significance,
    va.consequence,
    g.gene_symbol
FROM `{CDR}.cb_variant_attribute` va
JOIN `{CDR}.cb_variant_attribute_genes` g ON va.vid = g.vid
WHERE g.gene_symbol IN ('BRCA1', 'BRCA2')
  AND (
      va.clinical_significance LIKE '%Pathogenic%'
      OR va.clinical_significance LIKE '%pathogenic%'
  )
"""
plp_variants = client.query(plp_sql).to_dataframe()
print(f"P/LP variants: {len(plp_variants):,}")
print(plp_variants["clinical_significance"].value_counts())
```

> **Pitfall: exact-match filtering on `clinical_significance`.** If you write `WHERE clinical_significance = 'Pathogenic'`, you will miss every compound classification: `"Pathogenic/Likely pathogenic"`, `"Pathogenic, risk factor"`, `"Likely pathogenic"`, and others. ClinVar uses slash-separated and comma-separated compound strings. Use `LIKE '%Pathogenic%'` or parse the string. Note that `LIKE '%Pathogenic%'` will also match `"Conflicting classifications of pathogenicity"` -- you may want to exclude that explicitly (see Step 3).

> **Pitfall — `LIKE '%Pathogenic%'` silently includes "Conflicting classifications of pathogenicity".** This inflates your P/LP carrier count by including variants where submissions disagree on pathogenicity. These are not definitive P/LP calls. Add `AND va.clinical_significance NOT LIKE '%Conflicting%'` to exclude them (see Step 3).

### Step 3: Exclude conflicting classifications

The `LIKE '%Pathogenic%'` pattern matches "Conflicting classifications of pathogenicity", which is not a definitive P/LP call. Exclude it:

```python
plp_strict_sql = f"""
SELECT
    va.vid,
    va.clinical_significance,
    g.gene_symbol
FROM `{CDR}.cb_variant_attribute` va
JOIN `{CDR}.cb_variant_attribute_genes` g ON va.vid = g.vid
WHERE g.gene_symbol IN ('BRCA1', 'BRCA2')
  AND (
      va.clinical_significance LIKE '%Pathogenic%'
      OR va.clinical_significance LIKE '%pathogenic%'
  )
  AND va.clinical_significance NOT LIKE '%Conflicting%'
"""
plp_strict = client.query(plp_strict_sql).to_dataframe()
print(f"Strict P/LP variants (excl. conflicting): {len(plp_strict):,}")
```

### Step 4: Join to carriers

Combine the P/LP filter with a carrier-status query:

```python
plp_carriers_sql = f"""
SELECT DISTINCT
    vp.person_id,
    g.gene_symbol,
    va.clinical_significance,
    vp.allele_count
FROM `{CDR}.cb_variant_attribute_genes` g
JOIN `{CDR}.cb_variant_attribute` va ON g.vid = va.vid
JOIN `{CDR}.cb_variant_to_person` vp ON va.vid = vp.vid
WHERE g.gene_symbol IN UNNEST(@genes)
  AND (
      va.clinical_significance LIKE '%Pathogenic%'
      OR va.clinical_significance LIKE '%pathogenic%'
  )
  AND va.clinical_significance NOT LIKE '%Conflicting%'
"""
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ArrayQueryParameter(
            "genes", "STRING", ["BRCA1", "BRCA2"]
        )
    ]
)
plp_carriers = client.query(
    plp_carriers_sql, job_config=job_config
).to_dataframe()
print(f"P/LP carriers: {plp_carriers['person_id'].nunique():,}")
```

> **Pitfall: ClinVar annotations change between CDR releases.** A variant classified as VUS (Variant of Uncertain Significance) in CDR v7 may be reclassified as Pathogenic in v8, and vice versa. The same query run against different CDR versions can return different participant sets. Always document which CDR version your classification is based on, and re-run classification queries when upgrading CDR versions.

```python
# Document the CDR version in your output
print(f"CDR version: {CDR}")
print(f"Query date: {pd.Timestamp.now().date()}")
print(f"ClinVar classifications are CDR-version-specific.")
```

## Variations

### Including VUS for sensitivity analyses

For exploratory work, you may want a tiered classification that includes VUS:

```python
tiered_sql = f"""
SELECT
    va.vid,
    g.gene_symbol,
    va.clinical_significance,
    CASE
        WHEN va.clinical_significance LIKE '%Pathogenic%'
             AND va.clinical_significance NOT LIKE '%Conflicting%'
             THEN 'P_LP'
        WHEN va.clinical_significance LIKE '%Conflicting%'
             THEN 'Conflicting'
        WHEN va.clinical_significance LIKE '%Uncertain%'
             THEN 'VUS'
        WHEN va.clinical_significance LIKE '%enign%'
             THEN 'B_LB'
        ELSE 'Other'
    END AS significance_tier
FROM `{CDR}.cb_variant_attribute` va
JOIN `{CDR}.cb_variant_attribute_genes` g ON va.vid = g.vid
WHERE g.gene_symbol IN ('BRCA1', 'BRCA2')
"""
tiered = client.query(tiered_sql).to_dataframe()
print(tiered["significance_tier"].value_counts())
```

### Case-insensitive matching with LOWER()

If you are uncertain about capitalization conventions across CDR versions:

```python
# Case-insensitive approach
case_safe_filter = """
    LOWER(va.clinical_significance) LIKE '%pathogenic%'
    AND LOWER(va.clinical_significance) NOT LIKE '%conflicting%'
"""
```

### Regex-based parsing for compound strings

For fine-grained control, parse the compound strings with `REGEXP_CONTAINS`:

```python
regex_sql = f"""
SELECT vid, clinical_significance
FROM `{CDR}.cb_variant_attribute`
WHERE REGEXP_CONTAINS(
    clinical_significance,
    r'(?i)^(Likely )?[Pp]athogenic'
)
AND NOT REGEXP_CONTAINS(
    clinical_significance,
    r'(?i)conflicting'
)
"""
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `LIKE '%Pathogenic%'` returns no rows | Column may be NULL for most variants (only ClinVar-annotated variants have a value), or the column name may differ in your CDR version. Check with `INFORMATION_SCHEMA`. |
| `Unrecognized name: clinical_significance` | Column name differs in this CDR release. Run the schema discovery query from [Discover genomics table schemas](discover-genomics-tables.md). |

## Cost note

The ClinVar filter adds one join to `cb_variant_attribute`, which is much smaller than `cb_variant_to_person`. The marginal cost increase is minimal. The most expensive part of the query remains the scan of `cb_variant_to_person` for carrier lookup.

## See also

- [Query carrier status for a gene panel](query-carrier-status.md) -- the base carrier query this filter extends
- [Discover genomics table schemas](discover-genomics-tables.md) -- verify column names and available annotations

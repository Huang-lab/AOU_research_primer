# Query carrier status for a gene panel

Determine which participants carry variants in one or more specified genes using the Cohort Builder genomics tables.

## Prerequisites

- Controlled-tier workspace access (genomic data is controlled-tier only)
- Gene symbols for your panel (e.g., BRCA1, BRCA2, TP53)
- A defined cohort with `person_id` values to join against
- Python 3, `google-cloud-bigquery`, `pandas`

**Tier:** Controlled
**CDR versions:** v7+ (verify column names with `INFORMATION_SCHEMA`; see [Discover genomics table schemas](discover-genomics-tables.md))

## Reference

AoU stores short-variant (SNV/indel) genomic data in several tables. For carrier-status queries, the key Cohort Builder tables are:

| Table | Purpose |
|---|---|
| `cb_variant_to_person` | Maps each variant (by `vid`) to carriers (`person_ids` — an ARRAY of INT64) |
| `cb_variant_attribute` | Variant-level annotations (consequence, allele frequency, etc.) |
| `cb_variant_attribute_genes` | Maps variants to gene symbols |

The join path is: `cb_variant_attribute_genes` (gene filter) --> `cb_variant_attribute` (optional annotation filter) --> `cb_variant_to_person` (carrier lookup).

**Join keys:** The shared key between these tables is `vid` (variant ID). In earlier CDR releases, the join key was named differently or required an intermediate table. Always verify with `INFORMATION_SCHEMA` if working with an unfamiliar CDR version.

> **Version note — `person_ids` is an ARRAY column.** `cb_variant_to_person.person_ids` stores carrier IDs as a `REPEATED INT64` (BigQuery ARRAY). You must use `UNNEST(person_ids) AS person_id` to extract individual rows. Treating it as a scalar column will silently produce wrong results or fail.

> **Version note — column names changed in recent CDR releases.** The consequence column is now `cons_str` (was `consequence`) and the ClinVar column is `clinical_significance_string` (was `clinical_significance`). Similarly, there is no `allele_count` column on `cb_variant_to_person`; determine zygosity by counting distinct variants per person per gene. Always verify with `INFORMATION_SCHEMA`.

## Usage

### Step 1: Query carriers for a gene panel

```python
import os
import pandas as pd
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

genes = ["BRCA1", "BRCA2"]

carrier_sql = f"""
SELECT DISTINCT
    person_id,
    g.gene_symbol,
    vp.vid
FROM `{CDR}.cb_variant_attribute_genes` g
JOIN `{CDR}.cb_variant_to_person` vp
    ON g.vid = vp.vid,
    UNNEST(vp.person_ids) AS person_id
WHERE g.gene_symbol IN UNNEST(@genes)
"""
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ArrayQueryParameter("genes", "STRING", genes)
    ]
)
carriers_df = client.query(carrier_sql, job_config=job_config).to_dataframe()
print(f"Carrier rows returned: {len(carriers_df):,}")
print(f"Unique carriers: {carriers_df['person_id'].nunique():,}")
```

> **Pitfall: the result returns CARRIERS ONLY.** Non-carriers are completely absent from the output -- they do not appear as rows with zero variants. If you compute a carrier rate as `len(carriers_df) / len(carriers_df)`, you get 100%. Any rate, odds ratio, or enrichment calculated on the raw result has a missing denominator and is silently wrong. You must left-join back to your full cohort and fill missing values with zero.

> **Pitfall — counting variants instead of carriers inflates carrier counts.** If you use `COUNT(*)` or `len(carriers_df)` to count carriers, you are counting variant rows, not distinct people. A participant carrying three variants in BRCA1 contributes three rows. Use `COUNT(DISTINCT person_id)` in SQL or `carriers_df['person_id'].nunique()` in pandas to get the true carrier count.

### Step 2: Left-join to full cohort and fill non-carriers

```python
# cohort_df: DataFrame with all person_ids in your study
cohort_df = pd.read_gbq(
    f"SELECT DISTINCT person_id FROM `{CDR}.cb_search_person`",
    progress_bar_type=None,
)

# Summarize: does each person carry any variant in the panel?
carrier_flag = (
    carriers_df.groupby("person_id")["vid"]
    .count()
    .reset_index()
    .rename(columns={"vid": "n_variants"})
)

# Left join -- non-carriers get NaN, then fill with 0
cohort_carriers = cohort_df.merge(carrier_flag, on="person_id", how="left")
cohort_carriers["n_variants"] = cohort_carriers["n_variants"].fillna(0).astype(int)
cohort_carriers["is_carrier"] = (cohort_carriers["n_variants"] > 0).astype(int)

print(f"Total cohort: {len(cohort_carriers):,}")
print(f"Carriers: {cohort_carriers['is_carrier'].sum():,}")
print(f"Carrier rate: {cohort_carriers['is_carrier'].mean():.4%}")
```

### Step 3: Per-gene carrier status (for multi-gene panels)

```python
# Pivot to one column per gene
per_gene = (
    carriers_df.groupby(["person_id", "gene_symbol"])["vid"]
    .count()
    .reset_index()
    .rename(columns={"vid": "n_variants"})
)
per_gene_wide = per_gene.pivot(
    index="person_id",
    columns="gene_symbol",
    values="n_variants",
).fillna(0).astype(int)
per_gene_wide.columns = [f"carrier_{g}" for g in per_gene_wide.columns]

# Merge with cohort
cohort_gene = cohort_df.merge(
    per_gene_wide, on="person_id", how="left"
).fillna(0)
for col in per_gene_wide.columns:
    cohort_gene[col] = cohort_gene[col].astype(int)
```

> **Pitfall: join key changes across CDR releases.** The column name used to link variant tables has changed in past CDR updates (e.g., `vid` may have been `variant_id` or required joining through an intermediate table). If your query returns zero rows unexpectedly, do not assume the data is empty -- verify the join key exists with `INFORMATION_SCHEMA`. See [Discover genomics table schemas](discover-genomics-tables.md).

## Variations

### Restrict to ClinVar Pathogenic/Likely Pathogenic

Add a ClinVar significance filter to return only clinically actionable variants:

```python
plp_carrier_sql = f"""
SELECT DISTINCT
    person_id,
    g.gene_symbol,
    vp.vid,
    va.clinical_significance_string
FROM `{CDR}.cb_variant_attribute_genes` g
JOIN `{CDR}.cb_variant_attribute` va ON g.vid = va.vid
JOIN `{CDR}.cb_variant_to_person` vp ON va.vid = vp.vid,
    UNNEST(vp.person_ids) AS person_id
WHERE g.gene_symbol IN UNNEST(@genes)
  AND va.clinical_significance_string LIKE '%athogenic%'
  AND va.clinical_significance_string NOT LIKE '%enign%'
"""
```

For full details on ClinVar filtering, see [Filter variants to ClinVar Pathogenic/Likely Pathogenic](filter-clinvar-plp.md).

### Single gene lookup

For a single gene, use a string parameter instead of an array:

```python
single_gene_sql = f"""
SELECT DISTINCT person_id, vp.vid
FROM `{CDR}.cb_variant_attribute_genes` g
JOIN `{CDR}.cb_variant_to_person` vp ON g.vid = vp.vid,
    UNNEST(vp.person_ids) AS person_id
WHERE g.gene_symbol = 'BRCA1'
"""
```

### Add variant consequence filtering

Restrict to loss-of-function variants (frameshift, stop gained, splice donor/acceptor):

```python
lof_sql = f"""
SELECT DISTINCT person_id, g.gene_symbol, va.cons_str
FROM `{CDR}.cb_variant_attribute_genes` g
JOIN `{CDR}.cb_variant_attribute` va ON g.vid = va.vid
JOIN `{CDR}.cb_variant_to_person` vp ON va.vid = vp.vid,
    UNNEST(vp.person_ids) AS person_id
WHERE g.gene_symbol IN UNNEST(@genes)
  AND (va.cons_str LIKE '%frameshift%'
       OR va.cons_str LIKE '%stop_gained%'
       OR va.cons_str LIKE '%splice_donor%'
       OR va.cons_str LIKE '%splice_acceptor%')
"""
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| Query returns 0 rows | (1) Gene symbol not in `cb_variant_attribute_genes` -- check spelling and case. (2) Join key mismatch across CDR versions -- run `INFORMATION_SCHEMA` query to verify column names. |
| `BadRequest: Unrecognized name: vid` | The CDR version uses a different column name for the variant identifier. See [Discover genomics table schemas](discover-genomics-tables.md). |
| Query runs for >10 minutes | `cb_variant_to_person` is very large. Add a dry-run first (see [Dry-run a query](../cost-awareness/dry-run-query.md)). Consider filtering on specific chromosomes if your gene panel allows it. |
## Cost note

**Medium-high.** `cb_variant_to_person` is one of the largest tables in the CDR. A full scan can process hundreds of GB. Always dry-run first. If querying repeatedly, materialize the carrier table for your gene panel as a saved query result or temporary table.

## See also

- [Filter variants to ClinVar Pathogenic/Likely Pathogenic](filter-clinvar-plp.md) -- add clinical significance filtering
- [Discover genomics table schemas](discover-genomics-tables.md) -- verify table and column names for your CDR version
- [Dry-run a query to estimate cost](../cost-awareness/dry-run-query.md) -- estimate cost before running genomics queries

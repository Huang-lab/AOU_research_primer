# Compute genetic ancestry principal components

Access pre-computed ancestry principal components from the AoU genomics pipeline and merge them into a cohort dataframe for use as covariates in genetic association analyses.

## Prerequisites

- Researcher Workbench notebook environment with **Controlled Tier** CDR
- Access to the AoU genomics data (requires approval for Controlled Tier genomic data)
- `pandas`, `google-cloud-bigquery` installed (default in AoU environment)

## Tier availability

| Feature | Registered Tier | Controlled Tier |
|---|---|---|
| Ancestry PCs | No | Yes |
| Genomic data | No | Yes |

Ancestry principal components are only available in the Controlled Tier because they are derived from genomic data.

## CDR versions

CDR v7+ includes the genomics ancillary tables with pre-computed PCs. Earlier CDR versions may require computing PCs from the WGS VCFs directly.

---

## Reference

### Key tables

| Table | Purpose |
|---|---|
| `cb_search_person` | Cohort Builder person table. Used to define your analytic cohort before joining PCs. |
| `person` | Core OMOP person table. Contains `race_concept_id` for self-reported race. |
| `prep_ancestry` | AoU genomics ancillary table containing pre-computed ancestry principal components and predicted ancestry labels. |

### Key columns on `prep_ancestry`

| Column | Type | Notes |
|---|---|---|
| `person_id` | INT64 | Joins to `person.person_id` |
| `pca_features` | STRING (repeated/array) or FLOAT64 columns | Pre-computed PC values. Format may vary by CDR version -- check schema. |
| `ancestry_pred` | STRING | Predicted genetic ancestry label (e.g., `eur`, `afr`, `amr`, `eas`, `sas`, `mid`) |
| `ancestry_pred_other` | STRING | Secondary ancestry prediction for admixed individuals |

> The exact table name and column layout for PCs may vary across CDR releases. Use `INFORMATION_SCHEMA.COLUMNS` to confirm the current schema:
>
> ```python
> schema_query = f"""
> SELECT table_name, column_name, data_type
> FROM `{CDR}.INFORMATION_SCHEMA.COLUMNS`
> WHERE table_name LIKE '%ancestry%' OR table_name LIKE '%pca%'
> ORDER BY table_name, ordinal_position
> """
> schema_df = client.query(schema_query).to_dataframe()
> ```

---

## Usage

### Retrieve pre-computed PCs

```python
import os
import pandas as pd
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

pc_query = f"""
SELECT
    person_id,
    ancestry_pred,
    pca_features
FROM `{CDR}.prep_ancestry`
"""

pc_df = client.query(pc_query).to_dataframe()
print(f"Participants with PCs: {len(pc_df):,}")
print(f"Ancestry distribution:\n{pc_df['ancestry_pred'].value_counts()}")
```

If PCs are stored as an array column, expand them into separate columns:

```python
# Expand array of PCs into individual columns
pc_expanded = pd.DataFrame(
    pc_df["pca_features"].tolist(),
    columns=[f"PC{i+1}" for i in range(len(pc_df["pca_features"].iloc[0]))]
)
pc_expanded["person_id"] = pc_df["person_id"].values
pc_expanded["ancestry_pred"] = pc_df["ancestry_pred"].values
```

!!! pitfall "using self-reported race as a proxy for genetic ancestry"
    Self-reported race does not capture genetic admixture and is a social, not biological, construct. In any genetic association analysis (GWAS, PRS, Mendelian randomization), using race instead of ancestry PCs as covariates will leave population stratification uncontrolled, producing spurious associations. For example, a variant common in one ancestry group will appear associated with any trait that differs in prevalence across racial groups. Always include ancestry PCs as covariates in your regression model, not self-reported race.


### Merge PCs into a cohort dataframe

```python
# Define a cohort (example: adults with type 2 diabetes)
cohort_query = f"""
SELECT DISTINCT person_id
FROM `{CDR}.cb_search_person`
WHERE has_ehr_data = 1
"""

cohort_df = client.query(cohort_query).to_dataframe()

# Merge cohort with ancestry PCs
cohort_with_pcs = cohort_df.merge(
    pc_expanded,
    on="person_id",
    how="inner"
)

print(f"Cohort size: {len(cohort_df):,}")
print(f"With PCs available: {len(cohort_with_pcs):,}")
print(f"Dropped (no genomic data): "
      f"{len(cohort_df) - len(cohort_with_pcs):,}")
```

!!! pitfall "not adjusting for enough PCs"
    AoU enrolls participants across diverse ancestry backgrounds, including substantial admixed populations. The standard practice of adjusting for 3-4 PCs (common in European-only biobanks like UK Biobank) is insufficient here. AoU's population structure typically requires 10-16 PCs to adequately control for stratification. Validate by checking whether additional PCs are associated with your outcome -- if PC12 is still significantly associated, you need more PCs in your model. A common diagnostic is to run a regression of your phenotype on PCs and look for the elbow in the variance explained.


### Using PCs in a regression model

```python
import statsmodels.api as sm

# Example: logistic regression with 16 PCs as covariates
pc_cols = [f"PC{i+1}" for i in range(16)]

# Assume cohort_with_pcs has a binary 'case' column and a 'genotype' column
covariates = cohort_with_pcs[pc_cols + ["genotype"]]
covariates = sm.add_constant(covariates)
outcome = cohort_with_pcs["case"]

model = sm.Logit(outcome, covariates).fit()
print(model.summary())
```

---

## Variations

### 1. Stratified analysis by predicted ancestry

Run analyses within predicted ancestry groups when your study design requires ancestry-homogeneous subsets (e.g., computing ancestry-specific allele frequencies or PRS weights).

```python
for ancestry in pc_expanded["ancestry_pred"].unique():
    subset = cohort_with_pcs[
        cohort_with_pcs["ancestry_pred"] == ancestry
    ]
    print(f"{ancestry}: n={len(subset):,}")
    # Run ancestry-specific analysis on subset
```

### 2. Diagnostic: how many PCs to include

```python
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
import numpy as np

losses = []
for n_pcs in range(1, 21):
    cols = [f"PC{i+1}" for i in range(n_pcs)]
    X = cohort_with_pcs[cols].values
    y = cohort_with_pcs["case"].values
    lr = LogisticRegression(max_iter=1000).fit(X, y)
    losses.append(log_loss(y, lr.predict_proba(X)))

# Plot to find the elbow
import matplotlib.pyplot as plt
plt.plot(range(1, 21), losses, marker="o")
plt.xlabel("Number of PCs")
plt.ylabel("Log-loss")
plt.title("Elbow plot for PC selection")
plt.show()
```

### 3. Cross-referencing predicted vs self-reported ancestry

Useful for understanding concordance and identifying participants where self-report diverges from genetic ancestry.

```python
concordance_query = f"""
SELECT
    a.person_id,
    a.ancestry_pred,
    c.concept_name AS self_reported_race
FROM `{CDR}.prep_ancestry` a
JOIN `{CDR}.person` p
    ON a.person_id = p.person_id
JOIN `{CDR}.concept` c
    ON p.race_concept_id = c.concept_id
"""

concordance_df = client.query(concordance_query).to_dataframe()
print(pd.crosstab(
    concordance_df["self_reported_race"],
    concordance_df["ancestry_pred"]
))
```

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Table `prep_ancestry` not found | You are in the Registered Tier or your CDR version predates the genomics ancillary tables. Ancestry PCs require Controlled Tier with genomic data access. |
| Inner join drops many participants | Not all AoU participants have whole-genome sequencing. As of CDR v7, roughly 250K participants have WGS data. The rest will not appear in `prep_ancestry`. Report the drop in your methods section. |
| `pca_features` returns a single string instead of array | Some CDR versions store PCs as a comma-separated string. Parse with `pc_df["pca_features"].str.split(",", expand=True).astype(float)`. |
| Column names differ from this document | AoU updates table schemas across CDR versions. Use the `INFORMATION_SCHEMA.COLUMNS` query in the Reference section to discover the current layout. |

---

## Deep dive

### Why PCs matter for AoU specifically

AoU's enrollment intentionally oversamples communities historically underrepresented in biomedical research. As a result, AoU has far more population structure than typical single-ancestry biobanks. The first few PCs separate continental ancestry groups, but subsequent PCs capture finer structure within groups -- for example, distinguishing Central American from South American admixture patterns, or East African from West African ancestry. Failing to account for this structure is the single most common source of false positives in AoU genetic analyses.

### Interpreting `ancestry_pred`

The predicted ancestry label uses a classifier trained on reference panels (e.g., 1000 Genomes, HGDP). Common labels:

- `eur` -- European
- `afr` -- African
- `amr` -- Admixed American (Latino/Hispanic)
- `eas` -- East Asian
- `sas` -- South Asian
- `mid` -- Middle Eastern

These are statistical clusters, not racial or ethnic identities. A participant labeled `amr` may self-report as White, Hispanic, or any other category.

---

## Cost note

The `prep_ancestry` table is moderate in size (one row per participant with WGS data, ~250K rows). Queries typically process 100 MB-1 GB depending on how many PC columns are stored. Repeated queries during interactive analysis are unlikely to exceed free-tier BigQuery limits, but cache results in a dataframe when possible to minimize redundant scans.

---

## See also

- [extract-demographic-features.md](extract-demographic-features.md) -- Self-reported demographics from the `person` table
- [query-condition-occurrence.md](../conditions-phenotypes/query-condition-occurrence.md) -- Linking conditions to participants for phenotype-genotype analysis

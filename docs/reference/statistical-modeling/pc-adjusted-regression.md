# Run PC-adjusted logistic regression

Fit a logistic regression with genetic ancestry principal components (PCs) as covariates to control for population stratification in genetic association analyses.

## Prerequisites

- A feature matrix with `person_id`, a binary outcome, carrier status, and covariates
- Ancestry PCs for each participant (extracted from the AoU genomic data)
- Python 3, `pandas`, `statsmodels`, `numpy`

**Tier:** Controlled (ancestry PCs require controlled-tier access)
**CDR versions:** v7+ (PC column names may vary)

## Reference

Population stratification occurs when allele frequencies and disease prevalence both vary by ancestry, creating spurious associations between genetic variants and phenotypes. Principal components (PCs) derived from genome-wide genotype data capture axes of genetic ancestry variation. Including PCs as covariates in regression absorbs confounding due to ancestry.

AoU's participant population is notably diverse and admixed, making PC adjustment especially important:

| Factor | European-only GWAS | AoU |
|---|---|---|
| Population structure | Low (relatively homogeneous) | High (diverse, admixed) |
| PCs typically used | 3-4 | 10-16 |
| Admixture | Minimal | Substantial |
| Risk of confounding without PCs | Moderate | High |

The standard model:

```
logit(P(outcome=1)) = beta_0 + beta_1 * carrier_status
                     + beta_2 * age + beta_3 * sex
                     + beta_4 * PC1 + ... + beta_19 * PC16
```

The coefficient of interest is `beta_1` (carrier status OR), adjusted for age, sex, and population structure.

## Usage

### Step 1: Extract ancestry PCs from the CDR

```python
import os
import pandas as pd
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

# Ancestry PCs are typically in a person-level genomics table
# Verify table/column names first (see discover-genomics-tables)
pc_sql = f"""
SELECT
    person_id,
    pca_features   -- often stored as an ARRAY or repeated field
FROM `{CDR}.cb_search_person`
WHERE has_whole_genome_variant = 1
"""
# Note: the exact column name and format for PCs varies by CDR version.
# Some versions store PCs as individual columns (pc1, pc2, ..., pc16),
# others as an array. Check INFORMATION_SCHEMA if the above fails.
```

If PCs are stored as individual columns:

```python
pc_cols = [f"pc{i}" for i in range(1, 17)]
pc_sql = f"""
SELECT person_id, {', '.join(pc_cols)}
FROM `{CDR}.cb_search_person`
WHERE has_whole_genome_variant = 1
"""
pc_df = client.query(pc_sql).to_dataframe()
print(f"Participants with PCs: {len(pc_df):,}")
print(pc_df[pc_cols].describe().round(4))
```

### Step 2: Assemble the regression dataset

```python
# Merge: outcome + carrier_status + demographics + PCs
# Assumes carrier_df has: person_id, is_carrier (0/1)
# Assumes demo_df has: person_id, age_at_index, sex_male (0/1)
# Assumes outcome_df has: person_id, outcome (0/1)

reg_df = (
    outcome_df[["person_id", "outcome"]]
    .merge(carrier_df[["person_id", "is_carrier"]], on="person_id")
    .merge(demo_df[["person_id", "age_at_index", "sex_male"]],
           on="person_id")
    .merge(pc_df, on="person_id")
)

# Drop rows with any missing covariates
n_before = len(reg_df)
reg_df = reg_df.dropna()
print(f"Complete cases: {len(reg_df):,} / {n_before:,}")
```

### Step 3: Fit the logistic regression

```python
import statsmodels.api as sm

# Define covariates: carrier_status + age + sex + 16 PCs
pc_cols = [f"pc{i}" for i in range(1, 17)]
covariates = ["is_carrier", "age_at_index", "sex_male"] + pc_cols

X = reg_df[covariates].astype(float)
X = sm.add_constant(X)  # add intercept
y = reg_df["outcome"].astype(float)

model = sm.Logit(y, X)
result = model.fit(disp=False)

print(result.summary2())
```

!!! pitfall "not including enough PCs"
    AoU's diverse, admixed population typically requires 10-16 PCs for adequate adjustment. Using 3-4 PCs (common in European-only GWAS) leaves residual confounding that can produce spurious associations. The carrier-status odds ratio will be biased if ancestry variation is not fully absorbed. Use at least 10 PCs; 16 is standard for AoU analyses.


### Step 4: Extract the odds ratio and confidence interval

```python
import numpy as np

# Extract carrier_status results
beta = result.params["is_carrier"]
ci_low, ci_high = result.conf_int().loc["is_carrier"]
p_value = result.pvalues["is_carrier"]

or_est = np.exp(beta)
or_ci_low = np.exp(ci_low)
or_ci_high = np.exp(ci_high)

print(f"Carrier OR: {or_est:.3f} "
      f"(95% CI: {or_ci_low:.3f} - {or_ci_high:.3f})")
print(f"P-value: {p_value:.2e}")
```

!!! pitfall "extremely wide confidence intervals (e"
    g., 0.01 to 100) indicate quasi-separation.** The model converges without error, but the odds ratio is unreliable because there are too few carriers in one or both outcome groups for stable maximum-likelihood estimation. Use Firth's penalized logistic regression (see Variation below), or aggregate variants (e.g., any P/LP variant in the gene panel) to increase the effective carrier count.


!!! pitfall "including both self-reported race AND PCs as covariates"
    Self-reported race/ethnicity and genetic ancestry PCs are collinear -- PCs capture the same ancestry variation that race categories approximate, plus continuous admixture that race categories miss. Including both inflates standard errors (due to multicollinearity), can cause model instability, and does not improve confounding control. Use PCs alone for genetic association analyses. If you need race for descriptive stratification, do that in a separate analysis.


```python
# WRONG: including both race and PCs
# X_wrong = reg_df[["is_carrier", "age_at_index", "sex_male",
#                    "race_white", "race_black", "race_asian",
#                    "pc1", "pc2", ..., "pc16"]]

# CORRECT: PCs only (they subsume race)
X_correct = reg_df[
    ["is_carrier", "age_at_index", "sex_male"] + pc_cols
]
```

### Step 5: Diagnostic checks

```python
# Check for multicollinearity (VIF)
from statsmodels.stats.outliers_influence import variance_inflation_factor

vif_data = pd.DataFrame({
    "feature": X.columns[1:],  # skip constant
    "VIF": [
        variance_inflation_factor(X.values, i + 1)
        for i in range(X.shape[1] - 1)
    ],
})
print("Variance Inflation Factors:")
print(vif_data.sort_values("VIF", ascending=False).to_string(index=False))

# VIFs > 10 suggest problematic multicollinearity
high_vif = vif_data[vif_data["VIF"] > 10]
if len(high_vif) > 0:
    print(f"\nWARNING: {len(high_vif)} features with VIF > 10:")
    print(high_vif.to_string(index=False))
```

## Variations

### Linear regression for continuous outcomes

For continuous outcomes (e.g., HbA1c level, BMI), use OLS instead of Logit:

```python
# Continuous outcome regression
model_ols = sm.OLS(y_continuous, X)
result_ols = model_ols.fit()

beta = result_ols.params["is_carrier"]
ci_low, ci_high = result_ols.conf_int().loc["is_carrier"]
p_value = result_ols.pvalues["is_carrier"]

print(f"Carrier effect: {beta:.4f} "
      f"(95% CI: {ci_low:.4f} - {ci_high:.4f})")
print(f"P-value: {p_value:.2e}")
```

### Firth's penalized logistic regression for rare variants

When carrier counts are low (e.g., < 20 carriers), standard logistic regression suffers from separation -- the MLE does not exist or is at infinity. Firth's penalized likelihood method adds a bias-reduction penalty:

```python
# pip install firthlogist
from firthlogist import FirthLogisticRegression

firth_model = FirthLogisticRegression(max_iter=200)
firth_model.fit(X.values, y.values)

# Extract carrier_status coefficient (index 1, after intercept)
carrier_idx = list(X.columns).index("is_carrier")
beta_firth = firth_model.coef_[0][carrier_idx]
or_firth = np.exp(beta_firth)
p_firth = firth_model.pvalues_[carrier_idx]

print(f"Firth OR: {or_firth:.3f}, p = {p_firth:.2e}")
```

When to use Firth:
- Fewer than ~50 events per covariate in the smaller outcome group
- Carrier count < 20 in either outcome category
- Standard logit warns about "Perfect separation" or fails to converge

### Interaction model: carrier x ancestry

Test whether the genetic effect varies by ancestry background:

```python
# Add interaction between carrier status and PC1
reg_df["carrier_x_pc1"] = reg_df["is_carrier"] * reg_df["pc1"]

interaction_covs = (
    ["is_carrier", "age_at_index", "sex_male", "carrier_x_pc1"]
    + pc_cols
)
X_int = sm.add_constant(reg_df[interaction_covs].astype(float))
result_int = sm.Logit(y, X_int).fit(disp=False)

p_interaction = result_int.pvalues["carrier_x_pc1"]
print(f"Carrier x PC1 interaction p-value: {p_interaction:.2e}")
if p_interaction < 0.05:
    print("Significant interaction: genetic effect varies by "
          "ancestry along PC1.")
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `PerfectSeparationError` or `PerfectSeparationWarning` | A covariate perfectly predicts the outcome. Usually caused by very low carrier counts. Use Firth's method (see Variation above). |
| `LinAlgError: Singular matrix` | Perfect multicollinearity among covariates. Check for duplicate columns or both race and PCs included. |
| `ConvergenceWarning: Maximum number of iterations reached` | Increase `maxiter`: `model.fit(maxiter=1000, disp=False)`. If still fails, check for separation. |

## Cost note

This page is mostly Python/statsmodels. The only BigQuery cost is extracting ancestry PCs (Step 1), which scans `cb_search_person` -- a moderately sized table. The regression itself runs on local compute and has no cloud cost.

## See also

- [Compute genetic ancestry principal components](../demographics-ancestry/compute-ancestry-pcs.md) -- extract the ancestry PCs used as covariates in this regression
- [Query carrier status for a gene panel](../genomics/query-carrier-status.md) -- generate the `is_carrier` variable
- [Build a SHAP-ready feature matrix](build-shap-feature-matrix.md) -- alternative modeling approach for the same features
- [Discover genomics table schemas](../genomics/discover-genomics-tables.md) -- find the correct PC column names in your CDR version

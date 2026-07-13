# Guide: Take Case/Control Pairs to an FDR-Corrected Results Table

## Purpose

You have a case-control cohort with carrier status for multiple genes and
ancestry principal components from
[build-genomic-case-control-cohort](./build-genomic-case-control-cohort.md).
Now you need to run the statistical analysis: test each gene for association
with case status, correct for multiple testing, and produce a publication-ready
results table.

This guide covers the pipeline from feature matrix verification through
FDR-corrected results. The main complexity lies not in any individual step but
in the discipline of running many tests correctly, reporting them honestly,
and interpreting them carefully.

---

## Prerequisites

- An analysis-ready dataframe (`analysis_df`) with:
  - `person_id`, `case_control` (0/1), `index_date`
  - `carrier_GENE` columns (0/1) for each gene tested
  - Ancestry PCs (`PC1` through `PC10` or similar)
  - Demographics (`age`, `sex_at_birth_concept_id`)
- Python packages: `statsmodels`, `scipy`, `pandas`, `numpy`

```python
import os
import pandas as pd
import numpy as np
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.multitest import multipletests
from google.cloud import bigquery

CDR = os.environ["WORKSPACE_CDR"]
client = bigquery.Client()
```

---

## Pipeline Overview

```
Step 1  Verify the feature matrix
  │
Step 2  For each gene: run PC-adjusted logistic regression
  │
Step 3  Collect p-values across all tests
  │
Step 4  Apply FDR correction (Benjamini-Hochberg)
  │
Step 5  Format results table
  │
Step 6  Flag significant results (q < 0.05)
```

---

## Step 1: Verify the Feature Matrix

**Reference:** [audit-temporal-leakage](../reference/temporal-windowing/audit-temporal-leakage.md),
[build-shap-feature-matrix](../reference/statistical-modeling/build-shap-feature-matrix.md)

Before running any regression, verify that the feature matrix is clean. Two
classes of problems must be checked:

### 1a. Temporal leakage

If the cohort includes features derived from temporal data (lab values,
medication history), verify that no feature uses post-index-date information.

```python
# Check for temporal leakage in any date columns
date_cols = [c for c in analysis_df.columns if "date" in c.lower() and c != "index_date"]
for col in date_cols:
    leakage = analysis_df[analysis_df[col] >= analysis_df["index_date"]]
    if len(leakage) > 0:
        print(f"LEAKAGE in {col}: {len(leakage)} rows")
    else:
        print(f"{col}: clean")
```

### 1b. Encoding and completeness

Verify that the feature matrix has the expected structure. See the Reference
pages for the full checks.

```python
# Carrier columns should be 0/1 with no missing values
carrier_cols = [c for c in analysis_df.columns if c.startswith("carrier_")]
for col in carrier_cols:
    assert analysis_df[col].isin([0, 1]).all(), f"{col} has values outside 0/1"
    assert analysis_df[col].notna().all(), f"{col} has missing values"

# Case/control should be 0/1
assert analysis_df["case_control"].isin([0, 1]).all()

# PCs should have no missing values
pc_cols = [c for c in analysis_df.columns if c.startswith("PC")]
assert analysis_df[pc_cols].notna().all().all(), "Missing values in PCs"

# No duplicate participants
assert analysis_df["person_id"].is_unique, "Duplicate person_ids"

print(f"Feature matrix verified: {len(analysis_df)} participants, "
      f"{len(carrier_cols)} genes, {len(pc_cols)} PCs")
```

**Why this comes first:** A regression will run happily on a corrupted feature
matrix and produce plausible-looking but wrong results. These checks take
seconds and prevent you from interpreting garbage.

---

## Step 2: Run PC-Adjusted Logistic Regression for Each Gene

**Reference:** [pc-adjusted-regression](../reference/statistical-modeling/pc-adjusted-regression.md)

For each gene, fit a logistic regression predicting case/control status from
carrier status, adjusted for ancestry PCs, age, and sex. This is the core
statistical test.

The Reference page provides the full `run_gene_regression` function. The key
design decisions in the glue code:

- **Check carrier counts first.** If either group has <5 carriers, return `NaN`
  instead of fitting a model (quasi-separation produces unreliable estimates).
- **Model:** `sm.Logit(y, X).fit(disp=0)` where X includes the carrier column,
  all PCs, and covariates (age, sex).
- **Extract** the coefficient for the carrier variable specifically, convert to
  OR via `np.exp(coef)`, and compute 95% CI from the standard error.

Run the regression for each gene:

```python
pc_cols = [c for c in analysis_df.columns if c.startswith("PC")]
covariates = ["age", "sex_at_birth_concept_id"]

results = []
for gene_col in carrier_cols:
    gene_result = run_gene_regression(
        analysis_df, gene_col, pc_cols, covariates
    )
    results.append(gene_result)
    gene_name = gene_result["gene"]
    if gene_result["warning"]:
        print(f"{gene_name}: {gene_result['warning']}")
    else:
        print(f"{gene_name}: OR={gene_result['OR']:.2f} "
              f"({gene_result['CI_lower']:.2f}-{gene_result['CI_upper']:.2f}), "
              f"p={gene_result['p_value']:.4e}")

results_df = pd.DataFrame(results)
```

> **Pitfall: Including genes with fewer than 5 carriers in either group.**
> Logistic regression with quasi-complete separation (when the carrier variable
> perfectly or nearly perfectly predicts the outcome) produces inflated odds ratios
> with enormous confidence intervals. The regression may converge but the estimates
> are unreliable.
>
> The code above handles this by returning `NaN` for genes with <5 carriers in
> either group. For a more principled approach, use Firth's penalized logistic
> regression, which handles separation gracefully. See the
> [pc-adjusted-regression](../reference/statistical-modeling/pc-adjusted-regression.md) Variation
> section for the Firth implementation.

---

## Step 3: Collect P-Values Across All Tests

Separate the genes that produced valid p-values from those that did not.

```python
# Genes with valid results
valid_results = results_df[results_df["p_value"].notna()].copy()
invalid_results = results_df[results_df["p_value"].isna()].copy()

print(f"Valid tests: {len(valid_results)}")
print(f"Excluded (too few carriers or model failure): {len(invalid_results)}")
if len(invalid_results) > 0:
    print(f"Excluded genes: {invalid_results['gene'].tolist()}")
```

**Why invalid results are separated, not dropped silently:** The number of tests
performed affects the FDR correction in Step 4. If you tested 20 genes but only
report the 15 that produced results, you are performing the FDR correction on
the wrong denominator. Transparency about which genes were tested and which
produced results is essential for reproducibility.

---

## Step 4: Apply FDR Correction (Benjamini-Hochberg)

**Why FDR correction is required:** If you test 20 genes at alpha = 0.05, you
expect one false positive by chance alone. The Benjamini-Hochberg procedure
controls the false discovery rate -- the expected proportion of false positives
among all discoveries -- at the specified level.

```python
if len(valid_results) > 0:
    # Benjamini-Hochberg FDR correction
    rejected, q_values, _, _ = multipletests(
        valid_results["p_value"].values,
        alpha=0.05,
        method="fdr_bh",
    )
    valid_results["q_value"] = q_values
    valid_results["significant_fdr"] = rejected
else:
    print("No valid p-values to correct")
```

> **Pitfall: Running multiple genes through regression but not correcting for
> multiple testing.**
> Raw p-values from Step 2 are not interpretable when you have tested more than
> one gene. A raw p-value of 0.03 means nothing special when you have run 20
> tests -- you would expect approximately one p-value below 0.05 by chance.
> The FDR-corrected q-value is what determines significance.
>
> This is the most common statistical error in candidate-gene studies.
> Always report q-values alongside p-values, and always base significance
> decisions on q-values, not p-values.

---

## Step 5: Format the Results Table

Produce a publication-ready table with all the information a reader needs to
evaluate the findings.

```python
# Format the results table
if len(valid_results) > 0:
    results_table = valid_results[[
        "gene", "OR", "CI_lower", "CI_upper",
        "p_value", "q_value",
        "n_carriers_case", "n_carriers_control", "n_total_carriers",
        "significant_fdr",
    ]].copy()

    # Sort by q-value (most significant first)
    results_table = results_table.sort_values("q_value")

    # Format for display
    results_table["OR_95CI"] = results_table.apply(
        lambda r: f"{r['OR']:.2f} ({r['CI_lower']:.2f}-{r['CI_upper']:.2f})",
        axis=1,
    )
    results_table["p_value_fmt"] = results_table["p_value"].apply(
        lambda p: f"{p:.2e}" if p < 0.001 else f"{p:.4f}"
    )
    results_table["q_value_fmt"] = results_table["q_value"].apply(
        lambda q: f"{q:.2e}" if q < 0.001 else f"{q:.4f}"
    )

    print("\n=== Results Table ===\n")
    display_cols = [
        "gene", "OR_95CI", "p_value_fmt", "q_value_fmt",
        "n_carriers_case", "n_carriers_control", "significant_fdr",
    ]
    print(results_table[display_cols].to_string(index=False))
```

If any genes were excluded due to low carrier counts, report them separately:

```python
if len(invalid_results) > 0:
    print("\n=== Genes Excluded from Analysis ===\n")
    print(invalid_results[["gene", "n_carriers_case", "n_carriers_control",
                           "warning"]].to_string(index=False))
```

> **Pitfall: Not reporting carrier counts alongside statistical results.**
> A "significant" odds ratio of 15 based on 2 carriers in the case group and
> 0 in the control group is not the same finding as an odds ratio of 2.5 based
> on 200 carriers in cases and 150 in controls. The confidence intervals
> partially capture this, but readers need to see the raw carrier counts to
> evaluate clinical meaningfulness.
>
> Always include `n_carriers_case` and `n_carriers_control` in the results table.
> A large OR with tiny carrier counts is a hypothesis for future validation, not
> an established finding.

---

## Step 6: Flag Significant Results

```python
significant = results_table[results_table["significant_fdr"]].copy()

if len(significant) > 0:
    print(f"\n{len(significant)} gene(s) significant at FDR < 0.05:\n")
    for _, row in significant.iterrows():
        print(f"  {row['gene']}: OR = {row['OR']:.2f} "
              f"({row['CI_lower']:.2f}-{row['CI_upper']:.2f}), "
              f"q = {row['q_value']:.4f}, "
              f"carriers: {row['n_carriers_case']} cases / "
              f"{row['n_carriers_control']} controls")
else:
    print("\nNo genes reached significance at FDR < 0.05")
    print("This may reflect:")
    print("  - Genuinely no association (the genes are not risk factors)")
    print("  - Insufficient power (too few participants or carriers)")
    print("  - Overly conservative multiple testing correction")
```

---

## Sensitivity Analyses

After the primary analysis, consider these additional checks:

- **Bonferroni correction** as a conservative complement to FDR. Compute the
  threshold as `0.05 / len(valid_results)` and flag genes that survive it.
- **Power analysis** for non-significant genes. Use `statsmodels.stats.power`
  to compute the minimum detectable effect size at 80% power. This clarifies
  whether null results reflect true negatives or insufficient sample size.
- **Stratified analysis by ancestry group.** Run the regression within each
  group separately to check for ancestry-specific effects. These have lower
  power than the combined analysis -- the purpose is to detect heterogeneity,
  not to replace the primary analysis.

---

## Pipeline-Level Pitfalls

### 1. Multiple testing without correction

This is the most common statistical error in candidate-gene studies. If you
test 20 genes at alpha = 0.05, you expect 1 false positive by chance. At
50 genes, you expect 2.5. Raw p-values from Step 2 are not interpretable
when you have tested more than one gene. The FDR correction in Step 4 is
not optional.

### 2. Quasi-separation inflating odds ratios

When a gene has very few carriers (<5) in one group, the logistic regression
may converge but produce an odds ratio of 50+ with a confidence interval
spanning several orders of magnitude. This happens because the model is
trying to separate two groups using a predictor that is nearly constant in
one group.

The code in Step 2 handles this by excluding genes with <5 carriers in either
group. For a more principled approach, use Firth's penalized logistic regression,
which shrinks the coefficient toward zero and produces finite estimates even
under separation. See the [pc-adjusted-regression](../reference/statistical-modeling/pc-adjusted-regression.md)
Variation section.

### 3. Impressive OR, negligible carrier count

A result like "GENE_X: OR = 12.3, p = 0.001, q = 0.01" looks compelling until
you see that it is based on 3 carriers in 500 cases and 0 carriers in 2500
controls. The odds ratio is technically correct, but:

- The confidence interval is enormous (e.g., 2.1 to 72.0)
- A single misclassification (genotyping error, phenotype error) could
  eliminate the signal
- The population-level impact is negligible even if the effect is real

Always report carrier counts. Always evaluate results in context. A moderate OR
(e.g., 2.0) supported by hundreds of carriers is a stronger finding than a
dramatic OR supported by a handful.

---

## Exporting Results

```python
results_table.to_csv("gene_association_results.csv", index=False)
```

For the manuscript, report: how many genes were tested, how many were excluded
(and why), and how many reached significance after FDR correction. The
`results_table` dataframe contains everything needed for the results section
and supplementary tables.

---

## What Comes Next

- For SHAP-based feature importance analysis, see
  [build-shap-feature-matrix](../reference/statistical-modeling/build-shap-feature-matrix.md)
- To add clinical features (lab values, medications) and re-run the analysis,
  see [add-windowed-lab-feature](./add-windowed-lab-feature.md)
- To visualize results (forest plots, Manhattan-style plots), see your
  preferred plotting library; the `results_table` dataframe has all the
  data needed

# Run propensity score matching

Perform 1:N propensity score matching between cases and controls using logistic regression and nearest-neighbor matching, without scikit-learn.

## Prerequisites

- A cohort dataframe with a binary outcome column and covariates
- Ancestry PCs merged (see [Compute ancestry PCs](../demographics-ancestry/compute-ancestry-pcs.md))
- Python 3, `statsmodels`, `scipy`, `numpy`, `pandas`

**Tier:** N/A (operates on already-extracted data)
**CDR versions:** All

## Reference

Propensity score matching (PSM) estimates a treatment/exposure effect by matching each case to one or more controls with similar covariate distributions. The propensity score is the predicted probability of being a case given the covariates.

In AoU analyses, PSM is used to control for confounding when ancestry PCs alone are insufficient — for example, when matching on age, sex, and ancestry simultaneously.

!!! note "scikit-learn is broken in Dataproc/Hail environments"
    This implementation uses `statsmodels.api.Logit` for the propensity model
    and `scipy.spatial.cKDTree` for nearest-neighbor matching. See [Choose the
    right compute environment](../environment/choose-compute-environment.md).


## Usage

### Step 1: Fit propensity model and match

```python
import statsmodels.api as sm
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

def propensity_match(df, outcome_col, covariates, ratio=3, caliper=0.2):
    """1:N propensity score matching using logit PS and cKDTree."""
    X = sm.add_constant(df[covariates])
    y = df[outcome_col]

    ps_model = sm.Logit(y, X).fit(disp=0, maxiter=200)
    df = df.copy()
    df["ps"] = ps_model.predict(X)
    df["logit_ps"] = np.log(df["ps"] / (1 - df["ps"] + 1e-10))

    cases = df[df[outcome_col] == 1].reset_index(drop=True)
    controls = df[df[outcome_col] == 0].reset_index(drop=True)
    cal = caliper * df["logit_ps"].std()

    tree = cKDTree(controls[["logit_ps"]].values)
    used = set()
    matched_case_idx, matched_ctrl_idx = [], []
    k_query = min(ratio * 5, len(controls))

    for i, case_logit in enumerate(cases["logit_ps"].values):
        dists, idxs = tree.query([[case_logit]], k=k_query)
        dists, idxs = dists.flatten(), idxs.flatten()
        picked = []
        for d, idx in zip(dists, idxs):
            if idx not in used and d <= cal:
                picked.append(idx)
                used.add(idx)
            if len(picked) == ratio:
                break
        if len(picked) == ratio:
            matched_case_idx.append(i)
            matched_ctrl_idx.extend(picked)

    return cases.iloc[matched_case_idx], controls.iloc[matched_ctrl_idx]
```

### Step 2: Run matching and test association

```python
from scipy.stats import fisher_exact

pc_cols = [f"PC{i+1}" for i in range(16)]
covars = ["age", "sex_male"] + pc_cols

matched_cases, matched_ctrls = propensity_match(
    dt, outcome_col="y", covariates=covars, ratio=3,
)

# 2x2 table for a binary exposure (e.g., carrier status)
a = int(matched_cases["carrier"].sum())
b = int(len(matched_cases) - a)
c = int(matched_ctrls["carrier"].sum())
d = int(len(matched_ctrls) - c)

odds_ratio, p_val = fisher_exact([[a, c], [b, d]])
print(f"Matched cases: {len(matched_cases)}, controls: {len(matched_ctrls)}")
print(f"OR = {odds_ratio:.2f}, p = {p_val:.2e}")
```

!!! pitfall "matching without replacement inflates precision"
    The `used` set prevents a control from being reused, which is standard for
    without-replacement matching. But if your case count is large relative to
    controls, many cases will fail to find enough matches. Report the match
    rate (matched / total cases) and consider reducing the ratio.


### Step 3: Verify covariate balance

```python
print("Covariate balance after matching:")
for col in covars:
    case_mean = matched_cases[col].mean()
    ctrl_mean = matched_ctrls[col].mean()
    smd = (case_mean - ctrl_mean) / np.sqrt(
        (matched_cases[col].var() + matched_ctrls[col].var()) / 2
    )
    flag = " *** IMBALANCED" if abs(smd) > 0.1 else ""
    print(f"  {col:20s}  SMD = {smd:+.3f}{flag}")
```

## Variations

### Adjust matching ratio

For rare exposures (few cases), 1:1 matching retains more cases but has less power. For common exposures, 1:5 or 1:10 adds statistical power at the cost of weaker matches:

```python
matched_cases, matched_ctrls = propensity_match(
    dt, outcome_col="y", covariates=covars,
    ratio=1,      # 1:1 matching
    caliper=0.25,  # wider caliper to retain more cases
)
```

### Handle sex-specific cancers

For cancers where one sex dominates (e.g., ovarian, prostate), drop `sex_male` from covariates to avoid singular matrix errors:

```python
if cancer_type in ("Ovarian", "Prostate"):
    use_covars = [c for c in covars if c != "sex_male"]
else:
    use_covars = covars
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `PerfectSeparationError` | A covariate perfectly predicts the outcome. Drop it or use regularized logistic regression (`sm.Logit` with `method='bfgs'` and `alpha` penalty). |
| Very few cases matched | Caliper too tight or too few controls. Increase caliper or reduce ratio. |
| `LinAlgError: Singular matrix` | Near-zero variance in a covariate (e.g., `sex_male` for ovarian cancer). Drop the offending column. |

## Cost note

No BigQuery cost — this operates on already-extracted data. CPU cost scales with `O(n_cases × k_query × log(n_controls))` due to the kd-tree queries.

## See also

- [Run PC-adjusted logistic regression](pc-adjusted-regression.md) — alternative approach using regression covariates instead of matching
- [Compute genetic ancestry PCs](../demographics-ancestry/compute-ancestry-pcs.md) — PCs used as matching covariates
- [Choose the right compute environment](../environment/choose-compute-environment.md) — sklearn alternatives for Dataproc

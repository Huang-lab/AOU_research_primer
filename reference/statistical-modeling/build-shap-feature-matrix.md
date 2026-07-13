# Build a SHAP-ready feature matrix

Construct a wide-format feature matrix (one row per participant, one column per feature) suitable for tree-based models and SHAP explanation.

## Prerequisites

- Extracted clinical data: labs, conditions, demographics, drugs (typically from temporal-windowed queries)
- A defined cohort with `person_id` and a binary or continuous label
- Python 3, `pandas`, `numpy`; optionally `xgboost`, `shap`

**Tier:** N/A (operates on already-extracted data)
**CDR versions:** All (data extraction is CDR-dependent; matrix assembly is not)

## Reference

SHAP (SHapley Additive exPlanations) requires a numeric matrix where each row is a sample and each column is a feature. The matrix must be:

1. **Wide format** -- one row per `person_id`
2. **Numeric** -- all values are int, float, or NaN (no strings)
3. **Free of the target variable and its proxies**
4. **Consistently encoded** -- categorical features use the same encoding across train/test splits

The typical assembly pipeline:

```
Raw event tables (long) --> temporal windowing --> aggregation --> pivot --> feature matrix (wide)
```

## Usage

### Step 1: Aggregate lab features

Starting from extracted lab data (already temporally windowed):

```python
import pandas as pd
import numpy as np

# baseline_labs: person_id, measurement_concept_id, value_as_number
# (already filtered to the pre-index window)

lab_features = (
    baseline_labs
    .groupby(["person_id", "measurement_concept_id"])["value_as_number"]
    .agg(["mean", "count", "last"])
    .reset_index()
)

# Pivot to wide format: one column per lab x aggregation
lab_wide = lab_features.pivot(
    index="person_id",
    columns="measurement_concept_id",
    values=["mean", "count", "last"],
)
# Flatten multi-level column names
lab_wide.columns = [
    f"lab_{concept}_{agg}" for agg, concept in lab_wide.columns
]
lab_wide = lab_wide.reset_index()
print(f"Lab features: {lab_wide.shape[1] - 1} columns")
```

### Step 2: Aggregate condition features

```python
# baseline_conditions: person_id, condition_concept_id
# Binary: has the person ever had this condition in the window?

condition_counts = (
    baseline_conditions
    .groupby(["person_id", "condition_concept_id"])
    .size()
    .reset_index(name="n_occurrences")
)

cond_wide = condition_counts.pivot(
    index="person_id",
    columns="condition_concept_id",
    values="n_occurrences",
).fillna(0).astype(int)
cond_wide.columns = [f"cond_{c}" for c in cond_wide.columns]
cond_wide = cond_wide.reset_index()
print(f"Condition features: {cond_wide.shape[1] - 1} columns")
```

### Step 3: Add demographics

```python
# demographics_df: person_id, year_of_birth, gender_concept_id,
#                  race_concept_id, ethnicity_concept_id

demo = demographics_df.copy()

# Age at index date
demo = demo.merge(
    index_dates_df[["person_id", "index_date"]], on="person_id"
)
demo["age_at_index"] = (
    demo["index_date"].dt.year - demo["year_of_birth"]
)

# Encode sex as binary (example: 8507=male, 8532=female)
demo["sex_male"] = (demo["gender_concept_id"] == 8507).astype(int)
```

> **Pitfall: including the target variable or its proxies in the feature matrix.** If the label is "has cancer" and you include `cond_cancer_diagnosis` as a feature, the model achieves near-perfect accuracy and SHAP assigns it all importance -- but the result is meaningless. Proxies are subtler: a cancer-specific drug or a cancer-staging lab test. Audit your concept list against the target condition and remove any concepts that are definitionally linked to the outcome.

### Step 4: Merge all feature blocks

```python
# Start with the full cohort to ensure every person_id appears
feature_matrix = cohort_df[["person_id", "label"]].copy()

# Left-join each feature block
for block_name, block_df in [
    ("labs", lab_wide),
    ("conditions", cond_wide),
    ("demographics", demo[["person_id", "age_at_index", "sex_male"]]),
]:
    feature_matrix = feature_matrix.merge(
        block_df, on="person_id", how="left"
    )
    print(f"After {block_name}: {feature_matrix.shape}")
```

> **Pitfall: inconsistent categorical encoding.** SHAP values for one-hot encoded features vs. ordinal encoded features are not comparable. One-hot encoding distributes importance across K dummy columns, diluting per-category SHAP values. Ordinal encoding concentrates importance in one column but imposes an ordering that may not exist. Choose one strategy, apply it to all categoricals, and document it. If using tree-based models (XGBoost, LightGBM), ordinal encoding is usually preferred -- these models handle ordinal splits natively.

```python
# Consistent ordinal encoding for remaining categoricals
categorical_cols = feature_matrix.select_dtypes(
    include=["object", "category"]
).columns

for col in categorical_cols:
    feature_matrix[col] = (
        feature_matrix[col].astype("category").cat.codes
    )
    # Note: .cat.codes assigns -1 to NaN, which XGBoost handles
```

### Step 5: Handle NaN values

> **Pitfall: NaN handling varies by model framework.** XGBoost treats NaN as a learnable split direction (left or right at each node), which is often beneficial. Scikit-learn tree models raise errors on NaN. LightGBM handles NaN but treats it differently than XGBoost. If you impute before training, SHAP values reflect the imputation strategy, not the missing data. If you leave NaN for XGBoost, SHAP correctly attributes importance to the "missing" pathway. Decide and document your strategy.

```python
# Option A: Leave NaN for XGBoost (recommended for tree models)
X = feature_matrix.drop(columns=["person_id", "label"])
y = feature_matrix["label"]
print(f"NaN fraction: {X.isna().mean().mean():.2%}")

# Option B: Impute if required by the framework
from sklearn.impute import SimpleImputer
imputer = SimpleImputer(strategy="median")
X_imputed = pd.DataFrame(
    imputer.fit_transform(X), columns=X.columns, index=X.index
)
```

### Step 6: Verify matrix properties

```python
# Final checks
assert feature_matrix["person_id"].is_unique, "Duplicate person_ids"
assert "label" not in X.columns, "Label leaked into features"
assert X.select_dtypes(include=["object"]).shape[1] == 0, (
    "Non-numeric columns remain"
)
print(f"Feature matrix: {X.shape[0]:,} participants x "
      f"{X.shape[1]:,} features")
print(f"Label distribution:\n{y.value_counts()}")
print(f"NaN columns (>50% missing): "
      f"{(X.isna().mean() > 0.5).sum()}")
```

## Variations

### Sparse matrix format

For high-dimensional feature matrices (e.g., all condition concepts), sparse format saves memory:

```python
from scipy import sparse

# Convert to sparse CSR matrix
X_sparse = sparse.csr_matrix(X.fillna(0).values)
print(f"Dense size:  {X.values.nbytes / 1024**2:.1f} MB")
print(f"Sparse size: {(X_sparse.data.nbytes + X_sparse.indices.nbytes + X_sparse.indxptr.nbytes) / 1024**2:.1f} MB")

# XGBoost accepts sparse matrices directly
import xgboost as xgb
dtrain = xgb.DMatrix(X_sparse, label=y)
```

### Feature selection before SHAP

Reduce dimensionality to make SHAP computation tractable:

```python
# Remove near-zero-variance features
from sklearn.feature_selection import VarianceThreshold

selector = VarianceThreshold(threshold=0.01)
X_filtered = pd.DataFrame(
    selector.fit_transform(X),
    columns=X.columns[selector.get_support()],
    index=X.index,
)
print(f"Features after variance filter: "
      f"{X.shape[1]} -> {X_filtered.shape[1]}")
```

### Train/test split with SHAP computation

```python
from sklearn.model_selection import train_test_split
import xgboost as xgb
import shap

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

model = xgb.XGBClassifier(
    n_estimators=100, max_depth=6, random_state=42,
    use_label_encoder=False, eval_metric="logloss",
)
model.fit(X_train, y_train)

explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X_test)
shap.summary_plot(shap_values, X_test, max_display=20)
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `ValueError: Input contains NaN` from scikit-learn | Scikit-learn models do not accept NaN. Impute missing values or switch to XGBoost/LightGBM. |
| SHAP summary plot shows one feature dominating everything | Likely target leakage -- the dominant feature is a proxy for the label. Check whether removing it drops AUC significantly. |
| `MemoryError` during pivot | Too many unique concept IDs for a dense pivot. Use sparse format or filter to the top N most frequent concepts. |
| Feature matrix has more rows than the cohort | A merge introduced duplicates (e.g., multiple observation periods per person). Deduplicate to one row per `person_id` before merging. |

## Cost note

This page is mostly pandas, not BigQuery. The expensive step is the upstream data extraction (lab values, conditions, etc.), which should already be done and stored locally. Matrix assembly and SHAP computation use only local compute.

## See also

- [Apply pre/post-index-date temporal windowing](../temporal-windowing/apply-index-date-window.md) -- extract temporally clean features for the matrix
- [Audit a feature matrix for temporal leakage](../temporal-windowing/audit-temporal-leakage.md) -- validate the matrix before modeling
- [Run PC-adjusted logistic regression](pc-adjusted-regression.md) -- a complementary modeling approach using the same features

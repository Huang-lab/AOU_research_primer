# Choose the right compute environment

Select the correct AoU Researcher Workbench compute environment for your task and avoid losing work on ephemeral Dataproc clusters.

## Prerequisites

- Active AoU workspace with Controlled Tier access
- Familiarity with AoU Workbench 2.0 interface

**Tier:** Registered (environment setup) / Controlled (genomic tasks)

## Reference

### Which environment for which task

| Task | Environment | Why |
|---|---|---|
| BigQuery queries, pandas, statsmodels | **AoU Jupyter (Compute Engine)** | Cheaper ($0.08–0.13/hr), sufficient for tabular work |
| Accessing genomic storage bucket (GCS) | **JupyterLab Spark cluster for AoU** with Hail pre-installed | Required for GCS access within VPC perimeter |
| Hail genomic operations (VCF, MatrixTable) | **JupyterLab Spark cluster** | Only environment with Hail + Spark |

### Working directory differences

```
Regular Jupyter notebook:  /home/jupyter/workspace/...
Dataproc/Hail cluster:     /home/dataproc/workspace/...
```

!!! pitfall "hardcoded paths break across environments"
    If you copy a notebook from regular Jupyter to a Dataproc cluster, any
    path starting with `/home/jupyter/` will fail. Always use `os.getcwd()` or
    relative paths.


## Usage

### Step 1: Create a Dataproc/Hail cluster

1. Go to workspace → **Apps** tab
2. Select **JupyterLab Spark cluster for AoU**
3. Advanced options → Software to install → **Hail (Spark 3.5.3, hail 0.2.135)**
4. Recommended: Single node for light work, Standard for heavy Hail jobs
5. Set autostop to 1 hour to avoid billing surprises

### Step 2: Set CDR manually (Dataproc only)

The `WORKSPACE_CDR` environment variable is **not auto-injected** in Dataproc environments:

```python
import os
from google.cloud import bigquery

cdr = os.environ.get("WORKSPACE_CDR")
print(f"WORKSPACE_CDR = {cdr}")  # Often None in Dataproc

# If None, set manually (check workspace Resources tab for dataset ID)
CDR = "your-workspace-project.C2024Q3R9"  # Replace with your value
client = bigquery.Client()

# Verify access
test = client.query(f"SELECT COUNT(*) as n FROM `{CDR}.person`").to_dataframe()
print(f"CDR access confirmed: {test['n'][0]:,} participants")
```

!!! pitfall "`WORKSPACE_CDR` is None in Dataproc"
    Queries using `os.environ["WORKSPACE_CDR"]` will raise `KeyError` in
    Dataproc/Hail clusters. Always check and set manually if needed. Find your
    CDR string from the workspace Resources tab or from existing notebooks.


To find the CDR string from existing notebooks:

```python
import glob, re

notebooks = glob.glob("/home/*/workspace/*/notebooks/*.ipynb")
for nb_path in notebooks:
    with open(nb_path) as f:
        content = f.read()
    tables = re.findall(r'`[^`]*\.[^`]*`', content)
    if tables:
        print(f"{nb_path.split('/')[-1]}: {set(tables)}")
```

### Step 3: Persist files to GCS before shutdown

Dataproc clusters use **ephemeral local disk**. When the cluster is stopped, destroyed, or a new one is created, **all local files are lost** — notebooks, CSVs, pickles, everything.

!!! pitfall "Dataproc files are NOT persistent"
    Unlike regular Jupyter Compute Engine instances, Dataproc does NOT persist
    `/workspace/` across cluster lifecycles. If you shut down without syncing
    to GCS, your work is gone.


Every workspace has a GCS staging bucket. Find yours:

```python
import subprocess

result = subprocess.run(
    "gsutil ls 2>&1 | head -10",
    shell=True, capture_output=True, text=True,
)
print(result.stdout)
# Look for: gs://dataproc-staging-<workspace-id>/
```

Save files to GCS at the end of every session:

```python
import subprocess

BUCKET = "gs://dataproc-staging-<your-workspace-id>/your-name"
LOCAL = "/home/dataproc/workspace/your-name"

cmd = f"gsutil -m rsync -r {LOCAL} {BUCKET}"
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
print(result.stdout or result.stderr)
```

Restore files at the start of a new session:

```python
cmd = f"gsutil -m rsync -r {BUCKET} {LOCAL}"
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
print(result.stdout or result.stderr)
```

### Step 4: Initialize Hail (if using Hail kernel)

```python
import hail as hl
hl.init()
```

## Variations

### scikit-learn alternatives for Dataproc/Hail

scikit-learn is broken in Dataproc Hail environments (`ValueError: numpy.dtype size changed`). Use these alternatives:

| sklearn feature | Alternative | Package |
|---|---|---|
| `LogisticRegression` | `sm.Logit` | `statsmodels` |
| `NearestNeighbors` | `cKDTree` | `scipy.spatial` |
| `StandardScaler` | `(x - x.mean()) / x.std()` | manual |

### Packages confirmed working in Dataproc Hail

| Package | Status |
|---|---|
| `pandas`, `numpy`, `scipy`, `statsmodels` | Working |
| `openpyxl` | Working (for `.xlsx` files) |
| `scikit-learn` | **Broken** (dtype mismatch) |

## Troubleshooting

| Symptom | Cause |
|---|---|
| `KeyError: 'WORKSPACE_CDR'` | Variable not injected in Dataproc. Set CDR manually. |
| `FileNotFoundError` on files saved yesterday | Dataproc cluster was destroyed. Files on local disk are lost. Restore from GCS. |
| `ValueError: numpy.dtype size changed` on `import sklearn` | Known incompatibility in Hail environment. Use statsmodels/scipy alternatives. |
| `gsutil cp` fails with "requester pays" error | Add `-u $GOOGLE_PROJECT` flag to gsutil commands. |
| "Request is prohibited by organization's policy" | VPC Service Controls — Controlled Tier data collection must be attached to workspace in Resources. |

## Cost note

Regular Jupyter instances cost $0.08–0.13/hr. Dataproc clusters cost more (depends on machine type and node count). Set autostop to 1 hour to avoid billing surprises. Only use Dataproc when you need GCS access or Hail.

## See also

- [Compute genetic ancestry PCs](../demographics-ancestry/compute-ancestry-pcs.md) — uses GCS path that requires Dataproc
- [Dry-run a query to estimate cost](../cost-awareness/dry-run-query.md) — estimate BigQuery costs before running

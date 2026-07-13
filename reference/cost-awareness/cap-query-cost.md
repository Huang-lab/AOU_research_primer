# Cap query cost before execution

Set `maximum_bytes_billed` in `QueryJobConfig` to abort any query that would exceed a cost threshold, preventing expensive accidental scans.

## Prerequisites

- Python 3, `google-cloud-bigquery`
- A query you want to cost-protect

**Tier:** Registered or Controlled (depending on tables referenced)
**CDR versions:** All

## Reference

BigQuery's `maximum_bytes_billed` setting instructs the query engine to abort the query before execution if the estimated bytes to be scanned exceed the specified limit. When triggered, BigQuery raises a `google.api_core.exceptions.Forbidden` (HTTP 403) error with a message indicating the query would exceed the billing cap.

This is a server-side safety net -- the query never starts processing, so no data is scanned and no charges are incurred.

| Parameter | Type | Effect |
|---|---|---|
| `maximum_bytes_billed` | `int` (bytes) | Aborts query if estimated scan exceeds this value |
| Setting too low | N/A | Legitimate queries are blocked; exception must be handled |
| Setting too high | N/A | No practical protection; large queries still run |

Recommended defaults for AoU work:

| Use case | Suggested cap | Rationale |
|---|---|---|
| Exploratory queries | 1 GB | Catch accidental `SELECT *` on large tables |
| Standard analysis | 10 GB | Most OMOP queries scan under 10 GB |
| Genomics queries | 100 GB | `cb_variant_to_person` is large by design |

## Usage

### Step 1: Set a byte cap on a query

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

sql = f"""
SELECT person_id, measurement_concept_id, value_as_number
FROM `{CDR}.measurement`
WHERE measurement_concept_id = 3004249
"""

# Cap at 5 GB
cap_bytes = 5 * (1024**3)  # 5 GB in bytes
job_config = bigquery.QueryJobConfig(maximum_bytes_billed=cap_bytes)

try:
    df = client.query(sql, job_config=job_config).to_dataframe()
    print(f"Query succeeded. Rows: {len(df):,}")
except Exception as e:
    if "bytesBilledLimitExceeded" in str(e) or "403" in str(e):
        print(f"Query BLOCKED: would exceed {cap_bytes / (1024**3):.0f} GB cap.")
        print(f"Details: {e}")
    else:
        raise
```

> **Pitfall: not catching the exception.** When `maximum_bytes_billed` is exceeded, BigQuery raises a `google.api_core.exceptions.Forbidden` error. If your code does not catch this, the error propagates as an opaque 403, and you lose the context of *why* it failed. In a notebook, this looks like a confusing traceback with no mention of the billing cap. Always wrap capped queries in a `try/except` that checks for the billing limit message.

### Step 2: Build a reusable capped query function

```python
from google.api_core.exceptions import Forbidden

def capped_query(sql, max_gb=10, client=None):
    """Execute a query with a byte-billing cap.

    Parameters
    ----------
    sql : str
        The SQL query to execute.
    max_gb : float
        Maximum gigabytes to allow. Query is aborted if it
        would scan more than this.
    client : bigquery.Client, optional

    Returns
    -------
    pd.DataFrame

    Raises
    ------
    RuntimeError
        If the query exceeds the billing cap.
    """
    if client is None:
        client = bigquery.Client()

    cap_bytes = int(max_gb * (1024**3))
    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=cap_bytes
    )

    try:
        return client.query(sql, job_config=job_config).to_dataframe()
    except Forbidden as e:
        raise RuntimeError(
            f"Query blocked by billing cap ({max_gb} GB). "
            f"The query would scan more data than allowed.\n"
            f"Options: (1) add filters to reduce scan size, "
            f"(2) select fewer columns, "
            f"(3) increase max_gb if the cost is acceptable.\n"
            f"BigQuery error: {e}"
        ) from e


# Usage
df = capped_query(
    f"SELECT person_id, value_as_number FROM `{CDR}.measurement` "
    f"WHERE measurement_concept_id = 3004249",
    max_gb=5,
)
```

### Step 3: Set a default cap for all queries in a session

```python
# Create a client-level default by wrapping the client
class CappedBQClient:
    """BigQuery client wrapper with a default billing cap."""

    def __init__(self, default_max_gb=10):
        self._client = bigquery.Client()
        self._default_cap = int(default_max_gb * (1024**3))

    def query(self, sql, max_gb=None, **kwargs):
        cap = int(max_gb * (1024**3)) if max_gb else self._default_cap
        job_config = kwargs.pop("job_config", bigquery.QueryJobConfig())
        if job_config.maximum_bytes_billed is None:
            job_config.maximum_bytes_billed = cap
        return self._client.query(sql, job_config=job_config, **kwargs)


# All queries now have a 10 GB default cap
safe_client = CappedBQClient(default_max_gb=10)
df = safe_client.query(
    f"SELECT * FROM `{CDR}.person`"
).to_dataframe()
```

## Variations

### Two-stage safety: dry-run check + billing cap

Combine a dry-run estimate with a hard billing cap for defense in depth:

```python
def safe_query_two_stage(sql, max_gb=10, client=None):
    """Dry-run first, then execute with a billing cap.

    Stage 1: Dry run estimates bytes. Warns if close to cap.
    Stage 2: Execute with maximum_bytes_billed as a hard stop.
    """
    if client is None:
        client = bigquery.Client()

    cap_bytes = int(max_gb * (1024**3))

    # Stage 1: dry run
    dry_config = bigquery.QueryJobConfig(
        dry_run=True, use_query_cache=False
    )
    dry_job = client.query(sql, job_config=dry_config)
    est_bytes = dry_job.total_bytes_processed
    est_gb = est_bytes / (1024**3)

    print(f"Dry-run estimate: {est_gb:.2f} GB (cap: {max_gb} GB)")

    if est_gb > max_gb:
        raise RuntimeError(
            f"Dry run shows {est_gb:.1f} GB, exceeding "
            f"{max_gb} GB limit. Query not attempted."
        )

    if est_gb > max_gb * 0.8:
        print(f"WARNING: estimate is >{int(max_gb*0.8)} GB "
              f"({est_gb/max_gb:.0%} of cap). Proceeding with caution.")

    # Stage 2: execute with hard cap
    exec_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=cap_bytes
    )
    return client.query(sql, job_config=exec_config).to_dataframe()


df = safe_query_two_stage(
    f"SELECT * FROM `{CDR}.condition_occurrence` "
    f"WHERE condition_concept_id = 201826",
    max_gb=5,
)
```

### Per-table caps based on known sizes

Set different caps depending on which tables the query touches:

```python
# Table-specific caps based on known AoU table sizes
TABLE_CAPS_GB = {
    "person": 1,
    "condition_occurrence": 10,
    "measurement": 50,
    "drug_exposure": 20,
    "cb_variant_to_person": 200,
}

def auto_capped_query(sql, client=None):
    """Infer an appropriate cap from the tables referenced."""
    max_gb = 1  # default
    for table, cap in TABLE_CAPS_GB.items():
        if table in sql:
            max_gb = max(max_gb, cap)
    print(f"Auto-selected cap: {max_gb} GB")
    return capped_query(sql, max_gb=max_gb, client=client)
```

### Notebook cell magic for interactive use

A lightweight pattern for notebooks where you want a cap on every cell:

```python
# Set once at the top of the notebook
DEFAULT_CAP_GB = 10
DEFAULT_JOB_CONFIG = bigquery.QueryJobConfig(
    maximum_bytes_billed=int(DEFAULT_CAP_GB * (1024**3))
)

# Then use in every query cell
df = client.query(sql, job_config=DEFAULT_JOB_CONFIG).to_dataframe()
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Forbidden: 403 Query exceeded limit for bytes billed` | The query would scan more than `maximum_bytes_billed`. This is the cap working as intended. Reduce the query scope or raise the cap. |
| Cap blocks a query that dry-run said was under the limit | The actual query plan differs from the dry-run estimate. The dry-run is an estimate; the cap is evaluated on the actual plan. Increase the cap slightly above the dry-run estimate. |
| No error, but query returns 0 rows | The cap was not exceeded (query ran successfully). The zero rows are a data issue, not a cost issue. |

## Cost note

The `maximum_bytes_billed` setting itself is **free**. When it triggers, the query is aborted before any data is scanned, so no charges are incurred. The only cost is from queries that pass the cap and execute normally.

## See also

- [Dry-run a query to estimate cost](dry-run-query.md) -- estimate cost before execution
- [Discover genomics table schemas](../genomics/discover-genomics-tables.md) -- understand table sizes before setting caps

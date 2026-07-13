# Dry-run a query to estimate cost

Use BigQuery's `dry_run=True` option to estimate bytes processed before executing a query, so you can decide whether to proceed or optimize.

## Prerequisites

- Python 3, `google-cloud-bigquery`
- A query string you want to cost-check

**Tier:** Registered or Controlled (depending on tables referenced)
**CDR versions:** All

## Reference

BigQuery charges based on the amount of data scanned (bytes processed). A dry run validates the query syntax, resolves table references, and returns an estimate of `total_bytes_processed` without actually executing the query or incurring charges.

AoU cost reference points:

| Table | Approximate size | Notes |
|---|---|---|
| `person` | Small (< 1 GB) | Demographics, always cheap |
| `condition_occurrence` | Medium (5-20 GB) | Depends on CDR version |
| `measurement` | Large (50-200 GB) | Labs, vitals -- biggest OMOP table |
| `cb_variant_to_person` | Very large (100+ GB) | Genomic carrier data |

BigQuery on-demand pricing: $5 per TB scanned. The first 1 TB/month is free for most projects, but AoU workspaces may have different billing structures through the Researcher Workbench.

## Usage

### Step 1: Basic dry run

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

sql = f"""
SELECT person_id, measurement_concept_id, value_as_number
FROM `{CDR}.measurement`
WHERE measurement_concept_id = 3004249  -- HbA1c
"""

# Dry run: validates and estimates cost without executing
job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
dry_run_job = client.query(sql, job_config=job_config)

bytes_processed = dry_run_job.total_bytes_processed
print(f"Estimated bytes processed: {bytes_processed:,}")
```

### Step 2: Convert to human-readable units

```python
def format_bytes(n_bytes):
    """Convert bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n_bytes) < 1024:
            return f"{n_bytes:.2f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.2f} PB"

def estimate_cost_usd(n_bytes, price_per_tb=5.0):
    """Estimate BigQuery cost in USD at on-demand pricing."""
    tb = n_bytes / (1024**4)
    return tb * price_per_tb

print(f"Data scanned:    {format_bytes(bytes_processed)}")
print(f"Estimated cost:  ${estimate_cost_usd(bytes_processed):.4f}")
```

!!! pitfall "dry-run estimates are upper bounds, not guarantees"
    The estimate reflects the maximum bytes that *could* be scanned based on column sizes and table metadata. Actual execution may scan less (due to query caching or partition pruning) or, in rare cases, more (if the query plan changes between dry run and execution, or if the table grows between the two calls). Treat the estimate as an order-of-magnitude guide, not a bill preview.


### Step 3: Wrap in a reusable helper

```python
def dry_run(sql, client=None):
    """Dry-run a query and print estimated cost.

    Returns the estimated bytes processed.
    """
    if client is None:
        client = bigquery.Client()
    job_config = bigquery.QueryJobConfig(
        dry_run=True, use_query_cache=False
    )
    job = client.query(sql, job_config=job_config)
    b = job.total_bytes_processed

    print(f"Estimated scan:  {format_bytes(b)}")
    print(f"Estimated cost:  ${estimate_cost_usd(b):.4f}")
    return b


# Usage
bytes_est = dry_run(f"""
    SELECT * FROM `{CDR}.measurement` LIMIT 1000
""")
```

### Step 4: Decision gate -- proceed or abort

```python
MAX_BYTES = 10 * (1024**3)  # 10 GB threshold

sql = f"""
SELECT person_id, measurement_date, value_as_number
FROM `{CDR}.measurement`
WHERE measurement_concept_id = 3004249
"""

estimated = dry_run(sql)

if estimated > MAX_BYTES:
    print(f"ABORT: query would scan {format_bytes(estimated)}, "
          f"exceeding {format_bytes(MAX_BYTES)} threshold.")
else:
    print("Proceeding with query execution...")
    result = client.query(sql).to_dataframe()
    print(f"Rows returned: {len(result):,}")
```

## Variations

### Dry-run helper with automatic abort

A stricter version that raises an exception if the estimate exceeds a threshold:

```python
def safe_query(sql, max_gb=10, client=None):
    """Run a query only if dry-run estimate is under max_gb.

    Raises RuntimeError if the estimate exceeds the threshold.
    """
    if client is None:
        client = bigquery.Client()

    # Dry run
    dry_config = bigquery.QueryJobConfig(
        dry_run=True, use_query_cache=False
    )
    dry_job = client.query(sql, job_config=dry_config)
    est_gb = dry_job.total_bytes_processed / (1024**3)

    if est_gb > max_gb:
        raise RuntimeError(
            f"Query would scan {est_gb:.1f} GB, "
            f"exceeding limit of {max_gb} GB. "
            f"Optimize the query or raise the limit."
        )

    print(f"Dry run passed: {est_gb:.2f} GB estimated. Executing...")
    return client.query(sql).to_dataframe()


# Usage
df = safe_query(
    f"SELECT * FROM `{CDR}.condition_occurrence` WHERE condition_concept_id = 201826",
    max_gb=5,
)
```

### Compare costs of two query approaches

Use dry runs to decide between query strategies:

```python
# Approach A: scan full measurement table with WHERE
sql_a = f"""
SELECT person_id, value_as_number
FROM `{CDR}.measurement`
WHERE measurement_concept_id = 3004249
"""

# Approach B: join through cb_search_person first
sql_b = f"""
SELECT m.person_id, m.value_as_number
FROM `{CDR}.cb_search_person` sp
JOIN `{CDR}.measurement` m ON sp.person_id = m.person_id
WHERE m.measurement_concept_id = 3004249
"""

print("Approach A (direct filter):")
a_bytes = dry_run(sql_a)

print("\nApproach B (join through cb_search_person):")
b_bytes = dry_run(sql_b)

cheaper = "A" if a_bytes <= b_bytes else "B"
print(f"\nApproach {cheaper} is cheaper.")
```

### Batch dry-run for multiple queries

Check the cost of an entire analysis pipeline before running any of it:

```python
queries = {
    "demographics": f"SELECT * FROM `{CDR}.person`",
    "conditions": f"""
        SELECT * FROM `{CDR}.condition_occurrence`
        WHERE condition_concept_id = 201826""",
    "labs": f"""
        SELECT * FROM `{CDR}.measurement`
        WHERE measurement_concept_id = 3004249""",
}

total_bytes = 0
for name, sql in queries.items():
    b = dry_run(sql)
    total_bytes += b
    print(f"  {name}: {format_bytes(b)}")

print(f"\nTotal pipeline estimate: {format_bytes(total_bytes)}")
print(f"Total estimated cost:   ${estimate_cost_usd(total_bytes):.4f}")
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `dry_run` raises a syntax error | The query has a SQL error. Dry run validates syntax, so fix the query and re-run. This is useful -- it catches errors for free. |
| `total_bytes_processed` is 0 | The query references only metadata or `INFORMATION_SCHEMA` views, which are free. This is correct, not an error. |
| Actual bytes billed differ significantly from estimate | Query caching reduced the actual cost, or the table was modified between dry run and execution. Disable cache with `use_query_cache=False` for more predictable estimates. |

## Cost note

Dry-run itself is **free**. It does not execute the query and incurs no charges. Use it liberally, especially before querying large tables like `measurement` or `cb_variant_to_person`.

## See also

- [Cap query cost before execution](cap-query-cost.md) -- set a hard byte limit to prevent expensive queries from running
- [Discover genomics table schemas](../genomics/discover-genomics-tables.md) -- check table sizes before querying

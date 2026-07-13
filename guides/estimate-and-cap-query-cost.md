# Guide: Estimate and Cap the Cost of a Large Cohort Query Before Running It

## Purpose

BigQuery charges by bytes scanned. Genomic queries on the All of Us CDR can scan
hundreds of gigabytes. Before running an expensive query, you should estimate
what it will cost and set a safety cap so that a mistake in your SQL does not
result in an unexpectedly large bill.

This is the shortest guide in the collection -- it chains only two Reference
pages -- but the connective reasoning between them is where the value lies.
The dry-run tells you what the query *will* cost. The cap prevents the query
from *exceeding* a budget. Between these two steps sits the decision: is this
cost acceptable, and if not, what can you change?

---

## Prerequisites

- A Researcher Workbench workspace with CDR access
- A query you intend to run (written but not yet executed)
- An understanding of your workspace's billing budget

```python
import os
from google.cloud import bigquery

CDR = os.environ["WORKSPACE_CDR"]
client = bigquery.Client()
```

---

## Pipeline Overview

```
Step 1  Write your query
  │
Step 2  Dry-run it to estimate bytes scanned
  │
Step 3  Evaluate whether the cost is acceptable
  │
  ├── If acceptable ──> Step 5
  │
  └── If too expensive ──> Step 4: Optimize
                              │
                              └──> Step 2 (re-estimate)
  │
Step 5  Set a cost cap
  │
Step 6  Execute with the cap in place
  │
Step 7  Check actual bytes billed
```

---

## Step 1: Write Your Query

Write the full query exactly as you intend to execute it. Do not simplify it
for the dry-run. Do not add `LIMIT`. Do not remove columns. The dry-run must
evaluate the exact query you plan to execute, or the estimate will be wrong.

```python
query = f"""
SELECT
    p.person_id,
    v.variant_id,
    v.gene_symbol,
    v.consequence,
    v.allele_frequency
FROM `{CDR}.short_read_wgs_variants` v
JOIN `{CDR}.person` p ON v.person_id = p.person_id
WHERE v.gene_symbol IN ('BRCA1', 'BRCA2', 'PALB2', 'ATM', 'CHEK2')
  AND v.consequence IN ('missense_variant', 'frameshift_variant',
                         'stop_gained', 'splice_donor_variant',
                         'splice_acceptor_variant')
"""
```

---

## Step 2: Dry-Run the Query

**Reference:** [dry-run-query](../reference/cost-awareness/dry-run-query.md)

A dry-run validates the query syntax and estimates the bytes that will be
scanned, without actually executing the query or incurring any cost.

```python
job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)

dry_run_job = client.query(query, job_config=job_config)

bytes_estimate = dry_run_job.total_bytes_processed
gb_estimate = bytes_estimate / (1024 ** 3)
tb_estimate = bytes_estimate / (1024 ** 4)

# BigQuery on-demand pricing: $6.25 per TB (as of 2024; verify current pricing)
cost_per_tb = 6.25
cost_estimate = tb_estimate * cost_per_tb

print(f"Estimated bytes scanned: {bytes_estimate:,}")
print(f"Estimated size: {gb_estimate:.2f} GB ({tb_estimate:.4f} TB)")
print(f"Estimated cost: ${cost_estimate:.2f}")
```

The dry-run returns instantly and costs nothing. There is no reason not to
run it before every expensive query.

> **Pitfall: Dry-running a simplified version of your query.**
> The most common mistake is running the dry-run on a version of the query
> that differs from the actual query. Three specific traps:
>
> - **Adding `LIMIT`:** `LIMIT 100` does not reduce bytes scanned in BigQuery.
>   BigQuery scans the full columns referenced in the query and then truncates
>   the output. The dry-run of `SELECT * FROM big_table LIMIT 10` reports the
>   same bytes as `SELECT * FROM big_table`. This is correct -- that is how
>   much the query will scan. But people add `LIMIT` thinking it will make
>   the query cheaper, then are surprised when the full query costs the same.
>
> - **Removing columns:** If you dry-run `SELECT person_id FROM table` but
>   execute `SELECT person_id, variant_id, gene_symbol, ... FROM table`, the
>   estimate will be lower than the actual cost because BigQuery is columnar --
>   fewer columns means fewer bytes scanned.
>
> - **Adding filters:** If you dry-run with an extra `WHERE` clause that you
>   later remove, the estimate may be lower (though BigQuery's pruning depends
>   on whether the filter maps to partition/cluster keys).
>
> **Rule:** The dry-run query must be character-for-character identical to the
> query you will execute.

---

## Step 3: Evaluate Whether the Cost Is Acceptable

This is a judgment call that depends on your budget, the importance of the
query, and whether optimization is feasible.

```python
budget_limit_usd = 10.00  # your per-query budget

if cost_estimate <= budget_limit_usd:
    print(f"Cost (${cost_estimate:.2f}) is within budget "
          f"(${budget_limit_usd:.2f}). Proceeding.")
    needs_optimization = False
else:
    print(f"Cost (${cost_estimate:.2f}) exceeds budget "
          f"(${budget_limit_usd:.2f}). Consider optimizing.")
    needs_optimization = True
```

Rules of thumb for All of Us workbench queries:

| Query type | Typical scan size | Notes |
|---|---|---|
| EHR table (condition, measurement) | 1-20 GB | Usually inexpensive |
| Person/demographics | < 1 GB | Tiny table |
| Short-read WGS variants | 50-500 GB | Depends on filters and columns |
| Whole-genome structural variants | 10-100 GB | Smaller than short-read |
| Survey data | < 5 GB | Small tables |

---

## Step 4: Optimize the Query (If Needed)

If the estimated cost exceeds your budget, consider these optimization
strategies, ordered from most to least effective:

### 4a. Reduce columns

BigQuery is a columnar store. Every column you `SELECT` adds to the bytes
scanned. Remove columns you do not need.

```python
# Before: selecting all variant fields
query_v1 = f"SELECT * FROM `{CDR}.short_read_wgs_variants` WHERE ..."

# After: selecting only needed columns
query_v2 = f"""
SELECT person_id, variant_id, gene_symbol, consequence
FROM `{CDR}.short_read_wgs_variants` WHERE ...
"""
# Re-run dry-run on query_v2 to see the savings
```

### 4b. Filter earlier

If you are joining tables, add filter conditions as early as possible. Push
`WHERE` clauses into subqueries or CTEs so that BigQuery can prune partitions
before the join.

```python
# Before: filter after join
query_v1 = f"""
SELECT v.*, p.sex_at_birth_concept_id
FROM `{CDR}.short_read_wgs_variants` v
JOIN `{CDR}.person` p ON v.person_id = p.person_id
WHERE v.gene_symbol IN ('BRCA1', 'BRCA2')
"""

# After: filter in subquery
query_v2 = f"""
SELECT v.person_id, v.variant_id, v.gene_symbol, p.sex_at_birth_concept_id
FROM (
    SELECT person_id, variant_id, gene_symbol
    FROM `{CDR}.short_read_wgs_variants`
    WHERE gene_symbol IN ('BRCA1', 'BRCA2')
) v
JOIN `{CDR}.person` p ON v.person_id = p.person_id
"""
```

### 4c. Materialize intermediate results

If you will run multiple queries against the same subset of a large table,
materialize the subset into a temporary table first. The materialization
scans the big table once; subsequent queries scan only the smaller temp table.

```python
# Create a temp table with the subset
materialize_sql = f"""
CREATE OR REPLACE TEMP TABLE my_variants AS
SELECT person_id, variant_id, gene_symbol, consequence
FROM `{CDR}.short_read_wgs_variants`
WHERE gene_symbol IN ('BRCA1', 'BRCA2', 'PALB2', 'ATM', 'CHEK2')
  AND consequence IN ('missense_variant', 'frameshift_variant',
                       'stop_gained', 'splice_donor_variant',
                       'splice_acceptor_variant')
"""
# This costs one full scan, but all subsequent queries against
# my_variants scan only the filtered subset
client.query(materialize_sql).result()
```

### 4d. Restrict to cohort person_ids

If your cohort is small relative to the full participant set, filtering the
variant table to only your cohort's person_ids can reduce scanned data
(depending on table partitioning).

After optimizing, **re-run the dry-run** (Step 2) to confirm the savings:

```python
# Re-estimate with the optimized query
dry_run_job = client.query(query_v2, job_config=job_config)
new_estimate = dry_run_job.total_bytes_processed / (1024 ** 4) * cost_per_tb
print(f"Optimized cost estimate: ${new_estimate:.2f} "
      f"(was ${cost_estimate:.2f})")
```

---

## Step 5: Set a Cost Cap

**Reference:** [cap-query-cost](../reference/cost-awareness/cap-query-cost.md)

Even after a dry-run, set a cost cap as a safety net. The cap prevents the query
from scanning more than a specified number of bytes. If the query would exceed
the cap, BigQuery rejects it immediately without scanning anything.

```python
# Set the cap slightly above the estimate to allow for minor variations
# but well below the amount that would cause budget problems
cap_bytes = int(bytes_estimate * 1.2)  # 20% margin above estimate

job_config = bigquery.QueryJobConfig(
    maximum_bytes_billed=cap_bytes,
)
print(f"Cost cap set: {cap_bytes / (1024 ** 3):.2f} GB "
      f"(${cap_bytes / (1024 ** 4) * cost_per_tb:.2f})")
```

**Why set a cap when you already have an estimate?** Two reasons:

1. **The estimate can be wrong.** Dry-run estimates are upper bounds. But query
   plan changes, schema evolution, or CDR version updates could cause the actual
   scan to differ. The cap is a hard limit that protects against surprises.

2. **You might run the wrong query.** If you accidentally execute a different
   query (e.g., one without the `WHERE` clause), the cap prevents a full table
   scan. This is the most common scenario where the cap saves real money.

See the Reference page for how to choose the cap value, the error message
format when a query is rejected, and how to handle the rejection gracefully.

---

## Step 6: Execute with the Cap in Place

```python
try:
    query_job = client.query(query, job_config=job_config)
    results_df = query_job.to_dataframe()
    print(f"Query returned {len(results_df)} rows")
except Exception as e:
    if "bytesBilledLimitExceeded" in str(e):
        print(f"Query exceeded cost cap of {cap_bytes / (1024 ** 3):.2f} GB. "
              f"No data was scanned and no cost was incurred.")
        print("Review the query and increase the cap if the cost is justified.")
    else:
        raise
```

If the query is rejected by the cap, no data is scanned and no cost is incurred.
You can safely increase the cap and try again, or investigate why the query
would scan more than expected.

---

## Step 7: Check Actual Bytes Billed

After successful execution, check what the query actually scanned. This is your
ground truth for future estimates.

```python
actual_bytes = query_job.total_bytes_billed
actual_gb = actual_bytes / (1024 ** 3)
actual_cost = (actual_bytes / (1024 ** 4)) * cost_per_tb

print(f"Actual bytes billed: {actual_bytes:,}")
print(f"Actual size: {actual_gb:.2f} GB")
print(f"Actual cost: ${actual_cost:.2f}")
print(f"Estimate accuracy: {actual_bytes / bytes_estimate * 100:.1f}% of estimate")
```

Note the difference between `total_bytes_processed` (from the dry-run) and
`total_bytes_billed` (from execution). The billed amount may differ due to
query cache hits (which reduce billed bytes to 0), the 10 MB minimum per query,
or partition pruning being more effective than estimated. Keep a log of actual
costs for your common query patterns to calibrate future budgets.

---

## Pipeline-Level Pitfall

### The dry-run must match the executed query exactly

This is the single most important rule in this guide. If you dry-run a
simplified query (fewer genes, added `LIMIT`, fewer columns) and then execute
the full query, the estimate will be wrong -- potentially by 5x or more.

The fix: use the same `query` variable for both calls:

```python
query = f"""..."""  # define once
dry_run_job = client.query(query, job_config=bigquery.QueryJobConfig(
    dry_run=True, use_query_cache=False
))
# ... evaluate cost ...
result_job = client.query(query, job_config=bigquery.QueryJobConfig(
    maximum_bytes_billed=cap_bytes
))
```

Using the same variable guarantees the dry-run and execution are identical.

---

## Quick-Reference Decision Table

| Estimated cost | Action |
|---|---|
| < $0.10 | Just run it. Set a cap at 2x the estimate as insurance. |
| $0.10 - $1.00 | Run it with a cap at 1.5x the estimate. |
| $1.00 - $10.00 | Consider optimizing (Step 4). Set a tight cap. |
| > $10.00 | Optimize first. Materialize intermediates. Discuss with team. |

These thresholds assume a standard Researcher Workbench billing setup. Adjust
based on your institution's budget allocation.

---

## What Comes Next

- Use this guide before Step 9 of
  [build-genomic-case-control-cohort](./build-genomic-case-control-cohort.md)
  to estimate the cost of the carrier-status query
- The dry-run pattern works for any BigQuery query, not just genomic ones --
  consider using it as a habit for any query against tables larger than 10 GB

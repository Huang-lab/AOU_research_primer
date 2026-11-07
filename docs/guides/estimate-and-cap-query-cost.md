# Guide: Estimate and Cap the Cost of a Large Cohort Query Before Running It

## Purpose

BigQuery charges by bytes scanned.
Genomic queries on the All of Us CDR can scan anything from a few megabytes to 20 terabytes, depending on how they are written.
Before running an expensive query, you should estimate what it will cost and set a safety cap so that a mistake in your SQL does not result in an unexpectedly large bill.

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

# v9 variant annotations live in the search index dataset (name ends in a build date)
CDR_PROJECT, CDR_DATASET = CDR.split(".")
IDX = CDR_PROJECT + "." + sorted(
    d.dataset_id for d in client.list_datasets(CDR_PROJECT)
    if d.dataset_id.startswith(f"{CDR_DATASET}_index_")
)[-1]
```

The examples use CDR v9 (`C2025Q4R6`) tables and the cost figures measured on them.

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

The running example is a first draft of a carrier lookup: every participant who carries a ClinVar pathogenic or likely pathogenic variant in six cancer-predisposition genes.
It joins three v9 tables in one statement: `T_ESA_variant_gene` (gene to variant) and `T_ENT_variant` (variant annotations) from the search index, and `cb_variant_to_person` (variant to carriers) from the CDR.

```python
query = f"""
SELECT
    g.gene,
    e.id AS vid,
    e.consequence,
    e.clinvar_significance,
    e.allele_count,
    e.allele_number,
    p.element AS person_id
FROM `{IDX}.T_ESA_variant_gene` g
JOIN `{IDX}.T_ENT_variant` e ON e.id = g.id
JOIN `{CDR}.cb_variant_to_person` vp ON vp.vid = e.id
CROSS JOIN UNNEST(vp.person_ids.list) AS p
WHERE g.gene IN ('BRCA1', 'BRCA2', 'PALB2', 'ATM', 'CHEK2', 'TP53')
  AND EXISTS (SELECT 1 FROM UNNEST(e.clinvar_significance) c
              WHERE LOWER(c) IN ('pathogenic', 'likely pathogenic',
                                 'pathogenic, low penetrance'))
"""
```

The SQL is correct, and it returns the right carriers.
Steps 2 and 3 show that it is also very expensive.

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

!!! pitfall "Dry-running a simplified version of your query"
    The most common mistake is running the dry-run on a version of the query that differs from the actual query. Three specific traps:  - **Adding `LIMIT`:** `LIMIT 100` does not reduce bytes scanned in BigQuery.   BigQuery scans the full columns referenced in the query and then truncates   the output. The dry-run of `SELECT * FROM big_table LIMIT 10` reports the   same bytes as `SELECT * FROM big_table`. This is correct -- that is how   much the query will scan. But people add `LIMIT` thinking it will make   the query cheaper, then are surprised when the full query costs the same.  - **Removing columns:** If you dry-run `SELECT person_id FROM table` but   execute `SELECT person_id, variant_id, gene_symbol, ... FROM table`, the   estimate will be lower than the actual cost because BigQuery is columnar --   fewer columns means fewer bytes scanned.  - **Adding filters:** If you dry-run with an extra `WHERE` clause that you   later remove, the estimate may be lower (though BigQuery's pruning depends   on whether the filter maps to partition/cluster keys).  **Rule:** The dry-run query must be character-for-character identical to the query you will execute.


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

For the Step 1 query, the dry-run reports about 19,148 GB, or $116.87, far over a $10 budget.
Almost all of it is `cb_variant_to_person`, which is read in full because the query joins to it.

Sizes of common v9 tables, which are what a query that reads every column costs:

| Table | Full-scan size in v9 | Notes |
|---|---|---|
| `person` | 0.2 GB | Demographics, always cheap |
| `condition_occurrence` | 15.3 GB | Diagnoses |
| `measurement` | 83.3 GB | Labs and vitals, the largest OMOP table |
| `observation` | 47.3 GB | Includes survey answers |
| `T_ENT_variant` (search index) | 142.5 GB | One row per variant; a join to it reads its columns in full |
| `cb_variant_to_person` | 19,078 GB (about $116) | Clustered on `vid`: a literal list of 1,977 `vid`s read 4.5 GB |
| VAT (`v9_vat_bigquery`) | 3,153 GB | Not clustered: a one-gene query reads 129-216 GB |

GB here and throughout this guide is 1024<sup>3</sup> bytes, the unit Step 2 prints.
Pages that quote decimal gigabytes give larger numbers for the same tables (20,484 GB for `cb_variant_to_person`).

---

## Step 4: Optimize the Query (If Needed)

If the estimated cost exceeds your budget, consider these optimization
strategies, ordered from most to least effective:

### 4a. Filter clustered tables with literal values

A clustered table is sorted by its clustering column, so a filter on that column can skip most of the table.
The dry-run can count on that pruning only when the filter compares the clustering column with constant values.
For a join, or a subquery such as `WHERE vid IN (SELECT ...)`, it estimates a read of the whole table, and a cost cap below that estimate blocks the query.

`cb_variant_to_person` is clustered on `vid`.
Split the Step 1 query in two: first find the candidate variants, then look up their carriers with the `vid`s passed as an array parameter.

```python
# Query 1: candidate variants from the search index
candidates_sql = f"""
SELECT
    g.gene,
    e.id AS vid,
    e.consequence,
    e.clinvar_significance,
    e.allele_count,
    e.allele_number
FROM `{IDX}.T_ESA_variant_gene` g
JOIN `{IDX}.T_ENT_variant` e ON e.id = g.id
WHERE g.gene IN ('BRCA1', 'BRCA2', 'PALB2', 'ATM', 'CHEK2', 'TP53')
  AND EXISTS (SELECT 1 FROM UNNEST(e.clinvar_significance) c
              WHERE LOWER(c) IN ('pathogenic', 'likely pathogenic',
                                 'pathogenic, low penetrance'))
"""
candidates = client.query(candidates_sql).to_dataframe()

# Query 2: their carriers, with the vids as literal values
carriers_sql = f"""
SELECT vp.vid, p.element AS person_id
FROM `{CDR}.cb_variant_to_person` vp
CROSS JOIN UNNEST(vp.person_ids.list) AS p
WHERE vp.vid IN UNNEST(@vids)
"""
carriers_config = bigquery.QueryJobConfig(query_parameters=[
    bigquery.ArrayQueryParameter("vids", "STRING", sorted(candidates["vid"]))
])
carriers = client.query(carriers_sql, job_config=carriers_config).to_dataframe()
carrier_df = carriers.merge(candidates, on="vid")
```

| Query | Dry-run estimate | Billed |
|---|---|---|
| Step 1 query (one join) | 19,148 GB | not run |
| Query 1 (candidate variants) | 70.06 GB | 29.79 GB |
| Query 2 (1,977 `vid`s as a parameter) | 4.52 GB | 4.52 GB |
| Query 2 with `WHERE vp.vid IN (SELECT ...)` instead | 19,103 GB | not run |

The two queries together cost about 34 GB (about $0.21) instead of 19,148 GB.
Query 1 is billed less than its estimate because BigQuery prunes the join to `T_ENT_variant` (clustered on `id`) at run time, which the dry-run cannot predict.

### 4b. Reduce columns

BigQuery is a columnar store. Every column you `SELECT` adds to the bytes
scanned. Remove columns you do not need.

The dry-run cannot tell which `T_ENT_variant` rows the gene filter will keep, so it estimates a full read of every `T_ENT_variant` column the query names, whatever the gene panel.
Keep only the columns you filter on or need downstream.

```python
# Before: Query 1 from 4a, five T_ENT_variant columns
query_v1 = candidates_sql

# After: only the variant id and the column the filter needs
query_v2 = f"""
SELECT g.gene, e.id AS vid, e.clinvar_significance
FROM `{IDX}.T_ESA_variant_gene` g
JOIN `{IDX}.T_ENT_variant` e ON e.id = g.id
WHERE g.gene IN ('BRCA1', 'BRCA2', 'PALB2', 'ATM', 'CHEK2', 'TP53')
  AND EXISTS (SELECT 1 FROM UNNEST(e.clinvar_significance) c
              WHERE LOWER(c) IN ('pathogenic', 'likely pathogenic',
                                 'pathogenic, low penetrance'))
"""
# Re-run the dry-run on query_v2 to see the savings
```

In v9, `query_v1` dry-runs at 70.06 GB and `query_v2` at 25.37 GB.

### 4c. Query once, reuse the result

If you need several subsets of the same large table, pull the superset once and split it in pandas.
For the same reason as in 4b, a query for one gene dry-runs at almost the same size as a query for the whole panel (25.31 GB for BRCA1 alone, 25.37 GB for six genes), and the cap you set must cover that estimate.

```python
# Before: one query per gene, each estimated at a full read of the
# T_ENT_variant columns (6 genes x 25.3 GB)

# After: one query for the panel, then filter locally
panel_df = client.query(query_v2).to_dataframe()
brca1_df = panel_df[panel_df["gene"] == "BRCA1"]
```

The same applies to alternative filters: pull the candidates once with the columns every filter needs, and compare filters (for example, ClinVar rules) in pandas instead of re-querying.

!!! note "`CREATE TEMP TABLE` does not survive between `client.query` calls"
    A temporary table lasts only for the multi-statement query that creates it, so a later `client.query` call cannot read it.
    Keep intermediate results in a DataFrame, or write them to a table in your workspace's own dataset.

### 4d. Restrict to cohort person_ids

A `person_id` filter saves bytes only on a table clustered on `person_id`.
No OMOP table in v9 is clustered or partitioned (`person`, `condition_occurrence`, `measurement` and `observation` included), so a cohort filter on them reads the same bytes as no filter.
`cb_variant_to_person` has one row per variant with a list of carriers, so a cohort filter cannot reduce what it reads.
Look up carriers for all participants, then keep your cohort in pandas (`carrier_df[carrier_df["person_id"].isin(cohort_df["person_id"])]`).

After optimizing, **re-run the dry-run** (Step 2) to confirm the savings:

```python
# Re-estimate with the optimized query
dry_run_job = client.query(query_v2, job_config=job_config)
new_estimate = dry_run_job.total_bytes_processed / (1024 ** 4) * cost_per_tb
print(f"Optimized cost estimate: ${new_estimate:.2f} "
      f"(was ${cost_estimate:.2f})")
```

Then make the optimized query the one you run (`query = query_v2`) and continue with Steps 5-7.
Give the carrier lookup (Query 2 in 4a) its own dry-run and cap in the same way.

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

Clustering is the large case in v9: Query 1 in 4a dry-runs at 70.06 GB but is billed 29.79 GB.
Do not count on it: Query 2 in 4a, also on a clustered table, is billed exactly its 4.52 GB estimate.

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

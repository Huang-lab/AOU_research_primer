# Optimize compute environment costs

Choose the cheapest Workbench compute configuration for your workload, and avoid the idle-cluster trap that burns credits overnight.

**You'll need:** A Researcher Workbench workspace with cloud credits
**Tier:** Registered or Controlled
**CDR versions validated:** C2025Q4R6

---

## Reference

The Researcher Workbench bills per-second for compute and per-GB/month for disk. Total cost is:

```
Cost = VM hourly rate + Dataproc premium + disk cost
```

where:

- **VM hourly rate** — depends on machine type (only `n1` family is available)
- **Dataproc premium** — `$0.01 × total vCPUs × hours` (only for Dataproc clusters)
- **Disk cost** — `$0.04/GB/month` for standard persistent disk (~$0.000055/GB/hr)

**Initial credits:** $300 per researcher, expiring **365 days** after you sign the Data
User Code of Conduct ([policy change effective 2025-02-18](https://support.researchallofus.org/hc/en-us/articles/37568567328788-Updates-to-All-of-Us-initial-credits-expirations-updated-to-365-days)).
For most usage patterns the clock, not the balance, is what runs out first — see
[Budget against the expiry clock](#budget-against-the-expiry-clock) below.

### VM pricing (us-central1)

| Machine type | vCPUs | RAM | On-demand $/hr | Spot $/hr |
|---|---|---|---|---|
| `n1-standard-2` | 2 | 7.5 GB | $0.095 | $0.049 |
| `n1-standard-4` | 4 | 15 GB | $0.190 | $0.098 |
| `n1-standard-8` | 8 | 30 GB | $0.380 | $0.196 |
| `n1-standard-16` | 16 | 60 GB | $0.760 | $0.392 |
| `n1-highmem-4` | 4 | 26 GB | $0.237 | $0.080 |
| `n1-highmem-8` | 8 | 52 GB | $0.474 | $0.159 |

## Usage

### Recommended configuration

For most AoU work — SQL, pandas, Hail, Spark, variant queries, PCA, regressions — a single-node Dataproc cluster handles everything at the minimum cost:

```python
# Workbench settings:
# Environment:  JupyterLab Spark Cluster for AoU (Dataproc)
# Master node:  n1-standard-2 (2 vCPU, 7.5 GB RAM)
# Workers:      0
# Disk:         50 GB standard
# Hail:         Enabled (no extra cost)
#
# Hourly cost breakdown:
#   VM:               $0.095
#   Dataproc premium:  $0.020  (2 vCPU × $0.01)
#   Disk:             $0.003  (50 GB × $0.000055/hr)
#   ─────────────────────────
#   Total:            ~$0.12/hr
#
# At 4 hrs/day, 20 days/month: ~$10/month
# $300 credits last:           625 working days
```

> **Pitfall: Dataproc clusters have NO autostop**
> Unlike Jupyter environments, Dataproc clusters do not auto-pause or auto-stop when idle. A cluster left running overnight at $0.12/hr wastes $1.44. A cluster with workers left over a weekend wastes $35+. **You must delete the cluster manually when you finish each session.** Set a calendar reminder or phone alarm until the habit is automatic.

### Environment setup

```python
import os
from google.cloud import bigquery

# Environment variables are auto-injected in Jupyter but NOT in Dataproc.
# Always use .get() with a manual fallback.
PROJECT = os.environ.get("GOOGLE_PROJECT", "your-project-id")
CDR = os.environ.get("WORKSPACE_CDR", "your-project.C2025Q4R6")
BUCKET = os.environ.get("WORKSPACE_BUCKET", "gs://fc-secure-your-bucket-id")
client = bigquery.Client(project=PROJECT)

print(f"PROJECT: {PROJECT}")
print(f"CDR:     {CDR}")
print(f"BUCKET:  {BUCKET}")
```

> **Pitfall: WORKSPACE_CDR is None in Dataproc**
> `os.environ["WORKSPACE_CDR"]` raises `KeyError` in Dataproc environments because the variable is not auto-injected. `os.environ.get("WORKSPACE_CDR")` returns `None`, which produces queries like `None.person` — resulting in a confusing `403 Forbidden` error, not a clear "variable not set" message. Always provide a manual fallback string, and print the CDR value before running queries.

### Finding your environment values

If the env vars are not set, find them manually:

```bash
# Project ID — visible in Workbench workspace settings
echo $GOOGLE_PROJECT

# CDR — visible in workspace under CDR version
# Format: project.dataset, e.g. "wb-silky-artichoke-2408.C2025Q4R6"
echo $WORKSPACE_CDR

# Bucket — list your GCS buckets and find the fc-secure- one
gsutil ls
```

## Recommended configurations by workload

| Workload | Environment | Master | Workers | Disk | $/hr | $/mo* |
|---|---|---|---|---|---|---|
| **All-purpose (SQL, Hail, PCA, regressions)** | Dataproc + Hail | n1-standard-2 | 0 | 50 GB | **$0.12** | **$10** |
| SQL queries, pandas, basic EDA | Jupyter | n1-standard-2 | — | 50 GB | $0.10 | $8 |
| Heavier pandas, PhecodeX, feature matrices | Jupyter | n1-standard-4 | — | 50 GB | $0.19 | $15 |
| Parallelized GWAS, GRM construction | Dataproc | n1-standard-4 | 2 preemptible | 100 GB | $0.37 | $30 |
| Large-scale GWAS, full-cohort Hail | Dataproc | n1-standard-4 | 2 std + 4 preempt | 100 GB | $0.85 | $68 |
| Team shared cluster (2–3 people) | Dataproc | n1-standard-8 | 4 preemptible | 100 GB | $0.90 | $72 |
| Memory-heavy (large matrix merges) | Jupyter | n1-highmem-4 | — | 50 GB | $0.24 | $19 |

*Monthly estimate = 4 hrs/day × 20 working days. Enabling Hail does not increase hourly cost. Disk-only cost while stopped: ~$0.003/hr.*

## Variations

### Preemptible workers for batch genomic jobs

For embarrassingly parallel jobs (GWAS across chromosomes, GRM construction), use preemptible (spot) workers instead of standard. They cost ~50% less, and Dataproc automatically retries tasks if Google reclaims a VM.

```python
# Workbench Dataproc settings for parallelized GWAS:
# Master:              n1-standard-4 (4 vCPU, 15 GB)
# Standard workers:    0
# Preemptible workers: 2 × n1-standard-4
# Disk:                100 GB
#
# Cost: ~$0.37/hr (vs $0.73/hr with 2 standard workers)
```

> **Note: When NOT to use preemptible workers**
> Avoid preemptible workers for **interactive Hail sessions** where you're building and caching matrix tables. Worker loss forces Hail to recompute from scratch, which can be more expensive than using standard workers in the first place.

### Team configuration

When multiple researchers share a workspace for coordinated analysis:

```python
# Each person: their own Jupyter (n1-standard-2, 50 GB) — $0.10/hr each
# Shared:      one Dataproc cluster, created/deleted by one designated person
#
# Shared cluster config:
# Master:              n1-standard-8 (8 vCPU, 30 GB)
# Preemptible workers: 4 × n1-standard-4
# Disk:                100 GB
#
# Cost: ~$0.90/hr for the shared cluster
#
# Best practices:
# - One person creates and deletes the cluster
# - Store intermediate results in the shared GCS bucket
#   so others don't re-run expensive queries
# - Set a budget alert at $200 to avoid surprise credit exhaustion
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `KeyError: 'WORKSPACE_CDR'` | Running on Dataproc — env vars are not auto-injected. Use `os.environ.get()` with a manual fallback. |
| `403 Forbidden: Table project:None.table` | CDR variable resolved to `None`. Print `CDR` value and set it manually. |
| `has_array_data` column not found | CDR version change. Check `INFORMATION_SCHEMA.COLUMNS` for the current column name — newer CDRs use `has_whole_genome_variant`. |
| Genomic flags all 0 | You are on the Registered Tier. Controlled Tier is required for genomic data (WGS, variants, carrier status). |
| Credits draining faster than expected | Check for an idle Dataproc cluster. Go to Workbench → Cloud Environments and delete any clusters not in active use. |

### Budget against the expiry clock

Credits expire 365 days after you sign the Data User Code of Conduct, whether or not you
have spent them. Two consequences that change how you should choose a machine:

**Below roughly 10 hours per working day, the expiry clock binds before the balance does.**
Downsizing the VM then saves nothing — it only increases the amount forfeited. If you have a
deadline, size *up* to finish sooner rather than down to reduce the hourly rate. The cheap
configuration is the right default for *idle* risk (a forgotten cluster), not for throughput.

| Usage | Spend in 365 days (at $0.12/hr) | Unspent at expiry |
|---|---|---|
| 2 hrs/day, 20 days/month | $57 | $243 |
| 4 hrs/day, 20 days/month | $113 | $187 |
| 8 hrs/day, 20 days/month | $226 | $74 |
| 10.6 hrs/day, 20 days/month | $300 | $0 |

> **Pitfall: expiry deletes your data, not just your credits**
> When initial credits are exhausted *or* reach their expiration date, you can no longer launch
> or access analysis environments, and **workspace buckets and persistent disks are deleted**.
> Export anything you need to keep before the date, and link an institutional billing account
> ahead of it if the work is continuing. This is a data-loss deadline, not only a budget one.

## Cost note

The compute environment itself is the largest cost driver in the Workbench — larger than BigQuery for most researchers. The #1 way to waste credits is forgetting to delete a Dataproc cluster.

But at the recommended rate the credits **expire before they are spent**: $0.12/hr at 4 hrs/day, 20 days/month is $9.42/month, so a year of that usage draws $113 of the $300 and the remaining **$187 is forfeited**. Spending the full grant inside 365 days takes about **10.6 hours per working day** on that configuration.

## See also

- [Dry-run a query to estimate cost](dry-run-query.md) — estimate BigQuery scan cost before execution
- [Cap query cost before execution](cap-query-cost.md) — set a hard byte limit on queries
- [Choose the right compute environment](../environment/choose-compute-environment.md) — Jupyter vs Dataproc, Hail setup, sklearn alternatives

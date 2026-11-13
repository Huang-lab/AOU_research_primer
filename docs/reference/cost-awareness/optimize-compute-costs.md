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

- **VM hourly rate**: depends on machine type and your workspace's region (see below)
- **Dataproc premium**: `$0.01 × total vCPUs × hours`, counting every node (only for Dataproc clusters)
- **Disk cost**: `$0.044/GB/month` for standard persistent disk in us-east4 (~$0.00006/GB/hr).
  Every Dataproc node has its own boot disk, and disks are billed while the environment is stopped.

**Initial credits:** $300 per researcher, expiring **365 days** after you sign the Data
User Code of Conduct ([policy change effective 2025-02-18](https://support.researchallofus.org/hc/en-us/articles/37568567328788-Updates-to-All-of-Us-initial-credits-expirations-updated-to-365-days)).
For most usage patterns the clock, not the balance, is what runs out first — see
[Budget against the expiry clock](#budget-against-the-expiry-clock) below.

### VM pricing (us-east4)

The region is set by the workspace and shown, read-only, when you create an environment.
The workspace we checked uses `us-east4`; if yours differs, so do the prices.
Prices below are Google Cloud on-demand list prices for us-east4, checked 2026-11-06 ([VMs](https://cloud.google.com/products/compute/pricing/general-purpose), [disks](https://cloud.google.com/compute/disks-image-pricing), [Dataproc](https://cloud.google.com/products/managed-service-for-apache-spark/pricing)).

| Machine type | vCPUs | RAM | Available in | On-demand $/hr |
|---|---|---|---|---|
| `n2-standard-2` | 2 | 8 GB | Jupyter, Dataproc | $0.109 |
| `n2-standard-4` | 4 | 16 GB | Jupyter, Dataproc | $0.219 |
| `n2-standard-8` | 8 | 32 GB | Jupyter, Dataproc | $0.438 |
| `n2-standard-16` | 16 | 64 GB | Jupyter, Dataproc | $0.875 |
| `n1-highmem-4` | 4 | 26 GB | Jupyter only | $0.266 |

Standard machines are N2 (`n2-standard-2` up to `n2-standard-128`) in both environments.
The only high-memory option is `n1-highmem-4`, in Jupyter; Dataproc offers `n2-standard` machines only.

## Usage

### Recommended configuration

For most AoU work — SQL, pandas, Hail, Spark, variant queries, PCA, regressions — a single-node Dataproc cluster handles everything at the minimum cost:

```python
# Workbench settings:
# Environment:  JupyterLab Spark Cluster for AoU (Dataproc)
# Master node:  n2-standard-2 (2 vCPU, 8 GB RAM)
# Workers:      0
# Disk:         50 GB standard (the form defaults to 500 GB; lower it)
# Hail:         Enabled (no extra cost)
#
# Hourly cost breakdown:
#   VM:               $0.109
#   Dataproc premium:  $0.020  (2 vCPU × $0.01)
#   Disk:             $0.003  (50 GB × $0.00006/hr)
#   ─────────────────────────
#   Total:            ~$0.13/hr
#
# At 4 hrs/day, 20 days/month: ~$11/month
# Credits expire after 365 days: see "Budget against the expiry clock"
```

!!! pitfall "Dataproc clusters have NO autostop"
    Unlike Jupyter environments, Dataproc clusters do not auto-pause or auto-stop when idle. A cluster left running overnight at $0.13/hr wastes about $1.60. A cluster with two workers left over a weekend wastes about $48. **You must delete the cluster manually when you finish each session.** Set a calendar reminder or phone alarm until the habit is automatic.

!!! pitfall "Dataproc boot disks default to 500 GB per node"
    The Dataproc form pre-fills 500 GB for the master and for each worker.
    At $0.044/GB/month, the default master-plus-two-workers cluster carries 1,500 GB of disk: about $66/month, billed even while the cluster is stopped.
    50-100 GB per node is enough for most work, so lower it before you create the cluster.

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

!!! pitfall "WORKSPACE_CDR is None in Dataproc"
    `os.environ["WORKSPACE_CDR"]` raises `KeyError` in Dataproc environments because the variable is not auto-injected. `os.environ.get("WORKSPACE_CDR")` returns `None`, which produces queries like `None.person` — resulting in a confusing `403 Forbidden` error, not a clear "variable not set" message. Always provide a manual fallback string, and print the CDR value before running queries.

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
| **All-purpose (SQL, Hail, PCA, regressions)** | Dataproc + Hail | n2-standard-2 | 0 | 50 GB | **$0.13** | **$11** |
| SQL queries, pandas, basic EDA | Jupyter | n2-standard-2 | - | 50 GB | $0.11 | $9 |
| Heavier pandas, PhecodeX, feature matrices | Jupyter | n2-standard-4 | - | 50 GB | $0.22 | $18 |
| Parallelized GWAS, GRM construction | Dataproc | n2-standard-4 | 2 × n2-standard-4, preemptible | 100 GB/node | < $0.79 | < $64 |
| Large-scale GWAS, full-cohort Hail | Dataproc | n2-standard-4 | 6 × n2-standard-4 (2 std + 4 preempt) | 100 GB/node | < $1.85 | < $148 |
| Team shared cluster (2-3 people) | Dataproc | n2-standard-8 | 4 × n2-standard-4, preemptible | 100 GB/node | < $1.58 | < $127 |
| Memory-heavy (large matrix merges) | Jupyter | n1-highmem-4 | - | 50 GB | $0.27 | $22 |

*Monthly estimate = 4 hrs/day × 20 working days.
Rows with preemptible workers show the price with every worker on-demand, so the real cost is lower; spot prices change too often to list.
Enabling Hail does not increase hourly cost.
Disk-only cost while stopped: ~$0.003/hr for 50 GB.*

## Variations

### Preemptible workers for batch genomic jobs

For embarrassingly parallel jobs (GWAS across chromosomes, GRM construction), use preemptible (spot) workers instead of standard ones.
They cost substantially less than on-demand, and Dataproc automatically retries tasks if Google reclaims a VM.
Spot prices change frequently, so this page does not list them.
Preemptible applies to workers only: the master is always on-demand, and a single-node cluster can't be preemptible at all.

```python
# Workbench Dataproc settings for parallelized GWAS:
# Master:              n2-standard-4 (4 vCPU, 16 GB)
# Standard workers:    0
# Preemptible workers: 2 × n2-standard-4
# Disk:                100 GB per node
#
# Cost: under $0.79/hr (the price with 2 on-demand workers)
```

!!! note "When NOT to use preemptible workers"
    Avoid preemptible workers for **interactive Hail sessions** where you're building and caching matrix tables. Worker loss forces Hail to recompute from scratch, which can be more expensive than using standard workers in the first place.

### Team configuration

When multiple researchers share a workspace for coordinated analysis:

```python
# Each person: their own Jupyter (n2-standard-2, 50 GB): $0.11/hr each
# Shared:      one Dataproc cluster, created/deleted by one designated person
#
# Shared cluster config:
# Master:              n2-standard-8 (8 vCPU, 32 GB)
# Preemptible workers: 4 × n2-standard-4
# Disk:                100 GB per node
#
# Cost: under $1.58/hr for the shared cluster (the price with on-demand workers)
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

**Below roughly 9.5 hours per working day, the expiry clock binds before the balance does.**
Downsizing the VM then saves nothing — it only increases the amount forfeited. If you have a
deadline, size *up* to finish sooner rather than down to reduce the hourly rate. The cheap
configuration is the right default for *idle* risk (a forgotten cluster), not for throughput.

| Usage | Spend in 365 days (at $0.132/hr) | Unspent at expiry |
|---|---|---|
| 2 hrs/day, 20 days/month | $64 | $236 |
| 4 hrs/day, 20 days/month | $127 | $173 |
| 8 hrs/day, 20 days/month | $254 | $46 |
| 9.4 hrs/day, 20 days/month | $300 | $0 |

!!! pitfall "Expiry deletes your data, not just your credits"
    When initial credits are exhausted *or* reach their expiration date, you can no longer launch
    or access analysis environments, and **workspace buckets and persistent disks are deleted**.
    Export anything you need to keep before the date, and link an institutional billing account
    ahead of it if the work is continuing. This is a data-loss deadline, not only a budget one.

## Cost note

The compute environment itself is the largest cost driver in the Workbench — larger than BigQuery for most researchers. The #1 way to waste credits is forgetting to delete a Dataproc cluster.

But at the recommended rate the credits **expire before they are spent**: $0.132/hr at 4 hrs/day, 20 days/month is $10.59/month, so a year of that usage draws $127 of the $300 and the remaining **$173 is forfeited**. Spending the full grant inside 365 days takes about **9.4 hours per working day** on that configuration.

## See also

- [Dry-run a query to estimate cost](dry-run-query.md) — estimate BigQuery scan cost before execution
- [Cap query cost before execution](cap-query-cost.md) — set a hard byte limit on queries
- [Choose the right compute environment](../environment/choose-compute-environment.md) — Jupyter vs Dataproc, Hail setup, sklearn alternatives

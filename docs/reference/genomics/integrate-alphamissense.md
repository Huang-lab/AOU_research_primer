# Integrate AlphaMissense pathogenicity scores

Match AoU variant data to AlphaMissense predictions for missense variant prioritization.

## Prerequisites

- **Dataproc/Hail cluster** (required for GCS access — see [Choose the right compute environment](../environment/choose-compute-environment.md))
- Variant data already extracted from `cb_variant_attribute` (see [Discover genomics table schemas](discover-genomics-tables.md))
- Python 3, `pandas`, `subprocess`

**Tier:** Controlled
**CDR versions:** v7+

## Reference

AlphaMissense is a deep learning model that predicts pathogenicity of all possible human missense variants. Scores range from 0 (benign) to 1 (pathogenic), with three classification tiers:

| `am_class` | Score range | Interpretation |
|---|---|---|
| `likely_benign` | < 0.34 | Predicted benign |
| `ambiguous` | 0.34 – 0.564 | Uncertain |
| `likely_pathogenic` | > 0.564 | Predicted damaging |

The full genome-wide file is 613 MB. To avoid downloading all of it, stream and filter to a specific gene region.

## Usage

### Step 1: Download gene-region AlphaMissense scores

```python
import subprocess
import pandas as pd

# MUTYH region on chromosome 1 (adjust coordinates for your gene)
# IMPORTANT: AlphaMissense uses "chr1" format, NOT "1"
cmd = (
    'gsutil cat gs://dm_alphamissense/AlphaMissense_hg38.tsv.gz '
    '| gunzip '
    "| awk -F'\\t' '$1==\"chr1\" && $2>=45327000 && $2<=45346000'"
    ' > /tmp/mutyh_alphamissense.tsv'
)
subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)

am = pd.read_csv(
    "/tmp/mutyh_alphamissense.tsv", sep="\t",
    names=["CHROM", "POS", "REF", "ALT", "genome", "uniprot_id",
           "transcript_id", "protein_variant", "am_pathogenicity", "am_class"],
)
print(f"AlphaMissense variants: {len(am):,}")
print(am["am_class"].value_counts())
```

!!! pitfall "AlphaMissense uses `chr1` format, AoU uses `1`"
    The AlphaMissense file uses `chr1`, `chr2`, etc. AoU's `vid` format uses
    bare chromosome numbers (`1-45331833-C-G`). When matching, strip the `chr`
    prefix from AlphaMissense or add it to AoU coordinates.


### Step 2: Parse AoU VID and match

```python
# Parse AoU vid format: chromosome-position-ref-alt
vid_parts = variants_df["vid"].str.split("-", expand=True)
variants_df["POS"] = vid_parts[1].astype(int)
variants_df["REF"] = vid_parts[2]
variants_df["ALT"] = vid_parts[3]

# Match on position + alleles
merged = variants_df.merge(
    am[["POS", "REF", "ALT", "am_pathogenicity", "am_class"]],
    on=["POS", "REF", "ALT"],
    how="left",
)
matched = merged["am_pathogenicity"].notna().sum()
print(f"Matched: {matched}/{len(merged)} variants")
```

### Step 3: Filter candidates before scoring

Exclude variants where ClinVar already provides a classification or where the variant is too common to be pathogenic:

```python
candidates = variants_df[
    (~variants_df["clinvar"].str.contains("athogenic", na=False))
    & (~variants_df["clinvar"].str.contains("enign", na=False))
    & (variants_df["allele_frequency"] < 0.01)
]
print(f"Unclassified rare missense candidates: {len(candidates):,}")
```

## Variations

### Use Chen et al. calibrated evidence tiers

If you have the Chen et al. calibration table (13.4M rows, 1.77 GB), extract gene-specific rows for ACMG-style evidence integration:

```bash
head -1 newAM_calibration_table_20260206.csv > gene_calibration.csv
grep "^BRCA1," newAM_calibration_table_20260206.csv >> gene_calibration.csv
```

Evidence tiers and ACMG point values:

| Tier | Points | Meaning |
|---|---|---|
| `PP3_Strong` | +4 | Strongest pathogenic evidence |
| `PP3_Moderate+` | +3 | |
| `PP3_Moderate` | +2 | |
| `PP3_Supporting` | +1 | |
| `NO_EVIDENCE` | 0 | |
| `BP4_Supporting` | -1 | |
| `BP4_Strong` | -4 | Strongest benign evidence |

## Troubleshooting

| Symptom | Cause |
|---|---|
| `gsutil cat` hangs or times out | The full file is 613 MB compressed. Ensure your awk filter is narrow enough. For genes spanning large regions, increase the `timeout` parameter. |
| Zero matches after merge | Coordinate mismatch: check that POS, REF, ALT match exactly. AlphaMissense is hg38-based, which matches AoU. |
| `gsutil` returns "requester pays" error | Add `-u $GOOGLE_PROJECT` flag. The `dm_alphamissense` bucket may require it. |

## Cost note

No BigQuery cost — AlphaMissense data is accessed via GCS, not BigQuery. Network transfer cost is minimal for gene-region extractions. The full file download (613 MB) takes under a minute on a Dataproc cluster.

## See also

- [Filter variants to ClinVar P/LP](filter-clinvar-plp.md) — ClinVar-based filtering (use before AlphaMissense)
- [Discover genomics table schemas](discover-genomics-tables.md) — VID format parsing
- [Choose the right compute environment](../environment/choose-compute-environment.md) — Dataproc required for GCS access

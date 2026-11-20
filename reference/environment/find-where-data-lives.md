# Find where data lives in CDR v9

`data type -> BigQuery dataset.table, or Cloud Storage folder`

A map of the Controlled Tier CDR v9: which BigQuery table or Cloud Storage folder holds each kind of data and how big it is.

**You'll need:** a Controlled Tier workspace; for the bucket, an environment that can reach the controlled genomics bucket (see [Choose the right compute environment](choose-compute-environment.md))

**Tier:** Controlled

**CDR versions validated:** C2025Q4R6 (v9), mapped 2026-11-07

---

## Reference

v9 data lives in three places:

| Where | What lives there |
|---|---|
| BigQuery dataset `C2025Q4R6` (the CDR) | EHR, surveys, physical measurements, Fitbit, cognitive tasks, ZIP-level SES, the carrier lookup table |
| Other BigQuery datasets in the same project | Clinical notes, Apple HealthKit, biospecimens, the variant annotation table (VAT), the search index |
| `gs://vwb-aou-datasets-controlled/v9/` | Genomic and multi-omic files: short-read WGS, long reads, structural variants, microarray, proteomics, RNA-seq |

The CDR's project is the part of `WORKSPACE_CDR` before the dot.
Row counts and sizes below are from C2025Q4R6.
Sizes are BigQuery storage sizes.

### Quick lookup

| Looking for | Look in |
|---|---|
| Sex at birth, race, ethnicity, gender | `person` (`*_concept_id` columns); `person_ext` adds self-reported category and state of residence |
| Where a participant lives | 3-digit ZIP only, masked as `XXX**`: the survey answer `StreetAddress_PIIZIP` in `observation`, or `ds_zip_code_socioeconomic.ZIP3_AS_STRING` |
| Neighborhood deprivation, income, education | `zip3_ses_map` (by 3-digit ZIP) or `ds_zip_code_socioeconomic` (one row per participant) |
| Survey answers with readable question and answer text | `ds_survey` (`survey`, `question`, `answer`); concept-coded answers are in `observation` |
| Which source a record came from | `src_id` in the record's `<table>_ext` table, joined on the record id |
| Death and cause of death | `aou_death` (`cause_concept_id`, `primary_death_record`) |
| Who has short-read WGS | The index's `T_ENT_person.has_whole_genome_variant`, not `cb_search_person` |
| EHR cutoff date and vocabulary version | `_cdr_metadata` (`ehr_cutoff_date` is 2025-01-01 in v9) |
| Clinical note text | `C_V9_R6_offcycle_nlp.note` (`note_text`) |
| Fitbit heart rate, steps, sleep | `heart_rate_*`, `steps_intraday`, `sleep_*`, `activity_summary` |
| Apple HealthKit vitals and activity | `C_V9_R6_offcycle_healthkit` |
| Plasma, serum, DNA sample availability | `C_V9_R3_aou_biospecimen.aou_sample_biospecimen` |
| A variant's gene, rsID, ClinVar class, allele frequencies | The VAT: `gene_symbol`, `dbsnp_rsid`, `clinvar_classification`, `gvs_<ancestry>_af`, `gnomad_*_af` |
| Carriers of a variant | `cb_variant_to_person` |
| Genotypes for GWAS (pgen, bgen, bed, VCF, Hail) | `v9/wgs/short_read/snpindel/<subset>/` in the bucket |
| Ancestry predictions, PCs, relatedness | `v9/wgs/short_read/snpindel/aux/` in the bucket |
| Proteomics, RNA-seq, QTLs | `v9/multiomics/` in the bucket |

### The CDR dataset: `C2025Q4R6`

**EHR (OMOP clinical tables)**

| Table | Rows | Size | Holds |
|---|---|---|---|
| `person` | 747,029 | 0.17 GB | One row per participant |
| `observation_period` | 747,029 | 0.03 GB | EHR coverage window per participant |
| `visit_occurrence` / `visit_detail` | 85.3M / 48.1M | 9.3 / 4.9 GB | Visits |
| `condition_occurrence` | 175.1M | 16.4 GB | Diagnoses |
| `drug_exposure` | 173.1M | 18.8 GB | Medications |
| `procedure_occurrence` | 57.7M | 5.3 GB | Procedures |
| `measurement` | 720.2M | 89.4 GB | Labs, vitals, physical measurements |
| `observation` | 357.3M | 50.8 GB | Survey answers and other observations |
| `device_exposure` | 3.7M | 0.32 GB | Medical devices from the EHR |
| `specimen` | 44.8M | 5.7 GB | Specimens |
| `condition_era` / `drug_era` | 105.7M / 41.3M | 5.1 / 2.3 GB | Derived eras |
| `death` | 9,341 | <0.01 GB | OMOP death records |
| `fact_relationship` | 182.2M | 7.3 GB | Links between records |

> **Pitfall: Several OMOP tables exist but are empty**
> `care_site`, `location`, `provider`, `cost`, `payer_plan_period`, `dose_era`, `metadata`, `cdm_source`, `source_to_concept_map`, the `cohort*` tables and the `*_cost` tables all have 0 rows in v9.
> A query against them returns nothing, without an error, which looks the same as "no participant matched".
> `location` has `address_1`, `city`, `county` and `zip` columns from the OMOP schema, but no rows, and `person.location_id` is NULL for every participant.

**Vocabulary**: `concept` (7.4M rows), `concept_ancestor` (82.9M), `concept_relationship` (48.6M), `concept_synonym` (2.6M), `drug_strength` (3.0M), plus small lookups (`domain`, `vocabulary`, `concept_class`, `relationship`).

**AoU-specific tables**

| Table(s) | Rows | Size | Holds |
|---|---|---|---|
| `aou_death` | 14,435 | <0.01 GB | AoU's death table |
| `*_ext` (27 tables) | Match parent | 48.7 GB total | One per OMOP table, keyed by the parent's id (e.g. `measurement_id`) and carrying `src_id`, the record's source; some add fields (`person_ext`: sex at birth, self-reported category, state of residence). Populated ones match the parent's row count, except `observation_ext` (39 more rows than `observation`) |
| `survey_conduct` | 6.4M | 1.2 GB | Survey administrations |
| `ds_*` (34 tables) | | 472.8 GB total | Dataset Builder's copies of the clinical tables with concept names joined in and mostly uppercase column names (`PERSON_ID`), e.g. `ds_survey` (156.4M rows), `ds_measurement` (720.2M) |
| `cb_*` (11 tables) | | 523.7 GB total | Cohort Builder tables, e.g. `cb_search_all_events` (2.39B rows), `cb_review_all_events` (1.46B) |
| `cb_variant_to_person` | 1.6B | 20,484 GB | The only variant table in the CDR: `vid` to carriers (`person_ids`), clustered on `vid` |
| `delaydiscounting`, `emorecog`, `flanker`, `gradcpt` | 82,791-108,320 each | 0.3-3.3 GB | Cognitive task data in nested `metadata` and `outcomes` STRUCT columns; flat versions in `ds_*_metadata`, `ds_*_outcomes`, `ds_*_trial_data` |
| `zip3_ses_map` | 893 | <0.01 GB | Deprivation index, median income, poverty, education and insurance fractions, one row per 3-digit ZIP |
| `ds_zip_code_socioeconomic` | 714,777 | 0.06 GB | The same measures, one row per participant with a usable 3-digit ZIP |
| `_cdr_metadata` | 1 | | `ehr_cutoff_date` (2025-01-01), `vocabulary_version`, `cdr_generation_date` (2026-04-27) and other release metadata |

> **Pitfall: `death` and `aou_death` disagree**
> `aou_death` has 14,435 rows; OMOP `death` has 9,341.
> `aou_death` can hold several records per participant from different sources (`src_id`), and flags one with `primary_death_record`.
> Counting its rows counts records, not people: filter on `primary_death_record` or count distinct `person_id`.

> **Pitfall: Location is a 3-digit ZIP, and 32,136 participants have none**
> There is no address, latitude/longitude or 5-digit ZIP.
> All 746,980 answers to the survey's ZIP question are masked to 3 digits plus `**` (e.g. `100**`), and 32,136 of them are `000**`, which links to no area.
> That leaves 714,844 participants with a usable 3-digit ZIP; `ds_zip_code_socioeconomic` covers 714,777 of them.
> Join on the string form: `zip3_ses_map.zip3` is an integer that drops leading zeros (`6` for `006**`).

> **Pitfall: `cb_search_person`'s genomic flags are all 0 in v9**
> `has_whole_genome_variant`, `has_array_data`, `has_lr_whole_genome_variant` and `has_structural_variant_data` are 0 for all 747,029 participants, so a cohort filtered on them is empty.
> Use the index's `T_ENT_person.has_whole_genome_variant` instead (TRUE for 535,662 participants).

**Wearables (Fitbit)**

| Table | Rows | Size |
|---|---|---|
| `activity_summary` | 68.1M | 8.9 GB |
| `heart_rate_summary` | 205.3M | 18.6 GB |
| `heart_rate_intraday` | 118.7B | **6,813 GB** |
| `steps_intraday` | 93.8B | **6,169 GB** |
| `sleep_daily_summary` (+ `_30dayavg`, `_counts`) | 46.7M | 5.6 GB |
| `sleep_daily_summary_ext` (sleep-log level, not an extension table) | 43.6M | 5.5 GB |
| `sleep_level` / `sleep_level_short` | 950.2M / 552.8M | 74.9 / 47.5 GB |
| `device` | 23.6M | 3.0 GB |
| `wear_study` | 45,460 | <0.01 GB |

> **Pitfall: `device` is Fitbit devices, not medical devices**
> `device` (23.6M rows) holds wearable device records (`battery`, `device_type`, `last_sync_time`); its row count matches the search index's `T_ENT_wearableDevice` exactly.
> EHR medical devices are in `device_exposure` (3.7M rows).
> The names are close enough to pick the wrong one.

### Other BigQuery datasets in the CDR project

| Dataset | Tables | Holds |
|---|---|---|
| `C_V9_R6_offcycle_nlp` | `note` (9.6M), `note_nlp` (96.8M), `note_ext`, `note_nlp_ext` | Clinical notes and NLP-derived concepts |
| `C_V9_R6_offcycle_healthkit` | `activity_measurements` (2.93B, 349 GB), `vital_measurements` (1.08B, 108 GB), `physical_measurements` (1.7M), `device_and_source` (1.1M) | Apple HealthKit |
| `C_V9_R3_aou_biospecimen` | `aou_sample_biospecimen` (431,365) | Biospecimens |
| `variant_annotation_table_CDRv9` | `v9_vat_bigquery` (5.57B rows, 3,385 GB, 114 columns) | Variant annotation table, one row per variant and transcript, keyed by `vid`: gene, rsID, consequence, ClinVar, REVEL, SpliceAI, LoF, gnomAD and AoU per-ancestry frequencies. Also a file in the bucket (`snpindel/vat/`) |
| `C2025Q4R6_index_061026` | 340 tables named `T_*` | The search index behind the Workbench's cohort tools, e.g. `T_ENT_person` (747,029 rows), `T_ENT_variant` (1.54B), `T_ESA_variant_gene`, `T_ESA_variant_rs_number` |

> **Pitfall: Clinical notes are not in the CDR dataset**
> `C2025Q4R6` has no `note` table.
> Notes are in `C_V9_R6_offcycle_nlp`, so a search of the CDR alone wrongly suggests v9 has no notes.

The project also holds other CDR releases (`C2022Q4R13`, `C2024Q3R5_serology`, `C2024Q3R8`, `C2024Q3R9` and their `_index_*` datasets), v8 off-cycle datasets (`C_V8_R2_offcycle_etm`, `C_V8_R2_offcycle_mhwb`, `C_V8_R4_aou_biospecimen`), and `export_dataset_uscentral1`.

> **Pitfall: `prep_*` datasets are build staging, not the CDR**
> `prep_C2025Q4R6` sits next to `C2025Q4R6` and has similar table names, but it holds the build pipeline's staging tables.
> For example, `prep_concept` has 100 rows against `concept`'s 7.4M.
> Point `CDR` at `C2025Q4R6`, never at `prep_C2025Q4R6`.

> **Version note: the v8 variant attribute tables are gone**
> v9's CDR has `cb_variant_to_person` but no `cb_variant_attribute` or `cb_variant_attribute_genes`.
> Look for gene and rsID data in the VAT or in the index's `T_ESA_variant_*` tables instead.
> ClinVar is the VAT's `clinvar_classification`; no v9 table has `clinical_significance_string`.
> `cb_variant_to_person.person_ids` is typed `STRUCT<list ARRAY<STRUCT<element INT64>>>`, so carriers come out with `UNNEST(person_ids.list) AS p` and `p.element`, not `UNNEST(person_ids)`.

### Cloud Storage: `gs://vwb-aou-datasets-controlled/v9/`

The bucket's top level has `pooled/`, `v7/`, `v8/` and `v9/`.

```
v9/
├── known_issues/                 10 files (.txt, .tsv, .bed): read before using any data below
├── microarray/
│   ├── plink/                    .bed/.bim/.fam (231 GB)
│   ├── hail.mt/                  Hail MatrixTable
│   ├── idat/                     one CSV manifest, no data files
│   ├── vcf/                      one CSV manifest, no data files
│   └── aux/qc/
├── multiomics/
│   ├── proteomics/               npx/ (tsv, parquet, batch_normalized), olink_report/ (61 PDFs), pqtl/
│   └── rnaseq/                   rnaseqc2/, rsem/, eqtl/ (per ancestry), sqtl/ (leafcutter)
└── wgs/
    ├── cram/                     one CSV manifest, no CRAM files
    ├── long_read/                <center>/<ont|pacbio>/jointcall/GRCh38_noalt/, haplotagged_bams/, methylation/<sample>/
    └── short_read/
        ├── snpindel/
        │   ├── acaf_threshold/   each subset: bed/ bgen/ pgen/ plink_bed/ vcf/ multiMT/ splitMT/
        │   ├── exome/
        │   ├── clinvar/
        │   ├── aux/              ancestry/, admixture_estimates/, pca/<ancestry>/, relatedness/, phasing/,
        │   │                     pgx/, hla_variants/, mitochondria/, cmrg/, qc/, vat/
        │   ├── vat/              VAT as .tsv.gz (188 GB)
        │   └── vds/hail.vds/     Hail VariantDataset (reference_data/, variant_data/)
        └── structural_variants/  vcf/full/ (per chromosome), vcf/sites-only/, vcf/unrelated-sites-only/, aux/
```

Long-read joint calls are split by sequencing center (`BCM`, `BI`, `HA`, `JHU`, `UW`) and platform (`ont`, `pacbio`), each as per-chromosome gVCFs.
`methylation/` has one folder per participant (12,262+).

> **Pitfall: `cram/`, `microarray/idat/` and `microarray/vcf/` hold only a manifest**
> Each of these folders contains a single CSV that lists where the actual files are.
> Look up the paths you need in the CSV instead of listing the folder.

The three short-read subsets come in the same formats, at very different sizes:

| Format | `acaf_threshold` | `exome` | `clinvar` |
|---|---|---|---|
| `bgen/` | 6,862 GB | 423 GB | 34 GB |
| `pgen/` | 1,625 GB | 140 GB | 12.8 GB |
| `plink_bed/` | 17,628 GB | 6,337 GB | 302 GB |
| `vcf/` | 333+ shards with interval lists | 333+ shards | 333+ shards |

> **Note: Use `pgen/` instead of `plink_bed/` when you can**
> For the same subset, `pgen/` is 11x (`acaf_threshold`) to 45x (`exome`) smaller than `plink_bed/`.
> PLINK 2 reads it directly, so copying or streaming it takes a fraction of the time and disk.

## Usage

### List what is in any BigQuery dataset

```python
import os
from google.cloud import bigquery

CDR = os.environ.get("WORKSPACE_CDR")  # set by hand if None, e.g. "<cdr-project>.C2025Q4R6"
PROJECT = os.environ.get("GOOGLE_PROJECT")
bq = bigquery.Client(project=PROJECT)

datasets = sorted(d.dataset_id for d in bq.list_datasets(CDR.split(".")[0]))

tables = bq.query(f"""
    SELECT table_id AS table_name, row_count, size_bytes
    FROM `{CDR}.__TABLES__`""").to_dataframe()

columns = bq.query(f"""
    SELECT table_name, column_name, data_type
    FROM `{CDR}.INFORMATION_SCHEMA.COLUMNS`""").to_dataframe()

columns[columns["column_name"].str.contains("zip")]  # which tables have a ZIP column?
```

Replace `CDR` with any `project.dataset` from `datasets` to map the other datasets the same way.

### Browse a bucket folder

```python
from google.cloud import storage

gcs = storage.Client(project=PROJECT)
bucket = gcs.bucket("vwb-aou-datasets-controlled", user_project=PROJECT)

it = gcs.list_blobs(bucket, prefix="v9/wgs/short_read/snpindel/", delimiter="/")
files = list(it)          # files directly in this folder
print(sorted(it.prefixes))  # its subfolders
```

`user_project` bills the listing to your workspace project.
Walk one level at a time: folders like `methylation/` and the Hail `index/` folders hold more than 100,000 subfolders.

## Troubleshooting

- If you see `Not found: Table <project>:C2025Q4R6.cb_variant_attribute` -> that table does not exist in v9; use the VAT or the index's `T_ESA_variant_*` tables.
- If you see `Not found: Table <project>:C2025Q4R6.note` -> notes are in `C_V9_R6_offcycle_nlp`.
- If `CDR.split` fails with `'NoneType' object has no attribute 'split'` -> `WORKSPACE_CDR` is not set in this environment; set `CDR` by hand.
- If listing the bucket returns `403 Forbidden` -> this environment cannot reach the controlled bucket; see [Choose the right compute environment](choose-compute-environment.md).

## See also

- [Choose the right compute environment](choose-compute-environment.md) - which environment can reach the bucket
- [Discover genomics tables](../genomics/discover-genomics-tables.md) - genomics schemas with `INFORMATION_SCHEMA`
- [Query carrier status](../genomics/query-carrier-status.md) - using `cb_variant_to_person`

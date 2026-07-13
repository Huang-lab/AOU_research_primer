# Glossary

Terms defined once here, linked from every Reference and Guide page that uses
them. If you find yourself re-explaining one of these inline, link here instead.

---

**CDR (Curated Data Repository)**
The versioned BigQuery dataset containing all *All of Us* research data. Each
release is identified by a version string (e.g. `C2024Q3R9`). Access it via
the `WORKSPACE_CDR` environment variable on the Researcher Workbench:
`os.environ["WORKSPACE_CDR"]`.

**Registered Tier**
The default data access level. Contains demographics, conditions, procedures,
measurements, drug exposures, and survey data. Does not include genomics or
unshifted dates (dates are shifted by a random offset per participant).

**Controlled Tier**
Elevated access requiring additional IRB approval. Adds genomic data
(short-read WGS), unshifted dates, and geographic data below state level.

**Index date**
The reference date for a participant in a study — typically the date of
first diagnosis for cases. All temporal features (labs, medications,
conditions) are anchored relative to this date to prevent temporal leakage.

**Pseudo-index date**
A synthetic index date assigned to controls who lack the defining event.
Common approaches: random date within the control's EHR span, or matched to
the case's index date in a paired design. Required for any temporal analysis
involving controls.

**Carrier**
A participant who carries at least one variant in a specified gene or gene
panel, as determined from short-read WGS data in the Controlled Tier.

**P/LP (Pathogenic / Likely Pathogenic)**
ClinVar classification indicating a variant is disease-causing or probably
disease-causing. The standard clinical-significance filter for germline
predisposition analyses.

**FDR / q-value**
False Discovery Rate correction for multiple hypothesis testing. The q-value
is the FDR-adjusted p-value. Use Benjamini-Hochberg (`statsmodels.stats.
multitest.multipletests(method='fdr_bh')`) as the default correction.

**Dry run**
A BigQuery feature that estimates bytes processed without executing the query
or incurring cost. Call `client.query(sql, job_config=QueryJobConfig
(dry_run=True))` and read `job.total_bytes_processed`.

**Bytes billed**
The actual storage scanned by a BigQuery query, rounded up to the nearest
10 MB minimum. AoU Workbench credits are consumed based on bytes billed, not
bytes returned.

**OMOP CDM (Common Data Model)**
The data model underlying AoU's CDR. Tables like `condition_occurrence`,
`measurement`, `drug_exposure`, and `person` follow OMOP conventions but with
AoU-specific extensions and naming in the `cb_` (Cohort Builder) tables.

**`cb_` tables vs. OMOP tables**
AoU provides both standard OMOP tables (e.g. `condition_occurrence`) and
Cohort Builder tables (e.g. `cb_condition`). The `cb_` tables are
pre-joined/denormalized for common queries. Reference pages specify which
table family they use.

**concept_id**
The OMOP integer identifier for a clinical concept (condition, drug, lab
test, etc.). Mapped from source codes (ICD-10, LOINC, RxNorm) via the
`concept` and `concept_relationship` tables.

**person_id**
The unique participant identifier in AoU. All clinical tables join on
`person_id`. Always cast as INT64 in BigQuery queries.

**observation_period**
The OMOP table recording each participant's span of data availability.
`observation_period_start_date` and `observation_period_end_date` define
when AoU has records for a participant — not necessarily when they first
entered the healthcare system.

**visit_occurrence_id**
Foreign key linking clinical events (conditions, measurements, drugs) to a
specific visit/encounter. Often NULL in AoU data — inner joins on this
column silently drop unlinked events.

**type_concept_id**
A family of columns (`condition_type_concept_id`,
`measurement_type_concept_id`, etc.) indicating the provenance of a
record: EHR, self-reported survey, physical measurement at enrollment,
etc. Critical for distinguishing data sources.

**ds_survey**
A denormalized survey table available in newer CDR versions. Provides
pre-joined survey questions and answers, simpler to query than the raw
`observation` table for survey data.

**Quasi-separation / complete separation**
A logistic regression failure mode where a predictor perfectly (or nearly
perfectly) predicts the outcome — common with rare variants where all
carriers are cases. Produces inflated odds ratios with enormous confidence
intervals. Use Firth's penalized regression when carrier counts are low.

**Temporal leakage**
Information from after the prediction point (index date) contaminating
features that should only use pre-index data. Produces models that look
accurate in development but fail on prospective data.

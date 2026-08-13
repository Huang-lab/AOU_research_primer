# AoU Research Primer — Project Context

## What this is
Task-based reference docs for querying the All of Us Researcher Workbench CDR.
27 reference pages, 4 guides, ~55 pitfall warnings. Built with mkdocs-material.

- **Live site**: https://huang-lab.github.io/AOU_research_primer/
- **Repo**: https://github.com/Huang-lab/AOU_research_primer
- **Audience**: Researchers fluent in SQL and pandas/R

## Repo structure
```
docs/                          # mkdocs source (admonition syntax)
├── reference/                 # 27 task pages grouped by domain
│   ├── cohort-definition/
│   ├── demographics-ancestry/
│   ├── conditions-phenotypes/
│   ├── labs-measurements/
│   ├── medications/
│   ├── temporal-windowing/
│   ├── genomics/
│   ├── cost-awareness/
│   ├── surveys/
│   ├── procedures/
│   ├── visits/
│   ├── data-quality/
│   ├── statistical-modeling/
│   └── environment/
├── guides/                    # 4 end-to-end workflow guides
├── pitfall-index.md
├── glossary.md
├── TEMPLATE.md
└── contributing.md
mkdocs.yml                     # nav, theme config
```

Root-level `.md` files are GitHub-rendered copies (blockquote callouts).
`docs/` copies use mkdocs admonition syntax (`!!! pitfall "title"`).

## Page template convention
Every reference page follows `docs/TEMPLATE.md`:
- When to use / Prerequisites / Parameters
- Step-by-step code with inline Pitfall/Note/Version note callouts
- Variations section for common alternatives
- Troubleshooting table
- Links to related pages

## Current state (as of Aug 2026)
- Validated against Pan-Cancer Germline Predisposition Project cookbook (CDR v8)
- 4 corrections applied (ARRAY person_ids, column renames, ClinVar compound strings, ancestry coverage)
- 18 new content items integrated from cookbook
- Site deployed via `mkdocs gh-deploy`

---

## Active collaboration: Asgari Lab (Mount Sinai)

### Source repo
https://github.com/asgarilab/SDoH-GeneticRisk-Biobank-MCA

**Paper**: "Integrating social determinants of health and genetic risk in disease risk models" — Biji, Ferar, Pejaver, Kenny, Liu, Asgari (AJHG 2026)

**Permission status**: Huang Lab has confirmed collaboration. Asgari Lab has agreed to adaptation of their code. License to be added to their repo later.

### Their 10 notebooks (all R, CDR v7)
| Notebook | Topic | Integration priority |
|----------|-------|---------------------|
| a | Demographics + PhecodeX phenotyping from ICD codes | HIGH |
| b | Plink array QC metrics (MAF, HWE, het, missingness) | MEDIUM |
| c | QC metric visualization | MEDIUM |
| d | Array QC filtering (geno≤5%, maf≥5%, HWE>1e-12, mind≤10%) | MEDIUM |
| e | PCA for GWAS (plink2 EUR, PCair non-EUR) | MEDIUM |
| f | Sparse GRM construction (SAIGE createSparseGRM.R) | MEDIUM |
| g | Survey extraction (136 questions, 4 modules) + MCA | LOW (research-specific) |
| h | PGS calibration + elastic net regression + SHAP | HIGH |
| i | GWAS (SAIGE Step 1+2) + METAL meta-analysis | HIGH |
| j | GWAS plots (Manhattan, QQ, Z-score comparison) | HIGH |

### What to do next
Translate their R notebooks to Python, validate on AoU Workbench (CDR v8), and write new reference pages. Each page should have both R and Python code.

**Key adaptations needed when translating:**
- CDR v7 → v8: paths, column names, GCS bucket (`fc-aou-datasets-controlled` → `vwb-aou-datasets-controlled`)
- R BigQuery (`bigrquery`) → Python (`google.cloud.bigquery` or pandas-gbq)
- R data wrangling (`tidyverse`) → Python (`pandas`)
- R plotting (`ggplot2`) → Python (`matplotlib`/`seaborn`)
- R genetics (`ade4`, PCair) → Python equivalents where they exist
- plink/SAIGE/METAL CLI commands stay the same (language-agnostic)
- Cite Biji et al. AJHG 2026 on every page derived from their work

### New reference pages to create (proposed)
1. **GWAS pipeline with SAIGE** (from notebooks i, j) — biggest gap
2. **PhecodeX phenotyping from ICD codes** (from notebook a)
3. **Polygenic score construction** (from notebook h)
4. **Microarray QC pipeline** (from notebooks b, c, d)
5. **GRM construction for mixed models** (from notebook f)
6. **Ancestry-aware PCA with PCair** (from notebook e)

### Pages NOT in scope
- MCA (Multiple Correspondence Analysis) — unique to their SDoH research, not general-purpose
- Their specific regression models (elastic net + SHAP for SDoH) — too study-specific

## Build & deploy
```bash
# Local preview
mkdocs serve

# Deploy to GitHub Pages
mkdocs gh-deploy
```

## Style rules
- No lorem ipsum — real AoU examples only
- Pitfall callouts for anything that silently produces wrong answers
- Version notes for CDR-version-dependent behavior
- Parameters section with type, default, and "why this value" for every magic number
- Troubleshooting table at the bottom of each page

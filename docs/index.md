# All of Us Research Primer

Task-based reference for querying the All of Us Researcher Workbench CDR.
Each page answers one "how do I do X" question with exact code, parameters, and inline **Pitfall** warnings for silent-wrong-answer traps.

Audience: fluent in SQL and pandas. No language basics here.

**Callout key:**

- **Pitfall**: produces a wrong answer silently; placed at the point of danger.
- **Note**: a clarifying aside.
- **Version note**: behavior that differs by CDR release.

## Find your task

<div class="grid cards" markdown>

-   :material-compass-outline:{ .lg .middle } __Start here__

    ---

    - [Choose the right compute environment](reference/environment/choose-compute-environment.md)

-   :material-account-group-outline:{ .lg .middle } __Build a cohort__

    ---

    - [Define a case cohort by condition codes](reference/cohort-definition/define-case-cohort-by-condition.md)
    - [Build matched controls](reference/cohort-definition/build-matched-controls.md)
    - [Exclude participants by condition history](reference/cohort-definition/exclude-by-condition-history.md)
    - [Discover OMOP concepts](reference/cohort-definition/discover-omop-concepts.md)
    - [Extract demographic features](reference/demographics-ancestry/extract-demographic-features.md)
    - [Compute genetic ancestry PCs](reference/demographics-ancestry/compute-ancestry-pcs.md)

-   :material-stethoscope:{ .lg .middle } __Clinical data__

    ---

    - [Query condition occurrence](reference/conditions-phenotypes/query-condition-occurrence.md)
    - [Build a multi-code phenotype](reference/conditions-phenotypes/build-multi-code-phenotype.md)
    - [Query lab measurements](reference/labs-measurements/query-lab-measurements.md)
    - [Query drug exposures](reference/medications/query-drug-exposures.md)
    - [Query procedure occurrence](reference/procedures/query-procedure-occurrence.md)
    - [Query visit occurrence](reference/visits/query-visit-occurrence.md)
    - [Query survey responses](reference/surveys/query-survey-responses.md)

-   :material-dna:{ .lg .middle } __Genomics__

    ---

    - [Query carrier status](reference/genomics/query-carrier-status.md)
    - [Filter variants to ClinVar P/LP](reference/genomics/filter-clinvar-plp.md)
    - [Discover genomics table schemas](reference/genomics/discover-genomics-tables.md)
    - [Integrate AlphaMissense scores](reference/genomics/integrate-alphamissense.md)

-   :material-timeline-clock-outline:{ .lg .middle } __Time windows and data quality__

    ---

    - [Apply index-date windowing](reference/temporal-windowing/apply-index-date-window.md)
    - [Audit for temporal leakage](reference/temporal-windowing/audit-temporal-leakage.md)
    - [Filter by observation period](reference/data-quality/filter-by-observation-period.md)
    - [Distinguish EHR from survey sources](reference/data-quality/distinguish-ehr-survey-sources.md)

-   :material-chart-bell-curve-cumulative:{ .lg .middle } __Statistical modeling__

    ---

    - [Build a SHAP-ready feature matrix](reference/statistical-modeling/build-shap-feature-matrix.md)
    - [Run PC-adjusted logistic regression](reference/statistical-modeling/pc-adjusted-regression.md)
    - [Run propensity score matching](reference/statistical-modeling/propensity-score-matching.md)

-   :material-cash-multiple:{ .lg .middle } __Cost awareness__

    ---

    - [Optimize compute environment costs](reference/cost-awareness/optimize-compute-costs.md)
    - [Dry-run a query to estimate cost](reference/cost-awareness/dry-run-query.md)
    - [Cap query cost before execution](reference/cost-awareness/cap-query-cost.md)

-   :material-map-marker-path:{ .lg .middle } __End-to-end guides__

    ---

    - [Build a genomic case-control cohort](guides/build-genomic-case-control-cohort.md)
    - [Add a windowed lab feature](guides/add-windowed-lab-feature.md)
    - [Estimate and cap query cost](guides/estimate-and-cap-query-cost.md)
    - [Case/control pairs to FDR results](guides/case-control-to-fdr-results.md)

</div>

## Before you submit

<div class="grid cards" markdown>

-   :material-alert-octagon-outline:{ .lg .middle } __[Pitfall Index](pitfall-index.md)__

    ---

    Every Pitfall callout, grouped by failure mode: missing denominators, temporal leakage, ancestry confounding, vocabulary errors, unit errors, provenance mixing and cost traps.
    Use it as a pre-submission checklist.

-   :material-book-alphabet:{ .lg .middle } __[Glossary](glossary.md)__

    ---

    CDR, Registered and Controlled Tier, index date, carrier, P/LP, FDR, dry run, OMOP CDM, concept_id and more.

</div>

## Contributing

Technical contributions must be battle tested in the All of Us Researcher Workbench before submission.
See the [contributing guide](contributing.md) for validation evidence, privacy requirements, content placement, and the pull request checklist.
Every Reference page follows the [page template](TEMPLATE.md).

---

*28 Reference pages · 4 Guides · Validated against Pan-Cancer Germline Predisposition Project cookbook (CDR v8, August 2026).*

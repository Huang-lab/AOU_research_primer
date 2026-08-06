# Contributing to the All of Us Research Primer

Thank you for helping make this primer more reliable and useful.

## Core requirement

New or changed technical guidance must be battle tested in the All of Us Researcher Workbench before it is submitted.
Do not contribute code or claims that are only theoretical, copied from generic OMOP documentation, or generated without being run in the All of Us Researcher Workbench.

Purely editorial changes, such as fixing spelling or a broken link, do not require a Workbench run if they do not change technical meaning.

## What battle tested means

Run every applicable code example from start to finish in the All of Us Researcher Workbench against an identified CDR release.
Confirm all of the following before opening a pull request:

- The referenced datasets, tables, columns, concepts, and environment variables exist in the stated CDR release.
- The code runs without relying on undeclared state from another notebook cell.
- The output schema, row grain, data types, null behavior, and denominator match the documented intent.
- Joins do not introduce unexpected duplication or silently remove eligible participants.
- Date windows, provenance filters, units, vocabulary mappings, and zero-filled comparison groups are checked when applicable.
- At least one relevant edge case is exercised, such as no matches, missing values, duplicate events, or participants without the target event.
- BigQuery examples are dry-run or otherwise reviewed for bytes processed, and cost caps are used where practical.
- Any limitations or CDR-specific behavior discovered during validation are documented next to the example.

## Protect participant data

Never include participant-level data, identifiers, row-level query output, access tokens, workspace identifiers, or screenshots containing protected information.
Use synthetic or clearly redacted examples for expected output.
Follow the All of Us Data User Code of Conduct and the access rules for the data tier used during validation.

## Choose the right content type

- Add a focused task to `docs/reference/` using [`docs/TEMPLATE.md`](TEMPLATE.md).
- Add an end-to-end workflow that connects existing reference tasks to `docs/guides/`.
- Add a short definition to `docs/glossary.md`.
- Add a recurring silent-wrong-answer risk as a **Pitfall** callout and include it in `docs/pitfall-index.md`.
- Update `mkdocs.yml` when adding a page so readers can find it in the site navigation.
- Keep any corresponding root-level documentation copy synchronized with the version under `docs/`.

Prefer narrow, reproducible examples over broad tutorials.
State assumptions explicitly and explain how a reader can tell whether the result is correct.

## Record validation evidence

Include a validation record in the pull request description.
Do not include a workspace name or other sensitive metadata.

```text
Workbench validation
- CDR release:
- Data tier: Registered or Controlled
- Validation date:
- Example run from start to finish: yes or no
- Output checks performed:
- Edge cases tested:
- Query cost check:
- Known limitations:
```

If the change affects multiple examples, identify which examples were run.
A reviewer must be able to distinguish directly observed behavior from assumptions or interpretation.

## Local documentation check

Use a temporary environment and run a strict documentation build before submitting:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-docs.txt
mkdocs build --strict
```

Review the rendered page for navigation, formatting, code wrapping, tables, admonitions, and links.

## Pull request checklist

- [ ] Every technical addition or behavior change was run in the All of Us Researcher Workbench.
- [ ] The pull request includes the validation record above.
- [ ] No protected or participant-level data is included.
- [ ] CDR release and data tier dependencies are stated.
- [ ] Assumptions, edge cases, limitations, and cost considerations are documented.
- [ ] New pages follow the repository template and appear in `mkdocs.yml`.
- [ ] Corresponding root and `docs/` copies are synchronized where both exist.
- [ ] `mkdocs build --strict` succeeds.

Submissions that add untested technical guidance should remain drafts until Workbench validation is complete.

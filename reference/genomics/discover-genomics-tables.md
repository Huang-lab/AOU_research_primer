# Discover genomics table schemas

Use `INFORMATION_SCHEMA` to inspect current column names, types, and available tables in the genomics portion of the CDR, before writing a new query.

## Prerequisites

- Any workspace with CDR access (Registered or Controlled)
- Python 3, `google-cloud-bigquery`

**Tier:** Registered (for `INFORMATION_SCHEMA` queries against the CDR dataset)
**CDR versions:** All

## Reference

AoU genomics tables have changed across CDR releases: columns have been renamed, new tables have been added, and join keys have been restructured. Code written against one CDR version may fail or silently return wrong results against another.

`INFORMATION_SCHEMA.COLUMNS` and `INFORMATION_SCHEMA.TABLES` are BigQuery system views that describe the schema of any dataset you have access to. They are the authoritative source for "what columns exist right now in this CDR?"

Key system views:

| View | What it shows |
|---|---|
| `INFORMATION_SCHEMA.TABLES` | All tables in the dataset: name, type, creation time |
| `INFORMATION_SCHEMA.COLUMNS` | All columns in all tables: name, data type, ordinal position, nullability |

## Usage

### Step 1: List all genomics-related tables

```python
import os
from google.cloud import bigquery

client = bigquery.Client()
CDR = os.environ["WORKSPACE_CDR"]

# Extract project.dataset from CDR path
# CDR looks like "project.dataset" or "project.dataset"
tables_sql = f"""
SELECT table_name, table_type, creation_time
FROM `{CDR}.INFORMATION_SCHEMA.TABLES`
WHERE table_name LIKE '%variant%'
   OR table_name LIKE '%genom%'
   OR table_name LIKE '%wgs%'
   OR table_name LIKE '%cb_variant%'
ORDER BY table_name
"""
tables = client.query(tables_sql).to_dataframe()
print(tables.to_string(index=False))
```

> **Pitfall: assuming column names from old code or documentation.** Genomics table schemas have changed across CDR releases. A query that worked in v7 may reference a column that was renamed or removed in v8. Always run the `INFORMATION_SCHEMA` query below before writing a new genomics query -- especially after a CDR upgrade.

### Step 2: Get columns for a specific table

```python
# Inspect the schema of cb_variant_to_person
columns_sql = f"""
SELECT
    column_name,
    data_type,
    is_nullable,
    ordinal_position
FROM `{CDR}.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'cb_variant_to_person'
ORDER BY ordinal_position
"""
cols = client.query(columns_sql).to_dataframe()
print(cols.to_string(index=False))
```

### Step 3: Compare schemas across genomics tables

To understand the join paths between tables, inspect shared column names:

```python
# Find columns shared between variant tables
shared_cols_sql = f"""
SELECT
    column_name,
    STRING_AGG(table_name, ', ') AS found_in_tables,
    COUNT(DISTINCT table_name) AS n_tables
FROM `{CDR}.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name LIKE '%variant%'
GROUP BY column_name
HAVING COUNT(DISTINCT table_name) > 1
ORDER BY n_tables DESC, column_name
"""
shared = client.query(shared_cols_sql).to_dataframe()
print("Columns shared across variant tables:")
print(shared.to_string(index=False))
```

### Step 4: Quick schema dump for all variant tables

```python
all_variant_cols_sql = f"""
SELECT
    table_name,
    column_name,
    data_type
FROM `{CDR}.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name LIKE '%variant%'
ORDER BY table_name, ordinal_position
"""
all_cols = client.query(all_variant_cols_sql).to_dataframe()

# Print grouped by table
for table, group in all_cols.groupby("table_name"):
    print(f"\n--- {table} ---")
    for _, row in group.iterrows():
        print(f"  {row['column_name']:30s} {row['data_type']}")
```

## Variations

### Check which CDR version you are running against

The CDR path itself encodes the version. Extract and display it:

```python
print(f"CDR path: {CDR}")

# The dataset name typically contains the version, e.g.,
# "fc-aou-cdr-prod.C2022Q4R9" or similar
dataset_parts = CDR.split(".")
if len(dataset_parts) == 2:
    project, dataset = dataset_parts
    print(f"Project: {project}")
    print(f"Dataset (CDR version): {dataset}")
```

For a programmatic check, query the CDR metadata if available:

```python
metadata_sql = f"""
SELECT table_name
FROM `{CDR}.INFORMATION_SCHEMA.TABLES`
WHERE table_name LIKE '%metadata%' OR table_name LIKE '%cdr_version%'
"""
meta = client.query(metadata_sql).to_dataframe()
if len(meta) > 0:
    print("Metadata tables found:")
    print(meta.to_string(index=False))
```

### Search for a specific column name across all tables

When you have code referencing a column and need to find which table it belongs to:

```python
# Find which tables contain a 'vid' column
find_col_sql = f"""
SELECT table_name, column_name, data_type
FROM `{CDR}.INFORMATION_SCHEMA.COLUMNS`
WHERE column_name = 'vid'
ORDER BY table_name
"""
found = client.query(find_col_sql).to_dataframe()
print(found.to_string(index=False))
```

### List all tables with row counts

Get an overview of table sizes to understand query cost implications:

```python
# Approximate row counts from table metadata
size_sql = f"""
SELECT
    t.table_name,
    t.table_type,
    p.total_rows,
    p.total_logical_bytes
FROM `{CDR}.INFORMATION_SCHEMA.TABLES` t
LEFT JOIN `{CDR}.INFORMATION_SCHEMA.TABLE_STORAGE` p
    ON t.table_name = p.table_name
WHERE t.table_name LIKE '%variant%'
ORDER BY p.total_logical_bytes DESC NULLS LAST
"""
sizes = client.query(size_sql).to_dataframe()
# Convert bytes to GB for readability
sizes["size_gb"] = sizes["total_logical_bytes"] / (1024**3)
print(sizes[["table_name", "total_rows", "size_gb"]].to_string(index=False))
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `INFORMATION_SCHEMA` query returns empty results | The `table_name LIKE` pattern does not match any tables. Try `LIKE '%'` to list all tables, then refine. |
| `Not found: Dataset` error | The `CDR` environment variable may not be set, or the dataset path is malformed. Verify `echo $WORKSPACE_CDR` in a terminal cell. |
| `Access Denied` on `INFORMATION_SCHEMA` | Your workspace may not have read access to the controlled-tier CDR. Verify workspace tier in the Researcher Workbench UI. |

## Cost note

`INFORMATION_SCHEMA` queries are **free**. They do not scan table data and are not billed. Run them as often as needed.

## See also

- [Query carrier status for a gene panel](query-carrier-status.md) -- uses the tables discovered here
- [Filter variants to ClinVar Pathogenic/Likely Pathogenic](filter-clinvar-plp.md) -- uses `cb_variant_attribute` columns discovered here
- [Dry-run a query to estimate cost](../cost-awareness/dry-run-query.md) -- estimate cost after discovering the tables you need

# Link area-level SDOH measures by 3-digit ZIP

`participants -> ZIP3 -> area-level measures (poverty, income, education, insurance, deprivation)`

Attach neighborhood socioeconomic measures to participants through their 3-digit ZIP code, the most detailed location available to researchers.

**You'll need:** a Controlled Tier workspace

**Tier:** Controlled

**CDR versions validated:** C2025Q4R6 (v9)

---

## Reference

- **Location available:** 3-digit ZIP only. Participants report their home ZIP code in a survey (`observation_source_value = 'StreetAddress_PIIZIP'`), stored masked to 3 digits plus `**` (e.g. `100**`). There is no street address, latitude/longitude or 5-digit ZIP; the OMOP `location` table has address columns but no rows.
- **Tables:**

| Table | Rows (v9) | What it holds |
|---|---|---|
| `ds_zip_code_socioeconomic` | 714,777 | One row per participant with a usable ZIP3: `PERSON_ID`, `ZIP3_AS_STRING` and the area measures, already linked |
| `zip3_ses_map` | 893 | One row per ZIP3: `zip3` (integer), `zip3_as_string` and the same measures |
| `observation` | 746,980 ZIP answers | The survey answer itself, with the date it was recorded |

- **Measures:** `fraction_poverty`, `fraction_no_health_ins`, `fraction_high_school_edu`, `fraction_assisted_income`, `fraction_vacant_housing`, `median_income`, `deprivation_index`, plus `acs`, the ACS period they come from.
- **Returns:** one row per linked participant with that participant's area values.
- **Behavior notes:** every participant gets the same ACS period, whenever their ZIP code was recorded.

!!! version-note "Version note: one ACS period per CDR"
    In v9 every row has `acs = 2017`, so all participants get the same period's values.
    Check `acs` in your CDR before comparing releases, and use Variation 2 to match each participant to the period of the year their ZIP code was recorded.

!!! pitfall "These are area measures, not participant characteristics"
    A participant linked to 15% poverty lives in an area where 15% of residents are below the poverty line; the participant may or may not be.
    Treating area values as individual traits is the ecological fallacy.
    Use them as neighborhood context, and use individual survey answers for the participant's own income or education.

## Usage

### Basic usage: the pre-linked table

```python
import os
from google.cloud import bigquery

CDR = os.environ["WORKSPACE_CDR"]  # e.g. "<cdr-project>.C2025Q4R6"; set by hand if not defined
client = bigquery.Client()

ses = client.query(f"""
SELECT * FROM `{CDR}.ds_zip_code_socioeconomic`
""").to_dataframe()
ses.columns = ses.columns.str.lower()
```

!!! pitfall "The `fraction_` columns are percentages"
    Despite their names, all five `fraction_` columns hold percentages: the median ZIP3 has `fraction_poverty` near 14.8, not 0.148, and `fraction_assisted_income` near 13.4.
    Multiplying by 100 again, or comparing with a 0-1 fraction from another source, silently mis-scales every value.

!!! pitfall "32,136 participants have no usable ZIP3"
    Their ZIP code is masked to `000**`, which identifies no area, so they are absent from `ds_zip_code_socioeconomic`.
    A further 67 participants in ZIP3s 008 (U.S. Virgin Islands) and 969 (Guam) are absent because those ZIP3s have no area values.
    An analysis restricted to linked participants drops these 32,203 people; report it, and check whether they differ from the rest of the cohort.

### Variation 1: link it yourself from the survey answer

Use this when you also need the year the ZIP code was recorded, or want to apply your own exclusions.

```python
zips = client.query(f"""
SELECT person_id, value_as_string AS zip_masked, observation_date
FROM `{CDR}.observation`
WHERE observation_source_value = 'StreetAddress_PIIZIP'
""").to_dataframe()
zips["zip3"] = zips["zip_masked"].str[:3]

area = client.query(f"SELECT * FROM `{CDR}.zip3_ses_map`").to_dataframe()
area["zip3"] = area["zip3_as_string"].str[:3]

linked = zips[zips["zip3"] != "000"].merge(area, on="zip3", how="inner")
```

!!! pitfall "Join on the text ZIP3, never the integer `zip3` column"
    `zip3_ses_map.zip3` is an integer, so `006` is stored as `6`.
    Converting it to text gives `6`, not `006`, so a join to the masked survey answer silently drops the 82 ZIP3s that start with 0 (New England, New Jersey, Puerto Rico): 69,948 participants in v9.
    Take the first three characters of `zip3_as_string`, as above.

### Variation 2: link your own ZIP3 table, matched by year

Use this for measures `zip3_ses_map` does not have, or to match each participant to the ACS period of the year their ZIP code was recorded.
It builds on `zips` from Variation 1 and expects one CSV per ACS period, each with a text `ZIP3` column and a `VINTAGE` column (the ACS 5-year period's end year).
Participants whose ZIP code was recorded in a year your table does not cover drop out; in v9 all were recorded between 2017 and 2024.

```python
import glob
import pandas as pd

own = pd.concat([pd.read_csv(f, dtype={"ZIP3": str}) for f in sorted(glob.glob("zip3/zip3_20*.csv"))])
assert own["ZIP3"].str.len().eq(3).all(), "ZIP3 lost its leading zeros"

zips["vintage"] = pd.to_datetime(zips["observation_date"]).dt.year
linked_own = zips.merge(own, left_on=["zip3", "vintage"], right_on=["ZIP3", "VINTAGE"], how="inner")
```

!!! pitfall "Spreadsheet software strips leading zeros"
    Opening a ZIP3 CSV in Excel and saving it turns `006` into `6`, and the merge then silently loses those ZIP3s.
    Read the file with `dtype={"ZIP3": str}` and keep the assertion above, which stops the run instead.

## Troubleshooting

- If you see `You are trying to merge on object and Int64 columns` -> one side's ZIP3 or year is text and the other is a number; convert ZIP3 to 3-character text and the year to an integer on both sides.
- If the merge returns far fewer rows than `ds_zip_code_socioeconomic` (714,777 in v9) -> ZIP3 lost its leading zeros on one side; compare `zip3.str.len()` on both tables.
- If `os.environ["WORKSPACE_CDR"]` raises `KeyError` -> the variable is not set in this environment; set `CDR` to your CDR project and dataset by hand.

## Cost note

`ds_zip_code_socioeconomic` and `zip3_ses_map` are small (0.06 GB and under 0.01 GB), so the basic usage costs a fraction of a cent.
Variation 1 reads about 13.6 GB of `observation`, about $0.08 at $6.25 per TiB; dry-run it first if your query differs (see [Dry-run a query](../cost-awareness/dry-run-query.md)).

## See also

- [Find where data lives in CDR v9](../environment/find-where-data-lives.md) - every table holding location and socioeconomic data
- [Extract demographic features](extract-demographic-features.md) - individual sex, race, ethnicity and age
- [Query survey responses](../surveys/query-survey-responses.md) - the participant's own income and education answers

# Starbuck validation: 2026-10-04T08:51:59+01:00

Starbuck 0.1.0; mode: replay of 2026-10-04.json.gz (recorded 2026-10-04T08:50:52+01:00); entries: 115; not checked: 0.

## Overall

- Sensitivity, strict (expected verdict and code): 64/65 = 98.5% (91.8 to 99.7)
- Sensitivity, flagged (any result other than Pass): 65/65 = 100.0% (94.4 to 100.0)
- Specificity (clean entries with Pass): 50/50 = 100.0% (92.9 to 100.0)

## Per error type

| Error type | Entries | Checked | Strict | Flagged |
|---|---|---|---|---|
| retracted | 5 | 5 | 5/5 = 100.0% (56.6 to 100.0) | 5/5 = 100.0% (56.6 to 100.0) |
| expression_of_concern | 4 | 4 | 4/4 = 100.0% (51.0 to 100.0) | 4/4 = 100.0% (51.0 to 100.0) |
| corrected | 12 | 12 | 12/12 = 100.0% (75.8 to 100.0) | 12/12 = 100.0% (75.8 to 100.0) |
| preprint_published | 5 | 5 | 5/5 = 100.0% (56.6 to 100.0) | 5/5 = 100.0% (56.6 to 100.0) |
| fabricated_doi | 4 | 4 | 4/4 = 100.0% (51.0 to 100.0) | 4/4 = 100.0% (51.0 to 100.0) |
| doi_of_other_paper | 4 | 4 | 4/4 = 100.0% (51.0 to 100.0) | 4/4 = 100.0% (51.0 to 100.0) |
| pmid_of_other_paper | 4 | 4 | 4/4 = 100.0% (51.0 to 100.0) | 4/4 = 100.0% (51.0 to 100.0) |
| doi_pmid_disagree | 4 | 4 | 4/4 = 100.0% (51.0 to 100.0) | 4/4 = 100.0% (51.0 to 100.0) |
| wrong_year | 4 | 4 | 4/4 = 100.0% (51.0 to 100.0) | 4/4 = 100.0% (51.0 to 100.0) |
| wrong_first_author | 4 | 4 | 4/4 = 100.0% (51.0 to 100.0) | 4/4 = 100.0% (51.0 to 100.0) |
| author_order | 4 | 4 | 4/4 = 100.0% (51.0 to 100.0) | 4/4 = 100.0% (51.0 to 100.0) |
| no_identifier_real | 4 | 4 | 3/4 = 75.0% (30.1 to 95.4) | 4/4 = 100.0% (51.0 to 100.0) |
| no_identifier_invented | 4 | 4 | 4/4 = 100.0% (51.0 to 100.0) | 4/4 = 100.0% (51.0 to 100.0) |
| dead_web_page | 3 | 3 | 3/3 = 100.0% (43.9 to 100.0) | 3/3 = 100.0% (43.9 to 100.0) |
| none (clean): Pass | 50 | 50 | 50/50 = 100.0% (92.9 to 100.0) | |

## Entries that differ from the truth table

| Key | Error type | Expected | Starbuck | Codes |
|---|---|---|---|---|
| castro2018-noid | no_identifier_real | note add_identifier | warn | not_found |

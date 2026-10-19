# Dashboard questions

Only models needed to answer these are built. Every dashboard chart maps to one question.

| # | Question | Answered by |
|---|---|---|
| Q1 | How has foreign vs local ownership changed over time? | `gold.mart_foreign_ownership_monthly` (value and foreign share per period and security type) |
| Q2 | How is ownership composed by investor type, and by security type? | by investor type: `gold.fact_holding_monthly` (period x security x investor type x local/foreign); by security type: `gold.mart_foreign_ownership_monthly`, which takes the type from the holding file (`gold.fact_holding_monthly`) |
| Q3 | What changed month over month? | `gold.mart_foreign_ownership_monthly` (previous period, change in value and in share) |

Conventions:
- Value = quantity x price from the holding file. Equity price is per share; for bonds the price is 1 and the quantity is the nominal amount, so the product works for all types.
- Value metrics cover IDR securities only (securities known to be in another currency are excluded); securities missing from the master file (about 1.2% of the value in the latest period, of which about 0.4% never appears in it, mostly mutual funds) are assumed to be IDR. The security type is the one the holding file gives every security, so there is no unknown type; the master file is used only for the currency.
- Investor types are written out on the dashboard with the names from its design (CP Corporate, ID Individual,
  MF Mutual fund, IB Financial institution, OT Others, IS Insurance, PF Pension fund, SC Securities company,
  FD Foundation). The one home of the names is the `investor_types` var of the dbt project (codes and names
  together); the gold column `investor_type_name` carries them, so Superset writes none out. KSEI's own
  document for these codes has still not been read (see `data-source.md`).

## The dashboard

`KSEI foreign vs local ownership` (slug `ksei-ownership`), built only on three gold datasets
`mart_foreign_ownership_monthly`, `mart_investor_type_monthly` and `fact_holding_monthly`. Every chart returns
rows in the smoke test. Everything except Q1 and the freshness card shows the latest period: each chart
filters on the gold column `is_latest_period = 1` (one macro, `is_latest_period()`, in dbt), so the numbers
are right before any filter is touched and no chart works out "the newest period" for itself.

| Chart | Dataset | Shows |
|---|---|---|
| Latest period | mart | the latest period loaded, as a date (data freshness) |
| Foreign share of value | mart | foreign value / total value, latest period |
| Total value held | mart | total value, latest period, in IDR trillion (T = 10^12) |
| Change since peak | mart | the latest foreign share minus the highest share on record, in pp; red below zero, green from zero |
| Largest holder group | holder mart | a card: the name of the investor type with the most value, and under it its value (T) and its foreign share |
| Q1 Foreign share of ownership over time | mart | the foreign share of every period |
| Local vs foreign split | holding fact | local and foreign value, latest period |
| Q2 Ownership by investor type | holding fact | local and foreign value per investor type, largest first |
| Q3 Biggest moves in foreign share | mart | pp change against the previous period for the security types that moved by 0.15 pp or more |

Native filters (default: no filter):

| Filter | Applies to |
|---|---|
| Date range (from, to) | Q1, the chart over time: it shows only the periods inside the range |
| Security type (`security_type`) | the mart charts: share, total value, Q1 and Q3 (the holding charts have no security type here) |

The other charts show the latest period whatever the date range is (`is_latest_period = 1`). "Latest period" and
"Change since peak" (it compares with the peak of the whole market) also ignore the security-type filter.

The "Largest holder group" card is a Handlebars chart (a template over the one row its query returns). Superset
refuses to run such a chart under its default security settings, so `superset_config.py` allows `unsafe-eval` for
scripts and the `style` attribute in chart HTML; see the runbook. "Latest period" is a Big Number formatted as a date.

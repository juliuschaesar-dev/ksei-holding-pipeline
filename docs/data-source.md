# Data source: KSEI

Not affiliated with KSEI; data belongs to KSEI. Educational/portfolio use only.

## Legal and politeness checks

| Check | Result (2026-10-07) |
|---|---|
| `https://www.ksei.co.id/robots.txt` | No robots file: 301 to the site's HTML 404 page. No crawl rules declared. |
| `https://web.ksei.co.id/robots.txt` | No robots file: returns the site's HTML page. No crawl rules declared. |
| "Ketentuan dan Kebijakan" page | Not yet checked. |
| Email to helpdesk@ksei.co.id about monthly automated retrieval | Not sent (recommended). |

Rate-limit policy (enforced in `src/ksei/client.py`, Phase 3): minimum delay
between requests (`KSEI_MIN_DELAY_SECONDS`), one request at a time (Airflow pool
`ksei_http`, 1 slot), monthly cadence only, descriptive User-Agent.

## Archive pages (server-rendered HTML, no login)

Since 2026-11-02 the pipeline reads the new site `www.ksei.co.id` (a Nuxt app that renders the
list on the server). The legacy site `web.ksei.co.id` (`/archive_download/<dataset>`, a year
dropdown, relative `/Download/` links) is no longer used.

| Dataset | Archive page (`KSEI_BASE_URL` + path) |
|---|---|
| `master_securities` | `https://www.ksei.co.id/id/publikasi/data-dan-statistik/statik-efek` |
| `holding_composition` | `https://www.ksei.co.id/id/publikasi/data-dan-statistik/kepemilikan-efek` |

- The list is **paged, 8 entries per page, newest first**. Page 1 has no query; later pages are
  `?page=2`, `?page=3`, ... (verified 2026-11-02 on both datasets: 5 pages, 36 entries; the last
  page holds 4). The page numbers are `<button>` elements, not links, and the page count is only a
  literal inside the minified Nuxt payload, so the client does not read it. It asks for the next
  page until one adds no new download link. An out-of-range page (`?page=6`) answers HTTP 200 with
  no entries, so the loop ends cleanly.
- The same list is also loaded client-side from a JSON API on `webcms.ksei.co.id`. The pipeline
  does **not** use it: only the public pages above are read.
- Each entry is a `<p class="data-item-title">` ("Kepemilikan Efek 30 Oktober 2026", "Master
  File Efek 30 Oktober 2026") plus an `<a href="https://www.ksei.co.id/storage/Download/<file>.zip">`
  (the "Unduh" button). Hrefs are **absolute**. Take the release date from the file name
  (`\d{8}`), not the title. The file names are the same as on the legacy site.
- Coverage: 36 months per dataset, 2023-11-30 to 2026-10-30. The legacy site also offered
  2023-10-31; the new site does not list it.
- Release dates are the last trading day, so they vary (for example
  2026-05-29, 2026-10-30, 2025-12-30); only the page list is authoritative.
- Other links on the pages (menu, footer, social media, guides) are not data and must be ignored
  by the link filter. Match only `/Download/(StatisEfek|BalanceposEfek)\d{8}(\.txt)?\.zip`.

## Observed server behaviour

The legacy year pages intermittently returned HTTP 500, sometimes several times in a row, and
succeeded on a later attempt (seen 2026-10-07). The new pages answered every request with HTTP 200
on 2026-11-02, but the client keeps its defaults: 5 attempts with exponential backoff starting at
5 s, never faster than the minimum request spacing.

## Request budget used during discovery

2026-10-07 (legacy site): about 20 requests (robots checks, 2 current pages, 6 year pages, 1 JS
asset, 2 sample zips plus the 2 earlier zips supplied by the project owner).

2026-11-02 (new site): 7 requests (the 2 archive pages, 1 JS asset, `?page=2` and `?page=6` on
`kepemilikan-efek`, `?page=2` and `?page=5` on `statik-efek`).

All of them at least 5 seconds apart, with a descriptive User-Agent, through `KseiClient`.

## Datasets and files

Profiled from the 2026-09-30 releases, and the layout was checked against 2023-10-31, the oldest file: the header, delimiter, field counts and line endings are identical (2,804 rows each). The samples used
for that profiling are not kept; never commit KSEI files. Tests use small synthetic fixtures
with the same shape.

| Dataset (registry key) | Zip name | File inside | Rows (2026-09-30) |
|---|---|---|---|
| `holding_composition` | `BalanceposEfek<YYYYMMDD>.zip` | `Balancepos<YYYYMMDD>.txt` | 3,751 |
| `master_securities` | `StatisEfek<YYYYMMDD>.txt.zip` | `StatisEfek<YYYYMMDD>.txt` | 3,679 |

`<YYYYMMDD>` is the release date, the last trading day of the month. Download
URLs still come from the archive pages, never from the date (see AGENTS.md).

## File format (both files)

- One file per zip, plain text, ASCII, no BOM.
- Delimiter `|`, no quoting, header row, `

` record terminator.
- **Embedded line break:** one `master_securities` record (AGLG01X9SCFS) has a
  bare `
` inside the Description. Split records on `

` only, never on
  `
` and never with a line-based CSV reader; otherwise the record splits
  in two (field counts 3 and 26 instead of 28).
- Dates are `DD-MON-YYYY` in English upper-case (`30-SEP-2026`).
- Numbers are plain digits with `.` as the decimal separator, no thousands
  separators. Empty field = no value.
- Every file holds exactly one `Date` (the release date).
- Parquet in S3 keeps every column as a string. The ClickHouse bronze tables are typed
  (types live in the `DATASETS` registry). Columns marked `optional` there may be empty in the
  source and are stored as `''`, `0` or `1970-01-01`; empty required values fail the load.
- Some rows write decimals without a leading zero (`.55`); ClickHouse reads them as 0.55.
- Some releases (2025-06 to 2026-02) contain Windows-1252 bytes (0x96, 0xA0) in text fields;
  the parser falls back from UTF-8 to Windows-1252.

## `holding_composition` (Balancepos), 25 columns

Key: (`Date`, `Code`, `Type`); no duplicates in the sample. Securities
quantities are counts of securities held, per investor type, split Local and
Foreign. Foreign `Total` holds the total of the nine Foreign columns, local
likewise. In the sample, both totals equal the sum of their nine columns for
every row.

| # | Column | Notes |
|---|---|---|
| 0 | `Date` | release date |
| 1 | `Code` | security code (3,751 distinct; join key to the master file) |
| 2 | `Type` | 21 values, e.g. EQUITY, CORPORATE BOND, SUKUK |
| 3 | `Sec. Num` | securities outstanding; empty for 215 rows |
| 4 | `Price` | price per security; never empty |
| 5-13 | `Local IS, CP, PF, IB, ID, MF, SC, FD, OT` | local holdings by investor type |
| 14 | `Total` | local total |
| 15-23 | `Foreign IS, CP, PF, IB, ID, MF, SC, FD, OT` | foreign holdings by investor type |
| 24 | `Total` | foreign total |

- **Duplicate header name:** `Total` appears twice (index 14 local, 24 foreign).
  The parser must rename by position (`local_total`, `foreign_total`).
- **Investor-type codes (unconfirmed):** IS, CP, PF, IB, ID, MF, SC, FD, OT
  are not defined in the files. KSEI's published statistics use Insurance,
  Corporate, Pension Fund, Financial Institution (bank), Individual, Mutual
  Fund, Securities Company, Foundation, Others. Confirm against the KSEI
  site before labelling anything in a dashboard.

## `master_securities` (StatisEfek), 28 columns

Key: `Code` per period (and `Isin Code`, both unique in the sample).

Columns in order: `Date`, `Code`, `Description`, `Type`, `Isin Code`, `Issuer`,
`Status`, `Stock Exchange`, `Listing Date`, `Currency`, `Form`,
`Eff. Date Isin`, `Maturity Date`, `Expire Date`, `Exercise Price`,
`Interest`, `Interest Type`, `Interest Freq`, `Nominal Value`, `Num. of Sec`,
`Originated Amt`, `Current Amt`, `Total Scripless`, `Local (%)`,
`Foreign (%)`, `Total (%)`, `Sector`, `Closing Price`.

Observations that matter for silver:
- `Type` has 24 values; 4 exist only in the master file (BI instruments such
  as SUKBI, SVBI, SUVBI, BI-FRN), and casing differs between values
  (`Bank Indonesia Foreign Currency Sukuk (SUVBI)` vs upper case). Normalise
  case before comparing.
- `Interest Type` mixes spellings for the same meaning: `FIXED`/`Fixed`,
  `FLOATING`/`Floating/Variable`, `Zero/Discounted`/`ZERO RATE / DISCOUNTED`.
- `Status` is `ACTIVE` for every row; `Currency` is `IDR` or `USD`; `Form` is
  `Electronic` or `Certificate`; `Stock Exchange` is `IDX` or empty (718 rows).
- Many columns are sparsely filled by design (for example `Exercise Price`
  and `Expire Date` apply to warrants only).
- `Local (%)`, `Foreign (%)`, `Total (%)` are percentages (0-100); empty for 209 rows.

## Period calendar (not a KSEI file)

A static calendar the project loads for `gold.dim_period`. It is not KSEI data and is not
fetched from KSEI: it comes from a shared file, `PERIOD_SOURCE_URL` in `.env` (the share link
`https://drive.google.com/file/d/<id>/view` in its direct-download form
`https://drive.google.com/uc?export=download&id=<id>`). The download answers with a 303
redirect to the real location, which the loader follows.

| Fact | Value |
|---|---|
| File | `raw_period.csv`, 3.6 MB, comma separated, header row, quoted text cells |
| Rows | 18,628: one per day, 2000-01-01 to 2050-12-31, sorted, no gaps, no duplicates |
| Columns | 26, listed in `PERIOD` in `src/ksei/config.py` (names equal the headers) |
| Dates | ISO `YYYY-MM-DD`; `date_actual_time` is `YYYY-MM-DD 00:00:00.000` |
| Line ends | CRLF, except one bare LF between two rows; the CSV reader accepts both |
| Empty cells | one: `week_of_year_iso` on 2000-09-11 (the others look like `2000-W52-6`) |

Bronze keeps every column, typed (the ISO week is the only optional one). The file is stored
once under `bronze/period/raw/` with its SHA-256 and source URL as object metadata.

## Relationship between the two files

3,470 codes appear in both; 281 only in Balancepos and 209 only in Statis.
So `fact_holding_monthly` to `fact_security_monthly` is **not** a total join; the
singular test "every held security exists in the master fact" only warns
(`assert_every_held_security_exists_in_the_master_file`).

## Still to document

The "Ketentuan dan Kebijakan" terms page; confirmation of the investor-type
codes (the linked PDF `Panduan_Acuan_Informasi_Berdasarkan_Tipe_Investor_guna_Pembentukan_SID.pdf`
could not be fetched from this machine); the helpdesk email.

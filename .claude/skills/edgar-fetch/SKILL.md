---
name: edgar-fetch
description: Use when writing or debugging code that downloads anything from SEC EDGAR (ticker→CIK lookup, submissions/filing index, 10-K documents, XBRL companyfacts) — covers required headers, rate limits, caching and how to pick the right 10-K and XBRL facts.
---

# Fetching from SEC EDGAR

All EDGAR access goes through `src/audit_agent/common/edgar_client.py`. Do not call
`requests.get` on sec.gov anywhere else. URLs live in `config/settings.yaml` → `edgar`.

## Headers (mandatory)

```python
headers = {
    "User-Agent": get_user_agent(settings.edgar.user_agent_env),  # "Name email@domain"
    "Accept-Encoding": "gzip, deflate",
}
```
- Value comes from `EDGAR_USER_AGENT` in `.env` (load with `python-dotenv` once at startup).
  Missing/invalid → `MissingUserAgentError`; never fall back to a default string.
- Don't set `Host` manually. Never log the User-Agent value (tracing redacts it).

## Rate limit

- SEC allows 10 req/s per host; we use `edgar.max_requests_per_second` (8).
- Call `self.rate_limiter.wait()` before **every** HTTP request, including cache-miss retries.
- On 403: usually a bad/missing User-Agent or too fast — stop, don't retry in a loop.
- On 429/5xx: exponential backoff (1s, 2s, 4s; max 3 tries).

## Caching (check cache first, always)

| What | Cache path |
|---|---|
| `company_tickers.json` | `data/raw/edgar/company_tickers.json` |
| submissions | `data/raw/edgar/submissions/CIK##########.json` |
| companyfacts | `data/raw/edgar/companyfacts/CIK##########.json` |
| filing documents | `data/raw/edgar/filings/<cik>/<accession_nodash>/<document>` |

Write atomically (tmp file → rename). Tests must use fixtures in `tests/fixtures/`, never the network.

## Endpoints

1. **Ticker → CIK:** `https://www.sec.gov/files/company_tickers.json`
   → `{"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}`.
   Match ticker case-insensitively; pad with `format_cik()` → `"0000320193"`.
2. **Submissions:** `https://data.sec.gov/submissions/CIK{cik10}.json`
   → `filings.recent` is column-oriented: parallel lists `form`, `accessionNumber`,
   `filingDate`, `reportDate`, `primaryDocument`. Older filings are in `filings.files[]`
   (extra JSON pages) — fetch them if the target year is not in `recent`.
3. **Document:** `https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{primaryDocument}`
   (`cik_int` = unpadded, accession without dashes).
4. **Companyfacts:** `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json`
   → `facts["us-gaap"][Tag]["units"]["USD"]` = list of
   `{start?, end, val, accn, fy, fp, form, filed, frame?}`.

## Picking the right 10-K

- Filter `form == "10-K"`. Use `10-K/A` only if no original exists; log it.
- Match the fiscal year by `reportDate` (period end), not `filingDate`. Watch non-calendar
  fiscal years (AAPL ends Sept, WMT ends Jan). Record the rule in `docs/decisions.md`.

## Picking XBRL facts

- Keep facts with `form == "10-K"` and `accn` == the chosen filing's accession.
- `fy` is the fiscal year **of the filing**, not of the value: a FY2024 10-K also contains
  FY2023 and FY2022 comparatives with `fy=2024`. Select by `end` date (+ `start` for durations).
- Duration KPIs (revenue, net income, cash flow): `end - start` ≈ 365 days (350–380).
  Instant KPIs (cash, assets, debt): `end` == fiscal year end, no `start`.
- Try tags in the order listed in `settings.yaml`; record which tag was used (it becomes the citation).
- Duplicates for the same period: prefer the one from the chosen accession; else latest `filed`.
- Values are in units (USD), not thousands. Shares are under `units.shares`.

## Checklist
- [ ] Goes through `EdgarClient`; rate limiter called; cache checked first
- [ ] No network in tests (fixtures)
- [ ] Fiscal-year / tag-selection rules logged in `docs/decisions.md`

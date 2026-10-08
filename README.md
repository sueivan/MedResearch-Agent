# MedResearch Agent V0.1

## Run locally (Python 3.10+)

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8000
```
Open http://127.0.0.1:8000

## Run on an authorized server
Use a reverse proxy with HTTPS and authentication. Do **not** expose this prototype directly to the public Internet. It has no user accounts, durable job storage, or request quotas. For a temporary LAN demo only, use `--host 0.0.0.0` behind a trusted firewall.

Optional environment variables: `NCBI_EMAIL`, `NCBI_API_KEY`. Do not commit credentials to GitHub.

## Functions
- PubMed, Europe PMC, Crossref, ClinicalTrials.gov live search
- PMID and DOI lookups: `/api/verify/pmid?pmid=...`, `/api/verify/doi?doi=...`
- Conservative exact DOI / PMID / NCT ID / normalized-title deduplication
- CSV, Excel, RIS export from one-hour in-memory jobs
- API docs: `/docs`

## Limitations
- Search returns at most 100 records **per source per request**, not a complete systematic-review search; pagination and search-history storage are required for systematic reviews.
- Crossref bibliographic search may be broad; matches are candidate records, not proof of relevance.
- DOI verification via Crossref is not universal DOI resolution.
- Same trial may have multiple legitimate papers. Deduplication of reports is distinct from trial-level grouping.
- Public health and hospital patient data integrations are not included in V0.1.
- Requires Internet access for live searches. Offline use supports only UI and unit tests.
- Check database terms of use and citation licensing before reuse.

## Tests
`pytest -q`

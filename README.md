# job-agent

A daily job-watcher driven by your profile + preferences. It:

1. Builds a profile from **`profile/resume.tex`** (the single source of truth) — a generator derives `linkedin.json` and `resume.md` from it — plus your `preferences.yaml`.
2. Pulls fresh postings from **LinkedIn, Indeed, Glassdoor, and Google Jobs** (via [python-jobspy](https://github.com/Bunsly/JobSpy)) across **every location in `search_locations`** (e.g. United States + Canada), plus direct ATS feeds from a curated seed list of companies (`companies.yaml` — Greenhouse / Lever / Ashby).
3. Drops postings that explicitly require no sponsorship (regex + LLM safety net) and anything older than the recency window.
4. Scores each posting against your profile with an LLM — either **Claude** (cloud) or a **local model via Ollama** (private; nothing leaves your machine). Two stages: a cheap pre-filter, then a deep 0–100 score. Prioritizes fresh postings.
5. Emails you a digest of the top matches (rendered from a deterministic Python template — no LLM truncation risk).
6. Persists a SQLite dedup DB so you never see the same role twice.
7. **Optionally** upserts every scored job into a Google Sheet for tracking (`status` and `notes` columns are yours to edit; never overwritten on re-runs).

Runs on demand (`python -m src.main`) or on a GitHub Actions cron 2×/day (08:00 and 17:00 PDT).

## Sources

| Source | Type | Coverage |
|---|---|---|
| LinkedIn (via jobspy) | aggregator | Broad: any LinkedIn-posted role matching your query |
| Indeed (via jobspy) | aggregator | Broad: any Indeed-posted role |
| Glassdoor (via jobspy) | aggregator | **Currently disabled** — Glassdoor blocks JobSpy's location lookup (bot detection). Re-enable via `glassdoor_metros` if upstream is fixed. |
| Google Jobs (via jobspy) | aggregator | Broad — surfaces roles only listed on company sites |
| Greenhouse | ATS-direct | Per-company, from `companies.yaml` |
| Lever | ATS-direct | Per-company, from `companies.yaml` |
| Ashby | ATS-direct | Per-company, from `companies.yaml` |

The aggregator searches are driven by `search_queries` and `search_locations` in [profile/preferences.yaml](profile/preferences.yaml). Each query runs once per location, with Indeed's country inferred per location (Canada vs United States). The ATS sources are a curated priority bonus — not a whitelist — and skip silently if a company slug 404s.

## Profile (single source of truth)

**`profile/resume.tex` is the source of truth.** Everything else about the candidate is generated from it:

```bash
python scripts/gen_linkedin_profile.py
#   profile/resume.tex  ──▶  profile/linkedin.json  +  profile/resume.md
```

- Don't hand-edit `linkedin.json` or `resume.md` — they're regenerated and your changes will be overwritten.
- Fields that aren't in the resume (languages, the editorial headline) live in [`profile/linkedin.overrides.json`](profile/linkedin.overrides.json) and are deep-merged on top of the generated output.
- A **git pre-commit hook** ([`.githooks/pre-commit`](.githooks/pre-commit)) regenerates and re-stages both files whenever `resume.tex` (or the overrides/generator) changes. Enable it once per clone:
  ```bash
  git config core.hooksPath .githooks
  ```

## LLM backend: cloud or local

Set `LLM_BACKEND` in `.env`:

| `LLM_BACKEND` | Models | Privacy | Notes |
|---|---|---|---|
| `anthropic` (default) | Claude (Haiku pre-filter, Sonnet score) | Calls Anthropic's API | Needs `ANTHROPIC_API_KEY`; prompt-cached profile keeps it cheap |
| `ollama` | Any local model | **Fully local** — nothing leaves your machine | Needs Ollama running; no API key |

**Local setup with Ollama:**

```bash
brew install ollama
brew services start ollama          # background server, restarts at login
ollama pull qwen2.5:14b             # ~9 GB; strong JSON/instruction following

# .env
LLM_BACKEND=ollama
OLLAMA_MODEL=qwen2.5:14b
OLLAMA_NUM_CTX=16384                # profile+job prompt is ~8K tokens; don't go below this
```

Model picks (the profile+job prompt needs ≥16K context, which rules out some models):
- **`qwen2.5:14b`** — best balance of quality, speed, and reliable JSON. Recommended starting point.
- **`qwen2.5:32b`** — sharper fit-scoring, closer to cloud quality; needs more RAM and runs slower.
- **`llama3.1:8b`** — fastest/lightest for testing; weaker judgment.

Local scoring is slower and runs at low concurrency (2 pre-filter / 1 score) to avoid thrashing one machine — use `--limit` while testing. Quality is below cloud Claude; tune `--threshold` accordingly.

## Dashboard

A self-contained, **fully local** HTML dashboard of every scraped role — search, source/company/score filters, sort, and a clickable link to each posting. Nothing leaves your machine.

```bash
python scripts/build_dashboard.py        # build data/dashboard.html from the dedup DB
open data/dashboard.html                 # static view

# …or serve it with a working "Refresh — run full flow" button:
python scripts/serve_dashboard.py        # http://localhost:8765/
```
The server's **Refresh** button runs `python -m src.main --dry-run` in the background, streams progress, and reloads when done. Change what it runs with `--run-args` (e.g. `--run-args "--dry-run --all"`). The dashboard also rebuilds automatically at the end of every `python -m src.main` run. Fit scores appear for jobs that have been through a scoring run.

## Tradeoffs you should know

- **python-jobspy scrapes LinkedIn/Indeed.** It can break when those sites update their layout, and is technically against LinkedIn's ToS. Widely used for personal job-search; don't deploy at scale.
- **Glassdoor is currently blocked upstream.** JobSpy resolves a Glassdoor metro ID via `findPopularLocationAjax.htm`, which Glassdoor now answers with a bot-detection "Security" page for every term. It's disabled by default (`glassdoor_metros: []`) so it doesn't waste calls or spam errors; LinkedIn/Indeed/Google still provide broad coverage. Re-enable by listing metros once a JobSpy release restores it.
- **GitHub Actions runner IPs** are sometimes rate-limited by LinkedIn. If aggregator runs degrade over time, consider switching the workflow to run on a self-hosted runner or your Mac via launchd.
- **Recency window is 72 hours by default** (`recency_hours: 72`). Widen in [preferences.yaml](profile/preferences.yaml) if the digest comes back empty too often.

## Quick start (local)

```bash
git clone <your-fork>
cd job-agent
python -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env   # fill in keys for cloud, or set LLM_BACKEND=ollama for local
git config core.hooksPath .githooks   # enable the resume→profile regen hook

# Edit your profile — resume.tex is the source of truth
$EDITOR profile/resume.tex               # your resume (LaTeX)
python scripts/gen_linkedin_profile.py   # regenerate linkedin.json + resume.md
$EDITOR profile/preferences.yaml         # confirm functions, queries, search_locations
$EDITOR companies.yaml                   # prune/extend the company seed list

# Dry run (no email sent; writes data/last_digest.html instead)
python -m src.main --dry-run --limit 30

# Real run
python -m src.main
```

For a **fully local, private** run, set `LLM_BACKEND=ollama` in `.env` (see [LLM backend](#llm-backend-cloud-or-local)) and use `--dry-run` so no email/cloud service is touched.

## GitHub Actions setup

1. Push this repo to GitHub.
2. Repo Settings → Secrets and variables → Actions → add:
   - `ANTHROPIC_API_KEY` *(Actions uses the cloud backend — Ollama isn't available on the runner)*
   - `RESEND_API_KEY`
   - `EMAIL_TO`
   - `EMAIL_FROM` (e.g. `onboarding@resend.dev` until you verify a domain in Resend)
   - `GOOGLE_SHEETS_SHEET_ID` *(optional — only if you want sheet export)*
   - `GOOGLE_SHEETS_CREDS_JSON` *(optional — full contents of your service-account JSON)*
3. Repo Settings → Actions → General → Workflow permissions → **Read and write permissions** (so the workflow can commit `seen_jobs.db` back).
4. The workflow runs automatically at 08:00 and 17:00 PDT (cron in UTC). Adjust in [.github/workflows/run.yml](.github/workflows/run.yml).
5. Trigger manually: Actions tab → "job-watcher" → "Run workflow" (option to dry-run).

## Architecture

```
profile + preferences + companies
                │
                ▼
        ┌────────────────┐
        │ JobSpy source  │  LinkedIn / Indeed / Glassdoor / Google
        │ (search-driven)│
        ├────────────────┤
        │ ATS sources    │  Greenhouse / Lever / Ashby (per-company)
        └───────┬────────┘
                │
                ▼
  stale + sponsorship filters    ──▶ regex pre-filters, free
                │
                ▼
       SQLite dedup (INSERT OR IGNORE)
                │
                ▼
   stage-1 pre-filter (Claude Haiku / local Ollama)  ──▶ drop obvious mismatches
                │
                ▼
   stage-2 scorer (Claude Sonnet / local Ollama)     ──▶ 0–100 score + reasons + concerns
                │                      recency-weighted
                ├─────────────────────────────┐
                ▼                             ▼
   digest render (Python template)    Google Sheets upsert
                │                     (preserves `status` + `notes`)
                ▼
              Resend
```

On the Anthropic backend the candidate profile is passed as a **prompt-cached** system block, so per-job scoring stays cheap. The digest is rendered from a deterministic Python template (no LLM call, no truncation risk).

## Cost

- **Anthropic backend:** ≈ $0.30 per run, ~$18/month at 2 runs/day. Roughly half once cache hits stabilize.
- **Ollama backend:** $0 — runs entirely on your machine. Trade-off is lower scoring quality and slower runs.

## Files of interest

- [src/main.py](src/main.py) — orchestrator
- [src/scorer.py](src/scorer.py) — two-stage LLM scoring + Python digest template
- [src/llm.py](src/llm.py) — LLM backend abstraction (Anthropic / Ollama)
- [scripts/gen_linkedin_profile.py](scripts/gen_linkedin_profile.py) — generates `linkedin.json` + `resume.md` from `resume.tex`
- [src/resume_render.py](src/resume_render.py) — renders the Markdown resume from the structured profile
- [.githooks/pre-commit](.githooks/pre-commit) — regenerates the profile when `resume.tex` changes
- [src/sources/jobspy_source.py](src/sources/jobspy_source.py) — LinkedIn/Indeed/Glassdoor/Google aggregator (multi-location)
- [src/sources/greenhouse.py](src/sources/greenhouse.py), [lever.py](src/sources/lever.py), [ashby.py](src/sources/ashby.py) — ATS fetchers
- [src/filters.py](src/filters.py) — sponsorship + recency pre-filters
- [src/gsheet.py](src/gsheet.py) — Google Sheets exporter
- [src/store.py](src/store.py) — SQLite dedup
- [src/prompts/](src/prompts/) — Claude prompts (tune these without touching code)
- [.github/workflows/run.yml](.github/workflows/run.yml) — cron + DB commit-back

## Google Sheets export (optional but recommended)

Upserts every scored job — not just emailed picks — into a single sheet so you have a searchable, editable history.

**Columns** (in order):

| Agent-owned (refreshed each run) | User-editable (preserved across runs) |
|---|---|
| `id`, `first_seen`, `last_seen`, `posted`, `emailed`, `company`, `title`, `location`, `remote`, `source`, `url`, `score`, `fit_summary`, `match_reasons`, `concerns` | `status`, `notes` |

Suggested `status` lifecycle: `new` → `interested` → `applied` → `interviewing` → `offer` / `passed` / `rejected`.

**Setup (one-time, ~10 min)**

1. **GCP project + service account** — https://console.cloud.google.com → create project → enable **Google Sheets API** and **Google Drive API** → IAM → Service Accounts → create `job-agent-bot` → Keys → Add Key → JSON. Download the JSON.
2. **Create the sheet** — https://sheets.new. Copy the **Sheet ID** from the URL (the chunk between `/d/` and `/edit`).
3. **Share with the bot** — open the JSON, find `client_email`. In the sheet → Share → paste that email → Editor.
4. **Wire up locally** — save the JSON as `gsheet-creds.json` in the repo root (it's gitignored). Add to `.env`:
   ```
   GOOGLE_SHEETS_SHEET_ID=<your-sheet-id>
   GOOGLE_SHEETS_CREDS_JSON_PATH=./gsheet-creds.json
   ```
5. **GitHub Actions** — add two repo secrets: `GOOGLE_SHEETS_SHEET_ID` (the ID) and `GOOGLE_SHEETS_CREDS_JSON` (the entire JSON contents pasted in).

**Behavior**

- Runs at the end of every job-agent run, after the email send.
- Failure is non-fatal — a Sheets API error logs a warning and the run continues. Email and dedup are not blocked.
- If env vars aren't configured, the exporter no-ops silently.
- On each run: existing rows have everything *except* `status` and `notes` refreshed; new rows are appended.
- Tab name defaults to `jobs`. Override with `GOOGLE_SHEETS_TAB`.

**Security**

- The JSON private key gives write access to any sheet shared with the bot. Treat it like a password.
- Rotate it (GCP → Service Account → Keys → Add new → delete old) if it ever leaves your machine.
- `gsheet-creds.json` and `*-service-account.json` are gitignored by default.

## Tuning playbook

If digests are too **noisy**: narrow `search_queries`, tighten `target_functions`, raise `--threshold` (default 70).
If digests are too **sparse**: widen `recency_hours`, broaden queries, lower threshold.
If you keep seeing **the same companies**: add to `exclusions`.
If the scorer keeps **misjudging seniority**: edit [src/prompts/score.txt](src/prompts/score.txt) with concrete examples.

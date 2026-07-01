from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from jobspy import scrape_jobs

from .base import JobPosting, JobSource

log = logging.getLogger(__name__)


class JobSpySource(JobSource):
    """Aggregator covering LinkedIn, Indeed, Glassdoor, and Google Jobs via python-jobspy.

    JobSpy scrapes these sites synchronously. We run one query per search term, parallelized
    with a small semaphore to stay under aggregator rate limits.
    """

    name = "jobspy"
    # LinkedIn/Indeed/Google accept country-level locations ("United States", "Canada").
    # Glassdoor resolves location to a specific metro ID and rejects country names,
    # so it's run separately against glassdoor_metros.
    BROAD_SITES = ["linkedin", "indeed", "google"]

    def __init__(
        self,
        queries: list[str],
        locations: list[str] | str = "United States",
        glassdoor_metros: list[str] | None = None,
        hours_old: int = 168,
        results_per_query: int = 20,
        concurrency: int = 2,
    ) -> None:
        self.queries = queries
        self.locations = [locations] if isinstance(locations, str) else list(locations)
        self.glassdoor_metros = list(glassdoor_metros) if glassdoor_metros else []
        self.hours_old = hours_old
        self.results_per_query = results_per_query
        self.concurrency = concurrency

    async def fetch(self, client: httpx.AsyncClient) -> list[JobPosting]:
        if not self.queries:
            log.info("jobspy: no queries configured; skipping")
            return []

        sem = asyncio.Semaphore(self.concurrency)
        # (query, location, sites). Broad sites run on country-level locations;
        # Glassdoor runs on metros only (skipped entirely if none configured).
        combos: list[tuple[str, str, list[str]]] = [
            (q, loc, self.BROAD_SITES) for q in self.queries for loc in self.locations
        ]
        combos += [
            (q, metro, ["glassdoor"]) for q in self.queries for metro in self.glassdoor_metros
        ]

        async def one(q: str, loc: str, sites: list[str]) -> list[JobPosting]:
            async with sem:
                return await asyncio.to_thread(self._scrape, q, loc, sites)

        batches = await asyncio.gather(*[one(q, loc, sites) for q, loc, sites in combos])
        all_jobs = [j for batch in batches for j in batch]
        log.info(
            "jobspy: %d total postings | %d queries x %d locations=%r (broad) "
            "+ %d glassdoor metros=%r (hours_old=%d)",
            len(all_jobs),
            len(self.queries),
            len(self.locations),
            self.locations,
            len(self.glassdoor_metros),
            self.glassdoor_metros,
            self.hours_old,
        )
        return all_jobs

    def _scrape(self, query: str, location: str, sites: list[str]) -> list[JobPosting]:
        # Indeed/Glassdoor need the country to match the location to return results.
        country_indeed = "Canada" if "canada" in location.lower() else "United States"
        try:
            df = scrape_jobs(
                site_name=sites,
                search_term=query,
                location=location,
                results_wanted=self.results_per_query,
                hours_old=self.hours_old,
                country_indeed=country_indeed,
                verbose=0,
            )
        except Exception as e:
            log.warning("jobspy query %r failed: %s", query, e)
            return []

        if df is None or df.empty:
            log.info("jobspy query %r returned 0 rows", query)
            return []

        out: list[JobPosting] = []
        for _, row in df.iterrows():
            try:
                site = str(row.get("site") or "jobspy")
                description = row.get("description")
                if description is None or (isinstance(description, float)):
                    description = ""

                posted = _parse_date(row.get("date_posted"))

                url = (
                    row.get("job_url")
                    or row.get("job_url_direct")
                    or ""
                )
                ext_id = f"{site}:{row.get('id') or url}"

                out.append(
                    JobPosting(
                        source=site,
                        company=str(row.get("company") or "").strip(),
                        title=str(row.get("title") or "").strip(),
                        location=str(row.get("location") or "").strip(),
                        url=str(url),
                        description=str(description)[:8000],
                        remote=bool(row.get("is_remote") or False),
                        posted_at=posted,
                        external_id=ext_id,
                    )
                )
            except Exception as e:
                log.warning("jobspy row parse failed: %s", e)
                continue

        log.info("jobspy query %r: %d postings", query, len(out))
        return out


def _parse_date(value) -> datetime | None:
    if value is None:
        return None
    try:
        # pandas sometimes hands us Timestamp, sometimes string, sometimes NaT
        if hasattr(value, "to_pydatetime"):
            dt = value.to_pydatetime()
        else:
            dt = datetime.fromisoformat(str(value))
    except (ValueError, TypeError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

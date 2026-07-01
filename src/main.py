from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

import httpx

from . import store
from .config import Config
from .email_sender import send_digest
from .filters import drop_no_sponsorship, drop_stale
from .gsheet import GSheetExporter
from .profile import load_companies, load_profile
from .scorer import build_digest_html, score_jobs
from .sources import AshbySource, GreenhouseSource, JobSpySource, LeverSource

log = logging.getLogger("job-agent")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def current_slot() -> str:
    # 8 AM run shows up as "morning"; 5 PM run as "evening".
    # Cutoff is noon — anything before noon counts as the morning slot.
    return "morning" if datetime.now().hour < 12 else "evening"


def slot_label(slot: str) -> str:
    return {"morning": "8 AM", "evening": "5 PM"}.get(slot, slot)


def _search_locations(prefs: dict) -> list[str]:
    # Prefer the new list form; fall back to the legacy single-string key.
    locs = prefs.get("search_locations")
    if locs:
        return locs if isinstance(locs, list) else [locs]
    one = prefs.get("search_location", "United States")
    return [one] if isinstance(one, str) else list(one)


async def fetch_all(companies: list[dict], prefs: dict) -> list:
    async with httpx.AsyncClient(headers={"User-Agent": "job-agent/0.1"}) as client:
        sources = [
            JobSpySource(
                queries=prefs.get("search_queries", []),
                locations=_search_locations(prefs),
                glassdoor_metros=prefs.get("glassdoor_metros", []),
                hours_old=int(prefs.get("recency_hours", 72)),
                results_per_query=int(prefs.get("results_per_query", 20)),
            ),
            GreenhouseSource(companies),
            LeverSource(companies),
            AshbySource(companies),
        ]
        results = await asyncio.gather(*[s.fetch(client) for s in sources], return_exceptions=True)
    jobs = []
    for src, result in zip(sources, results):
        if isinstance(result, Exception):
            log.warning("%s raised: %s", src.name, result)
            continue
        jobs.extend(result)
    return jobs


async def run(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    profile = load_profile()
    companies = load_companies()
    log.info("[1/6] loaded profile + %d companies", len(companies))

    if args.reset_db:
        wiped = store.reset()
        log.info("[1/6] --reset-db: cleared dedup store (%d rows removed)", wiped)

    log.info("[2/6] fetching postings from aggregators + %d ATS company boards…", len(companies))
    all_jobs = await fetch_all(companies, profile.preferences)
    log.info("[2/6] fetched %d total postings across all sources", len(all_jobs))

    recency_hours = int(profile.preferences.get("recency_hours", 72))
    all_jobs, stale = drop_stale(all_jobs, recency_hours)
    log.info("[3/6] dropped %d postings older than %dh; %d remain", stale, recency_hours, len(all_jobs))

    if profile.preferences.get("requires_sponsorship", False):
        all_jobs, dropped = drop_no_sponsorship(all_jobs)
        log.info("dropped %d postings that explicitly stated no sponsorship", dropped)

    if args.limit:
        all_jobs = all_jobs[: args.limit]
        log.info("--limit applied: trimmed to %d", len(all_jobs))

    if args.no_dedup:
        # Score everything currently posted, ignoring what we've seen before.
        # Still record them as seen so a later normal run won't re-notify.
        new_jobs = all_jobs
        store.insert_new(all_jobs)
        log.info("[4/6] --no-dedup: scoring all %d postings (dedup bypassed)", len(new_jobs))
    else:
        new_jobs = store.insert_new(all_jobs)
        log.info("[4/6] %d new postings since last run", len(new_jobs))
    if not new_jobs:
        log.info("nothing to score; exiting")
        return 0

    log.info("[5/6] scoring %d postings…", len(new_jobs))
    scored = await score_jobs(cfg, profile, new_jobs)
    # Persist fit scores for all scored jobs so the dashboard can rank by them.
    store.record_scores({s.job.id: s.score for s in scored})

    threshold = args.threshold
    top = [s for s in scored if s.score >= threshold][: args.max_picks]
    log.info("[6/6] %d picks at threshold %d (max %d)", len(top), threshold, args.max_picks)
    if not top:
        log.info("no postings cleared the threshold; exiting without email")
        return 0

    slot = current_slot()
    html = build_digest_html(top, slot)

    subject = f"Job picks — {slot_label(slot)} ({len(top)} role{'s' if len(top) != 1 else ''})"

    emailed_ids: set[str] = set()
    if args.dry_run:
        out_path = Path(__file__).resolve().parent.parent / "data" / "last_digest.html"
        out_path.write_text(html)
        log.info("--dry-run: wrote digest to %s (not sent)", out_path)
    else:
        send_digest(cfg, subject, html)
        store.mark_emailed([s.job.id for s in top], {s.job.id: s.score for s in top})
        emailed_ids = {s.job.id for s in top}

    # Push every scored job (not just emailed ones) to Google Sheets for tracking.
    # No-op if env vars aren't configured.
    GSheetExporter().export(scored, emailed_ids)

    log.info("dedup store: %s", store.stats())

    # Refresh the local jobs dashboard (non-fatal if it fails).
    try:
        from .dashboard import build_dashboard
        path = build_dashboard()
        log.info("dashboard refreshed: %s", path)
    except Exception as e:
        log.warning("dashboard build failed: %s", e)

    return 0


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(prog="job-agent")
    parser.add_argument("--dry-run", action="store_true", help="Score and compose, but don't send email.")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N postings (for dev).")
    parser.add_argument("--threshold", type=int, default=70, help="Minimum score to include in digest.")
    parser.add_argument("--max-picks", type=int, default=20, help="Maximum jobs per digest.")
    parser.add_argument("--no-dedup", action="store_true",
                        help="Score every currently-posted role, not just ones new since last run.")
    parser.add_argument("--reset-db", action="store_true",
                        help="Wipe the dedup DB (data/seen_jobs.db) before running, for a clean re-run.")
    parser.add_argument("--all", action="store_true",
                        help="Include every scored role in the digest (threshold 0, no limit, no dedup, high cap).")
    args = parser.parse_args()
    if args.all:
        args.no_dedup = True
        args.limit = 0
        args.threshold = 0
        if args.max_picks == 20:  # leave an explicit --max-picks untouched
            args.max_picks = 1000
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

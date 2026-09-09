#!/usr/bin/env python3
"""
Daily free-competitions scraper.

Pulls currently-running giveaways/sweepstakes/contests from a small set of
public sources (Reddit listing JSON + RSS feeds), dedupes them against
entries already seen, and writes:
  - data/competitions.json  (full running dataset, machine readable)
  - COMPETITIONS.md         (human readable list, newest first)

Sources are configured in scraper/sources.json so new ones can be added
without touching code.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "competitions.json"
SOURCES_PATH = ROOT / "scraper" / "sources.json"
OUTPUT_MD = ROOT / "COMPETITIONS.md"
USER_AGENT = "free-competitions-scraper/1.0 (personal use; contact via GitHub repo)"
MAX_AGE_DAYS = 45  # drop entries older than this so the list doesn't grow forever
REQUEST_TIMEOUT = 15

SPAM_TITLE_PATTERNS = re.compile(
    r"\b(nsfw|onlyfans|crypto airdrop|click here now)\b", re.IGNORECASE
)


def log(msg: str) -> None:
    print(f"[scraper] {msg}", file=sys.stderr)


def load_sources() -> dict:
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_existing() -> dict:
    if DATA_PATH.exists():
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"entries": {}}


def fetch_reddit(subreddit: str, name: str) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/new/.json?limit=50"
    try:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log(f"WARN: failed to fetch {name}: {e}")
        return []

    try:
        posts = resp.json()["data"]["children"]
    except (KeyError, ValueError):
        log(f"WARN: unexpected response shape from {name}")
        return []

    results = []
    for post in posts:
        p = post.get("data", {})
        title = p.get("title", "").strip()
        if not title or p.get("stickied") or SPAM_TITLE_PATTERNS.search(title):
            continue
        permalink = p.get("permalink")
        link = f"https://www.reddit.com{permalink}" if permalink else p.get("url")
        if not link:
            continue
        created = p.get("created_utc")
        published = (
            datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
            if created
            else datetime.now(timezone.utc).isoformat()
        )
        results.append(
            {
                "id": f"reddit:{p.get('id')}",
                "title": title,
                "url": link,
                "source": name,
                "published": published,
                "summary": (p.get("selftext") or "")[:400].strip(),
            }
        )
    return results


def fetch_rss(url: str, name: str) -> list[dict]:
    try:
        feed = feedparser.parse(
            url, request_headers={"User-Agent": USER_AGENT}
        )
    except Exception as e:  # feedparser rarely raises, but be defensive
        log(f"WARN: failed to parse {name}: {e}")
        return []

    if getattr(feed, "bozo", False) and not feed.entries:
        log(f"WARN: no entries parsed from {name} (bozo={feed.bozo_exception})")
        return []

    results = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link")
        if not title or not link or SPAM_TITLE_PATTERNS.search(title):
            continue
        if "published_parsed" in entry and entry.published_parsed:
            published = datetime(
                *entry.published_parsed[:6], tzinfo=timezone.utc
            ).isoformat()
        else:
            published = datetime.now(timezone.utc).isoformat()
        results.append(
            {
                "id": f"rss:{link}",
                "title": title,
                "url": link,
                "source": name,
                "published": published,
                "summary": (entry.get("summary", "") or "")[:400].strip(),
            }
        )
    return results


def collect() -> list[dict]:
    sources = load_sources()
    all_entries: list[dict] = []

    for r in sources.get("reddit", []):
        log(f"Fetching {r['name']}...")
        all_entries.extend(fetch_reddit(r["subreddit"], r["name"]))
        time.sleep(1)  # be polite to reddit's public API

    for r in sources.get("rss", []):
        log(f"Fetching {r['name']}...")
        all_entries.extend(fetch_rss(r["url"], r["name"]))

    return all_entries


def merge_and_prune(existing: dict, fresh: list[dict]) -> dict:
    entries = existing.get("entries", {})

    for e in fresh:
        entries[e["id"]] = e  # newer fetch overwrites (keeps summary fresh)

    cutoff = time.time() - MAX_AGE_DAYS * 86400
    pruned = {}
    for eid, e in entries.items():
        try:
            ts = datetime.fromisoformat(e["published"]).timestamp()
        except (ValueError, KeyError):
            ts = time.time()
        if ts >= cutoff:
            pruned[eid] = e

    return {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "entries": pruned,
    }


def domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except ValueError:
        return url


def write_markdown(data: dict) -> None:
    entries = sorted(
        data["entries"].values(), key=lambda e: e["published"], reverse=True
    )

    lines = [
        "# Free Competitions & Giveaways",
        "",
        f"_Last updated: {data['last_updated']} — {len(entries)} active listings "
        f"from the last {MAX_AGE_DAYS} days._",
        "",
        "> Auto-generated by `scraper/main.py`. Review each link before entering — "
        "always check the official rules, eligibility, and that it's not a scam.",
        "",
    ]

    by_source: dict[str, list[dict]] = {}
    for e in entries:
        by_source.setdefault(e["source"], []).append(e)

    for source, items in sorted(by_source.items()):
        lines.append(f"## {source} ({len(items)})")
        lines.append("")
        for e in items:
            date = e["published"][:10]
            title = e["title"].replace("\n", " ").strip()
            lines.append(f"- **[{title}]({e['url']})** — {date} ({domain(e['url'])})")
        lines.append("")

    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing()
    fresh = collect()
    log(f"Fetched {len(fresh)} raw entries this run")

    merged = merge_and_prune(existing, fresh)
    log(f"{len(merged['entries'])} entries after merge/prune")

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, sort_keys=True)

    write_markdown(merged)
    log(f"Wrote {DATA_PATH} and {OUTPUT_MD}")


if __name__ == "__main__":
    main()

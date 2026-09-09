# Free Competitions Scraper

Builds a daily-refreshed list of free-to-enter competitions, sweepstakes, and
giveaways so you can browse and pick which ones to enter.

- **The list:** [`COMPETITIONS.md`](./COMPETITIONS.md) — regenerated daily.
- **Raw data:** [`data/competitions.json`](./data/competitions.json) — full
  dataset with dedup metadata, in case you want to build your own view (a
  spreadsheet, a filtered page, etc).

## How it works

`scraper/main.py` pulls active listings from the sources in
[`scraper/sources.json`](./scraper/sources.json):

- **Reddit** listing JSON for subreddits like r/sweepstakes, r/contests,
  r/giveaways, r/gamegiveaways (no auth needed, public endpoint).
- **RSS feeds** from giveaway/sweepstakes sites.

Entries are deduped by a stable id (Reddit post id or RSS link), merged with
what was already collected, and anything older than 45 days is dropped so the
list stays current. A GitHub Actions workflow
([`.github/workflows/daily.yml`](./.github/workflows/daily.yml)) runs this
every day and commits the refreshed `COMPETITIONS.md` / `data/competitions.json`.

## Adding more sources

Edit `scraper/sources.json`:

```json
{
  "reddit": [{ "name": "r/some-subreddit", "subreddit": "some-subreddit" }],
  "rss": [{ "name": "Some Site", "url": "https://example.com/feed/" }]
}
```

Any subreddit or RSS feed works without code changes.

## Running locally

```bash
pip install -r requirements.txt
python scraper/main.py
```

## A note on safety

This only aggregates publicly posted links — it doesn't enter anything on
your behalf. Always check a competition's official rules, eligibility, and
legitimacy before entering; be wary of anything asking for payment or
sensitive personal/financial info to "claim a prize."

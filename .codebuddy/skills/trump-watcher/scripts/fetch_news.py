#!/usr/bin/env python3
"""
Fetch Trump-related news from Google News RSS and GNews API.
Outputs FetchedItem list as JSON to data/raw/.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List

# Allow running as standalone script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    DedupIndex,
    FetchedItem,
    ensure_data_dirs,
    http_get,
    load_config,
    now_iso,
    parse_datetime,
    save_json,
    setup_logging,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Google News RSS Fetcher
# ---------------------------------------------------------------------------

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def fetch_google_news_rss(query: str = "Trump", max_items: int = 50,
                          hours_back: int = 48) -> List[FetchedItem]:
    """Parse Google News RSS feed for Trump-related news."""
    try:
        import feedparser
    except ImportError:
        logger.error("feedparser not installed. Run: pip install feedparser")
        return []

    url = GOOGLE_NEWS_RSS_URL.format(query=query)
    logger.info("Fetching Google News RSS: %s", url)

    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        logger.warning("Google News RSS parse error: %s", feed.bozo_exception)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    items: List[FetchedItem] = []

    for entry in feed.entries[:max_items]:
        published = entry.get("published", "")
        pub_dt = parse_datetime(published)
        if pub_dt:
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            if pub_dt < cutoff:
                continue
            published_iso = pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            published_iso = now_iso()

        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", entry.get("description", ""))

        items.append(FetchedItem(
            source="google_news",
            type="news",
            title=title,
            published_at=published_iso,
            content=summary,
            url=link,
            fetched_at=now_iso(),
        ))

    logger.info("Google News RSS: fetched %d items", len(items))
    return items

# ---------------------------------------------------------------------------
# GNews API Fetcher
# ---------------------------------------------------------------------------

GNEWS_API_URL = "https://gnews.io/api/v4/search"


def fetch_gnews_api(query: str = "Trump", api_key: str = "",
                    max_items: int = 50, hours_back: int = 48) -> List[FetchedItem]:
    """Fetch news from GNews API (requires API key)."""
    if not api_key:
        api_key = os.environ.get("GNEWS_API_KEY", "")
    if not api_key:
        logger.info("GNews API key not configured, skipping.")
        return []

    from_dt = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params = {
        "q": query,
        "lang": "en",
        "max": min(max_items, 100),
        "from": from_dt,
        "apikey": api_key,
    }

    logger.info("Fetching GNews API: q=%s, from=%s", query, from_dt)
    resp_text = http_get(GNEWS_API_URL, params=params)
    if not resp_text:
        logger.warning("GNews API returned no data.")
        return []

    try:
        data = json.loads(resp_text)
    except json.JSONDecodeError as e:
        logger.warning("GNews API JSON parse error: %s", e)
        return []

    items: List[FetchedItem] = []
    for article in data.get("articles", []):
        pub_raw = article.get("publishedAt", "")
        pub_dt = parse_datetime(pub_raw)
        published_iso = pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if pub_dt else now_iso()

        items.append(FetchedItem(
            source="gnews_api",
            type="news",
            title=article.get("title", ""),
            published_at=published_iso,
            content=article.get("content", article.get("description", "")),
            url=article.get("url", ""),
            fetched_at=now_iso(),
        ))

    logger.info("GNews API: fetched %d items", len(items))
    return items

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(config: dict = None) -> List[FetchedItem]:
    """Execute all news fetchers and save results."""
    if config is None:
        config = load_config()

    dirs = ensure_data_dirs(config.get("data_dir", "data"))
    dedup = DedupIndex(os.path.join(config.get("data_dir", "data"), "seen_urls.json"))

    fetch_cfg = config.get("fetch", {})
    max_items = fetch_cfg.get("max_items_per_source", 50)
    hours_back = fetch_cfg.get("hours_back", 48)
    ds_cfg = config.get("data_sources", {})

    all_items: List[FetchedItem] = []

    # Google News RSS
    if ds_cfg.get("google_news_rss", {}).get("enabled", True):
        try:
            items = fetch_google_news_rss(max_items=max_items, hours_back=hours_back)
            all_items.extend(items)
        except Exception as e:
            logger.error("Google News RSS fetch failed: %s", e)

    # GNews API
    if ds_cfg.get("gnews_api", {}).get("enabled", True):
        try:
            api_key = ds_cfg.get("gnews_api", {}).get("api_key", "")
            items = fetch_gnews_api(api_key=api_key, max_items=max_items, hours_back=hours_back)
            all_items.extend(items)
        except Exception as e:
            logger.error("GNews API fetch failed: %s", e)

    # Dedup
    new_items: List[FetchedItem] = []
    for item in all_items:
        if item.url and not dedup.is_seen(item.url):
            dedup.add(item.url)
            new_items.append(item)

    dedup.save()

    # Save raw data
    if new_items:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(dirs["raw"], f"news_{ts}.json")
        save_json([item.to_dict() for item in new_items], out_path)
        logger.info("Saved %d new news items to %s", len(new_items), out_path)
    else:
        logger.info("No new news items to save.")

    return new_items


def main():
    parser = argparse.ArgumentParser(description="Fetch Trump-related news")
    parser.add_argument("--max-items", type=int, default=50)
    parser.add_argument("--hours-back", type=int, default=48)
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    setup_logging()
    config = load_config(args.config)
    config.setdefault("fetch", {})["max_items_per_source"] = args.max_items
    config["fetch"]["hours_back"] = args.hours_back

    items = run(config)
    print(f"Fetched {len(items)} news items.")


if __name__ == "__main__":
    main()

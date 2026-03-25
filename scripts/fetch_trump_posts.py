#!/usr/bin/env python3
"""
Fetch Trump posts from Truth Social mirrors and Nitter instances.
Outputs FetchedItem list as JSON to data/raw/.
"""

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional

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
# Truth Social Mirror Fetcher
# ---------------------------------------------------------------------------

TRUTH_SOCIAL_RSS_MIRRORS = [
    "https://truthsocial.com/@realDonaldTrump/rss",
    "https://trumptruthsocial.com/rss",
]


def fetch_truth_social(max_items: int = 50, hours_back: int = 48) -> List[FetchedItem]:
    """Fetch Trump posts from Truth Social RSS mirrors with fallback."""
    try:
        import feedparser
    except ImportError:
        logger.error("feedparser not installed. Run: pip install feedparser")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    for mirror_url in TRUTH_SOCIAL_RSS_MIRRORS:
        logger.info("Trying Truth Social mirror: %s", mirror_url)
        try:
            feed = feedparser.parse(mirror_url)
            if feed.bozo and not feed.entries:
                logger.warning("Mirror %s parse error: %s", mirror_url, feed.bozo_exception)
                continue

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

                content = entry.get("summary", entry.get("description", entry.get("title", "")))
                link = entry.get("link", "")
                title = entry.get("title", "")

                items.append(FetchedItem(
                    source="truth_social",
                    type="post",
                    title=title[:200] if title else None,
                    published_at=published_iso,
                    content=content,
                    url=link,
                    fetched_at=now_iso(),
                ))

            if items:
                logger.info("Truth Social (%s): fetched %d items", mirror_url, len(items))
                return items

        except Exception as e:
            logger.warning("Truth Social mirror %s failed: %s", mirror_url, e)
            continue

    logger.info("All Truth Social mirrors failed or returned no items.")
    return []

# ---------------------------------------------------------------------------
# Nitter Fetcher
# ---------------------------------------------------------------------------

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
]

NITTER_USER = "realDonaldTrump"


def _parse_nitter_html(html: str, base_url: str,
                       max_items: int = 50,
                       hours_back: int = 48) -> List[FetchedItem]:
    """Parse Nitter HTML page to extract tweets/posts."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("beautifulsoup4 not installed. Run: pip install beautifulsoup4")
        return []

    soup = BeautifulSoup(html, "html.parser")
    items: List[FetchedItem] = []

    tweet_containers = soup.select(".timeline-item")
    if not tweet_containers:
        tweet_containers = soup.select(".tweet-body")

    for container in tweet_containers[:max_items]:
        # Extract text content
        content_el = container.select_one(".tweet-content, .media-body")
        if not content_el:
            continue
        content = content_el.get_text(strip=True)
        if not content:
            continue

        # Extract timestamp
        time_el = container.select_one("time")
        if time_el and time_el.get("datetime"):
            published_iso = time_el["datetime"]
        else:
            published_iso = now_iso()

        # Extract link
        link_el = container.select_one("a.tweet-link, .tweet-date a")
        link = ""
        if link_el and link_el.get("href"):
            href = link_el["href"]
            link = href if href.startswith("http") else base_url + href

        items.append(FetchedItem(
            source="nitter",
            type="post",
            title=content[:100] + "..." if len(content) > 100 else content,
            published_at=published_iso,
            content=content,
            url=link or f"{base_url}/{NITTER_USER}",
            fetched_at=now_iso(),
        ))

    return items


def fetch_nitter(max_items: int = 50, hours_back: int = 48) -> List[FetchedItem]:
    """Fetch Trump posts from Nitter instances with fallback."""
    for instance in NITTER_INSTANCES:
        url = f"{instance}/{NITTER_USER}"
        logger.info("Trying Nitter instance: %s", url)
        try:
            html = http_get(url, timeout=10)
            if not html:
                continue
            items = _parse_nitter_html(html, instance, max_items, hours_back)
            if items:
                logger.info("Nitter (%s): fetched %d items", instance, len(items))
                return items
        except Exception as e:
            logger.warning("Nitter instance %s failed: %s", instance, e)
            continue

    # Also try RSS feed from Nitter
    for instance in NITTER_INSTANCES:
        rss_url = f"{instance}/{NITTER_USER}/rss"
        logger.info("Trying Nitter RSS: %s", rss_url)
        try:
            import feedparser
            feed = feedparser.parse(rss_url)
            if feed.bozo and not feed.entries:
                continue
            items: List[FetchedItem] = []
            for entry in feed.entries[:max_items]:
                pub = entry.get("published", "")
                pub_dt = parse_datetime(pub)
                published_iso = pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if pub_dt else now_iso()
                content = entry.get("summary", entry.get("description", ""))
                items.append(FetchedItem(
                    source="nitter",
                    type="post",
                    title=entry.get("title", "")[:200],
                    published_at=published_iso,
                    content=content,
                    url=entry.get("link", rss_url),
                    fetched_at=now_iso(),
                ))
            if items:
                logger.info("Nitter RSS (%s): fetched %d items", instance, len(items))
                return items
        except Exception as e:
            logger.warning("Nitter RSS %s failed: %s", rss_url, e)
            continue

    logger.info("All Nitter instances failed or returned no items.")
    return []

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(config: dict = None) -> List[FetchedItem]:
    """Execute all post fetchers and save results."""
    if config is None:
        config = load_config()

    dirs = ensure_data_dirs(config.get("data_dir", "data"))
    dedup = DedupIndex(os.path.join(config.get("data_dir", "data"), "seen_urls.json"))

    fetch_cfg = config.get("fetch", {})
    max_items = fetch_cfg.get("max_items_per_source", 50)
    hours_back = fetch_cfg.get("hours_back", 48)
    ds_cfg = config.get("data_sources", {})

    all_items: List[FetchedItem] = []

    # Truth Social
    if ds_cfg.get("truth_social", {}).get("enabled", True):
        try:
            items = fetch_truth_social(max_items=max_items, hours_back=hours_back)
            all_items.extend(items)
        except Exception as e:
            logger.error("Truth Social fetch failed: %s", e)

    # Nitter
    if ds_cfg.get("nitter", {}).get("enabled", True):
        try:
            items = fetch_nitter(max_items=max_items, hours_back=hours_back)
            all_items.extend(items)
        except Exception as e:
            logger.error("Nitter fetch failed: %s", e)

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
        out_path = os.path.join(dirs["raw"], f"posts_{ts}.json")
        save_json([item.to_dict() for item in new_items], out_path)
        logger.info("Saved %d new post items to %s", len(new_items), out_path)
    else:
        logger.info("No new post items to save.")

    return new_items


def main():
    parser = argparse.ArgumentParser(description="Fetch Trump social media posts")
    parser.add_argument("--max-items", type=int, default=50)
    parser.add_argument("--hours-back", type=int, default=48)
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    setup_logging()
    config = load_config(args.config)
    config.setdefault("fetch", {})["max_items_per_source"] = args.max_items
    config["fetch"]["hours_back"] = args.hours_back

    items = run(config)
    print(f"Fetched {len(items)} post items.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Data cleaning pipeline for Trump-Watcher.
Stages: HTML strip -> Unicode normalize -> dedup -> relevance filter ->
        topic tagging -> sort by time.
Reads data/raw/ and outputs CleanedItem list to data/cleaned/.
"""

import argparse
import glob
import logging
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    CleanedItem,
    DedupIndex,
    FetchedItem,
    ensure_data_dirs,
    load_config,
    load_json,
    parse_datetime,
    save_json,
    setup_logging,
    url_hash,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Topic keywords & categories
# ---------------------------------------------------------------------------

TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "tariff": ["tariff", "tariffs", "import tax", "import duty", "customs duty"],
    "trade_war": ["trade war", "trade deal", "trade agreement", "trade deficit", "trade surplus"],
    "sanctions": ["sanction", "sanctions", "embargo", "blacklist"],
    "fed": ["federal reserve", "the fed", "interest rate", "rate hike", "rate cut", "monetary policy", "powell"],
    "tax": ["tax cut", "tax reform", "tax plan", "tax policy", "corporate tax"],
    "china": ["china", "chinese", "beijing", "xi jinping", "ccp"],
    "nato": ["nato", "atlantic alliance", "defense spending"],
    "oil_energy": ["oil", "petroleum", "opec", "natural gas", "energy policy", "drill"],
    "crypto": ["bitcoin", "crypto", "cryptocurrency", "digital currency", "blockchain"],
    "immigration": ["immigration", "border", "deportation", "migrant", "asylum", "wall"],
    "tech": ["big tech", "silicon valley", "tiktok", "social media regulation", "antitrust"],
    "defense": ["military", "defense spending", "pentagon", "missile", "nuclear", "weapons"],
    "economy": ["economy", "gdp", "recession", "inflation", "unemployment", "jobs report"],
    "stock_market": ["stock market", "dow jones", "s&p 500", "nasdaq", "wall street", "rally", "crash"],
}

# Relevance keywords — content must mention Trump AND at least some policy terms
TRUMP_KEYWORDS = [
    "trump", "donald trump", "president trump", "potus", "truth social",
    "mar-a-lago", "maga", "make america",
]

POLICY_KEYWORDS: List[str] = []
for kw_list in TOPIC_KEYWORDS.values():
    POLICY_KEYWORDS.extend(kw_list)

# ---------------------------------------------------------------------------
# Cleaning functions
# ---------------------------------------------------------------------------

def strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(text, "html.parser").get_text(separator=" ")
    except ImportError:
        return re.sub(r"<[^>]+>", " ", text)


def normalize_text(text: str) -> str:
    """Unicode NFKC normalization + whitespace collapse."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)  # control chars
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_relevance(text: str) -> float:
    """Score 0-1 based on Trump + policy keyword matches."""
    text_lower = text.lower()

    # Must mention Trump
    trump_hit = any(kw in text_lower for kw in TRUMP_KEYWORDS)
    if not trump_hit:
        return 0.0

    # Count policy keyword hits
    hits = 0
    total = len(POLICY_KEYWORDS)
    for kw in POLICY_KEYWORDS:
        if kw in text_lower:
            hits += 1

    # Normalize: cap at 1.0, boost for having any policy hit
    if hits == 0:
        return 0.15  # Mentions Trump but no policy keywords
    score = min(1.0, 0.3 + (hits / max(total * 0.1, 1)) * 0.7)
    return round(score, 3)


def identify_topics(text: str) -> List[str]:
    """Identify topic tags present in the text."""
    text_lower = text.lower()
    tags = []
    for tag, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            tags.append(tag)
    return tags

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def clean_items(raw_items: List[dict], config: dict) -> List[CleanedItem]:
    """Run the full cleaning pipeline on raw fetched items."""
    clean_cfg = config.get("clean", {})
    min_len = clean_cfg.get("min_content_length", 50)
    relevance_threshold = clean_cfg.get("relevance_threshold", 0.3)

    seen_hashes: Set[str] = set()
    cleaned: List[CleanedItem] = []

    for raw in raw_items:
        item = FetchedItem(**{k: raw[k] for k in FetchedItem.__dataclass_fields__ if k in raw})

        # 1. Strip HTML
        text = strip_html(item.content)

        # 2. Normalize Unicode
        text = normalize_text(text)

        # Also clean title
        title = normalize_text(strip_html(item.title)) if item.title else item.title

        # 3. Length filter
        if len(text) < min_len:
            logger.debug("Skipped short content (%d chars): %s", len(text), item.url)
            continue

        # 4. Content-based dedup (hash of cleaned text)
        content_hash = url_hash(text[:500])
        if content_hash in seen_hashes:
            logger.debug("Skipped duplicate content: %s", item.url)
            continue
        seen_hashes.add(content_hash)

        # 5. Relevance scoring
        combined = f"{title or ''} {text}"
        relevance = compute_relevance(combined)
        if relevance < relevance_threshold:
            logger.debug("Skipped low relevance (%.3f): %s", relevance, item.url)
            continue

        # 6. Topic tagging
        topics = identify_topics(combined)

        cleaned.append(CleanedItem(
            source=item.source,
            type=item.type,
            title=title,
            published_at=item.published_at,
            content=item.content,
            clean_content=text,
            url=item.url,
            fetched_at=item.fetched_at,
            topic_tags=topics,
            relevance_score=relevance,
        ))

    # 7. Sort by published_at descending (newest first)
    cleaned.sort(key=lambda x: x.published_at, reverse=True)

    logger.info("Cleaning pipeline: %d raw -> %d cleaned", len(raw_items), len(cleaned))
    return cleaned

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(config: dict = None) -> List[CleanedItem]:
    """Load all raw data, clean, and save results."""
    if config is None:
        config = load_config()

    data_dir = config.get("data_dir", "data")
    dirs = ensure_data_dirs(data_dir)

    # Collect all raw JSON files
    raw_files = sorted(glob.glob(os.path.join(dirs["raw"], "*.json")))
    if not raw_files:
        logger.info("No raw data files found in %s", dirs["raw"])
        return []

    all_raw: List[dict] = []
    for fpath in raw_files:
        data = load_json(fpath)
        if isinstance(data, list):
            all_raw.extend(data)

    logger.info("Loaded %d raw items from %d files", len(all_raw), len(raw_files))

    # Run cleaning pipeline
    cleaned = clean_items(all_raw, config)

    # Save cleaned data
    if cleaned:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(dirs["cleaned"], f"cleaned_{ts}.json")
        save_json([item.to_dict() for item in cleaned], out_path)
        logger.info("Saved %d cleaned items to %s", len(cleaned), out_path)

    return cleaned


def main():
    parser = argparse.ArgumentParser(description="Clean Trump-Watcher raw data")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    setup_logging()
    cleaned = run(load_config(args.config))
    print(f"Cleaned {len(cleaned)} items.")


if __name__ == "__main__":
    main()

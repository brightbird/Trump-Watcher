#!/usr/bin/env python3
"""
trump-watcher utility module.
Provides data models, HTTP helpers, dedup index, config loading, and logging setup.
"""

import hashlib
import json
import logging
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class FetchedItem:
    """Raw item from any data source."""
    source: str              # "google_news" | "gnews_api" | "truth_social" | "nitter"
    type: str                # "news" | "post"
    title: Optional[str]
    published_at: str        # UTC ISO 8601
    content: str
    url: str
    fetched_at: str          # UTC ISO 8601

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CleanedItem:
    """Item after cleaning pipeline."""
    source: str
    type: str
    title: Optional[str]
    published_at: str
    content: str             # original content kept for reference
    clean_content: str
    url: str
    fetched_at: str
    topic_tags: List[str] = field(default_factory=list)
    relevance_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_fetched(cls, item: FetchedItem, clean_content: str = "",
                     topic_tags: List[str] = None,
                     relevance_score: float = 0.0) -> "CleanedItem":
        return cls(
            source=item.source,
            type=item.type,
            title=item.title,
            published_at=item.published_at,
            content=item.content,
            clean_content=clean_content or item.content,
            url=item.url,
            fetched_at=item.fetched_at,
            topic_tags=topic_tags or [],
            relevance_score=relevance_score,
        )


@dataclass
class AnalyzedItem:
    """Item after sentiment analysis and market prediction."""
    source: str
    type: str
    title: Optional[str]
    published_at: str
    content: str
    clean_content: str
    url: str
    fetched_at: str
    topic_tags: List[str] = field(default_factory=list)
    relevance_score: float = 0.0
    sentiment_score: float = 0.0        # -1.0 ~ +1.0
    sentiment_label: str = "neutral"    # "positive" | "negative" | "neutral"
    market_impact: str = "neutral"      # "bullish" | "bearish" | "neutral"
    affected_sectors: List[str] = field(default_factory=list)
    confidence: float = 0.0             # 0.0 ~ 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_cleaned(cls, item: CleanedItem,
                     sentiment_score: float = 0.0,
                     sentiment_label: str = "neutral",
                     market_impact: str = "neutral",
                     affected_sectors: List[str] = None,
                     confidence: float = 0.0) -> "AnalyzedItem":
        return cls(
            source=item.source,
            type=item.type,
            title=item.title,
            published_at=item.published_at,
            content=item.content,
            clean_content=item.clean_content,
            url=item.url,
            fetched_at=item.fetched_at,
            topic_tags=item.topic_tags,
            relevance_score=item.relevance_score,
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
            market_impact=market_impact,
            affected_sectors=affected_sectors or [],
            confidence=confidence,
        )

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "data_sources": {
        "google_news_rss": {"enabled": True},
        "gnews_api": {"enabled": True, "api_key": ""},
        "truth_social": {"enabled": True},
        "nitter": {"enabled": True},
    },
    "fetch": {
        "max_items_per_source": 50,
        "hours_back": 48,
    },
    "clean": {
        "min_content_length": 50,
        "relevance_threshold": 0.3,
    },
    "sentiment_engine": "vader",  # "vader" | "finbert"
    "schedule_interval_hours": 4,
    "data_dir": "data",
}


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load config from JSON file, falling back to defaults for missing keys."""
    config = dict(DEFAULT_CONFIG)
    if config_path is None:
        # Look in the skill root's assets/ directory first, then CWD
        for candidate in [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"),
            os.path.join(os.getcwd(), "config.json"),
        ]:
            if os.path.isfile(candidate):
                config_path = candidate
                break
    if config_path and os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        _deep_merge(config, user_cfg)
    return config


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 15  # seconds


def http_get(url: str, params: Optional[dict] = None,
             headers: Optional[dict] = None, retries: int = 1,
             timeout: int = REQUEST_TIMEOUT) -> Optional[str]:
    """Simple GET with retry. Returns response text or None on failure."""
    import requests

    hdrs = {"User-Agent": _DEFAULT_UA}
    if headers:
        hdrs.update(headers)

    for attempt in range(1 + retries):
        try:
            resp = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            logging.warning("HTTP GET %s attempt %d failed: %s", url, attempt + 1, exc)
    return None

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """Current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_datetime(dt_str: str) -> Optional[datetime]:
    """Try to parse a datetime string from various common formats."""
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None

# ---------------------------------------------------------------------------
# Dedup index
# ---------------------------------------------------------------------------

def url_hash(url: str) -> str:
    """SHA-256 hash of a URL for dedup."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class DedupIndex:
    """Persistent URL dedup index backed by a JSON file."""

    def __init__(self, path: str):
        self.path = path
        self._seen: Set[str] = set()
        self._load()

    def _load(self) -> None:
        if os.path.isfile(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._seen = set(data) if isinstance(data, list) else set()

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(sorted(self._seen), f)

    def is_seen(self, url: str) -> bool:
        return url_hash(url) in self._seen

    def add(self, url: str) -> None:
        self._seen.add(url_hash(url))

    def __len__(self) -> int:
        return len(self._seen)

# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------

def save_json(data: Any, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: str) -> Any:
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_dir: str = "data/logs", level: int = logging.INFO) -> None:
    os.makedirs(log_dir, exist_ok=True)
    handler = TimedRotatingFileHandler(
        os.path.join(log_dir, "trump_watcher.log"),
        when="midnight", backupCount=14, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    # Also log to stderr for interactive use
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(console)

# ---------------------------------------------------------------------------
# Data directory helpers
# ---------------------------------------------------------------------------

def ensure_data_dirs(base: str = "data") -> Dict[str, str]:
    """Create and return paths for raw/, cleaned/, analyzed/, reports/, logs/."""
    dirs = {}
    for sub in ("raw", "cleaned", "analyzed", "reports", "logs"):
        p = os.path.join(base, sub)
        os.makedirs(p, exist_ok=True)
        dirs[sub] = p
    return dirs

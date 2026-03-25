#!/usr/bin/env python3
"""
Market impact prediction engine for Trump-Watcher.
Maps topic tags to market sectors, combines with sentiment scores to produce
bullish/bearish/neutral signals with confidence ratings.
Reads data/analyzed/ and outputs prediction report to data/reports/.
"""

import argparse
import glob
import logging
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    AnalyzedItem,
    ensure_data_dirs,
    load_config,
    load_json,
    parse_datetime,
    save_json,
    setup_logging,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Topic -> Sector impact mapping rules
# ---------------------------------------------------------------------------

TOPIC_IMPACT_RULES: Dict[str, Dict[str, Any]] = {
    "tariff": {
        "affected_sectors": ["Manufacturing", "Tech", "Retail", "Agriculture"],
        "default_direction": "bearish",
        "weight": 0.9,
        "description": "Tariffs typically hurt importers/exporters, raise costs",
    },
    "trade_war": {
        "affected_sectors": ["Tech", "Manufacturing", "Semiconductors", "Agriculture"],
        "default_direction": "bearish",
        "weight": 0.95,
        "description": "Trade wars create broad market uncertainty",
    },
    "sanctions": {
        "affected_sectors": ["Energy", "Finance", "Tech", "Defense"],
        "default_direction": "bearish",
        "weight": 0.8,
        "description": "Sanctions disrupt supply chains and trade",
    },
    "fed": {
        "affected_sectors": ["Finance", "Real Estate", "Tech", "Bonds"],
        "default_direction": "neutral",
        "weight": 0.85,
        "description": "Fed policy impacts vary: rate cuts bullish, hikes bearish",
    },
    "tax": {
        "affected_sectors": ["All Sectors", "Finance", "Tech", "Small Cap"],
        "default_direction": "bullish",
        "weight": 0.8,
        "description": "Tax cuts generally boost corporate earnings",
    },
    "china": {
        "affected_sectors": ["Tech", "Semiconductors", "Manufacturing", "EV"],
        "default_direction": "bearish",
        "weight": 0.85,
        "description": "China tensions create uncertainty for exposed sectors",
    },
    "nato": {
        "affected_sectors": ["Defense", "Aerospace"],
        "default_direction": "bullish",
        "weight": 0.6,
        "description": "NATO discussions often lead to defense spending",
    },
    "oil_energy": {
        "affected_sectors": ["Energy", "Oil & Gas", "Utilities", "Renewables"],
        "default_direction": "neutral",
        "weight": 0.75,
        "description": "Energy policy affects sector rotation",
    },
    "crypto": {
        "affected_sectors": ["Crypto", "Fintech", "Finance"],
        "default_direction": "neutral",
        "weight": 0.7,
        "description": "Crypto regulation or support affects digital assets",
    },
    "immigration": {
        "affected_sectors": ["Agriculture", "Construction", "Healthcare"],
        "default_direction": "neutral",
        "weight": 0.5,
        "description": "Immigration policy impacts labor-intensive sectors",
    },
    "tech": {
        "affected_sectors": ["Tech", "Social Media", "Semiconductors"],
        "default_direction": "bearish",
        "weight": 0.75,
        "description": "Tech regulation and antitrust create uncertainty",
    },
    "defense": {
        "affected_sectors": ["Defense", "Aerospace", "Cybersecurity"],
        "default_direction": "bullish",
        "weight": 0.7,
        "description": "Military spending benefits defense contractors",
    },
    "economy": {
        "affected_sectors": ["All Sectors", "Consumer Discretionary", "Finance"],
        "default_direction": "neutral",
        "weight": 0.8,
        "description": "Broad economic commentary moves indices",
    },
    "stock_market": {
        "affected_sectors": ["All Sectors", "Finance"],
        "default_direction": "neutral",
        "weight": 0.9,
        "description": "Direct market commentary has immediate impact",
    },
}

# ---------------------------------------------------------------------------
# Prediction logic
# ---------------------------------------------------------------------------

def compute_recency_factor(published_at: str, half_life_hours: float = 12.0) -> float:
    """Exponential decay factor: 1.0 for now, ~0.5 at half_life_hours."""
    pub_dt = parse_datetime(published_at)
    if not pub_dt:
        return 0.5
    if pub_dt.tzinfo is None:
        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    age_hours = (now - pub_dt).total_seconds() / 3600
    if age_hours < 0:
        age_hours = 0
    return math.exp(-0.693 * age_hours / half_life_hours)


def predict_item(item: AnalyzedItem) -> AnalyzedItem:
    """Add market prediction fields to an analyzed item."""
    if not item.topic_tags:
        item.market_impact = "neutral"
        item.affected_sectors = []
        item.confidence = 0.1
        return item

    recency = compute_recency_factor(item.published_at)
    sentiment = item.sentiment_score

    sector_scores: Dict[str, float] = defaultdict(float)
    sector_counts: Dict[str, int] = defaultdict(int)
    total_weight = 0.0
    weighted_direction = 0.0

    for tag in item.topic_tags:
        rule = TOPIC_IMPACT_RULES.get(tag)
        if not rule:
            continue

        direction_val = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}.get(
            rule["default_direction"], 0.0
        )

        # Combine sentiment with default direction:
        # - If sentiment aligns with direction, amplify
        # - If sentiment opposes, reduce or flip
        if abs(sentiment) > 0.1:
            effective_direction = sentiment
        else:
            effective_direction = direction_val * 0.5

        w = rule["weight"]
        impact_score = effective_direction * w * recency
        weighted_direction += impact_score
        total_weight += w

        for sector in rule["affected_sectors"]:
            sector_scores[sector] += abs(impact_score)
            sector_counts[sector] += 1

    # Determine overall direction
    if total_weight > 0:
        avg_direction = weighted_direction / total_weight
    else:
        avg_direction = 0.0

    if avg_direction > 0.1:
        item.market_impact = "bullish"
    elif avg_direction < -0.1:
        item.market_impact = "bearish"
    else:
        item.market_impact = "neutral"

    # Top affected sectors
    sorted_sectors = sorted(sector_scores.items(), key=lambda x: x[1], reverse=True)
    item.affected_sectors = [s for s, _ in sorted_sectors[:5]]

    # Confidence: based on number of topic matches, sentiment strength, recency
    topic_factor = min(1.0, len(item.topic_tags) / 3.0)
    sentiment_factor = min(1.0, abs(sentiment) * 2)
    item.confidence = round(
        min(1.0, (topic_factor * 0.3 + sentiment_factor * 0.4 + recency * 0.3)), 3
    )

    return item

# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(items: List[AnalyzedItem]) -> Dict[str, Any]:
    """Generate a comprehensive market impact summary report."""
    if not items:
        return {"status": "no_data", "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    # Aggregate stats
    total = len(items)
    bullish_count = sum(1 for i in items if i.market_impact == "bullish")
    bearish_count = sum(1 for i in items if i.market_impact == "bearish")
    neutral_count = sum(1 for i in items if i.market_impact == "neutral")

    avg_sentiment = sum(i.sentiment_score for i in items) / total
    avg_confidence = sum(i.confidence for i in items) / total

    # Weighted direction (by confidence)
    weighted_sum = sum(
        (1 if i.market_impact == "bullish" else -1 if i.market_impact == "bearish" else 0)
        * i.confidence
        for i in items
    )
    if total > 0:
        weighted_signal = weighted_sum / total
    else:
        weighted_signal = 0.0

    if weighted_signal > 0.15:
        overall_direction = "bullish"
    elif weighted_signal < -0.15:
        overall_direction = "bearish"
    else:
        overall_direction = "neutral"

    # Sector impact aggregation
    sector_impact: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"bullish": 0, "bearish": 0, "neutral": 0, "total_score": 0.0}
    )
    for item in items:
        for sector in item.affected_sectors:
            sector_impact[sector][item.market_impact] += 1
            sector_impact[sector]["total_score"] += (
                item.sentiment_score * item.confidence
            )

    # Topic frequency
    topic_freq: Dict[str, int] = defaultdict(int)
    for item in items:
        for tag in item.topic_tags:
            topic_freq[tag] += 1

    # Sentiment distribution
    positive_count = sum(1 for i in items if i.sentiment_label == "positive")
    negative_count = sum(1 for i in items if i.sentiment_label == "negative")
    neutral_sent = sum(1 for i in items if i.sentiment_label == "neutral")

    # Top impactful items (highest confidence)
    top_items = sorted(items, key=lambda x: x.confidence, reverse=True)[:5]

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "total_items_analyzed": total,
            "overall_market_direction": overall_direction,
            "weighted_signal_score": round(weighted_signal, 4),
            "average_sentiment": round(avg_sentiment, 4),
            "average_confidence": round(avg_confidence, 4),
            "signal_strength": (
                "strong" if abs(weighted_signal) > 0.4
                else "moderate" if abs(weighted_signal) > 0.2
                else "weak"
            ),
        },
        "market_impact_distribution": {
            "bullish": bullish_count,
            "bearish": bearish_count,
            "neutral": neutral_count,
        },
        "sentiment_distribution": {
            "positive": positive_count,
            "negative": negative_count,
            "neutral": neutral_sent,
        },
        "top_topics": dict(sorted(topic_freq.items(), key=lambda x: x[1], reverse=True)),
        "sector_analysis": {
            sector: {
                "bullish_signals": data["bullish"],
                "bearish_signals": data["bearish"],
                "neutral_signals": data["neutral"],
                "net_impact_score": round(data["total_score"], 4),
                "direction": (
                    "bullish" if data["total_score"] > 0.1
                    else "bearish" if data["total_score"] < -0.1
                    else "neutral"
                ),
            }
            for sector, data in sorted(
                sector_impact.items(),
                key=lambda x: abs(x[1]["total_score"]),
                reverse=True,
            )[:10]
        },
        "top_impactful_items": [
            {
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at,
                "sentiment_score": item.sentiment_score,
                "sentiment_label": item.sentiment_label,
                "market_impact": item.market_impact,
                "affected_sectors": item.affected_sectors,
                "confidence": item.confidence,
                "topic_tags": item.topic_tags,
                "url": item.url,
            }
            for item in top_items
        ],
    }

    return report

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(config: dict = None) -> Dict[str, Any]:
    """Load analyzed data, run predictions, generate report."""
    if config is None:
        config = load_config()

    data_dir = config.get("data_dir", "data")
    dirs = ensure_data_dirs(data_dir)

    # Load analyzed data
    analyzed_files = sorted(glob.glob(os.path.join(dirs["analyzed"], "*.json")))
    if not analyzed_files:
        logger.info("No analyzed data files found.")
        return {"status": "no_data"}

    all_analyzed: List[dict] = []
    for fpath in analyzed_files:
        data = load_json(fpath)
        if isinstance(data, list):
            all_analyzed.extend(data)

    logger.info("Loaded %d analyzed items from %d files", len(all_analyzed), len(analyzed_files))

    # Reconstruct AnalyzedItem objects and run prediction
    items: List[AnalyzedItem] = []
    for raw in all_analyzed:
        item = AnalyzedItem(**{k: raw[k] for k in AnalyzedItem.__dataclass_fields__ if k in raw})
        item = predict_item(item)
        items.append(item)

    # Save updated analyzed items (now with predictions)
    if items:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(dirs["analyzed"], f"predicted_{ts}.json")
        save_json([item.to_dict() for item in items], out_path)
        logger.info("Saved %d predicted items to %s", len(items), out_path)

    # Generate and save report
    report = generate_report(items)
    if report.get("status") != "no_data":
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(dirs["reports"], f"report_{ts}.json")
        save_json(report, report_path)
        logger.info("Market prediction report saved to %s", report_path)

    return report


def main():
    parser = argparse.ArgumentParser(description="Run market impact prediction")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    setup_logging()
    report = run(load_config(args.config))

    summary = report.get("summary", {})
    direction = summary.get("overall_market_direction", "unknown")
    strength = summary.get("signal_strength", "unknown")
    print(f"\nMarket Direction: {direction.upper()} (strength: {strength})")
    print(f"Average Sentiment: {summary.get('average_sentiment', 0):.4f}")
    print(f"Items Analyzed: {summary.get('total_items_analyzed', 0)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Trump-Watcher unified pipeline orchestrator.
Runs: fetch -> clean -> sentiment -> predict in sequence.
Supports --once (single run) and --schedule (periodic execution).
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import ensure_data_dirs, load_config, setup_logging

logger = logging.getLogger("trump_watcher")


def run_pipeline(config: dict, skip_fetch: bool = False) -> dict:
    """Execute the full pipeline: fetch -> clean -> sentiment -> predict."""
    import fetch_news
    import fetch_trump_posts
    import clean_data
    import sentiment_analyzer
    import market_predictor

    results = {
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stages": {},
    }

    # Stage 1: Fetch
    if not skip_fetch:
        logger.info("=" * 60)
        logger.info("STAGE 1: Fetching data...")
        logger.info("=" * 60)
        try:
            news_items = fetch_news.run(config)
            results["stages"]["fetch_news"] = {"status": "ok", "count": len(news_items)}
        except Exception as e:
            logger.error("fetch_news failed: %s", e)
            results["stages"]["fetch_news"] = {"status": "error", "error": str(e)}

        try:
            post_items = fetch_trump_posts.run(config)
            results["stages"]["fetch_posts"] = {"status": "ok", "count": len(post_items)}
        except Exception as e:
            logger.error("fetch_trump_posts failed: %s", e)
            results["stages"]["fetch_posts"] = {"status": "error", "error": str(e)}
    else:
        logger.info("Skipping fetch stage (--skip-fetch)")
        results["stages"]["fetch"] = {"status": "skipped"}

    # Stage 2: Clean
    logger.info("=" * 60)
    logger.info("STAGE 2: Cleaning data...")
    logger.info("=" * 60)
    try:
        cleaned = clean_data.run(config)
        results["stages"]["clean"] = {"status": "ok", "count": len(cleaned)}
    except Exception as e:
        logger.error("clean_data failed: %s", e)
        results["stages"]["clean"] = {"status": "error", "error": str(e)}
        cleaned = []

    # Stage 3: Sentiment analysis
    logger.info("=" * 60)
    logger.info("STAGE 3: Sentiment analysis...")
    logger.info("=" * 60)
    try:
        analyzed = sentiment_analyzer.run(config)
        results["stages"]["sentiment"] = {"status": "ok", "count": len(analyzed)}
    except Exception as e:
        logger.error("sentiment_analyzer failed: %s", e)
        results["stages"]["sentiment"] = {"status": "error", "error": str(e)}

    # Stage 4: Market prediction
    logger.info("=" * 60)
    logger.info("STAGE 4: Market prediction...")
    logger.info("=" * 60)
    try:
        report = market_predictor.run(config)
        results["stages"]["prediction"] = {"status": "ok"}
        results["report_summary"] = report.get("summary", {})
    except Exception as e:
        logger.error("market_predictor failed: %s", e)
        results["stages"]["prediction"] = {"status": "error", "error": str(e)}

    results["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Log summary
    logger.info("=" * 60)
    logger.info("Pipeline complete.")
    for stage, info in results["stages"].items():
        status = info.get("status", "unknown")
        count = info.get("count", "")
        count_str = f" ({count} items)" if count != "" else ""
        logger.info("  %s: %s%s", stage, status, count_str)

    summary = results.get("report_summary", {})
    if summary:
        logger.info("Market Direction: %s (strength: %s)",
                     summary.get("overall_market_direction", "N/A"),
                     summary.get("signal_strength", "N/A"))
    logger.info("=" * 60)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Trump-Watcher: Full pipeline orchestrator"
    )
    parser.add_argument("--once", action="store_true", default=True,
                        help="Run pipeline once (default)")
    parser.add_argument("--schedule", action="store_true", default=False,
                        help="Run on a schedule (interval from config)")
    parser.add_argument("--skip-fetch", action="store_true", default=False,
                        help="Skip fetch stage, re-analyze existing data")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to config.json")
    args = parser.parse_args()

    config = load_config(args.config)
    data_dir = config.get("data_dir", "data")
    ensure_data_dirs(data_dir)
    setup_logging(os.path.join(data_dir, "logs"))

    if args.schedule:
        try:
            import schedule
        except ImportError:
            logger.error("schedule package not installed. Run: pip install schedule")
            sys.exit(1)

        interval_hours = config.get("schedule_interval_hours", 4)
        logger.info("Scheduling pipeline every %d hours.", interval_hours)

        # Run immediately, then schedule
        run_pipeline(config, skip_fetch=args.skip_fetch)

        schedule.every(interval_hours).hours.do(
            run_pipeline, config=config, skip_fetch=args.skip_fetch
        )

        try:
            while True:
                schedule.run_pending()
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user.")
    else:
        results = run_pipeline(config, skip_fetch=args.skip_fetch)
        summary = results.get("report_summary", {})
        if summary:
            print(f"\n{'='*50}")
            print(f"Market Direction: {summary.get('overall_market_direction', 'N/A').upper()}")
            print(f"Signal Strength:  {summary.get('signal_strength', 'N/A')}")
            print(f"Avg Sentiment:    {summary.get('average_sentiment', 0):.4f}")
            print(f"Items Analyzed:   {summary.get('total_items_analyzed', 0)}")
            print(f"{'='*50}")


if __name__ == "__main__":
    main()

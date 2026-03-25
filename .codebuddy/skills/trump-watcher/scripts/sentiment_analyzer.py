#!/usr/bin/env python3
"""
Sentiment analysis engine for Trump-Watcher.
Dual engine: VADER (default, lightweight) and FinBERT (optional, high-precision).
Reads data/cleaned/ and outputs AnalyzedItem list to data/analyzed/.
"""

import argparse
import glob
import logging
import os
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    AnalyzedItem,
    CleanedItem,
    ensure_data_dirs,
    load_config,
    load_json,
    save_json,
    setup_logging,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseSentimentAnalyzer(ABC):
    @abstractmethod
    def analyze(self, text: str) -> Tuple[float, str]:
        """Return (sentiment_score in [-1,+1], sentiment_label)."""
        ...

    @property
    @abstractmethod
    def engine_name(self) -> str:
        ...

    @staticmethod
    def score_to_label(score: float) -> str:
        if score >= 0.05:
            return "positive"
        elif score <= -0.05:
            return "negative"
        return "neutral"

# ---------------------------------------------------------------------------
# VADER engine
# ---------------------------------------------------------------------------

class VADERAnalyzer(BaseSentimentAnalyzer):
    """Rule-based sentiment analysis using VADER."""

    def __init__(self):
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        self._sia = SentimentIntensityAnalyzer()
        logger.info("VADER sentiment analyzer initialized.")

    @property
    def engine_name(self) -> str:
        return "vader"

    def analyze(self, text: str) -> Tuple[float, str]:
        scores = self._sia.polarity_scores(text)
        compound = scores["compound"]  # already in [-1, +1]
        return round(compound, 4), self.score_to_label(compound)

# ---------------------------------------------------------------------------
# FinBERT engine
# ---------------------------------------------------------------------------

class FinBERTAnalyzer(BaseSentimentAnalyzer):
    """Transformer-based financial sentiment analysis using ProsusAI/finbert."""

    def __init__(self):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        import torch

        model_name = "ProsusAI/finbert"
        logger.info("Loading FinBERT model: %s (this may take a moment)...", model_name)
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self._model.eval()
        self._labels = ["positive", "negative", "neutral"]
        logger.info("FinBERT model loaded successfully.")

    @property
    def engine_name(self) -> str:
        return "finbert"

    def analyze(self, text: str) -> Tuple[float, str]:
        import torch

        inputs = self._tokenizer(
            text, return_tensors="pt", truncation=True, max_length=512, padding=True
        )
        with torch.no_grad():
            outputs = self._model(**inputs)
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]

        # probs order: positive, negative, neutral
        pos, neg, neu = probs[0].item(), probs[1].item(), probs[2].item()

        # Map to compound score: positive contributes +, negative -, neutral 0
        score = pos - neg  # range [-1, +1]
        label = self._labels[probs.argmax().item()]

        return round(score, 4), label

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_analyzer(engine: str = "vader") -> BaseSentimentAnalyzer:
    """Create sentiment analyzer, with fallback from finbert to vader."""
    if engine == "finbert":
        try:
            return FinBERTAnalyzer()
        except Exception as e:
            logger.warning("FinBERT initialization failed (%s), falling back to VADER.", e)
            return VADERAnalyzer()
    return VADERAnalyzer()

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def analyze_items(cleaned_items: List[dict],
                  analyzer: BaseSentimentAnalyzer) -> List[AnalyzedItem]:
    """Run sentiment analysis on cleaned items."""
    results: List[AnalyzedItem] = []

    for raw in cleaned_items:
        item = CleanedItem(**{k: raw[k] for k in CleanedItem.__dataclass_fields__ if k in raw})

        text = item.clean_content or item.content
        if not text.strip():
            continue

        try:
            score, label = analyzer.analyze(text)
        except Exception as e:
            logger.warning("Sentiment analysis failed for %s: %s", item.url, e)
            score, label = 0.0, "neutral"

        results.append(AnalyzedItem.from_cleaned(
            item,
            sentiment_score=score,
            sentiment_label=label,
        ))

    logger.info("Sentiment analysis (%s): processed %d items",
                analyzer.engine_name, len(results))
    return results

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(config: dict = None) -> List[AnalyzedItem]:
    """Load cleaned data, run sentiment analysis, save results."""
    if config is None:
        config = load_config()

    data_dir = config.get("data_dir", "data")
    dirs = ensure_data_dirs(data_dir)

    engine = config.get("sentiment_engine", "vader")
    analyzer = create_analyzer(engine)

    # Load cleaned data
    cleaned_files = sorted(glob.glob(os.path.join(dirs["cleaned"], "*.json")))
    if not cleaned_files:
        logger.info("No cleaned data files found.")
        return []

    all_cleaned: List[dict] = []
    for fpath in cleaned_files:
        data = load_json(fpath)
        if isinstance(data, list):
            all_cleaned.extend(data)

    logger.info("Loaded %d cleaned items from %d files", len(all_cleaned), len(cleaned_files))

    # Analyze
    analyzed = analyze_items(all_cleaned, analyzer)

    # Save
    if analyzed:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(dirs["analyzed"], f"analyzed_{ts}.json")
        save_json([item.to_dict() for item in analyzed], out_path)
        logger.info("Saved %d analyzed items to %s", len(analyzed), out_path)

    return analyzed


def main():
    parser = argparse.ArgumentParser(description="Run sentiment analysis on cleaned data")
    parser.add_argument("--engine", choices=["vader", "finbert"], default=None)
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    setup_logging()
    config = load_config(args.config)
    if args.engine:
        config["sentiment_engine"] = args.engine

    analyzed = run(config)
    print(f"Analyzed {len(analyzed)} items using {config.get('sentiment_engine', 'vader')} engine.")


if __name__ == "__main__":
    main()

---
name: trump-watcher
description: "Track and analyze Trump social media posts and related news for stock market impact prediction. This skill should be used when users ask about Trump recent statements, policy announcements, or their potential impact on the stock market. It fetches data from multiple sources, cleans and filters content, performs sentiment analysis, and generates market impact predictions with sector-level detail. Trigger when users mention Trump rhetoric analysis, Trump market impact, tariff news sentiment, or political risk assessment for trading."
---

# Trump Watcher

## Overview

This skill provides a complete pipeline for monitoring Trump-related public statements and news, analyzing their sentiment, and predicting stock market impact. It operates in four stages: **Fetch → Clean → Analyze → Predict**, producing structured JSON reports that include overall market direction signals, affected sector analysis, and confidence ratings.

## When to Use

- User asks about Trump's recent public statements or policy announcements
- User wants to assess how Trump's rhetoric might affect stock markets
- User needs sentiment analysis of Trump-related news
- User requests a market impact report based on political developments
- User mentions tariffs, trade war, sanctions, or other Trump-related policy topics in a market context

## Workflow

### Prerequisites

1. Ensure Python 3.9+ is available
2. Install dependencies:
   ```bash
   pip install -r scripts/requirements.txt
   ```
3. (Optional) Copy `assets/config_template.json` to the skill root as `config.json` and customize settings
4. (Optional) Set `GNEWS_API_KEY` environment variable for GNews API access

### Full Pipeline Execution

Run the complete pipeline with a single command:

```bash
python scripts/run_all.py --once
```

This executes all four stages in sequence and outputs a summary to the console.

### Stage-by-Stage Execution

Each stage can be run independently for debugging or re-analysis:

#### Stage 1: Fetch Data

```bash
python scripts/fetch_news.py --max-items 50 --hours-back 48
python scripts/fetch_trump_posts.py --max-items 50 --hours-back 48
```

- Fetches from Google News RSS, GNews API, Truth Social mirrors, and Nitter instances
- Output: `data/raw/*.json` (FetchedItem format)
- Each source is isolated; failure of one does not block others

#### Stage 2: Clean & Filter

```bash
python scripts/clean_data.py
```

- Strips HTML, normalizes Unicode, deduplicates by URL hash and content hash
- Filters out short content (<50 chars) and low-relevance items
- Identifies topic tags (tariff, trade_war, sanctions, fed, tax, china, etc.)
- Output: `data/cleaned/*.json` (CleanedItem format)

#### Stage 3: Sentiment Analysis

```bash
python scripts/sentiment_analyzer.py --engine vader
```

- Default engine: VADER (rule-based, fast, no external model download)
- Optional engine: FinBERT (`--engine finbert`, requires `transformers` + `torch`, ~440MB model download)
- Scores each item from -1.0 (very negative) to +1.0 (very positive)
- FinBERT falls back to VADER automatically on failure
- Output: `data/analyzed/*.json` (AnalyzedItem format)

#### Stage 4: Market Prediction

```bash
python scripts/market_predictor.py
```

- Maps topic tags to affected market sectors using rule-based engine
- Combines sentiment score, topic weight, and recency factor into impact prediction
- Generates per-item predictions (bullish/bearish/neutral + confidence)
- Produces comprehensive summary report with sector analysis
- Output: `data/analyzed/predicted_*.json` + `data/reports/report_*.json`

### Scheduled Execution

Run the pipeline on a recurring schedule (default: every 4 hours):

```bash
python scripts/run_all.py --schedule
```

Stop with Ctrl+C.

### Re-analyze Existing Data

Skip fetching and re-run analysis on previously fetched data:

```bash
python scripts/run_all.py --once --skip-fetch
```

## Interpreting the Report

The report at `data/reports/report_*.json` contains:

### Summary Section
- **overall_market_direction**: `bullish`, `bearish`, or `neutral` — the aggregate signal
- **weighted_signal_score**: -1.0 to +1.0 — strength and direction of the signal
- **signal_strength**: `strong` (|score| > 0.4), `moderate` (> 0.2), or `weak`
- **average_sentiment**: Mean sentiment across all analyzed items
- **average_confidence**: Mean prediction confidence

### Sector Analysis
Each sector entry shows:
- Number of bullish/bearish/neutral signals
- Net impact score (positive = bullish, negative = bearish)
- Overall direction for that sector

### Top Topics
Frequency map of identified policy topics — shows which themes dominate current discourse.

### Top Impactful Items
The 5 items with highest prediction confidence, including their sentiment, market impact, and source URLs for manual review.

## Configuration

Copy `assets/config_template.json` to the skill root as `config.json`:

| Setting                      | Default   | Description                                    |
|------------------------------|-----------|------------------------------------------------|
| `data_sources.*.enabled`     | `true`    | Enable/disable individual data sources         |
| `data_sources.gnews_api.api_key` | `""`  | GNews API key (or use env var `GNEWS_API_KEY`) |
| `fetch.max_items_per_source` | `50`      | Max items to fetch per source                  |
| `fetch.hours_back`           | `48`      | How far back to fetch (hours)                  |
| `clean.min_content_length`   | `50`      | Minimum character count for content             |
| `clean.relevance_threshold`  | `0.3`     | Minimum relevance score to keep item (0-1)     |
| `sentiment_engine`           | `"vader"` | `"vader"` (fast) or `"finbert"` (accurate)     |
| `schedule_interval_hours`    | `4`       | Hours between scheduled runs                   |

## References

- `references/data_sources.md` — Detailed data source configuration, URLs, rate limits, and degradation strategies
- `references/output_schema.md` — Complete JSON schema for all data models (FetchedItem, CleanedItem, AnalyzedItem, Report)
- `references/topic_impact_rules.md` — Topic-to-sector mapping rules with weights and extension guide

## Directory Structure

```
trump-watcher/
├── SKILL.md                          # This file
├── scripts/
│   ├── utils.py                      # Data models, HTTP helpers, dedup, config
│   ├── fetch_news.py                 # Google News RSS + GNews API fetcher
│   ├── fetch_trump_posts.py          # Truth Social + Nitter fetcher
│   ├── clean_data.py                 # Cleaning pipeline
│   ├── sentiment_analyzer.py         # VADER / FinBERT sentiment engine
│   ├── market_predictor.py           # Market impact prediction + report
│   ├── run_all.py                    # Pipeline orchestrator
│   └── requirements.txt              # Python dependencies
├── references/
│   ├── data_sources.md               # Data source documentation
│   ├── output_schema.md              # Output format specification
│   └── topic_impact_rules.md         # Topic-sector mapping rules
└── assets/
    └── config_template.json          # Configuration template
```

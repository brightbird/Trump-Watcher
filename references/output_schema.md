# Output Data Schema Reference

## Data Model Progression

```
FetchedItem (raw) → CleanedItem (cleaned) → AnalyzedItem (analyzed + predicted)
```

---

## 1. FetchedItem (Raw Data)

Output location: `data/raw/*.json`

| Field         | Type            | Description                                      |
|---------------|-----------------|--------------------------------------------------|
| source        | string          | `"google_news"` \| `"gnews_api"` \| `"truth_social"` \| `"nitter"` |
| type          | string          | `"news"` \| `"post"`                             |
| title         | string \| null  | Article title or truncated post text              |
| published_at  | string          | UTC ISO 8601 (`2025-03-25T12:00:00Z`)            |
| content       | string          | Raw HTML/text content                            |
| url           | string          | Source URL                                       |
| fetched_at    | string          | UTC ISO 8601 timestamp of when item was fetched  |

### Example

```json
{
  "source": "google_news",
  "type": "news",
  "title": "Trump announces new tariffs on Chinese imports",
  "published_at": "2025-03-25T10:30:00Z",
  "content": "<p>President Trump announced sweeping new tariffs...</p>",
  "url": "https://example.com/article/123",
  "fetched_at": "2025-03-25T12:00:00Z"
}
```

---

## 2. CleanedItem (After Cleaning Pipeline)

Output location: `data/cleaned/*.json`

Inherits all FetchedItem fields plus:

| Field           | Type           | Description                                    |
|-----------------|----------------|------------------------------------------------|
| clean_content   | string         | Cleaned text (no HTML, normalized Unicode)     |
| topic_tags      | string[]       | Identified topics: `["tariff", "china"]`       |
| relevance_score | float (0-1)    | Relevance score based on keyword matching      |

### Example

```json
{
  "source": "google_news",
  "type": "news",
  "title": "Trump announces new tariffs on Chinese imports",
  "published_at": "2025-03-25T10:30:00Z",
  "content": "<p>President Trump announced sweeping new tariffs...</p>",
  "clean_content": "President Trump announced sweeping new tariffs on Chinese imports affecting technology and manufacturing sectors...",
  "url": "https://example.com/article/123",
  "fetched_at": "2025-03-25T12:00:00Z",
  "topic_tags": ["tariff", "china", "trade_war"],
  "relevance_score": 0.85
}
```

---

## 3. AnalyzedItem (After Sentiment + Prediction)

Output location: `data/analyzed/*.json`

Inherits all CleanedItem fields plus:

| Field            | Type           | Description                                          |
|------------------|----------------|------------------------------------------------------|
| sentiment_score  | float (-1 ~ +1)| Sentiment score: -1 (very negative) to +1 (very positive) |
| sentiment_label  | string         | `"positive"` \| `"negative"` \| `"neutral"`          |
| market_impact    | string         | `"bullish"` \| `"bearish"` \| `"neutral"`            |
| affected_sectors | string[]       | Top affected market sectors                          |
| confidence       | float (0-1)    | Prediction confidence rating                         |

### Example

```json
{
  "source": "google_news",
  "type": "news",
  "title": "Trump announces new tariffs on Chinese imports",
  "published_at": "2025-03-25T10:30:00Z",
  "content": "<p>President Trump announced sweeping new tariffs...</p>",
  "clean_content": "President Trump announced sweeping new tariffs on Chinese imports...",
  "url": "https://example.com/article/123",
  "fetched_at": "2025-03-25T12:00:00Z",
  "topic_tags": ["tariff", "china", "trade_war"],
  "relevance_score": 0.85,
  "sentiment_score": -0.62,
  "sentiment_label": "negative",
  "market_impact": "bearish",
  "affected_sectors": ["Tech", "Manufacturing", "Semiconductors", "Agriculture"],
  "confidence": 0.78
}
```

---

## 4. Market Report (Summary)

Output location: `data/reports/report_*.json`

| Field                     | Type    | Description                                 |
|---------------------------|---------|---------------------------------------------|
| generated_at              | string  | UTC ISO 8601 report generation time         |
| summary.total_items_analyzed | int  | Number of items in analysis                 |
| summary.overall_market_direction | string | `"bullish"` \| `"bearish"` \| `"neutral"` |
| summary.weighted_signal_score | float | Weighted direction signal (-1 ~ +1)       |
| summary.average_sentiment | float   | Average sentiment across all items          |
| summary.average_confidence | float  | Average prediction confidence               |
| summary.signal_strength   | string  | `"strong"` \| `"moderate"` \| `"weak"`     |
| market_impact_distribution | object | Count of bullish/bearish/neutral items      |
| sentiment_distribution    | object  | Count of positive/negative/neutral items    |
| top_topics                | object  | Topic frequency map                         |
| sector_analysis           | object  | Per-sector impact analysis                  |
| top_impactful_items       | array   | Top 5 highest-confidence items              |

# Topic-Sector Impact Mapping Rules

This document defines the mapping between Trump-related policy topics and their expected impact on market sectors. These rules are used by `market_predictor.py` to generate market direction predictions.

## How Impact is Calculated

For each analyzed item:
1. **Topic Tags** are identified during the cleaning stage
2. Each topic tag maps to **affected sectors** and a **default direction**
3. The **sentiment score** modulates the direction (positive sentiment can flip a bearish default, and vice versa)
4. A **recency factor** (exponential decay, half-life = 12 hours) weights recent items more heavily
5. **Final impact** = `sentiment_score × topic_weight × recency_factor`

## Topic-Sector Mapping Table

| Topic ID       | Keywords (triggers)                                         | Affected Sectors                                    | Default Direction | Weight | Notes                                    |
|----------------|------------------------------------------------------------|----------------------------------------------------|-------------------|--------|------------------------------------------|
| `tariff`       | tariff, tariffs, import tax, import duty, customs duty     | Manufacturing, Tech, Retail, Agriculture           | bearish           | 0.90   | Tariffs raise costs for importers        |
| `trade_war`    | trade war, trade deal, trade agreement, trade deficit      | Tech, Manufacturing, Semiconductors, Agriculture   | bearish           | 0.95   | Trade wars create broad uncertainty      |
| `sanctions`    | sanction, sanctions, embargo, blacklist                    | Energy, Finance, Tech, Defense                     | bearish           | 0.80   | Sanctions disrupt supply chains          |
| `fed`          | federal reserve, the fed, interest rate, rate hike/cut, powell | Finance, Real Estate, Tech, Bonds              | neutral           | 0.85   | Direction depends on rate action         |
| `tax`          | tax cut, tax reform, tax plan, tax policy, corporate tax   | All Sectors, Finance, Tech, Small Cap              | bullish           | 0.80   | Tax cuts boost corporate earnings        |
| `china`        | china, chinese, beijing, xi jinping, ccp                   | Tech, Semiconductors, Manufacturing, EV            | bearish           | 0.85   | China tensions create sector uncertainty |
| `nato`         | nato, atlantic alliance, defense spending                  | Defense, Aerospace                                 | bullish           | 0.60   | NATO talk -> defense spending increase    |
| `oil_energy`   | oil, petroleum, opec, natural gas, energy policy, drill    | Energy, Oil & Gas, Utilities, Renewables           | neutral           | 0.75   | Depends on drill vs. regulate stance     |
| `crypto`       | bitcoin, crypto, cryptocurrency, digital currency, blockchain | Crypto, Fintech, Finance                       | neutral           | 0.70   | Pro-crypto = bullish, regulation = bearish |
| `immigration`  | immigration, border, deportation, migrant, asylum, wall    | Agriculture, Construction, Healthcare              | neutral           | 0.50   | Indirect labor market impact             |
| `tech`         | big tech, silicon valley, tiktok, social media regulation  | Tech, Social Media, Semiconductors                 | bearish           | 0.75   | Regulation creates uncertainty           |
| `defense`      | military, defense spending, pentagon, missile, nuclear     | Defense, Aerospace, Cybersecurity                  | bullish           | 0.70   | Military spending benefits contractors   |
| `economy`      | economy, gdp, recession, inflation, unemployment, jobs    | All Sectors, Consumer Discretionary, Finance       | neutral           | 0.80   | Broad economic commentary moves indices  |
| `stock_market` | stock market, dow jones, s&p 500, nasdaq, wall street      | All Sectors, Finance                               | neutral           | 0.90   | Direct market commentary has immediate impact |

## Extending the Rules

To add a new topic:

1. Add the topic to `TOPIC_KEYWORDS` dict in `scripts/clean_data.py`:
   ```python
   "new_topic": ["keyword1", "keyword2", "keyword3"],
   ```

2. Add the mapping rule to `TOPIC_IMPACT_RULES` dict in `scripts/market_predictor.py`:
   ```python
   "new_topic": {
       "affected_sectors": ["Sector1", "Sector2"],
       "default_direction": "bullish",  # or "bearish" or "neutral"
       "weight": 0.7,  # 0.0 to 1.0
       "description": "Brief explanation of why this topic affects these sectors",
   },
   ```

3. Update this document with the new mapping for reference.

## Direction Determination Logic

- **Sentiment score > +0.1**: Use sentiment as direction (positive = bullish)
- **Sentiment score < -0.1**: Use sentiment as direction (negative = bearish)  
- **Sentiment ~ 0 (within +/-0.1)**: Fall back to topic's default direction at 50% strength
- **Multiple topics**: Weighted average across all matched topics
- **Overall signal**: Weighted average across all items, with confidence as weight

## Confidence Scoring

Confidence is calculated from three factors:
- **Topic coverage** (30%): More matching topics = higher confidence
- **Sentiment strength** (40%): Stronger sentiment = higher confidence
- **Recency** (30%): More recent items = higher confidence

Formula: `confidence = topic_factor * 0.3 + sentiment_factor * 0.4 + recency * 0.3`

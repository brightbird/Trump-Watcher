# Data Sources Reference

## 1. Google News RSS (Primary)

- **Type**: RSS Feed (free, no API key)
- **URL Template**: `https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en`
- **Default Query**: `Trump`
- **Rate Limit**: None (public RSS)
- **Data Fields**: title, link, published date, description/summary
- **Degradation**: If RSS feed is unreachable (HTTP timeout), skip silently and log warning

## 2. GNews API (Secondary)

- **Type**: REST API (free tier: 100 requests/day)
- **Endpoint**: `https://gnews.io/api/v4/search`
- **Parameters**:
  - `q`: Search query (default: "Trump")
  - `lang`: Language code (default: "en")
  - `max`: Max results per request (1-100)
  - `from`: Start datetime (ISO 8601)
  - `apikey`: API key (required)
- **API Key**: Set via `config.json` field `data_sources.gnews_api.api_key` or environment variable `GNEWS_API_KEY`
- **Free Tier Limits**: 100 requests/day, 10 articles/request
- **Degradation**: If API key missing or quota exceeded, skip and log info

## 3. Truth Social Mirrors (Social Media)

- **Type**: RSS Feed from public mirrors
- **Mirror List** (tried in order):
  1. `https://truthsocial.com/@realDonaldTrump/rss`
  2. `https://trumptruthsocial.com/rss`
- **Fallback Strategy**: Try each mirror in sequence; if all fail, skip and log warning
- **Data Fields**: title (truncated post), content, published date, link
- **Note**: Mirror availability varies; instances may go offline without notice

## 4. Nitter Instances (Social Media)

- **Type**: HTML scraping + RSS from Nitter (Twitter/X frontend)
- **Instance List** (tried in order):
  1. `https://nitter.net`
  2. `https://nitter.privacydev.net`
  3. `https://nitter.poast.org`
  4. `https://nitter.1d4.us`
- **User**: `realDonaldTrump`
- **Scraping Method**: 
  1. Try HTML page parsing (`.timeline-item` CSS selectors)
  2. Fallback to RSS feed (`/{user}/rss`)
- **Fallback Strategy**: Try each instance; if all fail, skip and log warning
- **Note**: Nitter instances frequently change; update the instance list in `fetch_trump_posts.py` as needed

## General Degradation Policy

- Each data source is wrapped in try-except; failure of one source does NOT block others
- All failures are logged with WARNING or ERROR level
- Pipeline continues with whatever data was successfully fetched
- If zero items are fetched from all sources, subsequent stages (clean/analyze/predict) will output empty results gracefully

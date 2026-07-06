### 7.6.0 [04-07-2026]
**Added** DiscourseAPI response caching and rate-limit handling
- New optional `cache` parameter on `DiscourseAPI`: pass a `ResponseCache` to cache responses per request signature, serve stale data while Discourse errors, and bound retries during outages
- New `ResponseCache` (TTL + short negative TTL, expired-then-oldest eviction, per-key error backoff, and a per-instance circuit breaker: a 429 opens a cooldown for every key so workers stop hammering Discourse until it recovers)
- New `RateLimitedError` (carries `retry_after`) raised instead of a bare `HTTPError` when Discourse returns 429 and no cached response is available
- `check_for_topic_updates`/`check_for_category_updates` invalidate the corresponding cache entries when an update is detected
- Behaviour is unchanged when `cache` is not passed

### 7.5.0 [25-06-2026]
**Updated** BaseParser._replace_lists
- Unwrap `<p>` elements nested inside `<li>` elements

### 7.4.0 [24-06-2026]
**Updated** EngagePages.get_index
- Now additionaly accepts tags as a list

### 7.3.0 [16-06-2026]
**Updated** BaseParser
- Adds the following parsers: blockquotes_block, highlights_block, image_block, standard_table_block, checklist_paragraph

### 7.2.0 [04-12-2025]
**Added**
- Handle apps with both the new (sentry_sdk) and old (raven) Sentry integrations 

### 7.1.1 [04-12-2025]
**Added**
- Better error handling when api key and username is missing

### 7.1.0 [17-11-2025]
**Updated** EngagePages class
- Support optional `value` in `get_engage_pages_tags` to return tags for a specific engage page type
**Fixed** DiscourseAPI filtering
- Only include `keyword` and `value` when both are provided; same for `second_keyword`/`second_value` to avoid sending `None` to the Data Explorer API

### 7.0.0 [01-07-2025]
**Added** Events class
- Created a new class to handle events from 'Discourse Calender (and events)' API
**Added** EventsParser class
- Created a new parser to process the events retrieve by the Events class
**Updated** check_for_category_updates & check_for_topic_updates
- Moved from Category into DiscourseAPI 
**Updated** Category class
- The function `get_topics_in_category` now returns an array of objects

### 6.5.0 [12-06-2025]
**Updated** Discourse API
- Created a new API to query upcoming events in a category
**Updated** Category class
- Exposes the events API on the Category class

### 6.4.0 [10-06-2025]
**Updated** CategoryParser
- Will split a link found in metadata tables into its href ('url') and text content ('text'), as properties on the table row item.
- Handles tables positioned below the string [details=NAME] and nested in a `<details>` element.
**Updated** test_parser.py
- Added tests for the Category parser

### 6.3.0 [02-07-2025]
**Updated** EngagePages class
- Remove duplicated tags from the list of tags returned from `get_engage_pages_tags`

### 6.2.0 [28-04-2025]
**Added** _inject_custom_css def
- A function that finds css directives (`[style=CLASSNAME]`) in the soup and applies to them to the next found element.

### 6.1.1 [12-03-2025]
**Updated** EngagePages class
- Pass values for the provided keys, even if the values are empty or null, as they can be a filter themselves.

### 6.1.0 [25-01-2025]
**Updated** Category class
- Check for additions or deletions of topics within a category and update cached data if needed

### 6.0.0 [28-01-2025]
**Updated** Category class 
- Removed to template handling from within the Category class.
- Bump to 6.0.0, as the previous update was a major

### 5.8.0 [28-01-2025]
**Added** Category class 
- A generic class for processing discourse categories and the topics they contain

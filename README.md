# canonicalwebteam.discourse

Flask extension to integrate discourse content generated to docs to your website. This project was previously named `discourse_docs`.

## Writing documentation

Documentation for how to write documentation pages in Discourse for consumption by this module and how to configure the website to use the module can be found [in the Canonical discourse](https://discourse.canonical.com/t/creating-discourse-based-documentation-pages/159).

Example Flask template for documentation pages can be found in [`examples`](/examples/) folder. Please refer to the [README](/examples/README.md) in that folder for more information.

## Install

Install the project with pip: `pip install canonicalwebteam.discourse`

You can add the extension on your project as follows, replacing, at least, `base_url` and `index_topic_id` with your own settings:

```python
import talisker.requests
from canonicalwebteam.discourse import DiscourseAPI, Tutorials, TutorialParser

app = Flask("myapp")
session = talisker.requests.get_session()

discourse = Tutorials(
    parser=TutorialParser(
        api=DiscourseAPI(
            base_url="https://forum.example.com/", session=session
        ),
        index_topic_id=321,
        url_prefix="/docs",
    ),
    document_template="docs/document.html",
    url_prefix="/docs",
)
discourse.init_app(app)
```

Once this is added you will need to add the file `document.html` to your template folder.

## Response caching and rate-limit handling (optional)

Discourse rate-limits API credentials (HTTP 429). Sites that fetch content
from Discourse on every page render will exhaust that limit whenever
crawlers cause bursts of traffic, turning every Discourse-backed page into
a 500. Passing a `ResponseCache` to `DiscourseAPI` bounds how often each
unique request reaches Discourse, serves the last known data while
Discourse is erroring, and raises a typed `RateLimitedError` (instead of a
bare `HTTPError`) when Discourse returns 429 and nothing is cached.

```python
from canonicalwebteam.discourse import DiscourseAPI, ResponseCache

api = DiscourseAPI(
    base_url="https://forum.example.com/",
    session=session,
    api_key=DISCOURSE_API_KEY,
    api_username=DISCOURSE_API_USERNAME,
    cache=ResponseCache(
        ttl=300,  # seconds a successful response is served from memory
        negative_ttl=60,  # empty results expire faster
        max_size=2000,  # per-worker entry cap
        error_retry=30,  # retry a failing Discourse at most this often
    ),
)
```

Consumers decide what a rate limit means for them, typically a 503 with
`Retry-After` rather than a 500:

```python
from canonicalwebteam.discourse import RateLimitedError


@app.errorhandler(RateLimitedError)
def discourse_rate_limited(error):
    response = flask.make_response(
        flask.render_template("503.html"), 503
    )
    response.headers["Retry-After"] = str(error.retry_after)
    return response
```

Notes:

- The cache is per-process: each worker warms independently, so a page
  costs at most one Discourse call per worker per `ttl` seconds.
- A 429 opens a circuit breaker on the whole `ResponseCache` (one cache
  maps to one API key, i.e. one quota): until the cooldown expires, all
  keys serve stale data or raise `RateLimitedError` without contacting
  Discourse, honouring Discourse's `Retry-After` header.
- `check_for_topic_updates` and `check_for_category_updates` invalidate
  the corresponding cache entries when they detect an update, so edited
  content is re-fetched immediately rather than waiting out the TTL.
- When `cache` is not passed, behaviour is exactly as before — the
  feature is fully opt-in.

## Local development

For local development, it's best to test this module with one of our website projects like [ubuntu.com](https://github.com/canonical-web-and-design/ubuntu.com/). For more information, follow [this guide (internal only)](https://discourse.canonical.com/t/how-to-run-our-python-modules-for-local-development/308).

### Running tests, linting and formatting

Tests can be run with [Tox](https://tox.wiki/en/latest/):

``` bash
pip3 install tox  # Install tox
tox               # Run tests
tox -e lint       # Check the format of Python code
tox -e format     # Reformat the Python code
```

## Instructions for Engage pages extension

Because you are viewing a protected topic, you must provide `api_key` and `api_username`. You also need an index topic id, which you can get from discourse.ubuntu.com. Your index topic must contain a metadata section. Visit the EngageParser for more information about the structure. You are encouraged to use an blueprint name that does not collide with existent blueprints. The templates must match the ones provided in the parameters indicated.

Here is an example of an implementation:

```python
engage_pages = EngagePages(
    api=DiscourseAPI(
        base_url="https://discourse.ubuntu.com/",
        session=session,
        get_topics_query_id=14,
        api_key=DISCOURSE_API_KEY, # replace with your API key
        api_username=DISCOURSE_API_USERNAME, # replace with correspoding username
    ),
    category_id=51,
    page_type="engage-pages", # one of ["engage-pages", "takeovers"]
    exclude_topics=[] # this is a list of topic ids that we want to exclude from Markdown error checks
    additional_metadata_validation=[] # list of additional keys in the metadata table that you want to validate existence for e.g. language
)
```

In your project, you need to create your own views:

```python
app.add_url_rule(
    "/engage", view_func=build_engage_index(engage_pages)
)

app.add_url_rule(
    "/engage/<path>", view_func=single_engage_page(engage_pages)
)
```

- Where `build_engage_index` would be your view for the list of engage pages, which you can get by using the method `EngagagePages(args).get_index()`
- While `single_engage_page` would be your single engage pages view, which you can get using `EngagePages(args).get_engage_page(path)`

Similarly for takeovers, you just need to pass `page_type="takeovers"`.

- To get a list of takeovers `EngagePages(args).get_index()` also.
- To get a list of active takeovers `EngagePages(args).parse_active_takeovers()`.

## Pagination
- `get_index` provides two additional arguments `limit` and `offset`, to provide pagination functionality. They default to 50 and 0 respectively.
- If you want to get all engage pages, which in the case of some sites like jp.ubuntu.com there are not that many, you can pass `limit=-1`
- Use `MaxLimitError` in the `exceptions.py` to handle excessive limit. By default, it will raise an error when it surpasses 500

## Tag filtering for Engage Pages

`get_index` and the underlying API methods accept a tag parameter that supports filtering by one or more tags using OR logic:

- **Single tag** (string, legacy): `engage_pages.get_index(tag_value="osm")`
- **Multiple tags, OR logic** (list): `engage_pages.get_index(tag_value=["osm", "gsi"])`
- **No tag filter**: omit the parameter, pass `None`, or pass an empty list

Tags are matched case-insensitively and duplicates are removed automatically. The same `str | list[str]` interface applies to the `tag` parameter of `DiscourseAPI.get_engage_pages_by_tag()` and the `tag_value` parameter of `DiscourseAPI.get_engage_pages_by_param()`.


## Instructions for Category class usage

This works similar to the other class but exposes some specific functions that can be run on the index topic and the category as a whole.

It exposes a some APIs that can then be called from within a view func for processing.

Here is an example of the implementation:

```
security_vulnerabilities = Category(
    parser=CategoryParser(
        api=discourse_api,
        index_topic_id=53193,
        url_prefix="/security/vulnerabilities",
    ),
    category_id=308,
)
```

The `security_vulnerabilities` object exposes the following APIs:

- get_topic(path): Fetches a single topic using its URL (path).
- get_category_index_metadata(data_name): Retrieves metadata for the category index. You can optionally specify a data_name to get data for just one table.
- get_topics_in_category(): Retrieves all topics within the currently active category.
- get_category_events(limit=100, offset=0): Retrieves all future events in a category. Requires the Discourse Events plugin to be installed on the instance.

## Instructions for Events class usage

This class provides functionality for managing and parsing events from Discourse topics, particularly useful for event-driven websites that need to display upcoming events, featured events, and event categories. It relies on the plugin, [Discourse Calendar](https://meta.discourse.org/t/discourse-calendar-and-event/97376).

It exposes APIs that can be called from within a view function for processing event data.

Here is an example of the implementation:

```python
events = Events(
    parser=EventsParser(
        api=discourse_api,
        index_topic_id=12345,
        url_prefix="/events",
    ),
    category_id=25,
)
```

The `events` object exposes the following APIs:

- get_events(): Fetches all future events from the target Discourse instance.
- get_featured_events(target_tag="featured-event"): Retrieves all events with a given tagrte tag, defaults to "featured-event"

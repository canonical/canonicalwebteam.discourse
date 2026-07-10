import logging
import re
import time

import requests
from canonicalwebteam.discourse.exceptions import (
    DataExplorerError,
    DiscourseEventsError,
    RateLimitedError,
)
import json

logger = logging.getLogger(__name__)

# Cache key prefixes, shared between the fetch sites and the
# invalidation sites in check_for_topic_updates /
# check_for_category_updates -- keep them in sync
_KEY_TOPIC = "topic"
_KEY_CATEGORY = "category"
_KEY_TOPIC_LIST = "topic_list"
_KEY_EVENTS = "events"

# Fallback/cap for the wait between retries of a 429, when honouring
# Discourse's own Retry-After header (see _retry_after_seconds)
DEFAULT_RETRY_AFTER = 60
MAX_RETRY_AFTER = 600

# Safety cap: give up blocking on a single request after this many
# consecutive 429s, so a persistently rate-limited credential can't
# hang a request forever. Overridable via DiscourseAPI(...).
DEFAULT_MAX_RATE_LIMIT_RETRIES = 10


def _retry_after_seconds(response):
    """
    Seconds to wait before retrying a 429, taken from Discourse's
    Retry-After header. Falls back to DEFAULT_RETRY_AFTER when the
    header is missing or invalid, and is capped at MAX_RETRY_AFTER.
    """
    value = response.headers.get("Retry-After", "").strip()
    if value.isdecimal():
        return min(int(value), MAX_RETRY_AFTER)
    return DEFAULT_RETRY_AFTER


def _normalise_tags(tags):
    """
    Accept None, a single tag string, or a list of tag strings.
    Returns an ordered, whitespace-stripped, case-insensitively de-duped list.
    """
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = [tags]
    seen = set()
    result = []
    for t in tags:
        t = str(t).strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            result.append(t)
    return result


def _build_tag_regex(tags):
    """
    Build a POSIX regex alternation string from a normalised tag list.
    Returns None for an empty list (caller should omit the param entirely).
    A single tag returns '(?:tag)', multiple tags return '(?:tagA|tagB)'.
    """
    if not tags:
        return None
    return "(?:" + "|".join(re.escape(t) for t in tags) + ")"


class DiscourseAPI:
    """
    Retrieve information from a Discourse installation
    through its API
    """

    def __init__(
        self,
        base_url,
        session,
        api_key=None,
        api_username=None,
        get_topics_query_id=None,
        cache=None,
        authenticated_reads=True,
        max_rate_limit_retries=DEFAULT_MAX_RATE_LIMIT_RETRIES,
    ):
        """
        @param base_url: The Discourse URL (e.g. https://discourse.example.com)
        @param cache: Optional ResponseCache. When set, responses are cached
            per request signature, stale data is served while Discourse
            errors, and an uncacheable HTTP 429 raises RateLimitedError
            instead of HTTPError. When None (default) behaviour is unchanged.
        @param authenticated_reads: When True (default) credentials are
            attached to the session, so every request is authenticated
            and counts against the shared admin API quota. When False,
            public GET endpoints are requested anonymously (verify the
            content is publicly visible first!) and only Data Explorer
            requests carry credentials.
        @param max_rate_limit_retries: Every request blocks and retries
            on HTTP 429, honouring Discourse's Retry-After header, for up
            to this many consecutive 429s before giving up and returning
            the 429 response (default 10), so a persistently
            rate-limited credential can't hang a request forever.
        """

        self.base_url = base_url.rstrip("/")
        self.session = session
        self.get_topics_query_id = get_topics_query_id
        self.api_key = api_key
        self.api_username = api_username
        self.cache = cache
        self.max_rate_limit_retries = max_rate_limit_retries

        self._auth_headers = {}
        if api_key and api_username:
            self._auth_headers = {
                "Api-Key": api_key,
                "Api-Username": api_username,
            }
            if authenticated_reads:
                self.session.headers = dict(self._auth_headers)

    def _require_authentication(self):
        """
        Check if API credentials are available and raise an error if not.
        This should be called before accessing authenticated endpoints.
        a.k.a. Data Explorer endpoints.
        """
        if not self.api_key or not self.api_username:
            raise ValueError(
                "API authentication required: API key and username "
                "are required to access this endpoint"
            )

    def __del__(self):
        self.session.close()

    def _cached(self, key, fetch):
        """
        Route a fetch through the response cache when one is configured
        """
        if self.cache is None:
            return fetch()
        return self.cache.get(key, fetch)

    def _send_with_retry(self, request_fn, *args, **kwargs):
        """
        Issue a request, blocking and retrying while Discourse responds
        429, honouring its Retry-After header. Gives up after
        self.max_rate_limit_retries consecutive 429s and returns that
        final 429 response, so callers' existing raise_for_status /
        circuit breaker handling takes over as before.
        """
        response = request_fn(*args, **kwargs)
        retries = 0
        while (
            response.status_code == 429
            and retries < self.max_rate_limit_retries
        ):
            delay = _retry_after_seconds(response)
            retries += 1
            logger.warning(
                "Discourse rate-limited %s: blocking and retrying in "
                "%ss (%s/%s)",
                getattr(response, "url", None) or "unknown URL",
                delay,
                retries,
                self.max_rate_limit_retries,
            )
            time.sleep(delay)
            response = request_fn(*args, **kwargs)
        return response

    def _get(self, url, **kwargs):
        return self._send_with_retry(self.session.get, url, **kwargs)

    def _post(self, url, **kwargs):
        return self._send_with_retry(self.session.post, url, **kwargs)

    def _breaker_guard(self):
        """
        Short-circuit uncached requests (freshness probes) while the
        circuit breaker is open, so they stop consuming the exhausted
        rate limit too
        """
        if self.cache is not None:
            remaining = self.cache.cooldown_remaining()
            if remaining:
                logger.info(
                    "Discourse circuit breaker open (%ss left): "
                    "skipping uncached request",
                    remaining,
                )
                raise RateLimitedError(retry_after=remaining)

    def _raise_for_status_with_breaker(self, response):
        """
        raise_for_status, but a 429 opens the circuit breaker and
        surfaces as RateLimitedError when a cache is configured
        """
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            if self.cache is not None and response.status_code == 429:
                self.cache.report_rate_limit(response)
                raise RateLimitedError(
                    retry_after=self.cache.cooldown_remaining()
                ) from error
            raise

    def get_topic(self, topic_id):
        """
        Retrieve topic object by path
        """

        def fetch():
            response = self._get(f"{self.base_url}/t/{topic_id}.json")
            response.raise_for_status()
            return response.json()

        # str() so int and str topic ids share one cache entry
        return self._cached((_KEY_TOPIC, str(topic_id)), fetch)

    def get_topics(self, topic_ids):
        """
        This endpoint returns multiple topics HTML cooked content.
        This is possible with the Data Explorer plugin for Discourse
        we are using it to obtain multiple Tutorials content without
        doing multiple API calls.
        """
        self._require_authentication()

        headers = {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data;",
            **self._auth_headers,
        }

        # Run query on Data Explorer with topic IDs
        topics = ",".join([str(i) for i in topic_ids])

        def fetch():
            response = self._post(
                f"{self.base_url}/admin/plugins/explorer/"
                f"queries/{self.get_topics_query_id}/run",
                headers=headers,
                data={"params": f'{{"topics":"{topics}"}}'},
            )

            # A 429 body also carries an "errors" key; raise it as a
            # rate limit instead of a Data Explorer query error. Other
            # statuses fall through so query errors keep raising the
            # descriptive DataExplorerError below.
            if response.status_code == 429:
                response.raise_for_status()

            result = response.json()

            if "errors" in result and "rows" not in result:
                raise DataExplorerError(
                    f'{result["errors"][0]} Have you set the right api_key?'
                )

            return result["rows"]

        # Sorted so differently-ordered id lists share one cache entry
        return self._cached(
            ("topics", ",".join(sorted(topics.split(",")))), fetch
        )

    def get_topics_category(self, category_id, page=0):
        """
        Retrieves the full catergory object including metadata, groups, topics
        """

        def fetch():
            response = self._get(
                f"{self.base_url}/c/{category_id}.json?page={page}"
            )
            response.raise_for_status()
            return response.json()

        return self._cached(
            (_KEY_CATEGORY, str(category_id), str(page)), fetch
        )

    def get_events(self):
        """
        Uses Discourse Events API to retrieve events.
        Requires the Discourse Events plugin to be installed on Discourse:
        https://meta.discourse.org/t/creating-and-managing-events/149964

        Returns:
            dict: JSON response from the events endpoint containing all events
        """

        def fetch():
            response = self._get(
                f"{self.base_url}/discourse-post-event/events.json"
                f"?include_details=true&limit=100"
            )
            response.raise_for_status()
            result = response.json()

            if not isinstance(result, dict):
                raise ValueError("Unexpected response format from events API")

            return result

        try:
            return self._cached((_KEY_EVENTS,), fetch)

        except ValueError as e:
            raise ValueError(f"Failed to parse events response: {str(e)}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in events response: {str(e)}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise DiscourseEventsError(
                    "Events endpoint not found. "
                    "Is the Discourse Events plugin installed?"
                ) from e
            raise
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Network error occurred: {str(e)}")

    def get_topics_by_tag(self, tag, limit=50, offset=0):
        """
        Uses the Discourse JSON API to retrieve topics by tag.

        :param tag: The tag to filter topics by.
        :param limit: The maximum number of topics to return (default is 50,
        this is also the max).
        :param offset: The number of topics to skip (default is 0).

        Note: upstream errors are converted to ValueError, except
        RateLimitedError, which propagates when a cache is configured
        so consumers can return a 503.
        """

        def fetch():
            response = self._get(
                f"{self.base_url}/search.json"
                f"?q=tags:{tag}&limit={limit}&offset={offset}"
            )
            response.raise_for_status()
            result = response.json()

            if not isinstance(result, dict):
                raise ValueError("Unexpected response format from topics API")

            return result

        try:
            return self._cached(
                ("topics_by_tag", str(tag), str(limit), str(offset)),
                fetch,
            )

        except ValueError as e:
            raise ValueError(f"Failed to parse topics response: {str(e)}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in topics response: {str(e)}")
        except requests.exceptions.HTTPError as e:
            raise ValueError(f"HTTP error occurred: {str(e)}")
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Network error occurred: {str(e)}")

    def get_topic_list_by_category(self, category_id, limit=100, offset=0):
        """
        Uses data-explorer to query topics within a given category
        Returns a list of topics 'id', 'title', 'slug'

        Args:
        - category_id [int]: The category ID
        - limit [int]: 100 by default, also set in data explorer
        - offset [int]: 0 by default (first page)
        """
        self._require_authentication()

        # See https://discourse.ubuntu.com/admin/plugins/explorer?id=89
        data_explorer_id = 89
        headers = {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data;",
            **self._auth_headers,
        }
        params = (
            {
                "params": (
                    f'{{"category_id":"{category_id}", '
                    f'"limit":"{limit}", "offset":"{offset}"}}'
                )
            },
        )

        def fetch():
            response = self._post(
                f"{self.base_url}/admin/plugins/explorer/"
                f"queries/{data_explorer_id}/run",
                headers=headers,
                data=params[0],
            )

            response.raise_for_status()
            result = response.json()

            columns = result.get("columns", [])
            rows = result.get("rows", [])

            return [dict(zip(columns, row)) for row in rows]

        return self._cached(
            (_KEY_TOPIC_LIST, str(category_id), str(limit), str(offset)),
            fetch,
        )

    def get_topics_last_activity_time(self, topic_id):
        """
        Uses data-explorer to the last time a specifc topic was updated

        Args:
        - topic_id [int]: The topic ID
        """
        self._require_authentication()
        self._breaker_guard()

        # See https://discourse.ubuntu.com/admin/plugins/explorer?id=122
        data_explorer_id = 122
        headers = {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data;",
            **self._auth_headers,
        }
        params = ({"params": (f'{{"topic_id":"{topic_id}"}} ')},)
        response = self._post(
            f"{self.base_url}/admin/plugins/explorer/"
            f"queries/{data_explorer_id}/run",
            headers=headers,
            data=params[0],
        )
        self._raise_for_status_with_breaker(response)
        result = response.json()

        return result["rows"]

    def get_categories_last_activity_time(self, category_id):
        """
        Uses data-explorer to get the last time a specific topic was updated

        Args:
        - category_id [int]: The category ID
        """
        self._require_authentication()
        self._breaker_guard()

        # See https://discourse.ubuntu.com/admin/plugins/explorer?id=123
        data_explorer_id = 123
        headers = {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data;",
            **self._auth_headers,
        }
        params = ({"params": (f'{{"category_id":"{category_id}"}} ')},)
        response = self._post(
            f"{self.base_url}/admin/plugins/explorer/"
            f"queries/{data_explorer_id}/run",
            headers=headers,
            data=params[0],
        )
        self._raise_for_status_with_breaker(response)
        result = response.json()

        return result["rows"]

    def check_for_topic_updates(self, topic_id, last_updated=None) -> tuple:
        """
        Check if a topic has been updated since the last_updated timestamp

        Args:
        - topic_id (int): The topic ID
        - last_updated (timestamp): The last time the topic was updated

        Returns:
        - tuple: (bool, timestamp) - whether there are updates and the most
        recent update time
        """
        most_recent_update = self.get_topics_last_activity_time(topic_id)[0][1]

        if last_updated and most_recent_update > last_updated:
            if self.cache is not None:
                # Drop the cached topic so the caller's re-parse sees
                # the new content instead of latching stale cached data
                self.cache.invalidate(_KEY_TOPIC, str(topic_id))
            return True, most_recent_update
        else:
            return False, most_recent_update

    def check_for_category_updates(
        self, category_id, last_updated=None
    ) -> tuple:
        """
        Check if the category has had topics added or removed since the
        last_updated timestamp

        Args:
        - category_id (int): The category ID
        - last_updated (timestamp): The last time the category was updated

        Returns:
        - tuple: (bool, timestamp) - whether there are updates and the most
        recent update time
        """
        most_recent_update = self.get_categories_last_activity_time(
            category_id
        )[0][1]

        if last_updated and most_recent_update > last_updated:
            if self.cache is not None:
                # Invalidate every fetch path the category consumers
                # use, or they re-read stale cache and latch it
                self.cache.invalidate(_KEY_CATEGORY, str(category_id))
                self.cache.invalidate(_KEY_TOPIC_LIST, str(category_id))
                self.cache.invalidate(_KEY_EVENTS)
            return True, most_recent_update
        else:
            return False, most_recent_update

    def get_engage_pages_by_param(
        self,
        category_id,
        key=None,
        value=None,
        limit=50,
        offset=0,
        second_key=None,
        second_value=None,
        tag_value=None,
    ):
        """
        Uses data-explorer to query topics with the category
        Engages pages or Takeovers

        Accepts keys and values that are listed in the metadata
        of engage pages or takovers e.g. in the following metadata
        table from /t/nfv-orchestration-for-open-source-telco/25422

        Key	          Value
        image	      https://assets.ubuntu.com/v1/176a11dd.svg
        image_width	  365
        image_height  236
        meta_image
        meta_copydoc  https://docs.google.com/document/d/1M_Oe
        banner_class  dark
        webinar_code  521943
        topic_name	  NFV Orchestration For Open Source Telco
        path	      /engage/nfv-management-and-orchestration
        -charmed-open-source-mano
        type	      webinar
        tags	      osm, gsi, cloud, open source, orchestration

        To get an engage page by path:
        key = path
        value = /engage/nfv-management-and-orchestration-charmed-open
        -source-mano

        Args:
        - category_id [int]: The category ID
        - key [str]: Metadata key to filter by
        - value [str]: Metadata value to filter by
        - limit [int]: 50 by default, also set in data explorer
        - offset [int]: 0 by default (first page)
        - second_key [str]: Second metadata key to filter by
        - second_value [str]: Second metadata value to filter by
        - tag_value [str | list[str]]: Filter by tag(s). Accepts either a
          single tag string (e.g. "osm") or a list of tag strings for OR
          matching (e.g. ["osm", "gsi"]). An empty list or None returns
          all pages with no tag filter.
        """
        self._require_authentication()

        headers = {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data;",
            **self._auth_headers,
        }
        # See https://discourse.ubuntu.com/admin/plugins/explorer?id=16
        data_explorer_id = 16

        params_dict = {
            "category_id": str(category_id),
            "limit": str(limit),
            "offset": str(offset),
        }

        # Tags support a single string or a list of strings (OR logic)
        # We serialise into a POSIX regex so the existing ~* clause
        # in the Data Explorer query handles OR matching without SQL changes
        tag_regex = _build_tag_regex(_normalise_tags(tag_value))
        if tag_regex:
            params_dict["tag_value"] = tag_regex

        if key and value:
            params_dict["keyword"] = key
            params_dict["value"] = value

        if second_key and second_value:
            params_dict["second_keyword"] = second_key
            params_dict["second_value"] = second_value

        # Get all engage pages to compile list of tags
        # last resort if you need to get all pages, not performant
        if limit == -1:
            params_dict.pop("limit")
            params_dict.pop("offset")

        params = ({"params": json.dumps(params_dict)},)

        def fetch():
            response = self._post(
                f"{self.base_url}/admin/plugins/explorer/"
                f"queries/{data_explorer_id}/run",
                headers=headers,
                data=params[0],
            )

            response.raise_for_status()
            result = response.json()

            if not result["success"]:
                raise DataExplorerError(result["errors"][0])

            return result["rows"]

        return self._cached(
            ("engage_by_param", json.dumps(params_dict, sort_keys=True)),
            fetch,
        )

    def get_engage_pages_by_tag(self, category_id, tag, limit=50, offset=0):
        """
        Uses data-explorer to query engage pages by tag.

        Same functionality and return values as
        get_engage_pages_by_param, but specifically
        for querying by tags.

        Args:
        - category_id [int]: The category ID
        - tag [str | list[str]]: Filter by tag(s). Accepts either a single
          tag string (e.g. "osm") or a list of tag strings for OR matching
          (e.g. ["osm", "gsi"]). An empty list or None returns all pages
          with no tag filter.
        - limit [int]: 50 by default, also set in data explorer
        - offset [int]: 0 by default (first page)
        """
        self._require_authentication()

        headers = {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data;",
            **self._auth_headers,
        }
        # See https://discourse.ubuntu.com/admin/plugins/explorer?id=55
        data_explorer_id = 55

        params_dict = {
            "category_id": str(category_id),
            "limit": str(limit),
            "offset": str(offset),
        }

        # Tags support a single string or a list of strings (OR logic).
        # We serialise into a POSIX regex so the existing ~* clause
        # in the Data Explorer query handles OR matching without SQL changes.
        tag_regex = _build_tag_regex(_normalise_tags(tag))
        if tag_regex:
            params_dict["tag"] = tag_regex

        params = ({"params": json.dumps(params_dict)},)

        def fetch():
            response = self._post(
                f"{self.base_url}/admin/plugins/explorer/"
                f"queries/{data_explorer_id}/run",
                headers=headers,
                data=params[0],
            )

            response.raise_for_status()
            result = response.json()

            if not result["success"]:
                raise DataExplorerError(result["errors"][0])

            return result["rows"]

        return self._cached(
            ("engage_by_tag", json.dumps(params_dict, sort_keys=True)),
            fetch,
        )

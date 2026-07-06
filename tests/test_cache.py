# Standard library
import time
import unittest
from unittest.mock import Mock

# Packages
import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError

# Local
from canonicalwebteam.discourse.cache import ResponseCache
from canonicalwebteam.discourse.exceptions import RateLimitedError
from canonicalwebteam.discourse.models import DiscourseAPI


def _http_error(status_code, retry_after=None):
    response = requests.Response()
    response.status_code = status_code
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return HTTPError(response=response)


def _expire(cache, key, seconds=3600):
    """Age a cache entry so the next read attempts a refresh"""
    timestamp, value = cache._entries[key]
    cache._entries[key] = (timestamp - seconds, value)


class TestResponseCache(unittest.TestCase):
    def setUp(self):
        self.cache = ResponseCache(ttl=300)

    def test_fresh_value_served_from_cache(self):
        calls = []

        def fetch():
            calls.append(1)
            return "value"

        self.assertEqual(self.cache.get(("topic", "1"), fetch), "value")
        self.assertEqual(self.cache.get(("topic", "1"), fetch), "value")
        self.assertEqual(len(calls), 1)

    def test_expired_value_is_refetched(self):
        values = iter(["first", "second"])
        key = ("topic", "1")

        self.cache.get(key, lambda: next(values))
        _expire(self.cache, key)
        self.assertEqual(self.cache.get(key, lambda: next(values)), "second")

    def test_empty_results_expire_faster(self):
        cache = ResponseCache(ttl=300, negative_ttl=60)
        key = ("engage", "/missing")
        values = iter([[], ["found"]])

        cache.get(key, lambda: next(values))
        # Age the entry past negative_ttl but not past ttl
        _expire(cache, key, seconds=90)
        self.assertEqual(cache.get(key, lambda: next(values)), ["found"])

    def test_serves_stale_on_http_error(self):
        key = ("topic", "1")
        self.cache.get(key, lambda: "stale")
        _expire(self.cache, key)

        def failing():
            raise _http_error(500)

        self.assertEqual(self.cache.get(key, failing), "stale")

    def test_serves_stale_on_connection_error(self):
        key = ("topic", "1")
        self.cache.get(key, lambda: "stale")
        _expire(self.cache, key)

        def failing():
            raise RequestsConnectionError("connection refused")

        self.assertEqual(self.cache.get(key, failing), "stale")

    def test_stale_serve_backs_off_refetching(self):
        key = ("topic", "1")
        self.cache.get(key, lambda: "stale")
        _expire(self.cache, key)

        calls = []

        def failing():
            calls.append(1)
            raise _http_error(500)

        self.assertEqual(self.cache.get(key, failing), "stale")
        # Entry was re-stamped: the immediate retry must not fetch again
        self.assertEqual(self.cache.get(key, failing), "stale")
        self.assertEqual(len(calls), 1)

    def test_rate_limit_without_cache_raises_typed_error(self):
        def rate_limited():
            raise _http_error(429, retry_after=300)

        with self.assertRaises(RateLimitedError) as context:
            self.cache.get(("topic", "1"), rate_limited)
        self.assertEqual(context.exception.retry_after, 300)

    def test_rate_limit_retry_after_is_clamped(self):
        def rate_limited():
            raise _http_error(429, retry_after=99999)

        with self.assertRaises(RateLimitedError) as context:
            self.cache.get(("topic", "1"), rate_limited)
        self.assertLessEqual(context.exception.retry_after, 600)

    def test_rate_limit_with_cache_serves_stale(self):
        key = ("topic", "1")
        self.cache.get(key, lambda: "stale")
        _expire(self.cache, key)

        def rate_limited():
            raise _http_error(429)

        self.assertEqual(self.cache.get(key, rate_limited), "stale")

    def test_other_http_errors_without_cache_are_raised(self):
        def failing():
            raise _http_error(404)

        with self.assertRaises(HTTPError):
            self.cache.get(("topic", "1"), failing)

    def test_eviction_drops_expired_then_oldest(self):
        cache = ResponseCache(ttl=300, max_size=4)
        for index in range(4):
            cache.get(("topic", str(index)), lambda i=index: i)

        # All fresh and full: inserting a new key drops the oldest half
        cache.get(("topic", "new"), lambda: "new")

        self.assertNotIn(("topic", "0"), cache._entries)
        self.assertIn(("topic", "3"), cache._entries)
        self.assertIn(("topic", "new"), cache._entries)
        self.assertLess(len(cache._entries), 5)

    def test_invalidate_exact_key(self):
        values = iter(["first", "second"])
        key = ("topic", "1")

        self.cache.get(key, lambda: next(values))
        self.cache.invalidate("topic", "1")
        self.assertEqual(self.cache.get(key, lambda: next(values)), "second")

    def test_invalidate_by_prefix(self):
        self.cache.get(("category", "5", "0"), lambda: "page0")
        self.cache.get(("category", "5", "1"), lambda: "page1")
        self.cache.get(("topic", "9"), lambda: "topic")

        self.cache.invalidate("category", "5")

        self.assertNotIn(("category", "5", "0"), self.cache._entries)
        self.assertNotIn(("category", "5", "1"), self.cache._entries)
        self.assertIn(("topic", "9"), self.cache._entries)


def _response(json_data, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


class TestDiscourseAPICache(unittest.TestCase):
    def _make_api(self, cache=None):
        session = Mock()
        api = DiscourseAPI(
            base_url="https://discourse.example.com",
            session=session,
            api_key="key",
            api_username="user",
            cache=cache,
        )
        return api, session

    def test_without_cache_every_call_fetches(self):
        api, session = self._make_api()
        session.get.return_value = _response({"id": 5})

        api.get_topic(5)
        api.get_topic(5)

        self.assertEqual(session.get.call_count, 2)

    def test_get_topic_is_cached(self):
        api, session = self._make_api(cache=ResponseCache(ttl=300))
        session.get.return_value = _response({"id": 5})

        self.assertEqual(api.get_topic(5), {"id": 5})
        self.assertEqual(api.get_topic(5), {"id": 5})
        session.get.assert_called_once()

    def test_get_topic_int_and_str_ids_share_one_entry(self):
        api, session = self._make_api(cache=ResponseCache(ttl=300))
        session.get.return_value = _response({"id": 5})

        api.get_topic(5)
        api.get_topic("5")

        session.get.assert_called_once()

    def test_engage_pages_cached_per_params(self):
        api, session = self._make_api(cache=ResponseCache(ttl=300))
        session.post.return_value = _response(
            {"success": True, "rows": [["row"]]}
        )

        api.get_engage_pages_by_param(category_id=51, key="path", value="/x")
        api.get_engage_pages_by_param(category_id=51, key="path", value="/x")
        api.get_engage_pages_by_param(category_id=51, key="path", value="/y")

        self.assertEqual(session.post.call_count, 2)

    def test_topic_update_invalidates_cached_topic(self):
        api, session = self._make_api(cache=ResponseCache(ttl=300))
        session.get.return_value = _response({"id": 5, "title": "old"})

        api.get_topic(5)

        # The activity-time query reports an update newer than last_updated
        session.post.return_value = _response({"rows": [[5, "2026-07-03"]]})
        updated, _ = api.check_for_topic_updates(5, "2026-07-01")
        self.assertTrue(updated)

        session.get.return_value = _response({"id": 5, "title": "new"})
        self.assertEqual(api.get_topic(5)["title"], "new")

    def test_rate_limited_topic_raises_typed_error(self):
        api, session = self._make_api(cache=ResponseCache(ttl=300))
        response = requests.Response()
        response.status_code = 429
        session.get.return_value = response

        with self.assertRaises(RateLimitedError):
            api.get_topic(5)


class TestCircuitBreaker(unittest.TestCase):
    """
    One ResponseCache maps to one DiscourseAPI instance (one API key,
    one quota): a 429 anywhere opens a cooldown for every key.
    """

    def setUp(self):
        self.cache = ResponseCache(ttl=300)

    def _trip_breaker(self, retry_after=None):
        def rate_limited():
            raise _http_error(429, retry_after=retry_after)

        with self.assertRaises(RateLimitedError):
            self.cache.get(("topic", "tripwire"), rate_limited)

    def test_429_opens_breaker_for_other_keys(self):
        self._trip_breaker()
        calls = []

        def fetch():
            calls.append(1)
            return "value"

        with self.assertRaises(RateLimitedError):
            self.cache.get(("topic", "other"), fetch)
        self.assertEqual(calls, [])

    def test_open_breaker_serves_stale_without_fetching(self):
        key = ("topic", "1")
        self.cache.get(key, lambda: "stale")
        _expire(self.cache, key)
        self._trip_breaker()

        calls = []

        def fetch():
            calls.append(1)
            return "fresh"

        self.assertEqual(self.cache.get(key, fetch), "stale")
        self.assertEqual(calls, [])

    def test_breaker_respects_retry_after_header(self):
        self._trip_breaker(retry_after=300)

        with self.assertRaises(RateLimitedError) as context:
            self.cache.get(("topic", "other"), lambda: "x")
        self.assertGreater(context.exception.retry_after, 200)
        self.assertLessEqual(context.exception.retry_after, 300)

    def test_breaker_closes_after_cooldown(self):
        self._trip_breaker()
        # Force the cooldown into the past
        self.cache._cooldown_until = 0.0

        self.assertEqual(self.cache.get(("topic", "1"), lambda: "v"), "v")

    def test_429_with_stale_still_opens_breaker(self):
        key = ("topic", "1")
        self.cache.get(key, lambda: "stale")
        _expire(self.cache, key)

        def rate_limited():
            raise _http_error(429)

        # Stale is served for this key...
        self.assertEqual(self.cache.get(key, rate_limited), "stale")
        # ...but the breaker still opens for everything else
        with self.assertRaises(RateLimitedError):
            self.cache.get(("topic", "other"), lambda: "x")


class TestRevocation(unittest.TestCase):
    """
    Deleted or de-listed content (403/404/410) must stop being served,
    not live on via the stale-on-error path.
    """

    def setUp(self):
        self.cache = ResponseCache(ttl=300)

    def test_revocation_statuses_drop_stale_entry_and_raise(self):
        for status in (403, 404, 410):
            with self.subTest(status=status):
                cache = ResponseCache(ttl=300)
                key = ("topic", "1")
                cache.get(key, lambda: "revoked-content")
                _expire(cache, key)

                def gone():
                    raise _http_error(status)

                with self.assertRaises(HTTPError):
                    cache.get(key, gone)
                self.assertNotIn(key, cache._entries)

    def test_server_errors_still_serve_stale(self):
        key = ("topic", "1")
        self.cache.get(key, lambda: "stale")
        _expire(self.cache, key)

        def failing():
            raise _http_error(502)

        self.assertEqual(self.cache.get(key, failing), "stale")


class TestCategoryUpdateInvalidation(unittest.TestCase):
    def test_category_update_invalidates_topic_list_and_events(self):
        session = Mock()
        api = DiscourseAPI(
            base_url="https://discourse.example.com",
            session=session,
            api_key="key",
            api_username="user",
            cache=ResponseCache(ttl=300),
        )

        session.post.return_value = _response(
            {"columns": ["id"], "rows": [[1]]}
        )
        session.get.return_value = _response({"events": []})

        api.get_topic_list_by_category(5)
        api.get_events()
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(session.get.call_count, 1)

        # Activity query reports an update newer than last_updated
        session.post.return_value = _response({"rows": [[5, "2026-07-06"]]})
        updated, _ = api.check_for_category_updates(5, "2026-07-01")
        self.assertTrue(updated)
        self.assertEqual(session.post.call_count, 2)

        # Both consumers of the update check must refetch, not serve
        # the cached pre-update data
        session.post.return_value = _response(
            {"columns": ["id"], "rows": [[2]]}
        )
        api.get_topic_list_by_category(5)
        api.get_events()
        self.assertEqual(session.post.call_count, 3)
        self.assertEqual(session.get.call_count, 2)


class TestBreakerGuardsProbes(unittest.TestCase):
    def _make_api(self, cache):
        session = Mock()
        api = DiscourseAPI(
            base_url="https://discourse.example.com",
            session=session,
            api_key="key",
            api_username="user",
            cache=cache,
        )
        return api, session

    def test_probe_short_circuits_during_cooldown(self):
        cache = ResponseCache(ttl=300)
        api, session = self._make_api(cache)
        cache._cooldown_until = time.monotonic() + 120

        with self.assertRaises(RateLimitedError) as context:
            api.get_topics_last_activity_time(1)

        session.post.assert_not_called()
        self.assertGreater(context.exception.retry_after, 60)

    def test_probe_429_opens_breaker(self):
        cache = ResponseCache(ttl=300)
        api, session = self._make_api(cache)
        response = requests.Response()
        response.status_code = 429
        session.post.return_value = response

        with self.assertRaises(RateLimitedError):
            api.get_categories_last_activity_time(5)

        # The breaker is now open: cached fetches short-circuit
        with self.assertRaises(RateLimitedError):
            cache.get(("topic", "other"), lambda: "x")

    def test_probe_without_cache_keeps_raising_http_error(self):
        api, session = self._make_api(cache=None)
        response = requests.Response()
        response.status_code = 429
        session.post.return_value = response

        with self.assertRaises(HTTPError):
            api.get_topics_last_activity_time(1)


class TestEdgeBehaviours(unittest.TestCase):
    def test_first_429_retry_after_matches_breaker_minimum(self):
        cache = ResponseCache(ttl=300)

        def rate_limited():
            raise _http_error(429, retry_after=5)

        with self.assertRaises(RateLimitedError) as context:
            cache.get(("topic", "1"), rate_limited)
        self.assertGreaterEqual(context.exception.retry_after, 60)

    def test_max_size_one_still_evicts(self):
        cache = ResponseCache(ttl=300, max_size=1)
        cache.get(("topic", "1"), lambda: "one")
        cache.get(("topic", "2"), lambda: "two")

        self.assertEqual(len(cache._entries), 1)
        self.assertIn(("topic", "2"), cache._entries)

    def test_get_topics_key_is_order_insensitive(self):
        session = Mock()
        api = DiscourseAPI(
            base_url="https://discourse.example.com",
            session=session,
            api_key="key",
            api_username="user",
            cache=ResponseCache(ttl=300),
        )
        session.post.return_value = _response({"rows": [["cooked"]]})

        api.get_topics([1, 2])
        api.get_topics([2, 1])

        session.post.assert_called_once()


class TestViewRateLimitHandling(unittest.TestCase):
    """
    The package's own view classes must translate RateLimitedError into
    a 503, not let it escape as an unhandled exception (500).
    """

    def test_category_topic_by_id_translates_to_503(self):
        from werkzeug.exceptions import ServiceUnavailable

        from canonicalwebteam.discourse.app import Category

        parser = Mock()
        parser.api.get_topic.side_effect = RateLimitedError(retry_after=42)
        category = Category(parser, category_id=5)

        with self.assertRaises(ServiceUnavailable) as context:
            category.get_topic_by_id(9)
        self.assertEqual(context.exception.retry_after, 42)

import os
import threading
import time
import unittest
from datetime import timedelta
from unittest.mock import Mock

import requests
from requests.exceptions import HTTPError, Timeout
from sqlalchemy import create_engine, select

from canonicalwebteam.discourse.db_cache import (
    DBResponseCache,
    _discourse_cache_table,
)
from canonicalwebteam.discourse.exceptions import RateLimitedError
from canonicalwebteam.discourse.models import DiscourseAPI

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres@localhost:5432/postgres"
)


def _http_error(status_code, retry_after=None):
    response = requests.Response()
    response.status_code = status_code
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return HTTPError(response=response)


def _response(json_data, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


class DBCacheTestCase(unittest.TestCase):
    """Base class for tests that need a real Postgres-backed cache"""

    engine = None

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            TEST_DATABASE_URL, pool_size=10, max_overflow=10
        )

    def setUp(self):
        # Unique namespace per test avoids cross-test interference on
        # the shared table
        self.namespace = f"test-{self._testMethodName}-{id(self)}"
        self.cache = DBResponseCache(
            self.engine, namespace=self.namespace, ttl=timedelta(seconds=1)
        )

    def tearDown(self):
        with self.engine.begin() as conn:
            conn.execute(
                _discourse_cache_table.delete().where(
                    _discourse_cache_table.c.namespace.startswith(
                        self.namespace
                    )
                )
            )


class TestDBResponseCache(DBCacheTestCase):
    def test_miss_fetches_with_no_timeout(self):
        calls = []

        def fetch(timeout=None):
            calls.append(timeout)
            return {"id": 1}

        self.assertEqual(self.cache.get(("topic", "1"), fetch), {"id": 1})
        self.assertEqual(calls, [None])

    def test_fresh_value_served_without_fetching(self):
        calls = []

        def fetch(timeout=None):
            calls.append(timeout)
            return {"id": 1}

        self.cache.get(("topic", "1"), fetch)
        self.cache.get(("topic", "1"), fetch)
        self.assertEqual(len(calls), 1)

    def test_stale_entry_is_refreshed_with_bounded_timeout(self):
        calls = []

        def fetch(timeout=None):
            calls.append(timeout)
            return {"n": len(calls)}

        self.cache.get(("topic", "1"), fetch)
        time.sleep(1.2)
        result = self.cache.get(("topic", "1"), fetch)

        self.assertEqual(result, {"n": 2})
        self.assertEqual(calls, [None, 8])

    def test_stale_refresh_timeout_serves_stale(self):
        self.cache.get(("topic", "1"), lambda timeout=None: "stale")
        time.sleep(1.2)

        def timing_out(timeout=None):
            raise Timeout("too slow")

        self.assertEqual(self.cache.get(("topic", "1"), timing_out), "stale")

    def test_stale_refresh_429_serves_stale(self):
        self.cache.get(("topic", "1"), lambda timeout=None: "stale")
        time.sleep(1.2)

        def rate_limited(timeout=None):
            raise _http_error(429)

        self.assertEqual(self.cache.get(("topic", "1"), rate_limited), "stale")

    def test_failed_refresh_backs_off_before_retrying(self):
        self.cache.get(("topic", "1"), lambda timeout=None: "stale")
        time.sleep(1.2)

        def failing(timeout=None):
            raise _http_error(500)

        self.cache.get(("topic", "1"), failing)  # claims the refresh, fails

        calls = []

        def should_not_be_called(timeout=None):
            calls.append(1)
            return "unreached"

        # Immediate retry lands inside the backoff window: no new fetch
        self.assertEqual(
            self.cache.get(("topic", "1"), should_not_be_called), "stale"
        )
        self.assertEqual(calls, [])

    def test_miss_with_429_raises_rate_limited_error(self):
        def rate_limited(timeout=None):
            raise _http_error(429, retry_after=120)

        with self.assertRaises(RateLimitedError) as context:
            self.cache.get(("topic", "1"), rate_limited)
        self.assertEqual(context.exception.retry_after, 120)

    def test_miss_with_other_error_propagates(self):
        def failing(timeout=None):
            raise _http_error(404)

        with self.assertRaises(HTTPError):
            self.cache.get(("topic", "1"), failing)

    def test_only_one_concurrent_refresh_hits_discourse(self):
        self.cache.get(("topic", "1"), lambda timeout=None: "original")
        time.sleep(1.2)

        fetch_count = []
        lock = threading.Lock()

        def slow_fetch(timeout=None):
            with lock:
                fetch_count.append(1)
            time.sleep(0.3)
            return "refreshed"

        results = []

        def worker():
            results.append(self.cache.get(("topic", "1"), slow_fetch))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(fetch_count), 1)
        self.assertIn("refreshed", results)
        self.assertTrue(
            all(result in ("original", "refreshed") for result in results)
        )

    def test_invalidate_exact_key(self):
        calls = []

        def fetch(timeout=None):
            calls.append(1)
            return len(calls)

        self.cache.get(("topic", "1"), fetch)
        self.cache.invalidate("topic", "1")
        self.cache.get(("topic", "1"), fetch)

        self.assertEqual(len(calls), 2)

    def test_invalidate_by_prefix_does_not_overmatch_similar_keys(self):
        self.cache.get(("category", "5", "0"), lambda timeout=None: "page0")
        self.cache.get(("category", "5", "1"), lambda timeout=None: "page1")
        self.cache.get(
            ("category", "50", "0"), lambda timeout=None: "other-category"
        )

        self.cache.invalidate("category", "5")

        with self.engine.begin() as conn:
            remaining = conn.execute(
                select(_discourse_cache_table.c.cache_key).where(
                    _discourse_cache_table.c.namespace == self.namespace
                )
            ).all()

        self.assertEqual(len(remaining), 1)

    def test_invalidate_with_no_args_clears_namespace(self):
        self.cache.get(("topic", "1"), lambda timeout=None: "a")
        self.cache.get(("topic", "2"), lambda timeout=None: "b")

        self.cache.invalidate()

        with self.engine.begin() as conn:
            remaining = conn.execute(
                select(_discourse_cache_table.c.cache_key).where(
                    _discourse_cache_table.c.namespace == self.namespace
                )
            ).all()
        self.assertEqual(remaining, [])

    def test_namespaces_do_not_collide(self):
        other = DBResponseCache(
            self.engine,
            namespace=f"{self.namespace}-other",
            ttl=timedelta(seconds=1),
        )
        self.cache.get(("topic", "1"), lambda timeout=None: "mine")
        other.get(("topic", "1"), lambda timeout=None: "theirs")

        self.assertEqual(
            self.cache.get(("topic", "1"), lambda timeout=None: "unreached"),
            "mine",
        )
        self.assertEqual(
            other.get(("topic", "1"), lambda timeout=None: "unreached"),
            "theirs",
        )


class TestDBUnavailableFallback(unittest.TestCase):
    """
    A Postgres outage must not become a new single point of failure: it
    should degrade to a bounded direct fetch, not hang or crash.
    """

    def setUp(self):
        # A closed port: connections fail immediately rather than hanging
        engine = create_engine("postgresql://postgres@localhost:5999/postgres")
        self.cache = DBResponseCache.__new__(DBResponseCache)
        self.cache.engine = engine
        self.cache.namespace = "unreachable"
        self.cache.ttl = timedelta(hours=6)
        self.cache.refresh_timeout = 8
        self.cache.error_retry = timedelta(seconds=30)
        self.cache.table = _discourse_cache_table

    def test_get_falls_back_to_bounded_direct_fetch(self):
        calls = []

        def fetch(timeout=None):
            calls.append(timeout)
            return "direct"

        self.assertEqual(self.cache.get(("topic", "1"), fetch), "direct")
        self.assertEqual(calls, [8])

    def test_get_still_raises_rate_limited_error_on_429(self):
        def rate_limited(timeout=None):
            raise _http_error(429, retry_after=90)

        with self.assertRaises(RateLimitedError) as context:
            self.cache.get(("topic", "1"), rate_limited)
        self.assertEqual(context.exception.retry_after, 90)


class TestDiscourseAPIWithDBCache(DBCacheTestCase):
    """
    Integration: DiscourseAPI's fetch closures forward the timeout the
    cache passes them, and DBResponseCache satisfies the get()/
    invalidate() contract DiscourseAPI expects from `cache=`.
    """

    def _make_api(self):
        session = Mock()
        api = DiscourseAPI(
            base_url="https://discourse.example.com",
            session=session,
            api_key="key",
            api_username="user",
            cache=self.cache,
        )
        return api, session

    def test_get_topic_is_cached_and_forwards_timeout(self):
        api, session = self._make_api()
        session.get.return_value = _response({"id": 5})

        self.assertEqual(api.get_topic(5), {"id": 5})
        self.assertEqual(api.get_topic(5), {"id": 5})

        session.get.assert_called_once()
        _, kwargs = session.get.call_args
        self.assertIn("timeout", kwargs)

    def test_topic_update_invalidates_cached_topic(self):
        api, session = self._make_api()
        session.get.return_value = _response({"id": 5, "title": "old"})

        api.get_topic(5)

        session.post.return_value = _response({"rows": [[5, "2026-07-10"]]})
        updated, _ = api.check_for_topic_updates(5, "2026-07-01")
        self.assertTrue(updated)

        session.get.return_value = _response({"id": 5, "title": "new"})
        self.assertEqual(api.get_topic(5)["title"], "new")

    def test_probe_methods_no_longer_consult_the_cache(self):
        # get_topics_last_activity_time/get_categories_last_activity_time
        # never went through _cached(); now that the circuit breaker is
        # gone, a 429 just raises the plain HTTPError like any other
        # uncached call
        api, session = self._make_api()
        response = requests.Response()
        response.status_code = 429
        session.post.return_value = response

        with self.assertRaises(HTTPError):
            api.get_topics_last_activity_time(1)


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

    def test_get_topics_in_category_error_fallback_is_a_list(self):
        from canonicalwebteam.discourse.app import Category

        parser = Mock()
        parser.api.check_for_category_updates.side_effect = RateLimitedError(
            retry_after=42
        )
        category = Category(parser, category_id=5)

        # Views slice and iterate this; the error fallback must be a
        # list like the success path, not a dict
        self.assertEqual(category.get_topics_in_category(), [])


if __name__ == "__main__":
    unittest.main()

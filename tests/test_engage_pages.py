import os
import unittest
import unittest.mock
import requests

import flask
from vcr_unittest import VCRTestCase

from canonicalwebteam.discourse import DiscourseAPI, EngagePages, ResponseCache
from canonicalwebteam.discourse.exceptions import RateLimitedError

this_dir = os.path.dirname(os.path.realpath(__file__))


class TestDiscourseAPI(VCRTestCase):
    def _get_vcr_kwargs(self):
        """
        This removes the authorization header
        from VCR so we don't record auth parameters
        """
        return {"filter_headers": ["Authorization"]}

    def setUp(self):
        app = flask.Flask("test-app")
        app.url_map.strict_slashes = False
        app.template_folder = f"{this_dir}/fixtures/templates"
        app.testing = True
        session = requests.Session()

        self.discourse_api = DiscourseAPI(
            base_url="https://discourse.ubuntu.com/",
            session=session,
            api_key="fake-api-key",
            api_username="fake-username",
        )
        self.engage_pages = EngagePages(
            category_id=51,
            api=self.discourse_api,
            page_type="engage-pages",
        )

        self.takeovers = EngagePages(
            category_id=106,
            api=self.discourse_api,
            page_type="takeovers",
        )

        self.client = app.test_client()
        return super().setUp()

    def test_get_topic(self):
        response = self.discourse_api.get_topic(17275)

        self.assertEqual(response["id"], 17275)

    def test_index_ep_takeovers(self):
        """
        Test endpoint that retrieves all takeovers/engage pages
        """

        response = self.discourse_api.get_engage_pages_by_param(51)
        self.assertEqual(len(response), 1)

    def test_individual_ep_takeovers(self):
        """
        Test endpoint that retrieves individual takeovers/engage pages
        """

        response = self.discourse_api.get_engage_pages_by_param(
            category_id=51, key="active", value="true"
        )

        self.assertEqual(len(response), 1)

    def test_pagination(self):
        """
        Test limit and offset params

        Args:
        - category_id=51, should always be 51 for
        https://discourse.ubuntu.com/c/design/engage-pages/51
        """
        response = self.discourse_api.get_engage_pages_by_param(
            category_id=51, limit=1, offset=0
        )

        self.assertEqual(len(response), 1)


class TestEngagePagesFreshness(unittest.TestCase):
    """
    EngagePages has no per-page freshness signal, so it probes its
    category directly and drops only its own scoped engage entries. The
    probe is best-effort and must never break a page.
    """

    def _make(self):
        api = unittest.mock.Mock()
        pages = EngagePages(api=api, category_id=51, page_type="engage-pages")
        return pages, api

    @staticmethod
    def _probe(timestamp):
        # get_categories_last_activity_time returns rows; [0][1] is the
        # most-recent-activity timestamp the freshness check reads.
        return [["2024-01-01", timestamp]]

    def test_first_refresh_records_timestamp_without_invalidating(self):
        pages, api = self._make()
        api.get_categories_last_activity_time.return_value = self._probe(100)

        pages._refresh_if_stale()

        self.assertEqual(pages.category_last_updated, 100)
        api.cache.invalidate.assert_not_called()

    def test_update_invalidates_both_query_paths_scoped_to_category(self):
        pages, api = self._make()
        pages.category_last_updated = 100
        api.get_categories_last_activity_time.return_value = self._probe(200)

        pages._refresh_if_stale()

        api.cache.invalidate.assert_any_call("engage_by_param", "51")
        api.cache.invalidate.assert_any_call("engage_by_tag", "51")
        self.assertEqual(api.cache.invalidate.call_count, 2)
        self.assertEqual(pages.category_last_updated, 200)

    def test_invalidation_scoped_and_leaves_shared_caches_alone(self):
        """
        A real ResponseCache: editing category 106 drops 106's engage
        entries (both query paths) without touching category 51's cache
        or the shared events cache.
        """
        cache = ResponseCache(ttl=3600)
        k_other = ("engage_by_param", "51", "{}")
        k_param = ("engage_by_param", "106", "{}")
        k_tag = ("engage_by_tag", "106", "{}")
        k_events = ("events",)
        for k in (k_other, k_param, k_tag, k_events):
            cache.get(k, lambda: ["v"])

        api = unittest.mock.Mock()
        api.cache = cache
        api.get_categories_last_activity_time.return_value = self._probe(200)
        pages = EngagePages(api=api, category_id=106, page_type="takeovers")
        pages.category_last_updated = 100

        pages._refresh_if_stale()

        self.assertNotIn(k_param, cache._entries)  # edited category, param
        self.assertNotIn(k_tag, cache._entries)  # edited category, tag
        self.assertIn(k_other, cache._entries)  # other category untouched
        self.assertIn(k_events, cache._entries)  # shared events untouched

    def test_no_update_does_not_invalidate(self):
        pages, api = self._make()
        pages.category_last_updated = 100
        api.get_categories_last_activity_time.return_value = self._probe(100)

        pages._refresh_if_stale()

        api.cache.invalidate.assert_not_called()
        self.assertEqual(pages.category_last_updated, 100)

    def test_rate_limited_probe_logs_info_without_traceback(self):
        pages, api = self._make()
        pages.category_last_updated = 100
        api.get_categories_last_activity_time.side_effect = RateLimitedError(
            retry_after=30
        )

        with self.assertLogs(
            "canonicalwebteam.discourse", level="INFO"
        ) as logs:
            pages._refresh_if_stale()

        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].levelname, "INFO")
        self.assertIsNone(logs.records[0].exc_info)  # no traceback
        api.cache.invalidate.assert_not_called()
        self.assertEqual(pages.category_last_updated, 100)

    def test_unexpected_probe_failure_is_swallowed_with_traceback(self):
        pages, api = self._make()
        pages.category_last_updated = 100
        api.get_categories_last_activity_time.side_effect = ValueError("boom")

        with self.assertLogs(
            "canonicalwebteam.discourse", level="WARNING"
        ) as logs:
            pages._refresh_if_stale()  # must not raise

        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertIsNotNone(logs.records[0].exc_info)
        api.cache.invalidate.assert_not_called()
        self.assertEqual(pages.category_last_updated, 100)

    def test_no_invalidate_when_cache_is_none(self):
        pages, api = self._make()
        pages.category_last_updated = 100
        api.cache = None
        api.get_categories_last_activity_time.return_value = self._probe(200)

        pages._refresh_if_stale()  # must not crash on cache.invalidate

        self.assertEqual(pages.category_last_updated, 200)

    def test_get_engage_page_triggers_refresh(self):
        pages, api = self._make()
        api.get_categories_last_activity_time.return_value = self._probe(100)
        api.get_engage_pages_by_param.return_value = []

        pages.get_engage_page("/engage/x")

        api.get_categories_last_activity_time.assert_called_once_with(51)

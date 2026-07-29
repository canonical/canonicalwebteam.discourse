import os
import unittest
import unittest.mock
import requests

import flask
from vcr_unittest import VCRTestCase

from canonicalwebteam.discourse import DiscourseAPI, EngagePages

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
    EngagePages has no per-page freshness signal, so it detects a
    category edit with one (throttled) probe and drops the cached engage
    entries. The probe is best-effort and must never break a page.
    """

    def _make(self):
        api = unittest.mock.Mock()
        pages = EngagePages(api=api, category_id=51, page_type="engage-pages")
        return pages, api

    def test_first_refresh_records_timestamp_without_invalidating(self):
        pages, api = self._make()
        api.check_for_category_updates.return_value = (False, 100)

        pages._refresh_if_stale()

        self.assertEqual(pages.category_last_updated, 100)
        api.cache.invalidate.assert_not_called()

    def test_update_invalidates_engage_entries(self):
        pages, api = self._make()
        pages.category_last_updated = 100
        api.check_for_category_updates.return_value = (True, 200)

        pages._refresh_if_stale()

        api.cache.invalidate.assert_called_once_with("engage_by_param")
        self.assertEqual(pages.category_last_updated, 200)

    def test_no_update_does_not_invalidate(self):
        pages, api = self._make()
        pages.category_last_updated = 100
        api.check_for_category_updates.return_value = (False, 100)

        pages._refresh_if_stale()

        api.cache.invalidate.assert_not_called()
        self.assertEqual(pages.category_last_updated, 100)

    def test_probe_failure_is_swallowed(self):
        pages, api = self._make()
        pages.category_last_updated = 100
        api.check_for_category_updates.side_effect = Exception("rate limited")

        pages._refresh_if_stale()  # must not raise

        api.cache.invalidate.assert_not_called()
        self.assertEqual(pages.category_last_updated, 100)

    def test_no_invalidate_when_cache_is_none(self):
        pages, api = self._make()
        pages.category_last_updated = 100
        api.cache = None
        api.check_for_category_updates.return_value = (True, 200)

        pages._refresh_if_stale()  # must not crash on cache.invalidate

        self.assertEqual(pages.category_last_updated, 200)

    def test_get_engage_page_triggers_refresh(self):
        pages, api = self._make()
        api.check_for_category_updates.return_value = (False, 100)
        api.get_engage_pages_by_param.return_value = []

        pages.get_engage_page("/engage/x")

        api.check_for_category_updates.assert_called_once_with(51, None)

import os
import unittest
from unittest import mock

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


class TestGetEngagePageArchived(unittest.TestCase):
    """
    get_engage_page must return None for pages that should not be served, so
    the consuming view serves a 404 instead of a 500 or the page itself:
    - malformed pages (parse_topics raises MetadataError)
    - archived topics (detected via an extra get_topic call, since the
      data-explorer row does not expose the archived flag)
    """

    def test_malformed_page_returns_none(self):
        api = mock.Mock()
        api.base_url = "https://discourse.example.com"
        # A row whose cooked content has no metadata table triggers a
        # MetadataError inside parse_topics.
        api.get_engage_pages_by_param.return_value = [
            (
                "<p>No metadata table here</p>",
                None,
                None,
                None,
                "2018-10-02T12:45:44.259Z",
                "2018-10-02T12:45:44.259Z",
                99,
                "archived-page",
                1,
                0,
                1,
            )
        ]
        engage = EngagePages(api=api, category_id=51, page_type="engage-pages")

        self.assertIsNone(engage.get_engage_page("/engage/archived-page"))

    def test_archived_topic_returns_none(self):
        api = mock.Mock()
        api.base_url = "https://discourse.example.com"
        api.get_engage_pages_by_param.return_value = [("row",)]
        api.get_topic.return_value = {"id": 72650, "archived": True}
        engage = EngagePages(api=api, category_id=51, page_type="engage-pages")

        with mock.patch.object(
            engage, "parse_topics", return_value={"topic_id": 72650}
        ):
            self.assertIsNone(engage.get_engage_page("/engage/archived"))
        api.get_topic.assert_called_once_with(72650)

    def test_active_topic_returns_metadata(self):
        api = mock.Mock()
        api.base_url = "https://discourse.example.com"
        api.get_engage_pages_by_param.return_value = [("row",)]
        api.get_topic.return_value = {"id": 1, "archived": False}
        engage = EngagePages(api=api, category_id=51, page_type="engage-pages")

        metadata = {"topic_id": 1, "path": "/engage/active"}
        with mock.patch.object(engage, "parse_topics", return_value=metadata):
            self.assertEqual(
                engage.get_engage_page("/engage/active"), metadata
            )

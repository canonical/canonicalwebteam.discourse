import os
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

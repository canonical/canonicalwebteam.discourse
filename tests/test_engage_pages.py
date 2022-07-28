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

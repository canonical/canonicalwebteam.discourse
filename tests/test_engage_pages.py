import os
import requests

import flask
from bs4 import BeautifulSoup
from vcr_unittest import VCRTestCase

from canonicalwebteam.discourse import DiscourseAPI, EngageParser, EngagePages

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

        self.discourse_api = DiscourseAPI(
            base_url="https://discourse.ubuntu.com/",
            session=requests.Session(),
        )
        self.engage_pages = EngagePages(
            parser=EngageParser(
                api=self.discourse_api,
                index_topic_id=17229,
                url_prefix="/engage",
            ),
            document_template="/engage.html",
            url_prefix="/engage",
            blueprint_name="engage-pages",
        ).init_app(app)

        self.client = app.test_client()
        return super().setUp()

    def test_get_topic(self):
        response = self.discourse_api.get_topic(17275)

        self.assertEqual(response["id"], 17275)

    def test_active_page_returns_200(self):
        response = self.client.get("/engage/finance")
        self.assertEqual(response.status_code, 200)

        soup = BeautifulSoup(response.data, "html.parser")
        self.assertIsNone(soup.find("meta"))

    def test_active_page_returns_adds_no_meta_with_preview_flag(self):
        response = self.client.get("/engage/finance?preview")
        self.assertEqual(response.status_code, 200)

        soup = BeautifulSoup(response.data, "html.parser")
        self.assertIsNone(soup.find("meta"))

    def test_inactive_page_returns_302(self):
        response = self.client.get("/engage/it/deployment-azienda-manuale")
        self.assertEqual(response.status_code, 302)

    def test_inactive_page_returns_page_with_preview_flag(self):
        response = self.client.get(
            "/engage/it/deployment-azienda-manuale?preview"
        )
        self.assertEqual(response.status_code, 200)

        soup = BeautifulSoup(response.data, "html.parser")
        self.assertIsNotNone(soup.find("meta"))
        self.assertEqual(soup.find("meta").get("content"), "nofollow")

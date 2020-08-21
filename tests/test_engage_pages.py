# Packages
import flask
import os
import requests
import re
import json

# Local
from canonicalwebteam.discourse_docs import DiscourseAPI, EngageParser
from vcr_unittest import VCRTestCase
from bs4 import BeautifulSoup


class TestDiscourseAPI(VCRTestCase):
    def _get_vcr_kwargs(self):
        """
        This removes the authorization header
        from VCR so we don't record auth parameters
        """
        return {"filter_headers": ["Authorization"]}

    def setUp(self):
        """
        Set up Flask app with Discourse extension for testing
        And set up mocking for discourse.example.com
        """
        this_dir = os.path.dirname(os.path.realpath(__file__))
        template_folder = f"{this_dir}/fixtures/templates/engage.html"
        app = flask.Flask("main", template_folder=template_folder)
        self.discourse_api = DiscourseAPI(
            base_url="https://discourse.ubuntu.com/",
            session=requests.Session(),
            api_key="secretkey",
            api_username="canonical",
        )
        self.parser = EngageParser(
            api=self.discourse_api, index_topic_id=17229, url_prefix="/engage",
        )

        app = flask.Flask("main", template_folder=template_folder)
        self.client = app.test_client()
        return super(TestDiscourseAPI, self).setUp()

    def test_get_topic(self):
        """
        Check API retrieves a protected topic 17275
        """
        response = self.discourse_api.get_topic(17275)
        # # Check for success
        self.assertEqual(response["id"], 17275)

    def test_engage_parser(self):
        """
        This tests the output of the parser,
        which should be consistent and independent
        from whatever the template renders.

        Check that engage-pages parsers work correctly:
        - Engage map is able match correct structure
        (if error is returned, it will fail to match URL pattern)
        - Metadata is correctly parsed from the table
        """
        # Retrieve response from cassette
        response = json.loads(self.cassette.responses[0]["body"]["string"])
        raw_index_soup = BeautifulSoup(
            response["post_stream"]["posts"][0]["cooked"],
            features="html.parser",
        )
        result = list(self.parser._parse_engage_map(raw_index_soup)[0].items())
        url_match = re.search("^/engage", result[0][0])

        # Engage map Test
        # Beginning matches `/engage`
        self.assertEqual(url_match.pos, 0)
        self.assertIsInstance(result[0][1], int)

        # Metadata is parsed correctly
        metadata_result = self.parser._parse_metadata(raw_index_soup)
        self.assertTrue(len(metadata_result) > 0)

# Packages
import flask
import os
import requests

# Local
from canonicalwebteam.discourse import DiscourseAPI, EngageParser
from vcr_unittest import VCRTestCase


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
            api=self.discourse_api,
            index_topic_id=17229,
            url_prefix="/engage",
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

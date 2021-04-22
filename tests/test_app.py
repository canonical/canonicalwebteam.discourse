# Standard library
import os
import unittest
import warnings

# Packages
import flask
import httpretty
import requests

# Local
from canonicalwebteam.discourse import DiscourseAPI, Tutorials, TutorialParser
from tests.fixtures.forum_mock import register_uris


this_dir = os.path.dirname(os.path.realpath(__file__))


class TestApp(unittest.TestCase):
    def setUp(self):
        """
        Set up Flask app with Discourse extension for testing
        And set up mocking for discourse.example.com
        """

        # Suppress annoying warnings from HTTPretty
        # See: https://github.com/gabrielfalcao/HTTPretty/issues/368
        warnings.filterwarnings(
            "ignore", category=ResourceWarning, message="unclosed.*"
        )

        # Enable HTTPretty and set up mock URLs
        httpretty.enable()
        register_uris()

        template_folder = f"{this_dir}/fixtures/templates"

        app = flask.Flask("main", template_folder=template_folder)
        app_no_nav = flask.Flask("no-nav", template_folder=template_folder)
        app_no_mappings = flask.Flask(
            "no-mappings", template_folder=template_folder
        )
        app_broken_mappings = flask.Flask(
            "broken-mappings", template_folder=template_folder
        )
        app_no_category = flask.Flask(
            "no-category", template_folder=template_folder
        )
        app_url_prefix = flask.Flask(
            "url-prefix", template_folder=template_folder
        )

        app.testing = True
        app_no_nav.testing = True
        app_no_mappings.testing = True
        app_broken_mappings.testing = True
        app_no_category.testing = True
        app_url_prefix.testing = True

        discourse_api = DiscourseAPI(
            base_url="https://discourse.example.com/",
            session=requests.Session(),
        )

        Tutorials(
            parser=TutorialParser(
                api=discourse_api,
                index_topic_id=34,
                url_prefix="/",
            ),
            document_template="document.html",
            url_prefix="/",
        ).init_app(app)

        Tutorials(
            parser=TutorialParser(
                api=discourse_api,
                index_topic_id=42,
                url_prefix="/",
            ),
            document_template="document.html",
            url_prefix="/",
        ).init_app(app_no_nav)

        Tutorials(
            parser=TutorialParser(
                api=discourse_api,
                index_topic_id=35,
                url_prefix="/",
            ),
            document_template="document.html",
            url_prefix="/",
        ).init_app(app_no_mappings)

        Tutorials(
            parser=TutorialParser(
                api=discourse_api,
                index_topic_id=36,
                url_prefix="/",
            ),
            document_template="document.html",
            url_prefix="/",
        ).init_app(app_broken_mappings)

        Tutorials(
            parser=TutorialParser(
                api=discourse_api, index_topic_id=37, url_prefix="/"
            ),
            document_template="document.html",
            url_prefix="/",
        ).init_app(app_no_category)

        Tutorials(
            parser=TutorialParser(
                api=discourse_api, index_topic_id=38, url_prefix="/docs"
            ),
            document_template="document.html",
            url_prefix="/tutorials",
        ).init_app(app_url_prefix)

        self.client = app.test_client()
        self.client_no_nav = app_no_nav.test_client()
        self.client_no_mappings = app_no_mappings.test_client()
        self.client_broken_mappings = app_broken_mappings.test_client()
        self.client_no_category = app_no_category.test_client()
        self.client_url_prefix = app_url_prefix.test_client()

    def tearDown(self):
        httpretty.disable()
        httpretty.reset()

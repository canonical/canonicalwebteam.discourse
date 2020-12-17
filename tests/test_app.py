# Standard library
import os
import unittest
import warnings

# Packages
import flask
import httpretty
import requests
from bs4 import BeautifulSoup

# Local
from canonicalwebteam.discourse import DiscourseAPI, Tutorials, TutorialParser
from canonicalwebteam.discourse.parsers.base_parser import TOPIC_URL_MATCH
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
                category_id=2,
                index_topic_id=34,
                url_prefix="/",
            ),
            document_template="document.html",
            url_prefix="/",
        ).init_app(app)

        Tutorials(
            parser=TutorialParser(
                api=discourse_api,
                category_id=2,
                index_topic_id=42,
                url_prefix="/",
            ),
            document_template="document.html",
            url_prefix="/",
        ).init_app(app_no_nav)

        Tutorials(
            parser=TutorialParser(
                api=discourse_api,
                category_id=2,
                index_topic_id=35,
                url_prefix="/",
            ),
            document_template="document.html",
            url_prefix="/",
        ).init_app(app_no_mappings)

        Tutorials(
            parser=TutorialParser(
                api=discourse_api,
                category_id=2,
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

    def test_index(self):
        """
        Check that the homepage (/) displays topic 34
        """

        response = self.client.get("/")

        # Check for success
        self.assertEqual(response.status_code, 200)

        soup = BeautifulSoup(response.data, features="html.parser")

        # Check the heading
        self.assertEqual(
            soup.find("header").decode_contents(), "An index page"
        )

        # Check body
        self.assertEqual(
            soup.find("main").decode_contents(), "<p>Some homepage content</p>"
        )

        # Check navigation
        self.assertNotIn(
            "<h1>Navigation</h1>", soup.find("main").decode_contents()
        )
        self.assertIn(
            '<li><a href="/t/b-page/12">B page</a></li>',
            soup.find("nav").decode_contents(),
        )

        # Check URL map worked
        self.assertNotIn(
            '<a href="/t/page-a/10">Page A</a>',
            soup.find("main").decode_contents(),
        )
        self.assertIn(
            '<a href="/a">Page A</a>', soup.find("nav").decode_contents()
        )

    def test_index_no_mapping(self):
        """
        Check that the homepage still works with no mappings
        """

        response = self.client_no_mappings.get("/")

        # Check for success
        self.assertEqual(response.status_code, 200)

        soup = BeautifulSoup(response.data, features="html.parser")

        # Check the heading
        self.assertEqual(
            soup.find("header").decode_contents(), "An index page"
        )

        # Check body
        self.assertEqual(
            soup.find("main").decode_contents(), "<p>Some homepage content</p>"
        )

        # Check navigation
        self.assertNotIn(
            "<h1>Navigation</h1>", soup.find("main").decode_contents()
        )
        self.assertIn(
            '<a href="/t/page-a/10">Page A</a>',
            soup.find("nav").decode_contents(),
        )
        self.assertIn(
            '<li><a href="/t/b-page/12">B page</a></li>',
            soup.find("nav").decode_contents(),
        )

        # Check URL map wasn't applied (as it is supposed to be missing)
        self.assertNotIn(
            '<a href="/a">Page A</a>', soup.find("nav").decode_contents()
        )

    def test_document(self):
        """
        Check that a normal document, in the right category,
        can be retrieved, and includes the navigation
        """

        response = self.client.get("/t/a-page/42")

        # Check for success
        self.assertEqual(response.status_code, 200)

        soup = BeautifulSoup(response.data, features="html.parser")

        # Check the heading
        self.assertEqual(soup.find("header").decode_contents(), "A page")

        # Check body
        self.assertEqual(
            soup.find("main").decode_contents(), "<p>Content of Page A</p>"
        )

        # Check navigation
        self.assertIn(
            '<a href="/t/b-page/12">B page</a>',
            soup.find("nav").decode_contents(),
        )

    def test_pretty_url_document(self):
        """
        Check that a normal document with a pretty URL assigned,
        in the right category, can be retrieved, and includes the navigation
        """

        response = self.client.get("/a")
        response_2 = self.client_no_mappings.get("/a")
        response_3 = self.client_no_category.get("/a")
        response_4 = self.client_url_prefix.get("/tutorials/a")
        response_5 = self.client_url_prefix.get("/tutorials/b")
        response_6 = self.client_url_prefix.get("/tutorials/c")

        # Check pretty URL fails when no mapping
        self.assertEqual(response_2.status_code, 404)

        # Check for success
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response_3.status_code, 200)
        self.assertEqual(response_4.status_code, 200)
        self.assertEqual(response_5.status_code, 200)
        self.assertEqual(response_6.status_code, 200)

        soup = BeautifulSoup(response.data, features="html.parser")

        # Check the heading
        self.assertEqual(soup.find("header").decode_contents(), "Page A")

        # Check body
        self.assertEqual(
            soup.find("main").decode_contents(), "<p>Content of this page</p>"
        )

        # Check navigation
        self.assertIn(
            '<a href="/t/b-page/12">B page</a>',
            soup.find("nav").decode_contents(),
        )

    def test_homepage_redirects(self):
        """
        Check that if the index topic is requested
        at a different URL, it redirects to /
        """

        response_1 = self.client.get("/t/some-slug/34")
        response_2 = self.client.get("/t/34")
        response_3 = self.client.get("/some-slug/34")
        response_4 = self.client.get("/34")

        self.assertEqual(response_1.status_code, 302)
        self.assertEqual(response_2.status_code, 302)
        self.assertEqual(response_3.status_code, 302)
        self.assertEqual(response_4.status_code, 302)

        self.assertEqual(response_1.headers["location"], "http://localhost/")
        self.assertEqual(response_2.headers["location"], "http://localhost/")
        self.assertEqual(response_3.headers["location"], "http://localhost/")
        self.assertEqual(response_4.headers["location"], "http://localhost/")

    def test_topic_redirects(self):
        """
        Check links to documents without the correct slug
        will redirect to the correct path
        """

        response_1 = self.client.get("/t/some-slug/42")
        response_2 = self.client.get("/t/42")
        response_3 = self.client.get("/some-slug/42")
        response_4 = self.client.get("/42")

        self.assertEqual(response_1.status_code, 302)
        self.assertEqual(response_2.status_code, 302)
        self.assertEqual(response_3.status_code, 302)
        self.assertEqual(response_4.status_code, 302)

        self.assertEqual(
            response_1.headers["location"], "http://localhost/t/a-page/42"
        )
        self.assertEqual(
            response_2.headers["location"], "http://localhost/t/a-page/42"
        )
        self.assertEqual(
            response_3.headers["location"], "http://localhost/t/a-page/42"
        )
        self.assertEqual(
            response_4.headers["location"], "http://localhost/t/a-page/42"
        )

    def test_pretty_urls_redirect(self):
        """
        Check links to topic paths for a topic that has
        a pretty URL will redirect to the pretty URL
        """

        response_1 = self.client.get("/t/page-a/10")
        response_2 = self.client.get("/t/10")
        response_3 = self.client.get("/page-a/10")
        response_4 = self.client.get("/10")

        self.assertEqual(response_1.status_code, 302)
        self.assertEqual(response_2.status_code, 302)
        self.assertEqual(response_3.status_code, 302)
        self.assertEqual(response_4.status_code, 302)

        self.assertEqual(response_1.headers["location"], "http://localhost/a")
        self.assertEqual(response_2.headers["location"], "http://localhost/a")
        self.assertEqual(response_3.headers["location"], "http://localhost/a")
        self.assertEqual(response_4.headers["location"], "http://localhost/a")

    def test_redirects(self):
        """
        Check redirects defined in the index topic redirect correctly
        """

        response_1 = self.client.get("/redir-a")
        response_2 = self.client.get("/example/page")

        self.assertEqual(response_1.status_code, 302)
        self.assertEqual(response_2.status_code, 302)

        self.assertEqual(response_1.headers["location"], "http://localhost/a")
        self.assertEqual(
            response_2.headers["location"], "https://example.com/page"
        )

    def test_broken_redirects(self):
        """
        Check redirects that clash don't redirect, produce warnings
        """

        response_1 = self.client_broken_mappings.get("/a")
        response_2 = self.client_broken_mappings.get("/invalid-location")
        response_3 = self.client_broken_mappings.get("/valid")

        self.assertEqual(response_1.status_code, 200)
        self.assertEqual(response_2.status_code, 404)
        self.assertEqual(response_3.status_code, 302)
        self.assertEqual(
            response_3.headers["location"], "http://localhost/target"
        )

        # Check we have 3 "Warning" headers from the broken mapping
        self.assertEqual(len(response_1.headers.get_all("Warning")), 3)

    def test_document_not_found(self):
        """
        If a document topic doesn't exist in Discourse we should get a 404
        """

        response_1 = self.client.get("/t/unknown-topic/99")
        response_2 = self.client.get("/t/99")
        response_3 = self.client.get("/99")

        self.assertEqual(response_1.status_code, 404)
        self.assertEqual(response_2.status_code, 404)
        self.assertEqual(response_3.status_code, 404)

    def test_document_not_in_category(self):
        """
        Check requesting a topic not in the selected category
        leads to a 404
        """

        response = self.client.get("/t/b-page/50")

        self.assertEqual(
            response.location, "https://discourse.example.com/t/b-page/50"
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.get("/b-page/50")

        self.assertEqual(
            response.location, "https://discourse.example.com/t/b-page/50"
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.get("/50")

        self.assertEqual(
            response.location, "https://discourse.example.com/t/b-page/50"
        )
        self.assertEqual(response.status_code, 302)

    def test_missing_nav(self):
        """
        If there's no navigation in the index page,
        check we see "Navigation missing"
        """

        response_1 = self.client_no_nav.get("/")

        # The origin index isn't the "index" defined in client_no_nav
        # Which is why it won't redirect in this case
        # We want to check its <navigation> hasn't been stripped
        response_2 = self.client_no_nav.get("/t/an-index-page/34")

        soup_1 = BeautifulSoup(response_1.data, features="html.parser")
        soup_2 = BeautifulSoup(response_2.data, features="html.parser")

        self.assertEqual(
            "Navigation missing", soup_1.find("nav").decode_contents()
        )
        self.assertEqual(
            "Navigation missing", soup_2.find("nav").decode_contents()
        )

        self.assertIn(
            "<h1>Navigation</h1>", soup_2.find("main").decode_contents()
        )

    def test_note_to_editors(self):
        """
        Check "note to editors" sections get stripped out
        """

        response = self.client.get("/t/note-to-editors/47")

        soup = BeautifulSoup(response.data, features="html.parser")

        self.assertEqual(
            "<p>Above</p><p>Below</p>", soup.find("main").decode_contents()
        )

    def test_notifications(self):
        """
        Check notification blocks get converted
        """

        response = self.client.get("/t/notifications/49")

        soup = BeautifulSoup(response.data, features="html.parser")

        note_contents = soup.select_one(
            ".p-notification .p-notification__response p"
        ).decode_contents()

        warn_contents = soup.select_one(
            ".p-notification--caution .p-notification__response p"
        ).decode_contents()

        self.assertEqual("A notification", note_contents)
        self.assertEqual("A warning", warn_contents)

    def test_sitemap(self):
        """
        Check we can retrieve a list of all URLs in the URL map at
        /sitemap.txt
        """

        response = self.client.get("/sitemap.txt")

        self.assertIn(
            "text/plain; charset=utf-8", response.headers.get("content-type")
        )
        self.assertEqual(
            b"http://localhost/a\nhttp://localhost/page-z\nhttp://localhost/",
            response.data,
        )

    def test_sitemap_xml(self):
        """
        Check we can retrieve a list of all URLs in the URL map at
        /sitemap.txt
        """

        response = self.client.get("/sitemap.xml")

        self.assertIn("application/xml", response.headers.get("content-type"))

        soup = BeautifulSoup(response.data, features="html.parser")
        expected_soup = BeautifulSoup(
            open("./tests/fixtures/templates/sitemap.xml")
            .read()
            .replace("\n", ""),
            features="html.parser",
        )
        self.assertEqual(
            soup.decode_contents(), expected_soup.decode_contents()
        )

    def test_topic_match_regex(self):
        """
        Test Regex TOPIC_URL_MATCH
        """

        url = "/t/topic-name/12346"
        match = TOPIC_URL_MATCH.match(url).groupdict()
        self.assertEqual(match["slug"], "topic-name")
        self.assertEqual(match["topic_id"], "12346")

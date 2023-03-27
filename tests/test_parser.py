import json
import unittest
from unittest.mock import MagicMock, patch
import warnings

from bs4 import BeautifulSoup
import httpretty
import requests

from canonicalwebteam.discourse.models import DiscourseAPI
from canonicalwebteam.discourse.parsers.base_parser import BaseParser
from canonicalwebteam.discourse.parsers.docs import DocParser
from canonicalwebteam.discourse.parsers.tutorials import TutorialParser


class TestBaseParser(unittest.TestCase):
    def test_parser_username_link(self):
        discourse_api = DiscourseAPI("https://base.url", session=MagicMock())

        parser = BaseParser(
            api=discourse_api,
            index_topic_id=1,
            url_prefix="/",
        )

        parsed_topic = parser.parse_topic(
            {
                "id": 1,
                "category_id": 1,
                "title": "Sample",
                "slug": "sample—text",
                "post_stream": {
                    "posts": [
                        {
                            "id": 11,
                            "cooked": (
                                "<a href='/u/evilnick'>@evilnick</a>"
                                "<a>No Link</a>"
                                "<a></a>"
                            ),
                            "updated_at": "2018-10-02T12:45:44.259Z",
                        }
                    ],
                },
            }
        )

        self.assertIn(
            '<a href="https://base.url/u/evilnick">@evilnick</a>',
            parsed_topic["body_html"],
        )

    def test_emdash_in_slug(self):
        discourse_api = DiscourseAPI("https://base.url", session=MagicMock())

        parser = BaseParser(
            api=discourse_api,
            index_topic_id=1,
            url_prefix="/",
        )

        parsed_topic = parser.parse_topic(
            {
                "id": 1,
                "category_id": 1,
                "title": "Sample",
                "slug": "sample—text",
                "post_stream": {
                    "posts": [
                        {
                            "id": 11,
                            "cooked": ("empty"),
                            "updated_at": "2018-10-02T12:45:44.259Z",
                        }
                    ],
                },
            }
        )

        self.assertEqual("/t/sample--text/1", parsed_topic["topic_path"])


class TestDocParserEnsureParsed(unittest.TestCase):
    def test_ensure_parsed(self):
        """Ensure parsed will call parse if and only index_topic is None."""
        discourse_api = DiscourseAPI("https://base.url", session=MagicMock())

        parser = DocParser(
            api=discourse_api,
            index_topic_id=1,
            url_prefix="/",
        )
        with patch.object(parser, "parse", autospec=True) as mock_parse:
            self.assertIsNone(parser.index_topic)
            parsed_already_first = parser.ensure_parsed()
            self.assertFalse(parsed_already_first)
            mock_parse.assert_called_once_with()
            mock_parse.reset_mock()
            parser.index_topic = object()
            parsed_already_second = parser.ensure_parsed()
            self.assertTrue(parsed_already_second)
            mock_parse.assert_not_called()


class TestTutorialParser(unittest.TestCase):
    def test_ensure_parsed(self):
        """Ensure parsed will call parse if and only index_topic is None."""
        discourse_api = DiscourseAPI("https://base.url", session=MagicMock())

        parser = TutorialParser(
            api=discourse_api,
            index_topic_id=1,
            url_prefix="/",
        )
        with patch.object(parser, "parse", autospec=True) as mock_parse:
            self.assertIsNone(parser.index_topic)
            parsed_already_first = parser.ensure_parsed()
            self.assertFalse(parsed_already_first)
            mock_parse.assert_called_once_with()
            mock_parse.reset_mock()
            parser.index_topic = object()
            parsed_already_second = parser.ensure_parsed()
            self.assertTrue(parsed_already_second)
            mock_parse.assert_not_called()


EXAMPLE_CONTENT = """
<p>Some homepage content</p>
<h2>Navigation</h2>

<details>
  <summary>Navigation items</summary>
  <div class="md-table">
    <table>
      <thead>
        <tr>
          <th>Level</th>
          <th>Path</th>
          <th>Navlink</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>0</td>
          <td>/a</td>
          <td><a href="/t/page-a/10">Page A</a></td>
        </tr>
        <tr>
          <td>1</td>
          <td>/page-z</td>
          <td><a href="/t/page-z/26">Page Z</a></td>
        </tr>
      </tbody>
    </table>
  </div>
</details>

<h2>Redirects</h2>
<details>
  <summary>Mapping table</summary>
  <div class="md-table">
    <table>
      <thead>
        <tr>
          <th>PATH</th>
          <th>LOCATION</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>/redir-a</td>
          <td>/a</td>
        </tr>
        <tr>
          <td>/example/page</td>
          <td>https://example.com/page</td>
        </tr>
      </tbody>
    </table>
  </div>
</details>
"""


class TestDocParser(unittest.TestCase):
    def setUp(self):
        # Suppress annoying warnings from HTTPretty
        # See: https://github.com/gabrielfalcao/HTTPretty/issues/368
        warnings.filterwarnings(
            "ignore", category=ResourceWarning, message="unclosed.*"
        )

        # Enable HTTPretty and set up mock URLs
        httpretty.enable()
        self.addCleanup(httpretty.disable)
        self.addCleanup(httpretty.reset)
        # Index page with navigation, URL map and redirects
        httpretty.register_uri(
            httpretty.GET,
            "https://discourse.example.com/t/34.json",
            body=json.dumps(
                {
                    "id": 34,
                    "category_id": 2,
                    "title": "An index page",
                    "slug": "an-index-page",
                    "post_stream": {
                        "posts": [
                            {
                                "id": 3434,
                                "cooked": EXAMPLE_CONTENT,
                                "updated_at": "2018-10-02T12:45:44.259Z",
                            }
                        ]
                    },
                }
            ),
            content_type="application/json",
        )

        discourse_api = DiscourseAPI(
            base_url="https://discourse.example.com/",
            session=requests.Session(),
        )

        self.parser = DocParser(
            api=discourse_api,
            index_topic_id=34,
            url_prefix="/",
        )
        self.parser.parse()

    def test_index_has_no_nav(self):
        index_topic = self.parser.index_topic
        index = self.parser.parse_topic(index_topic)
        soup = BeautifulSoup(index["body_html"], features="lxml")

        # Check body
        self.assertEqual(soup.p.string, "Some homepage content")

        # Check navigation
        self.assertIsNone(soup.h1)

        # Check URL map worked
        self.assertIsNone(soup.details)
        self.assertNotIn(
            '<a href="/t/page-a/10">Page A</a>',
            soup.decode_contents(),
        )

    def test_nav(self):
        index_topic = self.parser.index_topic
        self.parser.parse_topic(index_topic)
        navigation = self.parser.navigation
        page_a = navigation["nav_items"][0]
        self.assertEqual(page_a["path"], "/a")
        self.assertEqual(page_a["navlink_text"], "Page A")
        page_z = page_a["children"][0]
        self.assertEqual(page_z["path"], "/page-z")
        self.assertEqual(page_z["navlink_text"], "Page Z")

    def test_redirect_map(self):
        self.assertEqual(
            self.parser.redirect_map,
            {"/redir-a": "/a", "/example/page": "https://example.com/page"},
        )

        self.assertEqual(self.parser.warnings, [])

    def test_url_map(self):
        self.assertEqual(
            self.parser.url_map,
            {
                10: "/a",
                26: "/page-z",
                34: "/",
                "/": 34,
                "/a": 10,
                "/page-z": 26,
            },
        )

        self.assertEqual(self.parser.warnings, [])

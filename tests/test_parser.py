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
        """Ensure parsed will call parse if and only if index_topic is None."""
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
        """Ensure parsed will call parse if and only if index_topic is None."""
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
        self.index = self.parser.parse_topic(self.parser.index_topic)

    def test_index_has_no_nav(self):
        soup = BeautifulSoup(self.index["body_html"], features="lxml")

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

    def test_get_section(self):
        soup = BeautifulSoup(
            self.parser.index_topic["post_stream"]["posts"][0]["cooked"],
            features="lxml",
        )
        section = self.parser._get_section(soup, "Navigation")
        self.assertEqual(len(section("table")), 1)
        self.assertEqual(len(section.table("tr")), 3)
        last_entry = section.table("tr")[-1]
        self.assertEqual(
            list(last_entry.stripped_strings), ["1", "/page-z", "Page Z"]
        )

    def test_get_sections(self):
        soup = BeautifulSoup(
            self.parser.index_topic["post_stream"]["posts"][0]["cooked"],
            features="lxml",
        )
        soup_str = str(soup)
        sections = self.parser._get_sections(soup)
        self.assertEqual(len(sections), 2)
        first = sections[0]
        self.assertEqual(first.keys(), {"title", "content", "slug"})
        self.assertEqual(first["title"], "Navigation")
        self.assertEqual(first["slug"], "navigation")
        self.assertEqual(first["content"][:9], "<details>")
        self.assertEqual(first["content"][-10:], "</details>")
        self.assertEqual(len(first["content"]), 353)
        second = sections[1]
        self.assertEqual(second.keys(), {"title", "content", "slug"})
        self.assertEqual(second["title"], "Redirects")
        self.assertEqual(second["slug"], "redirects")
        self.assertEqual(second["content"][:9], "<details>")
        self.assertEqual(second["content"][-10:], "</details>")
        self.assertEqual(len(second["content"]), 286)
        self.assertEqual(str(soup), soup_str)

    def test_nav(self):
        navigation = self.parser.navigation
        page_a = navigation["nav_items"][0]
        self.assertEqual(page_a["path"], "/a")
        self.assertEqual(page_a["navlink_text"], "Page A")
        page_z = page_a["children"][0]
        self.assertEqual(page_z["path"], "/page-z")
        self.assertEqual(page_z["navlink_text"], "Page Z")

    def test_active_topic(self):
        for page_id in [10, 26]:
            httpretty.register_uri(
                httpretty.GET,
                f"https://discourse.example.com/t/{page_id}.json",
                body=json.dumps(
                    {
                        "id": page_id,
                        "category_id": 2,
                        "title": "A topic page",
                        "slug": "a-page",
                        "post_stream": {
                            "posts": [
                                {
                                    "id": 3434,
                                    "cooked": "<h1>Content</h1>",
                                    "updated_at": "2023-04-01T12:34:56.789Z",
                                }
                            ]
                        },
                    }
                ),
                content_type="application/json",
            )
        self.assertEqual(self.parser.active_topic_id, 34)
        root_navigation = self.parser.navigation

        root_page_a = root_navigation["nav_items"][0]
        self.assertFalse(root_page_a["is_active"])
        self.assertFalse(root_page_a["has_active_child"])

        # Simulate clicking on child page
        self.parser.parse_topic(self.parser.api.get_topic(10))
        self.assertEqual(self.parser.active_topic_id, 10)
        child = self.parser.navigation["nav_items"][0]
        self.assertTrue(child["is_active"])
        self.assertFalse(child["has_active_child"])

        # Simulate clicking on grand-child page
        self.parser.parse_topic(self.parser.api.get_topic(26))
        self.assertEqual(self.parser.active_topic_id, 26)
        child = self.parser.navigation["nav_items"][0]
        self.assertFalse(child["is_active"])
        self.assertTrue(child["has_active_child"])
        grandchild = child["children"][0]
        self.assertTrue(grandchild["is_active"])
        self.assertFalse(grandchild["has_active_child"])

        # Simulate clicking on root
        self.parser.parse_topic(self.parser.index_topic)
        child = self.parser.navigation["nav_items"][0]
        self.assertFalse(child["is_active"])
        self.assertFalse(child["has_active_child"])

    def test_versions(self):
        versions = self.parser.versions
        self.assertEqual(len(versions), 1)
        version = versions[0]
        self.assertEqual(version["index"], int(self.parser.index_topic_id))
        self.assertEqual(version["path"], "")
        self.assertEqual(version["version"], "latest")
        self.assertNotEqual(version["nav_items"], [])

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

import json
import unittest
from unittest.mock import MagicMock
import warnings

from bs4 import BeautifulSoup
import httpretty
import requests

from canonicalwebteam.discourse.models import DiscourseAPI
from canonicalwebteam.discourse.parsers.base_parser import BaseParser
from canonicalwebteam.discourse.parsers.docs import DocParser
from canonicalwebteam.discourse.parsers.category import CategoryParser
from canonicalwebteam.discourse.parsers.events import EventsParser

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

    def test_parser_upload(self):
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
                                "<a href='/uploads/test.png'>"
                                "<img src='test.png' srcset='test.png' />"
                                "</a>"
                                "<a href='/uploads/test2.png'>"
                                "<img src='test2.png' />"
                                "</a>"
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
            (
                '<a href="https://base.url/uploads/test.png">'
                '<img src="test.png"/>'
                "</a>"
            ),
            parsed_topic["body_html"],
        )
        self.assertIn(
            (
                '<a href="https://base.url/uploads/test2.png">'
                '<img src="test2.png"/>'
                "</a>"
            ),
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


class TestCategoryParser(unittest.TestCase):
    def setUp(self):
        warnings.filterwarnings(
            "ignore", category=ResourceWarning, message="unclosed.*"
        )

        httpretty.enable()
        self.addCleanup(httpretty.disable)
        self.addCleanup(httpretty.reset)

        httpretty.register_uri(
            httpretty.GET,
            "https://discourse.example.com/t/34.json",
            body=json.dumps(
                {
                    "id": 34,
                    "category_id": 2,
                    "title": "Category Index",
                    "slug": "category-index",
                    "post_stream": {
                        "posts": [
                            {
                                "id": 3434,
                                "cooked": EXAMPLE_CONTENT,
                                "updated_at": "2023-04-01T12:34:56.789Z",
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

        self.parser = CategoryParser(
            api=discourse_api,
            index_topic_id=34,
            url_prefix="/",
        )

    def test_parse_index_topic(self):
        """
        Test that parse_index_topic correctly extracts tables from both
        formats
        """
        data_tables = self.parser.parse_index_topic()

        # Check that both tables were extracted
        self.assertEqual(len(data_tables), 2)
        self.assertIn("Navigation items", data_tables)
        self.assertIn("Mapping table", data_tables)

        # Check navigation table content
        navigation_items = data_tables["Navigation items"]
        self.assertEqual(len(navigation_items), 2)
        self.assertEqual(navigation_items[0]["level"], "0")
        self.assertEqual(navigation_items[0]["path"], "/a")
        self.assertEqual(navigation_items[0]["navlink"]["text"], "Page A")
        self.assertEqual(navigation_items[0]["navlink"]["url"], "/t/page-a/10")
        self.assertEqual(navigation_items[1]["level"], "1")
        self.assertEqual(navigation_items[1]["path"], "/page-z")
        self.assertEqual(navigation_items[1]["navlink"]["text"], "Page Z")
        self.assertEqual(navigation_items[1]["navlink"]["url"], "/t/page-z/26")

        # Check mapping table content
        mapping_table = data_tables["Mapping table"]
        self.assertEqual(len(mapping_table), 2)
        self.assertEqual(mapping_table[0]["path"], "/redir-a")
        self.assertEqual(mapping_table[0]["location"], "/a")
        self.assertEqual(mapping_table[1]["path"], "/example/page")
        self.assertEqual(
            mapping_table[1]["location"], "https://example.com/page"
        )

    def test_parse_table_method(self):
        """Test that _parse_table correctly parses table with links"""
        html = """
        <table>
          <thead>
            <tr>
              <th>Link</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><a href="/page/1">Page One</a></td>
            </tr>
          </tbody>
        </table>
        """
        soup = BeautifulSoup(html, features="html.parser")
        table = soup.find("table")

        result = self.parser._parse_table(table)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["link"]["text"], "Page One")
        self.assertEqual(result[0]["link"]["url"], "/page/1")


class TestEventsParser(unittest.TestCase):
    def setUp(self):
        self.api = MagicMock()
        self.events_parser = EventsParser(
            api=self.api, index_topic_id=1, url_prefix="/"
        )

    def test_parse_featured_events_empty_list(self):
        """Test parsing featured events with empty lists."""
        all_events = []
        featured_events_ids = []

        result = self.events_parser.parse_featured_events(
            all_events, featured_events_ids
        )

        self.assertEqual(result, [])
        self.assertEqual(len(result), 0)

    def test_parse_featured_events_with_no_featured(self):
        """Test parsing featured events when none are featured."""
        all_events = [
            {"id": 1, "title": "Event 1"},
            {"id": 2, "title": "Event 2"},
            {"id": 3, "title": "Event 3"},
        ]
        featured_events_ids = [4, 5, 6]

        result = self.events_parser.parse_featured_events(
            all_events, featured_events_ids
        )

        self.assertEqual(result, [])
        self.assertEqual(len(result), 0)

    def test_parse_featured_events_with_featured(self):
        """Test parsing featured events when some are featured."""
        all_events = [
            {"id": 1, "title": "Event 1"},
            {"id": 2, "title": "Event 2"},
            {"id": 3, "title": "Event 3"},
            {"id": 4, "title": "Event 4"},
        ]
        featured_events_ids = [2, 4]

        result = self.events_parser.parse_featured_events(
            all_events, featured_events_ids
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], 2)
        self.assertEqual(result[0]["title"], "Event 2")
        self.assertEqual(result[1]["id"], 4)
        self.assertEqual(result[1]["title"], "Event 4")

    def test_parse_featured_events_duplicate_ids(self):
        """
        Test parsing featured events with duplicate IDs in featured_events_ids.
        """
        all_events = [
            {"id": 1, "title": "Event 1"},
            {"id": 2, "title": "Event 2"},
            {"id": 3, "title": "Event 3"},
        ]
        featured_events_ids = [1, 1, 2, 2, 3]

        result = self.events_parser.parse_featured_events(
            all_events, featured_events_ids
        )

        # Expecting no duplicates
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["id"], 1)
        self.assertEqual(result[1]["id"], 2)
        self.assertEqual(result[2]["id"], 3)

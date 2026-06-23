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


class TestReplaceBlockquotesBlock(unittest.TestCase):
    def setUp(self):
        discourse_api = DiscourseAPI("https://base.url", session=MagicMock())
        self.parser = BaseParser(
            api=discourse_api,
            index_topic_id=1,
            url_prefix="/",
        )

    def _parse(self, html):
        return self.parser._replace_blockquotes_block(
            BeautifulSoup(html, features="lxml")
        )

    def _make_table(self, quote, name="", position=""):
        return f"""
        <div class="md-table">
          <table>
            <thead><tr><th>QUOTE BLOCK</th><th></th><th></th></tr></thead>
            <tbody>
              <tr><td>QUOTE</td><td>NAME</td><td>POSITION AND COMPANY</td></tr>
              <tr>
                <td>{quote}</td>
                <td>{name}</td>
                <td>{position}</td>
              </tr>
            </tbody>
          </table>
        </div>
        """

    def test_basic_quote_no_citation(self):
        soup = self._parse(self._make_table('"Only the quote."'))
        quote_p = soup.find("p", class_="p-heading--4")
        self.assertIsNotNone(quote_p)
        self.assertEqual(quote_p.find("i").string, '"Only the quote."')
        # No citation paragraphs
        self.assertIsNone(soup.find("p", class_="u-text--muted"))
        self.assertIsNone(soup.find("p", class_="u-no-margin--bottom"))
        # Without citations the quote element gets u-sv3 for spacing
        self.assertIn("u-sv3", quote_p.get("class", []))

    def test_quote_with_author_only(self):
        soup = self._parse(self._make_table('"Quote text."', name="Jane Doe"))
        quote_p = soup.find("p", class_="p-heading--4")
        self.assertIsNotNone(quote_p)
        self.assertEqual(quote_p.find("i").string, '"Quote text."')
        # One citation element — no u-no-margin--bottom because len == 1
        self.assertIsNone(soup.find("p", class_="u-no-margin--bottom"))
        strong = soup.find("strong")
        self.assertIsNotNone(strong)
        self.assertEqual(strong.string, "Jane Doe")
        # Has citations, so u-sv3 should not be added
        self.assertNotIn("u-sv3", quote_p.get("class", []))

    def test_quote_with_author_and_organisation(self):
        soup = self._parse(
            self._make_table(
                '"Another quote."', name="John Smith", position="Canonical"
            )
        )
        quote_p = soup.find("p", class_="p-heading--4")
        self.assertIsNotNone(quote_p)
        # Author paragraph gets u-no-margin--bottom when there are 2 citations
        author_p = soup.find("p", class_="u-no-margin--bottom")
        self.assertIsNotNone(author_p)
        self.assertIsNotNone(author_p.find("strong"))
        # Organisation paragraph gets u-text--muted
        org_p = soup.find("p", class_="u-text--muted")
        self.assertIsNotNone(org_p)
        self.assertEqual(org_p.string, "Canonical")

    def test_table_removed_after_transform(self):
        soup = self._parse(self._make_table('"Text."'))
        self.assertIsNone(soup.find("div", class_="md-table"))
        self.assertIsNone(soup.find("table"))

    def test_missing_quote_text_is_skipped(self):
        soup = self._parse(self._make_table(""))
        self.assertIsNone(soup.find("p", class_="p-heading--4"))

    def test_non_quote_table_is_ignored(self):
        html = """
        <div class="md-table">
          <table>
            <thead><tr><th>SOMETHING ELSE</th></tr></thead>
            <tbody><tr><td>data</td></tr></tbody>
          </table>
        </div>
        """
        soup = self._parse(html)
        # Table should be untouched
        self.assertIsNone(soup.find("p", class_="p-heading--4"))
        self.assertIsNotNone(soup.find("table"))


class TestReplaceImageBlock(unittest.TestCase):
    def setUp(self):
        discourse_api = DiscourseAPI("https://base.url", session=MagicMock())
        self.parser = BaseParser(
            api=discourse_api,
            index_topic_id=1,
            url_prefix="/",
        )

    def _parse(self, html):
        return self.parser._replace_image_block(
            BeautifulSoup(html, features="lxml")
        )

    def _make_table(self, img_url, caption=""):
        return f"""
        <div class="md-table">
          <table>
            <thead><tr><th>IMAGE BLOCK</th><th></th></tr></thead>
            <tbody>
              <tr><td>IMAGE CAPTION (OPTIONAL)</td><td>ASSET LINK</td></tr>
              <tr>
                <td>{caption}</td>
                <td><a href="{img_url}">{img_url}</a></td>
              </tr>
            </tbody>
          </table>
        </div>
        """

    def test_basic_image_no_caption(self):
        soup = self._parse(
            self._make_table("https://assets.ubuntu.com/img/photo.jpg")
        )
        container = soup.find("div", class_="p-image-container")
        self.assertIsNotNone(container)
        self.assertIn("is-cover", container.get("class", []))
        img = container.find("img")
        self.assertIsNotNone(img)
        self.assertIn("p-image-container__image", img.get("class", []))
        self.assertEqual(img["src"], "https://assets.ubuntu.com/img/photo.jpg")
        # No caption; u-sv3 should be added for spacing
        self.assertIsNone(soup.find("p", class_="u-text--muted"))
        self.assertIn("u-sv3", container.get("class", []))

    def test_image_with_caption(self):
        soup = self._parse(
            self._make_table(
                "https://assets.ubuntu.com/img/photo.jpg",
                caption="This is a caption",
            )
        )
        container = soup.find("div", class_="p-image-container")
        self.assertIsNotNone(container)
        caption_p = soup.find("p", class_="u-text--muted")
        self.assertIsNotNone(caption_p)
        self.assertEqual(caption_p.string, "This is a caption")
        # u-sv3 should not be added when there is a caption
        self.assertNotIn("u-sv3", container.get("class", []))

    def test_table_removed_after_transform(self):
        soup = self._parse(
            self._make_table("https://assets.ubuntu.com/img/photo.jpg")
        )
        self.assertIsNone(soup.find("div", class_="md-table"))
        self.assertIsNone(soup.find("table"))

    def test_missing_img_url_is_skipped(self):
        html = """
        <div class="md-table">
          <table>
            <thead><tr><th>IMAGE BLOCK</th><th></th></tr></thead>
            <tbody>
              <tr><td>CAPTION</td><td>ASSET LINK</td></tr>
              <tr><td>caption</td><td></td></tr>
            </tbody>
          </table>
        </div>
        """
        soup = self._parse(html)
        self.assertIsNone(soup.find("div", class_="p-image-container"))

    def test_non_image_table_is_ignored(self):
        html = """
        <div class="md-table">
          <table>
            <thead><tr><th>SOMETHING ELSE</th></tr></thead>
            <tbody><tr><td>data</td></tr></tbody>
          </table>
        </div>
        """
        soup = self._parse(html)
        self.assertIsNone(soup.find("div", class_="p-image-container"))
        self.assertIsNotNone(soup.find("table"))


class TestReplaceHighlightsBlock(unittest.TestCase):
    def setUp(self):
        discourse_api = DiscourseAPI("https://base.url", session=MagicMock())
        self.parser = BaseParser(
            api=discourse_api,
            index_topic_id=1,
            url_prefix="/",
        )

    def _parse(self, html):
        return self.parser._replace_highlights_block(
            BeautifulSoup(html, features="lxml")
        )

    def _make_table(self, items, title=""):
        check = '<img title=":check_mark:" class="emoji"/>'
        items_html = "".join(f"{check}{item} " for item in items).strip()
        return f"""
        <div class="md-table">
          <table>
            <thead><tr><th>HIGHLIGHTS BLOCK</th><th></th></tr></thead>
            <tbody>
              <tr><td>TITLE</td><td>ITEMS</td></tr>
              <tr>
                <td>{title}</td>
                <td>{items_html}</td>
              </tr>
            </tbody>
          </table>
        </div>
        """

    def test_basic_highlights_no_title(self):
        soup = self._parse(self._make_table(["Highlight 1", "Highlight 2"]))
        wrapper = soup.find("div", class_="p-list--horizontal-section-wrapper")
        self.assertIsNotNone(wrapper)
        ul = wrapper.find("ul")
        self.assertIsNotNone(ul)
        self.assertIn("p-list--horizontal-section", ul.get("class", []))
        lis = ul.find_all("li")
        self.assertEqual(len(lis), 2)
        for li in lis:
            self.assertIn("p-list__item", li.get("class", []))
            self.assertIn("is-ticked", li.get("class", []))
        # No title paragraph
        self.assertIsNone(soup.find("p", class_="p-text--small-caps"))

    def test_highlights_with_title(self):
        soup = self._parse(
            self._make_table(["Feature A"], title="Key features")
        )
        title_p = soup.find("p", class_="p-text--small-caps")
        self.assertIsNotNone(title_p)
        self.assertEqual(title_p.string, "Key features")
        wrapper = soup.find("div", class_="p-list--horizontal-section-wrapper")
        self.assertIsNotNone(wrapper)
        ul = wrapper.find("ul")
        self.assertIsNotNone(ul)
        self.assertIn("p-list--horizontal-section", ul.get("class", []))

    def test_items_text_correct(self):
        soup = self._parse(self._make_table(["Alpha", "Beta", "Gamma"]))
        lis = soup.find_all("li")
        texts = [li.get_text(strip=True) for li in lis]
        self.assertEqual(texts, ["Alpha", "Beta", "Gamma"])

    def test_table_removed_after_transform(self):
        soup = self._parse(self._make_table(["Item"]))
        self.assertIsNone(soup.find("div", class_="md-table"))
        self.assertIsNone(soup.find("table"))

    def test_no_items_is_skipped(self):
        html = """
        <div class="md-table">
          <table>
            <thead><tr><th>HIGHLIGHTS BLOCK</th><th></th></tr></thead>
            <tbody>
              <tr><td>TITLE</td><td>ITEMS</td></tr>
              <tr><td>My title</td><td>No check marks here</td></tr>
            </tbody>
          </table>
        </div>
        """
        soup = self._parse(html)
        self.assertIsNone(
            soup.find("div", class_="p-list--horizontal-section-wrapper")
        )

    def test_non_highlights_table_is_ignored(self):
        html = """
        <div class="md-table">
          <table>
            <thead><tr><th>SOMETHING ELSE</th></tr></thead>
            <tbody><tr><td>data</td></tr></tbody>
          </table>
        </div>
        """
        soup = self._parse(html)
        self.assertIsNone(
            soup.find("div", class_="p-list--horizontal-section-wrapper")
        )
        self.assertIsNotNone(soup.find("table"))


class TestReplaceStandardTableBlock(unittest.TestCase):
    def setUp(self):
        discourse_api = DiscourseAPI("https://base.url", session=MagicMock())
        self.parser = BaseParser(
            api=discourse_api,
            index_topic_id=1,
            url_prefix="/",
        )

    def _parse(self, html):
        return self.parser._replace_standard_table_block(
            BeautifulSoup(html, features="lxml")
        )

    def _make_table(self, headers, rows):
        header_cells = "".join(f"<td>{h}</td>" for h in headers)
        data_rows = "".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
            for row in rows
        )
        marker_ths = "".join("<th></th>" for _ in range(len(headers) - 1))
        return f"""
        <div class="md-table">
          <table>
            <thead><tr><th>STANDARD TABLE</th>{marker_ths}</tr></thead>
            <tbody>
              <tr>{header_cells}</tr>
              {data_rows}
            </tbody>
          </table>
        </div>
        """

    def test_md_table_wrapper_removed(self):
        soup = self._parse(self._make_table(["H1", "H2"], [["R1C1", "R1C2"]]))
        self.assertIsNone(soup.find("div", class_="md-table"))

    def test_first_row_becomes_thead(self):
        soup = self._parse(
            self._make_table(["Col A", "Col B"], [["v1", "v2"]])
        )
        table = soup.find("table")
        self.assertIsNotNone(table)
        thead = table.find("thead")
        self.assertIsNotNone(thead)
        ths = thead.find_all("th")
        self.assertEqual([th.get_text() for th in ths], ["Col A", "Col B"])

    def test_data_rows_stay_in_tbody(self):
        soup = self._parse(
            self._make_table(["H1", "H2"], [["A", "B"], ["C", "D"]])
        )
        tbody = soup.find("tbody")
        self.assertIsNotNone(tbody)
        rows = tbody.find_all("tr")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].get_text(separator="|", strip=True), "A|B")
        self.assertEqual(rows[1].get_text(separator="|", strip=True), "C|D")

    def test_marker_thead_removed(self):
        soup = self._parse(self._make_table(["H1"], [["data"]]))
        # The original STANDARD TABLE marker th should not appear
        for th in soup.find_all("th"):
            self.assertNotIn("STANDARD TABLE", th.get_text())

    def test_non_standard_table_is_ignored(self):
        html = """
        <div class="md-table">
          <table>
            <thead><tr><th>SOMETHING ELSE</th></tr></thead>
            <tbody><tr><td>data</td></tr></tbody>
          </table>
        </div>
        """
        soup = self._parse(html)
        # md-table wrapper should remain untouched
        self.assertIsNotNone(soup.find("div", class_="md-table"))

    def test_plain_table_outside_md_table_untouched(self):
        html = """
        <table>
          <thead><tr><th>Normal Header</th></tr></thead>
          <tbody><tr><td>Normal data</td></tr></tbody>
        </table>
        """
        soup = self._parse(html)
        table = soup.find("table")
        self.assertIsNotNone(table)
        self.assertEqual(table.find("th").get_text(), "Normal Header")


class TestReplaceChecklistParagraph(unittest.TestCase):
    def setUp(self):
        discourse_api = DiscourseAPI("https://base.url", session=MagicMock())
        self.parser = BaseParser(
            api=discourse_api,
            index_topic_id=1,
            url_prefix="/",
        )

    def _parse(self, html):
        return self.parser._replace_checklist_paragraph(
            BeautifulSoup(html, features="lxml")
        )

    CHECK = (
        '<img title=":check_mark:" class="emoji" alt=":check_mark:"'
        'src="/images/emoji/twitter/check_mark.png"/>'
    )

    def test_basic_checklist_becomes_ul(self):
        html = f"<p>{self.CHECK}First item<br/>{self.CHECK}Second item</p>"
        soup = self._parse(html)
        self.assertIsNone(soup.find("p"))
        ul = soup.find("ul")
        self.assertIsNotNone(ul)
        self.assertIn("p-list--divided", ul.get("class", []))
        lis = ul.find_all("li")
        self.assertEqual(len(lis), 2)
        self.assertEqual(lis[0].get_text(), "First item")
        self.assertEqual(lis[1].get_text(), "Second item")

    def test_li_classes(self):
        html = f"<p>{self.CHECK}Only item</p>"
        soup = self._parse(html)
        li = soup.find("li")
        self.assertIsNotNone(li)
        self.assertIn("p-list__item", li.get("class", []))
        self.assertIn("is-ticked", li.get("class", []))

    def test_paragraph_without_checkmarks_is_unchanged(self):
        html = "<p>Just a normal paragraph</p>"
        soup = self._parse(html)
        p = soup.find("p")
        self.assertIsNotNone(p)
        self.assertEqual(p.get_text(), "Just a normal paragraph")

    def test_multiple_paragraphs_only_checklist_converted(self):
        html = (
            "<p>Normal</p>" f"<p>{self.CHECK}Item A<br/>{self.CHECK}Item B</p>"
        )
        soup = self._parse(html)
        # Normal paragraph unchanged
        self.assertIsNotNone(soup.find("p"))
        # Checklist paragraph converted
        ul = soup.find("ul")
        self.assertIsNotNone(ul)
        self.assertEqual(len(ul.find_all("li")), 2)

    def test_item_text_is_stripped(self):
        html = (
            f"<p>{self.CHECK}  Trimmed item  <br/>{self.CHECK}"
            " Also trimmed  </p>"
        )
        soup = self._parse(html)
        lis = soup.find_all("li")
        self.assertEqual(lis[0].get_text(), "Trimmed item")
        self.assertEqual(lis[1].get_text(), "Also trimmed")


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

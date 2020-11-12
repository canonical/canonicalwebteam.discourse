# Standard library
import re

# Packages
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# Regex that matches Discourse topic URL
# It is used to pull out the slug and topic_id
TOPIC_URL_MATCH = re.compile(
    r"(?:/t)?(?:/(?P<slug>[^/]+))?/(?P<topic_id>\d+)(?:/\d+)?"
)


class BaseParser(object):
    """
    Parsers used commonly by Docs and Engage pages
    """

    def _get_section(self, soup, title_text):
        """
        Given some HTML soup and the text of a title within it,
        get the content between that title and the next title
        of the same level, and return it as another soup object.

        E.g. if `soup` contains is:

        <p>Pre</p>
        <h2>My heading</h2>
        <p>Content</p>
        <h2>Next heading</h2>

        and `title_text` is "My heading", then it will return:

        <p>Content</p>
        """

        heading = soup.find(re.compile("^h[1-6]$"), text=title_text)

        if not heading:
            return None

        heading_tag = heading.name

        section_html = "".join(map(str, heading.fetchNextSiblings()))
        section_soup = BeautifulSoup(section_html, features="html.parser")

        # If there's another heading of the same level
        # get the content before it
        next_heading = section_soup.find(heading_tag)
        if next_heading:
            section_elements = next_heading.fetchPreviousSiblings()
            section_elements.reverse()
            section_html = "".join(map(str, section_elements))
            section_soup = BeautifulSoup(section_html, features="html.parser")

        return section_soup

    def _get_preamble(self, soup, break_on_title):
        """
        Given a BeautifulSoup HTML document,
        separate out the HTML at the start, up to
        the heading defined in `break_on_title`,
        and return it as a BeautifulSoup object
        """

        heading = soup.find(re.compile("^h[1-6]$"), text=break_on_title)

        if not heading:
            return soup

        preamble_elements = heading.fetchPreviousSiblings()
        preamble_elements.reverse()
        preamble_html = "".join(map(str, preamble_elements))

        return BeautifulSoup(preamble_html, features="html.parser")

    def _parse_metadata(self, index_soup, section_name):
        """
        Given the HTML soup of an index topic
        extract the metadata from the name designated
        by section_name

        This section_name section should contain a table
        (extra markup around this table doesn't matter)
        e.g.:

        <h1>Metadata</h1>
        <details>
            <summary>Mapping table</summary>
            <table>
            <tr><th>Column 1</th><th>Column 2</th></tr>
            <tr>
                <td>data 1</td>
                <td>data 2</td>
            </tr>
            <tr>
                <td>data 3</td>
                <td>data 4</td>
            </tr>
            </table>
        </details>

        This will typically be generated in Discourse from Markdown similar to
        the following:

        # Redirects

        [details=Mapping table]
        | Column 1| Column 2|
        | -- | -- |
        | data 1 | data 2 |
        | data 3 | data 4 |

        The function will return a list of dictionaries of this format:
        [
            {"column-1": "data 1", "column-2": "data 2"},
            {"column-1": "data 3", "column-2": "data 4"},
        ]
        """
        metadata_soup = self._get_section(index_soup, section_name)

        topics_metadata = []
        if metadata_soup:
            titles = [
                title_soup.text.lower().replace(" ", "_").replace("-", "_")
                for title_soup in metadata_soup.select("th")
            ]
            for row in metadata_soup.select("tr:has(td)"):
                row_dict = {}
                for index, value in enumerate(row.select("td")):
                    if value.find("a"):
                        row_dict["topic_name"] = value.find("a").text

                    # Beautiful soup renders URLs as anchors
                    # Avoid that default behaviour
                    if value.find("a") and (
                        value.find("a")["href"] == value.find("a").text
                    ):
                        value.contents[0] = value.find("a").text

                    row_dict[titles[index]] = "".join(
                        str(content) for content in value.contents
                    )

                topics_metadata.append(row_dict)

        return topics_metadata

    def _parse_url_map(
        self, index_soup, url_prefix, index_topic_id, url_section_name
    ):
        """
        Given the HTML soup of an index topic
        extract the URL mappings from a "URLs" section.

        This section could be called whatever is
        passed in `url_section_name` but it must
        contain a table of
        "Topic" to "Path" mappings
        (extra markup around this table doesn't matter)
        e.g.:

        <h1>URLs</h1>
        <details>
            <summary>Mapping table</summary>
            <table>
            <tr><th>Topic</th><th>Path</th></tr>
            <tr>
                <td><a href="https://forum.example.com/t/page/10">Page</a></td>
                <td>/cool-page</td>
            </tr>
            <tr>
                <td>
                    <a href="https://forum.example.com/t/place/11">Place</a>
                </td>
                <td>/cool-place</td>
            </tr>
            </table>
        </details>

        This will typically be generated in Discourse from Markdown similar to
        the following:

        # URLs

        [details=Mapping table]
        | Topic | Path |
        | -- | -- |
        | https://forum.example.com/t/place/11| /cool-page |
        | https://forum.example.com/t/place/11  | /cool-place |

        """

        url_soup = self._get_section(index_soup, url_section_name)
        url_map = {}
        warnings = []

        if url_soup:
            for row in url_soup.select("tr:has(td)"):
                topic_a = row.select_one("td:first-child a[href]")
                path_td = row.select_one("td:nth-child(2)")

                if not topic_a or not path_td:
                    warnings.append("Could not parse URL map item {item}")
                    continue

                topic_url = topic_a.attrs.get("href", "")
                topic_path = urlparse(topic_url).path
                topic_match = TOPIC_URL_MATCH.match(topic_path)

                pretty_path = path_td.text
                if not pretty_path.startswith("/"):
                    pretty_path = "/" + pretty_path
                if not pretty_path.startswith(url_prefix):
                    pretty_path = url_prefix + pretty_path

                if not topic_match or not pretty_path.startswith(url_prefix):
                    warnings.append("Could not parse URL map item {item}")
                    continue

                topic_id = int(topic_match.groupdict()["topic_id"])

                url_map[pretty_path] = topic_id

        # Add the reverse mappings as well, for efficiency
        ids_to_paths = dict([reversed(pair) for pair in url_map.items()])
        url_map.update(ids_to_paths)

        # Add the homepage path
        home_path = url_prefix
        if home_path != "/" and home_path.endswith("/"):
            home_path = home_path.rstrip("/")
        url_map[home_path] = index_topic_id
        url_map[index_topic_id] = home_path

        return url_map, warnings

# Standard library
import os
import re
from urllib.parse import urlparse, urlunparse

# Packages
import dateutil.parser
import humanize
import validators
from bs4 import BeautifulSoup
from jinja2 import Template

# Local
from canonicalwebteam.discourse_docs.exceptions import (
    PathNotFoundError,
    RedirectFoundError,
)


TOPIC_URL_MATCH = re.compile(
    r"(?:/t)?(?:/(?P<slug>[^/]+))?/(?P<topic_id>\d+)(?:/\d+)?"
)


class DocParser:
    def __init__(self, api, index_topic_id, url_prefix):
        self.api = api
        self.index_topic_id = index_topic_id
        self.url_prefix = url_prefix

    def parse(self):
        """
        Get the index topic and split it into:
        - navigation
        - index document content
        - URL map
        - redirects map
        And set those as properties on this object
        """
        index_topic = self.api.get_topic(self.index_topic_id)
        raw_index_soup = BeautifulSoup(
            index_topic["post_stream"]["posts"][0]["cooked"],
            features="html.parser",
        )

        # Parse URL & redirects mappings (get warnings)
        self.url_map, url_warnings = self._parse_url_map(raw_index_soup)
        self.redirect_map, redirect_warnings = self._parse_redirect_map(
            raw_index_soup
        )
        self.warnings = url_warnings + redirect_warnings

        # Get body and navigation HTML
        self.index_document = self.parse_topic(index_topic)
        index_soup = BeautifulSoup(
            self.index_document["body_html"], features="html.parser"
        )
        self.index_document["body_html"] = str(
            self._get_preamble(index_soup, break_on_title="Navigation")
        )

        # Parse navigation
        self.navigation = self._parse_navigation(index_soup)

    def resolve_path(self, relative_path):
        """
        Given a path to a Discourse topic, and a mapping of
        URLs to IDs and IDs to URLs, resolve the path to a topic ID

        A PathNotFoundError will be raised if the path is not recognised.

        A RedirectFoundError will be raised if the topic should be
        accessed at a different URL path.
        """

        full_path = os.path.join(self.url_prefix, relative_path.lstrip("/"))

        if full_path in self.redirect_map:
            raise RedirectFoundError(
                full_path, target_url=self.redirect_map[full_path]
            )
        elif full_path in self.url_map:
            topic_id = self.url_map[full_path]
        else:
            topic_match = TOPIC_URL_MATCH.match(relative_path)

            if not topic_match:
                raise PathNotFoundError(relative_path)

            topic_id = int(topic_match.groupdict()["topic_id"])

            if not topic_id:
                raise PathNotFoundError(relative_path)

            if topic_id in self.url_map:
                raise RedirectFoundError(
                    full_path, target_url=self.url_map[topic_id]
                )

        return topic_id

    def parse_topic(self, topic):
        """
        Parse a topic object from the Discourse API
        and return document data:
        - title: The title
        - body_html: The HTML content of the initial topic post
                        (with some post-processing)
        - updated: A human-readable date, relative to now
                    (e.g. "3 days ago")
        - forum_link: The link to the original forum post
        """

        updated_datetime = dateutil.parser.parse(
            topic["post_stream"]["posts"][0]["updated_at"]
        )

        topic_path = f"/t/{topic['slug']}/{topic['id']}"

        topic_soup = BeautifulSoup(
            topic["post_stream"]["posts"][0]["cooked"], features="html.parser"
        )

        return {
            "title": topic["title"],
            "body_html": str(self._process_topic_soup(topic_soup)),
            "updated": humanize.naturaltime(
                updated_datetime.replace(tzinfo=None)
            ),
            "topic_path": topic_path,
        }

    def _parse_navigation(self, index_soup):
        """
        Given the HTML soup of a index topic
        extract the "navigation" section, and rewrite any
        links in the url_map
        """

        nav_soup = self._get_section(index_soup, "Navigation")

        if nav_soup:
            nav_html = str(self._replace_links(nav_soup))
        else:
            nav_html = "Navigation missing"

        return nav_html

    def _process_topic_soup(self, soup):
        """
        Given topic HTML soup, apply post-process steps
        """

        soup = self._replace_notifications(soup)
        soup = self._replace_notes_to_editors(soup)
        soup = self._replace_links(soup)

        return soup

    def _replace_links(self, soup):
        """
        Given some HTML soup, replace links which look like
        Discourse topic URLs with either the pretty_url in
        the URL map, or the target in the Redirect map,
        or simply add the any url_prefix to the URL
        """

        for a in soup.findAll("a"):
            if a.get("href", "").startswith("/"):
                link_match = TOPIC_URL_MATCH.match(a["href"])

                if link_match:
                    topic_id = int(link_match.groupdict()["topic_id"])
                    url_parts = urlparse(a["href"])
                    full_path = os.path.join(
                        self.url_prefix, url_parts.path.lstrip("/")
                    )

                    if topic_id in self.url_map:
                        url_parts = url_parts._replace(
                            path=self.url_map[topic_id]
                        )
                    elif full_path in self.redirect_map:
                        url_parts = url_parts._replace(
                            path=self.redirect_map[full_path]
                        )
                    else:
                        url_parts = url_parts._replace(path=full_path)

                    a["href"] = urlunparse(url_parts)

        return soup

    def _parse_url_map(self, index_soup):
        """
        Given the HTML soup of an index topic
        extract the URL mappings from the "URLs" section.

        The URLs section should contain a table of
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

        url_soup = self._get_section(index_soup, "URLs")
        url_map = {}
        warnings = []

        if url_soup:
            for row in url_soup.select("tr:has(td)"):
                topic_a = row.select_one(f"td:first-child a[href]")
                path_td = row.select_one("td:last-child")

                if not topic_a or not path_td:
                    warnings.append("Could not parse URL map item {item}")
                    continue

                topic_url = topic_a.attrs.get("href", "")
                topic_path = urlparse(topic_url).path
                topic_match = TOPIC_URL_MATCH.match(topic_path)

                pretty_path = path_td.text

                if not topic_match or not pretty_path.startswith(
                    self.url_prefix
                ):
                    warnings.append("Could not parse URL map item {item}")
                    continue

                topic_id = int(topic_match.groupdict()["topic_id"])

                url_map[pretty_path] = topic_id

        # Add the reverse mappings as well, for efficiency
        ids_to_paths = dict([reversed(pair) for pair in url_map.items()])
        url_map.update(ids_to_paths)

        # Add the homepage path
        home_path = self.url_prefix
        if home_path != "/" and home_path.endswith("/"):
            home_path = home_path.rstrip("/")
        url_map[home_path] = self.index_topic_id
        url_map[self.index_topic_id] = home_path

        return url_map, warnings

    def _parse_redirect_map(self, index_soup):
        """
        Given the HTML soup of an index topic
        extract the redirect mappings from the "Redirects" section.

        The URLs section should contain a table of
        "Path" to "Location" mappings
        (extra markup around this table doesn't matter)
        e.g.:

        <h1>Redirects</h1>
        <details>
            <summary>Mapping table</summary>
            <table>
            <tr><th>Path</th><th>Location</th></tr>
            <tr>
                <td>/my-funky-path</td>
                <td>/cool-page</td>
            </tr>
            <tr>
                <td>/some/other/path</td>
                <td>https://example.com/cooler-place</td>
            </tr>
            </table>
        </details>

        This will typically be generated in Discourse from Markdown similar to
        the following:

        # Redirects

        [details=Mapping table]
        | Path | Path |
        | -- | -- |
        | /my-funky-path | /cool-page |
        | /some/other/path | https://example.com/cooler-place |
        """

        redirect_soup = self._get_section(index_soup, "Redirects")
        redirect_map = {}
        warnings = []

        if redirect_soup:
            for row in redirect_soup.select("tr:has(td)"):
                path_cell = row.select_one(f"td:first-child")
                location_cell = row.select_one("td:last-child")

                if not path_cell or not location_cell:
                    warnings.append(
                        f"Could not parse redirect map {path_cell}"
                    )
                    continue

                path = path_cell.text
                location = location_cell.text

                if not path.startswith(self.url_prefix):
                    warnings.append(f"Could not parse redirect map for {path}")
                    continue

                if not (
                    location.startswith(self.url_prefix)
                    or validators.url(location, public=True)
                ):
                    warnings.append(
                        f"Redirect map location {location} is invalid"
                    )
                    continue

                if path in self.url_map:
                    warnings.append(
                        f"Redirect path {path} clashes with URL map"
                    )
                    continue

                redirect_map[path] = location

        return redirect_map, warnings

    def _replace_notes_to_editors(self, soup):
        """
        Given HTML soup, remove 'NOTE TO EDITORS' sections.

        We expect these sections to be of the HTML format:

        <blockquote>
            <p>
            <img title=":construction:" class="emoji" ...>
            <strong>NOTE TO EDITORS</strong>
            <img title=":construction:" class="emoji" ...>
            </p>
            <p> ... </p>
        </blockquote>

        This is the Markup structure that Discourse will generate
        from the following Markdown:

        > :construction: **NOTE TO EDITORS** :construction:
        >
        > ...
        """

        notes_to_editors_text = soup.find_all(text="NOTE TO EDITORS")

        for text in notes_to_editors_text:
            # If this section is of the expected HTML format,
            # we should find the <aside> container 4 levels up from
            # the "NOTE TO EDITORS" text
            container = text.parent.parent.parent.parent

            if (
                container.name == "aside"
                and "quote" in container.attrs["class"]
            ):
                container.decompose()

        return soup

    def _replace_notifications(self, soup):
        """
        Given some BeautifulSoup of a document,
        replace blockquotes with the appropriate notification markup.

        E.g. the following Markdown in a Discourse topic:

            > ⓘ Content

        Will generate the following markup, as per the CommonMark spec
        (https://spec.commonmark.org/0.29/#block-quotes):

            <blockquote><p>ⓘ Content</p></blockquote>

        Becomes:

            <div class="p-notification">
                <div class="p-notification__response">
                    <p class="u-no-padding--top u-no-margin--bottom">
                        Content
                    </p>
                </div>
            </div>
        """

        notification_html = (
            "<div class='{{ notification_class }}'>"
            "<div class='p-notification__response'>"
            "{{ contents | safe }}"
            "</div></div>"
        )

        notification_template = Template(notification_html)
        for note_string in soup.findAll(text=re.compile("ⓘ ")):
            first_paragraph = note_string.parent
            blockquote = first_paragraph.parent
            last_paragraph = blockquote.findChildren(recursive=False)[-1]

            if first_paragraph.name == "p" and blockquote.name == "blockquote":
                # Remove extra padding/margin
                first_paragraph.attrs["class"] = "u-no-padding--top"
                if last_paragraph.name == "p":
                    if "class" in last_paragraph.attrs:
                        last_paragraph.attrs["class"] += " u-no-margin--bottom"
                    else:
                        last_paragraph.attrs["class"] = "u-no-margin--bottom"

                # Remove control emoji
                notification_html = blockquote.encode_contents().decode(
                    "utf-8"
                )
                notification_html = re.sub(
                    r"^\n?<p([^>]*)>ⓘ +", r"<p\1>", notification_html
                )

                notification = notification_template.render(
                    notification_class="p-notification",
                    contents=notification_html,
                )
                blockquote.replace_with(
                    BeautifulSoup(notification, features="html.parser")
                )

        for warning in soup.findAll("img", title=":warning:"):
            first_paragraph = warning.parent
            blockquote = first_paragraph.parent
            last_paragraph = blockquote.findChildren(recursive=False)[-1]

            if first_paragraph.name == "p" and blockquote.name == "blockquote":
                warning.decompose()

                # Remove extra padding/margin
                first_paragraph.attrs["class"] = "u-no-padding--top"
                if last_paragraph.name == "p":
                    if "class" in last_paragraph.attrs:
                        last_paragraph.attrs["class"] += " u-no-margin--bottom"
                    else:
                        last_paragraph.attrs["class"] = "u-no-margin--bottom"

                # Strip leading space
                first_item = last_paragraph.contents[0]
                first_item.replace_with(first_item.lstrip(" "))

                notification = notification_template.render(
                    notification_class="p-notification--caution",
                    contents=blockquote.encode_contents().decode("utf-8"),
                )

                blockquote.replace_with(
                    BeautifulSoup(notification, features="html.parser")
                )

        return soup

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

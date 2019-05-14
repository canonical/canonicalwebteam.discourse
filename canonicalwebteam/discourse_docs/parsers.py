# Standard library
import re
from urllib.parse import urlparse

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


def resolve_path(path, url_map):
    """
    Given a path to a Discourse topic, and a mapping of
    URLs to IDs and IDs to URLs, resolve the path to a topic ID

    A PathNotFoundError will be raised if the path is not recognised.

    A RedirectFoundError will be raised if the topic should be
    accessed at a different URL path.
    """

    if path in url_map:
        topic_id = url_map[path]
    else:
        topic_match = TOPIC_URL_MATCH.match(path)

        if not topic_match:
            raise PathNotFoundError(path)

        topic_id = int(topic_match.groupdict()["topic_id"])

        if not topic_id:
            raise PathNotFoundError(path)

        if topic_id in url_map:
            raise RedirectFoundError(path, target_url=url_map[topic_id])

    return topic_id


def parse_index(topic):
    """
    Parse the index document topic to parse out:
    - The body HTML
    - The navigation markup
    - The URL mappings

    Set all as properties on the object
    """

    index = parse_topic(topic)
    index_soup = BeautifulSoup(index["body_html"], features="html.parser")

    # Get the nav
    index["body_html"] = str(
        get_preamble(index_soup, break_on_title="Navigation")
    )

    # Parse URL mapping
    index["url_map"], url_warnings = parse_url_map(index_soup)
    # Add the homepage path
    index["url_map"]["/"] = topic["id"]
    index["url_map"][topic["id"]] = "/"

    # Parse redirects
    index["redirect_map"], redirect_warnings = parse_redirect_map(
        index_soup, index["url_map"]
    )

    index["warnings"] = url_warnings + redirect_warnings

    # Parse navigation
    index["navigation"] = parse_navigation(index_soup, index["url_map"])

    return index


def parse_redirect_map(soup, url_map):
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

    redirect_soup = get_section(soup, "Redirects")
    redirect_map = {}
    warnings = []

    if redirect_soup:
        for row in redirect_soup.select("tr:has(td)"):
            path_cell = row.select_one(f"td:first-child")
            location_cell = row.select_one("td:last-child")

            if not path_cell or not location_cell:
                warnings.append(f"Could not parse redirect map {path_cell}")
                continue

            path = path_cell.text
            location = location_cell.text

            if not path.startswith("/"):
                warnings.append(f"Could not parse redirect map for {path}")
                continue

            if not (
                location.startswith("/")
                or validators.url(location, public=True)
            ):
                warnings.append(f"Redirect map location {location} is invalid")
                continue

            if path in url_map:
                warnings.append(f"Redirect path {path} clashes with URL map")
                continue

            redirect_map[path] = location

    return redirect_map, warnings


def parse_topic(topic):
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

    return {
        "title": topic["title"],
        "body_html": process_topic_html(
            topic["post_stream"]["posts"][0]["cooked"]
        ),
        "updated": humanize.naturaltime(updated_datetime.replace(tzinfo=None)),
        "topic_path": f"/t/{topic['slug']}/{topic['id']}",
    }


def parse_navigation(index_soup, url_map):
    """
    Given the HTML soup of a index topic
    extract the "navigation" section, and rewrite any
    links in the url_map
    """

    nav_soup = get_section(index_soup, "Navigation")
    nav_html = "Navigation missing"

    if nav_soup:
        # Convert links to the form needed in this site
        for link in nav_soup.find_all("a"):
            if "href" in link.attrs:
                url = link.attrs["href"]
                link_match = TOPIC_URL_MATCH.match(url)

                if link_match:
                    topic_id = int(link_match.groupdict()["topic_id"])
                    if topic_id in url_map:
                        link.attrs["href"] = url_map[topic_id]
        nav_html = str(nav_soup)

    return nav_html


def parse_url_map(index_soup):
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
            <td><a href="https://forum.example.com/t/place/11">Place</a></td>
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

    url_soup = get_section(index_soup, "URLs")
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

            if not topic_match or not pretty_path.startswith("/"):
                warnings.append("Could not parse URL map item {item}")
                continue

            topic_id = int(topic_match.groupdict()["topic_id"])

            url_map[pretty_path] = topic_id

    # Add the reverse mappings as well, for efficiency
    ids_to_paths = dict([reversed(pair) for pair in url_map.items()])
    url_map.update(ids_to_paths)

    return url_map, warnings


def process_topic_html(html):
    """
    Given topic HTML, apply post-process steps
    """

    soup = BeautifulSoup(html, features="html.parser")
    soup = replace_notifications(soup)
    soup = replace_notes_to_editors(soup)

    return str(soup)


def replace_notes_to_editors(soup):
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

        if container.name == "aside" and "quote" in container.attrs["class"]:
            container.decompose()

    return soup


def replace_notifications(soup):
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
                <p class="u-no-padding--top u-no-margin--bottom">Content</p>
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
            notification_html = blockquote.encode_contents().decode("utf-8")
            notification_html = re.sub(
                r"^\n?<p([^>]*)>ⓘ +", r"<p\1>", notification_html
            )

            notification = notification_template.render(
                notification_class="p-notification", contents=notification_html
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


def get_preamble(soup, break_on_title):
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


def get_section(soup, title_text):
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

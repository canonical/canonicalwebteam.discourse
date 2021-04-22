# Standard library
import os
from urllib.parse import urlparse

# Packages
import dateutil.parser
import humanize
from bs4 import BeautifulSoup
from jinja2 import Template

# Local
from canonicalwebteam.discourse.parsers.base_parser import (
    TOPIC_URL_MATCH,
    BaseParser,
)
from canonicalwebteam.discourse.exceptions import (
    PathNotFoundError,
    RedirectFoundError,
)


class DocParser(BaseParser):
    def __init__(
        self,
        api,
        index_topic_id,
        url_prefix,
        tutorials_index_topic_id=None,
        tutorials_url_prefix=None,
    ):
        self.versions = []
        self.navigations = []
        self.url_map_versions = {}

        # Tutorials
        self.tutorials_url_map = {}
        self.tutorials_index_topic_id = tutorials_index_topic_id
        self.tutorials_url_prefix = tutorials_url_prefix

        return super().__init__(api, index_topic_id, url_prefix)

    def parse(self):
        """
        Get the index topic and split it into:
        - navigation
        - index document content
        - URL map
        - redirects map
        And set those as properties on this object
        """
        self.index_topic = self.api.get_topic(self.index_topic_id)

        raw_index_soup = BeautifulSoup(
            self.index_topic["post_stream"]["posts"][0]["cooked"],
            features="html.parser",
        )

        # Parse navigation and version table (if present)
        self.versions = self._parse_version_table(raw_index_soup)
        self.navigations = self._parse_navigation_versions(raw_index_soup)

        # URL mapping
        self.url_map_versions = self._generate_url_map(self.navigations)
        self.url_map = self._generate_flat_url_map(self.url_map_versions)

        # URL mapping for tutorials
        if self.tutorials_index_topic_id:
            self.tutorials_url_map = self._generate_tutorials_url_map(
                self.tutorials_index_topic_id
            )

        # Parse redirects mappings
        self.redirect_map, redirect_warnings = self._parse_redirect_map(
            raw_index_soup
        )
        self.warnings += redirect_warnings

    def parse_topic(self, topic, docs_version=""):
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

        # Remove Navigation section from all the index topics
        version_topics = [x["index"] for x in self.versions]

        if topic["id"] in version_topics:
            topic_soup = self._get_preamble(
                topic_soup,
                break_on_title="Navigation",
            )

        # Set navigation for the current version
        self.navigation = self._generate_navigation(
            self.navigations, docs_version
        )

        soup = self._process_topic_soup(topic_soup)

        if self.tutorials_index_topic_id:
            self._parse_tutorials(topic_soup)

        self._replace_lightbox(soup)
        sections = self._get_sections(soup)

        return {
            "title": topic["title"],
            "body_html": str(soup),
            "sections": sections,
            "updated": humanize.naturaltime(
                updated_datetime.replace(tzinfo=None)
            ),
            "topic_id": topic["id"],
            "topic_path": topic_path,
        }

    def resolve_path(self, relative_path):
        """
        Given a path to a Discourse topic, and a mapping of
        URLs to IDs and IDs to URLs, resolve the path to a topic ID

        A PathNotFoundError will be raised if the path is not recognised.

        A RedirectFoundError will be raised if the topic should be
        accessed at a different URL path.
        """
        version = ""
        version_paths = [x["path"] for x in self.versions]
        version_path = relative_path.lstrip("/").split("/")[0]

        if version_path in version_paths:
            version = version_path

        full_path = os.path.join(self.url_prefix, relative_path.lstrip("/"))

        if full_path in self.redirect_map:
            raise RedirectFoundError(
                full_path, target_url=self.redirect_map[full_path]
            )
        elif full_path in self.url_map_versions[version]:
            topic_id = self.url_map_versions[version][full_path]
        else:
            topic_id = self._get_url_topic_id(relative_path)

            if topic_id in self.url_map_versions[version]:
                raise RedirectFoundError(
                    full_path,
                    target_url=self.url_map_versions[version][topic_id],
                )

        return topic_id, version

    def resolve_path_all_versions(self, relative_path, current_version):
        """
        Given a path to a pretty URL try to obtain all the
        paths using this URL for all the different versions.

        If the path doesn't exist the output will be the default
        version index path

        eg: /machines
        {"v1": "/v1/machines/", "": "/machines/"}
        """
        result = {}

        if relative_path.startswith(f"/{current_version}/"):
            chars_to_remove = len(current_version) + 1
            relative_path = relative_path[chars_to_remove:]

        for version in self.url_map_versions.keys():
            if version:
                version_relative_path = f"/{version}{relative_path}"
            else:
                version_relative_path = relative_path

            version_relative_path = f"{self.url_prefix}{version_relative_path}"

            if version_relative_path in self.url_map_versions[version]:
                result[version] = version_relative_path
            else:
                result[version] = f"{self.url_prefix}/{version}"

        return result

    def _generate_url_map(self, navigations):
        """
        Given all the navigation versions defined
        this method will iterate over them and call
        _parse_topic_url_map to process each of them.
        """

        url_map = {}

        for version_path, navigation in navigations.items():
            url_map[version_path] = {}

            if version_path:
                url_prefix = f"{self.url_prefix}/{version_path}"
            else:
                url_prefix = self.url_prefix

            for item in navigation["nav_items"]:
                pretty_path = item["path"]
                topic_url = item["navlink_href"]

                # URL has a path but is not linked to a topic
                if pretty_path and not topic_url:
                    self.warnings.append(
                        f"Missing topic link for {pretty_path}"
                    )
                    continue

                # There is a link to a topic without path
                if topic_url and not pretty_path:
                    # It's fine to not specify a path for an external link
                    if not self._match_url_with_topic(topic_url):
                        continue

                    # It's fine to not specify a path for the main topic
                    if self.index_topic != self._get_url_topic_id(topic_url):
                        self.warnings.append(
                            f"Missing topic path for {topic_url}"
                        )
                        continue

                # No need to map them when missing
                if not topic_url or not pretty_path:
                    continue

                topic_path = urlparse(topic_url).path
                topic_match = TOPIC_URL_MATCH.match(topic_path)

                if not pretty_path.startswith("/"):
                    pretty_path = "/" + pretty_path
                if not pretty_path.startswith(url_prefix):
                    pretty_path = url_prefix + pretty_path

                if not topic_match or not pretty_path.startswith(url_prefix):
                    self.warnings.append("Could not parse URL map item {item}")
                    continue

                topic_id = int(topic_match.groupdict()["topic_id"])

                url_map[version_path][pretty_path] = topic_id

            # Add the reverse mappings as well, for efficiency
            ids_to_paths = dict(
                [reversed(pair) for pair in url_map[version_path].items()]
            )
            url_map[version_path].update(ids_to_paths)

            # Add the homepage path
            home_path = url_prefix

            if home_path != "/" and home_path.endswith("/"):
                home_path = home_path.rstrip("/")

            url_map[version_path][home_path] = navigation["index"]
            url_map[version_path][navigation["index"]] = home_path

        return url_map

    def _generate_flat_url_map(self, url_map_versions):
        """
        This method generates a flatten URL map for
        compatibility with the other parsers, so things
        like sitemap generation work as expected.
        """
        url_map = {}

        for version, version_url_map in url_map_versions.items():
            url_map.update(version_url_map)

        return url_map

    def _parse_navigation_versions(self, main_index_soup):
        """
        Given the HTML soup of an index topic
        extract the navigation table from the "Navigation"
        section.

        The navigation section should contain a table of
        "Level", "Path" and "Navlink" mappings
        (extra markup around this table doesn't matter)

        # Navigation

        [details=Navigation]
        | Level | Path | Navlink |
        | -- | -- | -- |
        | 1 | | Getting started |
        | 1 | install | [Install](/t/install-the-example-charm/100000) |
        | 2 | install/gke | [GKE](/t/install-the-example-charm-on-gke/100002) |
        | 2 | install/aks | [AKS](/t/install-the-example-charm-on-gke/100002) |
        | 2 | install/eks | [EKS](/t/install-the-example-charm-on-gke/100002) |
        [/details]

        Optionally, it can contain a version table linking to
        previous docs topics:
        [details=Documentation versions]
        | Path | Version |
        |--|--|
        |  | 2.x, 3.x and dev |
        | v1 | [1.x and older](/t/1x-doc-nav) |
        [/details]
        """
        navigations = {}

        for version in self.versions:
            version["nav_items"] = self._parse_navigation_table(
                version["index"], main_index_soup
            )
            navigations[version["path"]] = version

        return navigations

    def _parse_navigation_table(self, topic_id, main_index_soup):
        """
        Given the HTML soup of an index topic
        extract the navigation table from the "Navigation" section.

        The URLs section should contain a table of
        "Path" to "Location" mappings
        (extra markup around this table doesn't matter)

        # Navigation

        [details=Navigation]
        | Level | Path | Navlink |
        | -- | -- | -- |
        | 1 | | Getting started |
        | 1 | install | [Install](/t/install-the-example-charm/100000) |
        | 2 | install/gke | [GKE](/t/install-the-example-charm-on-gke/100002) |
        | 2 | install/aks | [AKS](/t/install-the-example-charm-on-gke/100002) |
        | 2 | install/eks | [EKS](/t/install-the-example-charm-on-gke/100002) |
        [/details]
        """
        nav_items = []

        if topic_id == self.index_topic_id:
            index_soup = main_index_soup
        else:
            index_topic = self.api.get_topic(topic_id)
            index_soup = BeautifulSoup(
                index_topic["post_stream"]["posts"][0]["cooked"],
                features="html.parser",
            )

        navigation_soup = self._get_section(index_soup, "Navigation")

        if navigation_soup:
            navigation_table = []
            tables = navigation_soup.findAll("table")

            for table in tables:
                if table.select("tr:has(> th:-soup-contains('Navlink'))"):
                    navigation_table = table.select("tr:has(td)")

            for row in navigation_table:
                item = {}
                level = row.select_one("td:first-child").text

                if not level.isnumeric() or int(level) < 0:
                    self.warnings.append(f"Invalid level used: {level}")
                    continue

                path = row.select_one("td:nth-of-type(2)").text
                navlink_cell = row.select_one("td:last-child")

                navlink_href = navlink_cell.find("a", href=True)
                if navlink_href:
                    navlink_href = navlink_href.get("href")

                navlink_text = navlink_cell.text

                item["level"] = int(level)
                item["path"] = path
                item["navlink_href"] = navlink_href
                item["navlink_text"] = navlink_text
                item["children"] = []

                nav_items.append(item)

        return nav_items

    def _parse_version_table(self, main_index_soup):
        """
        Given the HTML soup of an index topic
        extract the version table from the "Navigation"
        section.

        The navigation section should contain a table of
        "Path" and "Version" mappings
        (extra markup around this table doesn't matter)

        # Navigation

        [details=Documentation versions]
        | Path | Version |
        |--|--|
        |  | 2.x, 3.x and dev |
        | v1 | [1.x and older](/t/1x-doc-nav) |
        [/details]
        """
        navigation_soup = self._get_section(main_index_soup, "Navigation")

        if not navigation_soup:
            return None

        # Get and identify the version table
        version_table = None
        tables = navigation_soup.findAll("table")

        for table in tables:
            if table.select("tr:has(> th:-soup-contains('Version'))"):
                version_table = table.select("tr:has(td)")

        # Parse version table or create a default version if missing
        if version_table:
            versions = []

            for row in version_table:
                topic_id = None
                path = row.select_one("td:first-child").text
                version_cell = row.select_one("td:last-child")

                version_href = version_cell.find("a", href=True)
                if version_href:
                    version_href = version_href.get("href")
                    topic_id = self._get_url_topic_id(version_href)

                if not topic_id or not path:
                    topic_id = self.index_topic_id

                versions.append(
                    {
                        "index": int(topic_id),
                        "path": path,
                        "version": version_cell.text,
                        "nav_items": [],
                    }
                )
        else:
            versions = [
                {
                    "index": int(self.index_topic_id),
                    "path": "",
                    "version": "latest",
                    "nav_items": [],
                }
            ]

        return versions

    def _process_nav_levels(self, nav_items):
        """
        Given a list of nav_items, it will generate a tree structure
        """
        root = {}
        root["children"] = []

        if nav_items:
            first_level = nav_items[0]["level"]

            # We need a level 0 parent to group them
            if first_level != 0:
                nav_items.insert(
                    0,
                    {
                        "level": 0,
                        "path": "",
                        "navlink_href": None,
                        "navlink_text": None,
                        "children": [],
                    },
                )

            for node in nav_items:
                last = root
                for _ in range(node["level"]):
                    last = last["children"][-1]
                last["children"].append(node)

        return root["children"]

    def _generate_navigation(self, navigations, version_path):
        navigation = navigations[version_path]

        # Replace links with url_map
        for item in navigation["nav_items"]:
            if item["navlink_href"] and self._match_url_with_topic(
                item["navlink_href"]
            ):
                topic_id = self._get_url_topic_id(item["navlink_href"])

                if topic_id in self.url_map_versions[version_path]:
                    item["navlink_href"] = self.url_map_versions[version_path][
                        topic_id
                    ]

        # Generate tree structure with levels
        navigation["nav_items"] = self._process_nav_levels(
            navigation["nav_items"]
        )

        return navigation

    def _parse_tutorials(self, soup):
        """
        Get a list of tutorials topic IDs from all the
        tutorial tables in a topic

        Example of a tutorial table:
        | Tutorials |
        | -- |
        | https://discourse.charmhub.io/t/add-docs-to-your-charm-page/3784 |
        """
        tutorial_tables = []

        tables = soup.select("table:has(th:-soup-contains('Tutorials'))")

        for table in tables:
            table_rows = table.select("tr:has(td)")

            if table_rows:
                tutorial_set = {"soup_table": table, "topics": []}

                # Get all tutorial topics in this table
                for row in table_rows:
                    navlink_href = row.find("a", href=True)

                    if navlink_href:
                        navlink_href = navlink_href.get("href")

                        try:
                            topic_id = self._get_url_topic_id(navlink_href)
                        except PathNotFoundError:
                            self.warnings.append("Invalid tutorial URL")
                            continue

                        tutorial_set["topics"].append(topic_id)

                tutorial_tables.append(tutorial_set)

        if tutorial_tables:
            # Get tutorials metadata from Data Explorer API
            tutorial_data = self._parse_tutorials_metadata(tutorial_tables)

            # Remplace tables with cards
            self._replace_tutorials(tutorial_tables, tutorial_data)

    def _parse_tutorials_metadata(self, tutorial_tables):
        """
        Get multiple tutorials from one API call and
        parse their metadata table

        Example of metadata table:
        | — | ----------------------- |
        | Summary | Learn how to deploy |
        | Categories | cloud |
        | Difficulty | 2 |
        | Author | John |
        """
        if not self.api.get_topics_query_id:
            self.warnings.append(
                "Tutorials found but Data Explorer query is not set"
            )

        # Topics that we need from the API
        topics = []

        for table in tutorial_tables:
            topics += table["topics"]

        response = self.api.get_topics(topics)
        tutorial_data = {}

        for topic in response:
            topic_soup = BeautifulSoup(
                topic[3],
                features="html.parser",
            )

            # Get table with tutorial metadata
            rows = topic_soup.select("table:first-child tr:has(td)")

            if not rows:
                self.warnings.append(
                    f"Invalid metadata table for tutorial topic {topic[0]}"
                )
                continue

            link = self.tutorials_url_map.get(
                topic[0], f"{self.api.base_url}/t/{topic[2]}/{topic[0]}"
            )

            metadata = {"title": topic[1], "link": link}
            for row in rows:
                key = row.select_one("td:first-child").text.lower()
                value = row.select_one("td:last-child").text
                metadata[key] = value

            tutorial_data[topic[0]] = metadata

        return tutorial_data

    def _generate_tutorials_url_map(self, index_topic_id):
        index_topic = self.api.get_topic(index_topic_id)
        raw_index_soup = BeautifulSoup(
            index_topic["post_stream"]["posts"][0]["cooked"],
            features="html.parser",
        )

        url_map, url_warnings = self._parse_url_map(
            raw_index_soup, self.tutorials_url_prefix, index_topic_id, "URLs"
        )

        self.warnings.extend(url_warnings)

        return url_map

    def _replace_tutorials(self, tutorial_tables, tutorial_data):
        """
        Replace tutorial tables to cards
        """
        card_template = Template(
            (
                '<div class="row">'
                "{% for tutorial in tutorials %}"
                '<div class="col-4 col-medium-3 p-card">'
                '<div class="p-card__content">'
                '<h3 class="p-card__title p-heading--four">'
                '<a class="inline-onebox" href="{{tutorial.link}}">'
                "{{ tutorial.title }}</a></h3>"
                "<p>{{ tutorial.summary }}</p>"
                "</div>"
                "</div>"
                "{% endfor %}"
                "</div>"
            )
        )

        for table in tutorial_tables:
            table_cards = [tutorial_data[topic] for topic in table["topics"]]

            card = card_template.render(
                tutorials=table_cards,
            )
            table["soup_table"].replace_with(
                BeautifulSoup(card, features="html.parser")
            )

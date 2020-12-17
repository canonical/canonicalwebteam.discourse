# Standard library
from urllib.parse import urlparse

# Packages
from bs4 import BeautifulSoup

# Local
from canonicalwebteam.discourse.parsers.base_parser import (
    TOPIC_URL_MATCH,
    BaseParser,
)


class DocParser(BaseParser):
    def __init__(self, api, index_topic_id, url_prefix, category_id=None):
        self.version_topics = []
        self.version_paths = []
        return super().__init__(api, index_topic_id, url_prefix, category_id)

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
        navigation = self._parse_navigation_section(raw_index_soup)
        self.url_map = self._parse_version_url_map(navigation, raw_index_soup)
        self.navigation = self._update_navigation_links(navigation)
        self.version_paths = [x["path"] for x in self.navigation]
        self.version_topics = [x["index"] for x in self.navigation]

        # Parse redirects mappings
        self.redirect_map = self._parse_redirect_map(raw_index_soup)

    def parse_topic(self, topic):
        # Override to remove Navigation section from all the index topics
        parsed_topic = super().parse_topic(topic)

        if parsed_topic["topic_id"] in self.version_topics:
            parsed_topic["body_html"] = str(
                self._get_preamble(
                    BeautifulSoup(
                        parsed_topic["body_html"],
                        features="html.parser",
                    ),
                    break_on_title="Navigation",
                )
            )
        return parsed_topic

    def resolve_path(self, relative_path):
        # Override to return docs version
        version = ""
        version_path = relative_path.lstrip("/").split("/")[0]
        if version_path in self.version_paths:
            version = version_path

        return super().resolve_path(relative_path), version

    def _parse_version_url_map(self, navigation, main_index_soup):
        """
        Given all the navigation versions defined
        this method will iterate over them and call
        _parse_topic_url_map to process each topic
        index.
        """

        url_map = {}

        for version in navigation:
            if version["index"] == self.index_topic_id:
                raw_index_soup = main_index_soup
                url_prefix = self.url_prefix
            else:
                index_topic = self.api.get_topic(version["index"])
                raw_index_soup = BeautifulSoup(
                    index_topic["post_stream"]["posts"][0]["cooked"],
                    features="html.parser",
                )
                url_prefix = f'{self.url_prefix}/{version["path"]}'

            url_map.update(
                self._parse_topic_url_map(
                    raw_index_soup,
                    url_prefix,
                    version["index"],
                    "Navigation",
                )
            )

        return url_map

    def _parse_topic_url_map(
        self, index_soup, url_prefix, index_topic_id, url_section_name
    ):
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

        url_soup = self._get_section(index_soup, url_section_name)
        url_map = {}

        if url_soup:
            navigation_table = []
            tables = url_soup.findAll("table")

            for table in tables:
                if table.select("tr:has(> th:-soup-contains('Navlink'))"):
                    navigation_table = table.select("tr:has(td)")

            for row in navigation_table:
                pretty_path = row.select_one("td:nth-of-type(2)").text
                topic_a = row.select_one("td:last-child a[href]")

                if not topic_a or not pretty_path:
                    self.warnings.append(
                        f"Could not parse URL map item {pretty_path}:{topic_a}"
                    )
                    continue

                topic_url = topic_a.attrs.get("href", "")
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

        return url_map

    def _parse_navigation_section(self, main_index_soup):
        """
        Given the HTML soup of an index topic
        extract the navigation table and the version table
        from the "Navigation" section.

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
            navigation = self._parse_version_table(version_table)
        else:
            navigation = [
                {
                    "index": self.index_topic_id,
                    "path": "",
                    "version": "latest",
                    "nav_items": [],
                }
            ]

        for i, version in enumerate(navigation):
            navigation[i]["nav_items"] = self._parse_navigation_table(
                version["index"], main_index_soup
            )

        return navigation

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

        return self._process_nav_levels(nav_items)

    def _parse_version_table(self, version_table):
        """
        Given a list of nav_items, it will generate a tree structure
        """
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
                    "index": topic_id,
                    "path": path,
                    "version": version_cell.text,
                    "nav_items": [],
                }
            )

        return versions

    def _process_nav_levels(self, nav_items):
        """
        Given a list of nav_items, it will generate a tree structure
        """
        root = {}
        root["children"] = []

        for node in nav_items:
            last = root
            for _ in range(node["level"]):
                last = last["children"][-1]
            last["children"].append(node)

        return root["children"]

    def _update_navigation_links(self, navigation):
        def update_link(nav):
            if nav["navlink_href"]:
                topic_id = self._get_url_topic_id(nav["navlink_href"])
                nav["navlink_href"] = self.url_map[topic_id]

            for nav in nav["children"]:
                update_link(nav)

        for version in navigation:
            for nav in version["nav_items"]:
                update_link(nav)

        return navigation

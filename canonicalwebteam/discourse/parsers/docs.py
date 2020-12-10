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
        self.api = api
        self.index_topic_id = index_topic_id
        self.url_prefix = url_prefix
        self.category_id = category_id

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

        # Parse URL map & redirects mappings (get warnings)
        self.url_map, url_warnings = self._parse_url_map(
            raw_index_soup, self.url_prefix, self.index_topic_id, "Navigation"
        )
        self.redirect_map, redirect_warnings = self._parse_redirect_map(
            raw_index_soup
        )

        # Get body HTML
        self.index_document = self.parse_topic(index_topic)
        index_soup = BeautifulSoup(
            self.index_document["body_html"], features="html.parser"
        )
        self.index_document["body_html"] = str(
            self._get_preamble(index_soup, break_on_title="Navigation")
        )

        # Parse navigation
        self.navigation, nav_warnings = self._parse_navigation(index_soup)

        self.warnings = url_warnings + nav_warnings + redirect_warnings
        self.metadata = None

    def _parse_url_map(
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
        warnings = []

        if url_soup:
            for row in url_soup.select("table:first-child tr:has(td)"):
                pretty_path = row.select_one("td:nth-of-type(2)").text
                topic_a = row.select_one("td:last-child a[href]")

                if not topic_a or not pretty_path:
                    warnings.append(
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

    def _parse_navigation(self, index_soup):
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
        warnings = []
        navigation_soup = self._get_section(index_soup, "Navigation")

        if navigation_soup:
            nav_items = []

            for row in navigation_soup.select("table:first-child tr:has(td)"):
                item = {}
                level = row.select_one("td:first-child").text

                if not level.isnumeric() or int(level) < 0:
                    warnings.append(f"Invalid level used: {level}")
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

        return self._process_nav_levels(nav_items), warnings

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

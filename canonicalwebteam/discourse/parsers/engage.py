# Standard library
import os

# Packages
import dateutil.parser
import humanize
from bs4 import BeautifulSoup

# Local
from canonicalwebteam.discourse.exceptions import (
    PathNotFoundError,
)
from canonicalwebteam.discourse.parsers.base_parser import BaseParser


class EngageParser(BaseParser):
    """
    Parser exclusively for Engage pages
    """

    def parse(self):
        """
        Get the index topic and split it into:
        - index document content
        - URL map
        And set those as properties on this object
        """
        index_topic = self.api.get_topic(self.index_topic_id)
        raw_index_soup = BeautifulSoup(
            index_topic["post_stream"]["posts"][0]["cooked"],
            features="html.parser",
        )

        # Parse URL
        self.url_map, self.warnings = self._parse_url_map(
            raw_index_soup, self.url_prefix, self.index_topic_id, "Metadata"
        )

        # Avoid markdown error to break site
        try:
            # Parse list of topics
            self.metadata = self._parse_metadata(raw_index_soup, "Metadata")
            self.takeovers = self._parse_metadata(raw_index_soup, "Takeovers")
        except IndexError:
            self.metadata = []
            self.takeovers = []
            self.warnings.append("Failed to parse metadata correctly")

        if index_topic["id"] != self.index_topic_id:
            # Get body and navigation HTML
            self.index_document = self.parse_topic(index_topic)

    def parse_topic(self, topic):
        """
        Parse a topic object of Engage pages category from the Discourse API
        and return document data:
        - title: The title of the engage page
        - body_html: The HTML content of the initial topic post
            (with some post-processing)
        - updated: A human-readable date, relative to now
            (e.g. "3 days ago")
        - topic_path: relative path of the topic
        """

        updated_datetime = dateutil.parser.parse(
            topic["post_stream"]["posts"][0]["updated_at"]
        )

        topic_path = f"/t/{topic['slug']}/{topic['id']}"

        topic_soup = BeautifulSoup(
            topic["post_stream"]["posts"][0]["cooked"], features="html.parser"
        )

        self.current_topic = {}
        content = []
        warnings = []
        metadata = []

        for row in topic_soup.contents[0]("tr"):
            metadata.append([cell.text for cell in row("td")])

        if metadata:
            metadata.pop(0)
            self.current_topic.update(metadata)
            content = topic_soup.contents
            # Remove takeover metadata table
            content.pop(0)
        else:
            warnings.append("Metadata could not be parsed correctly")

        # Find URL in order to find tags of current topic
        current_topic_path = next(
            path for path, id in self.url_map.items() if id == topic["id"]
        )
        self.current_topic_metadata = next(
            (
                item
                for item in self.metadata
                if item["path"] == current_topic_path
            ),
        )

        # Combine metadata from index with individual pages
        self.current_topic_metadata.update(self.current_topic)

        # Expose related topics for thank-you pages
        # This will make it available for the instance
        # rather than the view
        current_topic_related = self._parse_related(
            self.current_topic_metadata["tags"]
        )

        return {
            "title": topic["title"],
            "metadata": self.current_topic_metadata,
            "body_html": content,
            "updated": humanize.naturaltime(
                updated_datetime.replace(tzinfo=None)
            ),
            "related": current_topic_related,
            "topic_path": topic_path,
            "errors": warnings,
        }

    def resolve_path(self, relative_path):
        """
        Given a path to a Discourse topic, and a mapping of
        URLs to IDs and IDs to URLs, resolve the path to a topic ID

        A PathNotFoundError will be raised if the path is not recognised.
        """

        full_path = os.path.join(self.url_prefix, relative_path.lstrip("/"))

        if full_path in self.url_map:
            topic_id = self.url_map[full_path]
        else:
            raise PathNotFoundError(relative_path)

        return topic_id

    def get_topic(self, topic_id):
        """
        Receives a single topic_id and
        @return the content of the topic
        """
        index_topic = self.api.get_topic(topic_id)
        return self.parse_topic(index_topic)

    def _parse_related(self, tags):
        """
        Filter index topics by tag
        This provides a list of "Related engage pages"
        """
        index_list = [item for item in self.metadata if item["tags"] in tags]
        return index_list

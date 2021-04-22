# Packages
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# Local
from canonicalwebteam.discourse.parsers.base_parser import BaseParser


class TutorialParser(BaseParser):
    def __init__(self, api, index_topic_id, url_prefix):
        self.tutorials = None

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

        # Parse URL & redirects mappings (get warnings)
        self.url_map, url_warnings = self._parse_url_map(
            raw_index_soup, self.url_prefix, self.index_topic_id, "URLs"
        )
        self.redirect_map, redirect_warnings = self._parse_redirect_map(
            raw_index_soup
        )
        self.warnings = url_warnings + redirect_warnings

    def parse_topic(self, topic):
        if topic["id"] == self.index_topic_id:
            self.tutorials = self._get_tutorials_topics()

        return super().parse_topic(topic)

    def _get_sections(self, soup):
        headings = soup.findAll("h2")

        sections = []
        total_duration = datetime.strptime("00:00", "%M:%S")

        for heading in headings:
            section = {}
            section_soup = self._get_section(soup, heading.text)
            first_child = section_soup.find() if section_soup else None

            if first_child and first_child.text.startswith("Duration"):
                section["duration"] = first_child.text.replace(
                    "Duration: ", ""
                )

                try:
                    dt = datetime.strptime(section["duration"], "%M:%S")
                    total_duration += timedelta(
                        minutes=dt.minute, seconds=dt.second
                    )
                except Exception:
                    pass

                first_child.extract()

            section["title"] = heading.text
            section["content"] = str(section_soup)

            heading_pieces = filter(
                lambda s: s.isalnum() or s.isspace(), heading.text.lower()
            )
            section["slug"] = "".join(heading_pieces).replace(" ", "-")

            sections.append(section)

        sections = self._calculate_remaining_duration(total_duration, sections)

        return sections

    def _calculate_remaining_duration(self, total_duration, sections):
        for section in sections:
            if "duration" in section:
                try:
                    dt = datetime.strptime(section["duration"], "%M:%S")
                    total_duration -= timedelta(
                        minutes=dt.minute, seconds=dt.second
                    )
                    section["remaining_duration"] = total_duration.minute
                except Exception:
                    pass

        return sections

    def _get_tutorials_topics(self):
        if not self.api.get_topics_query_id:
            self.warnings.append("Data Explorer query ID is not set")

        # Topics that we need from the API
        topics = []

        for tutorial_id in self.url_map:
            if isinstance(tutorial_id, int):
                topics.append(tutorial_id)

        topics.remove(self.index_topic_id)

        response = self.api.get_topics(topics)
        tutorial_data = []

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

            link = self.url_map.get(
                topic[0], f"{self.api.base_url}/t/{topic[2]}/{topic[0]}"
            )

            metadata = {"id": topic[0], "title": topic[1], "link": link}
            for row in rows:
                key = row.select_one("td:first-child").text.lower()
                value = row.select_one("td:last-child").text
                metadata[key] = value

            tutorial_data.append(metadata)

        # Tutorial will be in the same order as in the URLs table
        return sorted(tutorial_data, key=lambda x: topics.index(x["id"]))

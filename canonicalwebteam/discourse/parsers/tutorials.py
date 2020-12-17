# Packages
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# Local
from canonicalwebteam.discourse.parsers.base_parser import BaseParser


class TutorialParser(BaseParser):
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
        self.url_map, url_warnings = self._parse_url_map(
            raw_index_soup, self.url_prefix, self.index_topic_id, "URLs"
        )
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

        if self.category_id:
            topics = self.get_all_topics_category()
            self.metadata = self._parse_metadata(
                self._replace_links(raw_index_soup, topics), "Metadata"
            )

    def get_all_topics_category(self):
        topics = []

        page = 0
        all = False

        while not all:
            try:
                response = self.api.get_topics_category(self.category_id, page)
            except Exception:
                break

            if (
                len(response["topic_list"]["topics"])
                < response["topic_list"]["per_page"]
            ):
                all = True
            else:
                page += 1

            if response["topic_list"]["topics"]:
                topics += response["topic_list"]["topics"]

        return topics

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

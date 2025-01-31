import re

# Packages
from slugify import slugify
from bs4 import BeautifulSoup

# Local
from canonicalwebteam.discourse.parsers.base_parser import BaseParser


class CategoryParser(BaseParser):
    """
    Parses a tables from a Discourse topic and stores them in a dictionary
    """

    def __init__(self, api, index_topic_id, url_prefix):
        self.category_metadata = None
        return super().__init__(api, index_topic_id, url_prefix)

    def parse_index_topic(self):
        """
        Retrieve the index topic raw html content.
        Find any data tables (distinguished by [details="NAME"]), store them
        in a dictionary and return it.
        """
        self.index_topic = self.api.get_topic(self.index_topic_id)
        raw_index_soup = BeautifulSoup(
            self.index_topic["post_stream"]["posts"][0]["cooked"],
            features="html.parser",
        )

        details_sections = raw_index_soup.find_all(
            "p", text=re.compile(r"\[details=.*\]")
        )
        data_tables = {}

        for section in details_sections:
            details_text = section.text
            section_name = re.search(r"\[details=(.*)\]", details_text).group(
                1
            )
            next_table = section.find_next("table")
            if next_table:
                data_tables[section_name] = self._parse_table(next_table)

        self.category_index_metadata = data_tables

    def _parse_table(self, table):
        """
        Parse HTML table(s) into a dictionary.

        :params table: HTML table element
        """
        headers = [slugify(th.text.strip()) for th in table.find_all("th")]
        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all("td")
            row = {
                headers[i]: cells[i].text.strip() for i in range(len(cells))
            }
            rows.append(row)
        return rows

    def parse_topic(self, topic):
        """
        Parse a topic and return the parsed content.

        :params topic: The topic object containing HTML soup and metadata
        """
        return super().parse_topic(topic)

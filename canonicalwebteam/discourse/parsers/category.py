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
        return super().__init__(api, index_topic_id, url_prefix)

    def parse_index_topic(self):
        """
        Retrieve the index topic raw html content.
        Find any data tables (distinguished by [details="NAME"] or
        <details><summary>NAME</summary>), store them in a dictionary.

        :return: Dictionary mapping section names to table data
        """
        self.index_topic = self.api.get_topic(self.index_topic_id)
        raw_index_soup = BeautifulSoup(
            self.index_topic["post_stream"]["posts"][0]["cooked"],
            features="html.parser",
        )

        data_tables = {}

        # This legacy method can be removed once this topic's updated:
        # https://discourse.ubuntu.com/t/vulnerability-knowledge-base-index/53193
        data_tables.update(
            self._extract_tables_based_details_paragraph(raw_index_soup)
        )

        data_tables.update(
            self._extract_tables_from_details_elements(raw_index_soup)
        )

        return data_tables

    def _extract_tables_based_details_paragraph(self, soup):
        """
        Extract tables that follow paragraphs with [details=NAME] format.

        :param soup: BeautifulSoup object containing the HTML
        :return: Dictionary mapping section names to table data
        """
        data_tables = {}
        details_sections = soup.find_all(
            "p", text=re.compile(r"\[details=.*\]")
        )

        for section in details_sections:
            details_text = section.text
            section_name = re.search(r"\[details=(.*)\]", details_text).group(
                1
            )
            next_table = section.find_next("table")
            if next_table:
                data_tables[section_name] = self._parse_table(next_table)

        return data_tables

    def _extract_tables_from_details_elements(self, soup):
        """
        Extract tables from within HTML <details> elements.

        :param soup: BeautifulSoup object containing the HTML
        :return: Dictionary mapping section names to table data
        """
        data_tables = {}
        details_elements = soup.find_all("details")

        for details in details_elements:
            summary = details.find("summary")
            if summary:
                section_name = summary.text.strip()
                table = details.find("table")
                if table:
                    data_tables[section_name] = self._parse_table(table)

        return data_tables

    def _parse_table(self, table):
        """
        Parse HTML table(s) into a dictionary.
        If a table cell contains a link (an `<a>` tag), both the text and the
        href URL are extracted.

        :param table: HTML table element
        """
        headers = [slugify(th.text.strip()) for th in table.find_all("th")]
        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all("td")
            row = {}

            for i, cell in enumerate(cells):
                if i >= len(headers):
                    continue

                key = headers[i]
                link = cell.find("a")
                if link and link.has_attr("href"):
                    row[key] = {"text": cell.text.strip(), "url": link["href"]}
                else:
                    row[key] = cell.text.strip()

            rows.append(row)

        return rows

    def parse_topic(self, topic):
        """
        Parse a topic and return the parsed content.

        :param topic: The topic object containing HTML soup and metadata
        """
        return super().parse_topic(topic)

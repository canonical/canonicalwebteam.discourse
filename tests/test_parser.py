import unittest
from unittest.mock import MagicMock
from canonicalwebteam.discourse.parsers.base_parser import BaseParser
from canonicalwebteam.discourse.parsers.docs import DocParser


class TestParser(unittest.TestCase):
    def test_parser_username_link(self):
        discourse_api_mock = MagicMock()
        discourse_api_mock.base_url = "https://base.url"

        parser = BaseParser(
            api=discourse_api_mock,
            index_topic_id=1,
            url_prefix="/",
            limit_redirects_to_url_prefix=False,
        )

        parsed_topic = parser.parse_topic(
            {
                "id": 1,
                "category_id": 1,
                "title": "Sample",
                "slug": "sample—text",
                "post_stream": {
                    "posts": [
                        {
                            "id": 11,
                            "cooked": (
                                "<a href='/u/evilnick'>@evilnick</a>"
                                "<a>No Link</a>"
                                "<a></a>"
                            ),
                            "updated_at": "2018-10-02T12:45:44.259Z",
                        }
                    ],
                },
            }
        )

        self.assertIn(
            '<a href="https://base.url/u/evilnick">@evilnick</a>',
            parsed_topic["body_html"],
        )

    def test_emdash_in_slug(self):
        discourse_api_mock = MagicMock()
        discourse_api_mock.base_url = "https://base.url"

        parser = BaseParser(
            api=discourse_api_mock,
            index_topic_id=1,
            url_prefix="/",
            limit_redirects_to_url_prefix=False,
        )

        parsed_topic = parser.parse_topic(
            {
                "id": 1,
                "category_id": 1,
                "title": "Sample",
                "slug": "sample—text",
                "post_stream": {
                    "posts": [
                        {
                            "id": 11,
                            "cooked": ("empty"),
                            "updated_at": "2018-10-02T12:45:44.259Z",
                        }
                    ],
                },
            }
        )

        self.assertEqual("/t/sample--text/1", parsed_topic["topic_path"])

    def test_url_prefix_limit(self):
        discourse_api_mock = MagicMock()
        discourse_api_mock.base_url = "https://base.url/"

        def get_topic(id):
            return {
                "id": 1,
                "category_id": 1,
                "title": "Sample",
                "slug": "sample—text",
                "post_stream": {
                    "posts": [
                        {
                            "id": 11,
                            "cooked": (
                                "<h1>Redirects</h1>"
                                "<details>"
                                "<summary>Mapping table</summary>"
                                "<table>"
                                "<tr><th>Path</th><th>Location</th></tr>"
                                "<tr>"
                                "<td>/docs/my-funky-path</td>"
                                "<td>/docs/cool-page</td>"
                                "</tr>"
                                "<tr>"
                                "<td>/docs/other/path</td>"
                                "<td>/scod/cooler-place</td>"
                                "</tr>"
                                "</table>"
                                "</details>"
                            ),
                            "updated_at": "2018-10-02T12:45:44.259Z",
                        }
                    ],
                },
            }

        discourse_api_mock.get_topic = get_topic

        limited_parser = DocParser(
            api=discourse_api_mock,
            index_topic_id=1,
            url_prefix="/docs",
            limit_redirects_to_url_prefix=True,
        )

        limited_parser.parse()

        self.assertNotIn(
            "/docs/other/path",
            limited_parser.redirect_map,
        )

        self.assertIn("/docs/my-funky-path", limited_parser.redirect_map)

        unlimited_parser = DocParser(
            api=discourse_api_mock,
            index_topic_id=1,
            url_prefix="/docs",
        )

        unlimited_parser.parse()

        self.assertIn(
            "/docs/other/path",
            unlimited_parser.redirect_map,
        )

        self.assertIn("/docs/my-funky-path", unlimited_parser.redirect_map)

import unittest
from unittest.mock import MagicMock
from canonicalwebteam.discourse.parsers.base_parser import BaseParser


class TestParser(unittest.TestCase):
    def test_parser_username_link(self):

        discourse_api_mock = MagicMock()
        discourse_api_mock.base_url = "https://base.url"

        parser = BaseParser(
            api=discourse_api_mock,
            index_topic_id=1,
            url_prefix="/",
        )

        parsed_topic = parser.parse_topic(
            {
                "id": 1,
                "category_id": 1,
                "title": "Sample",
                "slug": "sample",
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

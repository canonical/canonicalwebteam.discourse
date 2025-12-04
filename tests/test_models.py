import unittest
import httpretty
import requests

from canonicalwebteam.discourse.models import DiscourseAPI
from tests.fixtures.forum_mock import register_uris


class TestDiscourseAPI(unittest.TestCase):
    def setUp(self):
        httpretty.enable()
        register_uris()

        self.api = DiscourseAPI(
            base_url="https://discourse.example.com",
            session=requests.Session(),
        )

    def test_get_topic(self):
        """
        Check the DiscourseAPI object can get a topic by its ID
        """

        topic = self.api.get_topic(34)

        self.assertEqual(topic["id"], 34)
        self.assertEqual(topic["title"], "An index page")

    def test_require_authentication_raises_error_without_credentials(self):
        with self.assertRaises(ValueError) as context:
            self.api._require_authentication()
        self.assertIn("API authentication required", str(context.exception))


if __name__ == "__main__":
    unittest.main()

import json
import unittest
import unittest.mock
import httpretty
import requests

from canonicalwebteam.discourse.models import (
    DiscourseAPI,
    _normalise_tags,
    _build_tag_regex,
)
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


class TestNormaliseTags(unittest.TestCase):
    def test_none_returns_empty_list(self):
        self.assertEqual(_normalise_tags(None), [])

    def test_empty_string_returns_empty_list(self):
        self.assertEqual(_normalise_tags(""), [])

    def test_single_string_wrapped_in_list(self):
        self.assertEqual(_normalise_tags("osm"), ["osm"])

    def test_list_passthrough(self):
        self.assertEqual(_normalise_tags(["osm", "gsi"]), ["osm", "gsi"])

    def test_strips_whitespace(self):
        self.assertEqual(_normalise_tags(["  osm  ", " gsi"]), ["osm", "gsi"])

    def test_case_insensitive_dedup_preserves_first(self):
        self.assertEqual(_normalise_tags(["osm", "OSM", "Osm"]), ["osm"])

    def test_empty_list_returns_empty(self):
        self.assertEqual(_normalise_tags([]), [])

    def test_empty_strings_in_list_are_dropped(self):
        self.assertEqual(_normalise_tags(["osm", "", "  "]), ["osm"])


class TestBuildTagRegex(unittest.TestCase):
    def test_empty_list_returns_none(self):
        self.assertIsNone(_build_tag_regex([]))

    def test_single_tag(self):
        self.assertEqual(_build_tag_regex(["osm"]), "(?:osm)")

    def test_multiple_tags_joined_with_pipe(self):
        self.assertEqual(_build_tag_regex(["osm", "gsi"]), "(?:osm|gsi)")

    def test_regex_special_chars_are_escaped(self):
        self.assertEqual(_build_tag_regex(["c++"]), r"(?:c\+\+)")

    def test_three_tags(self):
        self.assertEqual(
            _build_tag_regex(["osm", "gsi", "cloud"]), "(?:osm|gsi|cloud)"
        )


def _make_authenticated_api():
    session = requests.Session()
    return DiscourseAPI(
        base_url="https://discourse.example.com",
        session=session,
        api_key="fake-key",
        api_username="fake-user",
    )


def _mock_post_response(rows=None):
    mock_response = unittest.mock.Mock()
    mock_response.raise_for_status = unittest.mock.Mock()
    mock_response.json.return_value = {
        "success": True,
        "errors": [],
        "rows": rows or [],
    }
    return mock_response


class TestGetEngagePagesByParamTagValue(unittest.TestCase):
    """
    Unit tests for the tag_value parameter of get_engage_pages_by_param.
    All HTTP calls are mocked; we assert on the serialised params sent to
    the Data Explorer endpoint.
    """

    def _call_and_capture_params(self, tag_value):
        api = _make_authenticated_api()
        with unittest.mock.patch.object(
            api.session, "post", return_value=_mock_post_response()
        ) as mock_post:
            api.get_engage_pages_by_param(category_id=51, tag_value=tag_value)
            call_kwargs = mock_post.call_args
            sent_data = (
                call_kwargs[1]["data"] if call_kwargs[1] else call_kwargs[0][1]
            )
            return json.loads(sent_data["params"])

    def test_legacy_single_string_becomes_regex(self):
        params = self._call_and_capture_params("osm")
        self.assertEqual(params["tag_value"], "(?:osm)")

    def test_multi_tag_list_becomes_alternation(self):
        params = self._call_and_capture_params(["osm", "gsi"])
        self.assertEqual(params["tag_value"], "(?:osm|gsi)")

    def test_empty_list_omits_tag_value(self):
        params = self._call_and_capture_params([])
        self.assertNotIn("tag_value", params)

    def test_none_omits_tag_value(self):
        params = self._call_and_capture_params(None)
        self.assertNotIn("tag_value", params)

    def test_duplicate_tags_are_deduped(self):
        params = self._call_and_capture_params(["osm", "OSM", "osm"])
        self.assertEqual(params["tag_value"], "(?:osm)")

    def test_single_item_list_matches_legacy_string(self):
        params_list = self._call_and_capture_params(["osm"])
        params_str = self._call_and_capture_params("osm")
        self.assertEqual(params_list["tag_value"], params_str["tag_value"])

    def test_regex_special_chars_escaped(self):
        params = self._call_and_capture_params(["c++"])
        self.assertEqual(params["tag_value"], r"(?:c\+\+)")

    def test_three_tags(self):
        params = self._call_and_capture_params(["osm", "gsi", "cloud"])
        self.assertEqual(params["tag_value"], "(?:osm|gsi|cloud)")


class TestGetEngagePagesByTagMultiTag(unittest.TestCase):
    """
    Unit tests for the tag parameter of get_engage_pages_by_tag.
    Mirrors TestGetEngagePagesByParamTagValue but exercises query 55.
    """

    def _call_and_capture_params(self, tag):
        api = _make_authenticated_api()
        with unittest.mock.patch.object(
            api.session, "post", return_value=_mock_post_response()
        ) as mock_post:
            api.get_engage_pages_by_tag(category_id=51, tag=tag)
            call_kwargs = mock_post.call_args
            sent_data = (
                call_kwargs[1]["data"] if call_kwargs[1] else call_kwargs[0][1]
            )
            return json.loads(sent_data["params"])

    def test_legacy_single_string_becomes_regex(self):
        params = self._call_and_capture_params("osm")
        self.assertEqual(params["tag"], "(?:osm)")

    def test_multi_tag_list_becomes_alternation(self):
        params = self._call_and_capture_params(["osm", "gsi"])
        self.assertEqual(params["tag"], "(?:osm|gsi)")

    def test_empty_list_omits_tag(self):
        params = self._call_and_capture_params([])
        self.assertNotIn("tag", params)

    def test_duplicate_tags_are_deduped(self):
        params = self._call_and_capture_params(["osm", "OSM", "osm"])
        self.assertEqual(params["tag"], "(?:osm)")

    def test_single_item_list_matches_legacy_string(self):
        params_list = self._call_and_capture_params(["osm"])
        params_str = self._call_and_capture_params("osm")
        self.assertEqual(params_list["tag"], params_str["tag"])

    def test_regex_special_chars_escaped(self):
        params = self._call_and_capture_params(["c++"])
        self.assertEqual(params["tag"], r"(?:c\+\+)")

    def test_three_tags(self):
        params = self._call_and_capture_params(["osm", "gsi", "cloud"])
        self.assertEqual(params["tag"], "(?:osm|gsi|cloud)")


if __name__ == "__main__":
    unittest.main()

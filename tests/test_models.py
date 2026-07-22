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


def _mock_response(status_code, json_data=None, retry_after=None):
    """
    A Mock response whose raise_for_status() behaves like a real one:
    a no-op below 400, an HTTPError (carrying this response) at/above it.
    """
    response = unittest.mock.Mock()
    response.status_code = status_code
    response.headers = {}
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=response
        )
    else:
        response.raise_for_status.return_value = None
    response.json.return_value = json_data
    return response


class TestRateLimitRetry(unittest.TestCase):
    """
    Every request blocks and retries on HTTP 429, honouring Discourse's
    Retry-After header, until it succeeds or max_rate_limit_retries is
    exhausted.
    """

    def _make_api(self, **kwargs):
        session = unittest.mock.Mock()
        api = DiscourseAPI(
            base_url="https://discourse.example.com",
            session=session,
            **kwargs,
        )
        return api, session

    @unittest.mock.patch("canonicalwebteam.discourse.models.time.sleep")
    def test_blocks_and_retries_until_success(self, mock_sleep):
        api, session = self._make_api()
        session.get.side_effect = [
            _mock_response(429, retry_after=5),
            _mock_response(429, retry_after=7),
            _mock_response(200, json_data={"id": 1, "title": "Retried"}),
        ]

        topic = api.get_topic(1)

        self.assertEqual(topic, {"id": 1, "title": "Retried"})
        self.assertEqual(session.get.call_count, 3)
        mock_sleep.assert_has_calls(
            [unittest.mock.call(5), unittest.mock.call(7)]
        )

    @unittest.mock.patch("canonicalwebteam.discourse.models.time.sleep")
    def test_falls_back_to_default_retry_after_when_header_missing(
        self, mock_sleep
    ):
        api, session = self._make_api()
        session.get.side_effect = [
            _mock_response(429),
            _mock_response(200, json_data={"id": 1}),
        ]

        api.get_topic(1)

        mock_sleep.assert_called_once_with(60)

    @unittest.mock.patch("canonicalwebteam.discourse.models.time.sleep")
    def test_retry_after_is_capped(self, mock_sleep):
        api, session = self._make_api()
        session.get.side_effect = [
            _mock_response(429, retry_after=99999),
            _mock_response(200, json_data={"id": 1}),
        ]

        api.get_topic(1)

        mock_sleep.assert_called_once_with(600)

    @unittest.mock.patch("canonicalwebteam.discourse.models.time.sleep")
    def test_gives_up_after_max_rate_limit_retries(self, mock_sleep):
        api, session = self._make_api(max_rate_limit_retries=2)
        session.get.return_value = _mock_response(429, retry_after=1)

        with self.assertRaises(requests.exceptions.HTTPError):
            api.get_topic(1)

        # 1 initial attempt + 2 retries, then give up
        self.assertEqual(session.get.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_zero_retries_fails_immediately_without_sleeping(self):
        api, session = self._make_api(max_rate_limit_retries=0)
        session.get.return_value = _mock_response(429)

        with self.assertRaises(requests.exceptions.HTTPError):
            api.get_topic(1)

        session.get.assert_called_once()


class TestFreshnessProbeThrottle(unittest.TestCase):
    """
    Freshness probes (get_topics_last_activity_time /
    get_categories_last_activity_time) are memoised for
    freshness_probe_ttl seconds, so a burst of renders issues at most one
    probe per key instead of one per render against the shared rate limit.
    """

    def _make_api(self, **kwargs):
        session = unittest.mock.Mock()
        api = DiscourseAPI(
            base_url="https://discourse.example.com",
            session=session,
            api_key="key",
            api_username="user",
            **kwargs,
        )
        return api, session

    @unittest.mock.patch("canonicalwebteam.discourse.models.time.monotonic")
    def test_topic_probe_is_memoised_within_ttl(self, mock_monotonic):
        mock_monotonic.return_value = 1000.0
        api, session = self._make_api(freshness_probe_ttl=60)
        session.post.return_value = _mock_response(
            200, json_data={"rows": [["2024-01-01", 42]]}
        )

        first = api.get_topics_last_activity_time(7)
        second = api.get_topics_last_activity_time(7)

        self.assertEqual(first, [["2024-01-01", 42]])
        self.assertEqual(second, first)
        # Second render served from the memo, not a fresh probe
        self.assertEqual(session.post.call_count, 1)

    @unittest.mock.patch("canonicalwebteam.discourse.models.time.monotonic")
    def test_topic_probe_refetched_after_ttl_expires(self, mock_monotonic):
        api, session = self._make_api(freshness_probe_ttl=60)
        session.post.return_value = _mock_response(
            200, json_data={"rows": [["2024-01-01", 42]]}
        )

        mock_monotonic.return_value = 1000.0
        api.get_topics_last_activity_time(7)
        mock_monotonic.return_value = 1061.0  # 61s later, past the 60s TTL
        api.get_topics_last_activity_time(7)

        self.assertEqual(session.post.call_count, 2)

    @unittest.mock.patch("canonicalwebteam.discourse.models.time.monotonic")
    def test_category_probe_is_memoised_within_ttl(self, mock_monotonic):
        mock_monotonic.return_value = 1000.0
        api, session = self._make_api(freshness_probe_ttl=60)
        session.post.return_value = _mock_response(
            200, json_data={"rows": [["2024-02-02", 7]]}
        )

        api.get_categories_last_activity_time(11)
        api.get_categories_last_activity_time(11)

        self.assertEqual(session.post.call_count, 1)

    @unittest.mock.patch("canonicalwebteam.discourse.models.time.monotonic")
    def test_throttle_is_per_key(self, mock_monotonic):
        mock_monotonic.return_value = 1000.0
        api, session = self._make_api(freshness_probe_ttl=60)
        session.post.return_value = _mock_response(
            200, json_data={"rows": [["2024-01-01", 42]]}
        )

        api.get_topics_last_activity_time(7)
        api.get_topics_last_activity_time(8)
        api.get_categories_last_activity_time(7)

        # Two distinct topics and a category share no memo entry
        self.assertEqual(session.post.call_count, 3)

    @unittest.mock.patch("canonicalwebteam.discourse.models.time.monotonic")
    def test_ttl_zero_disables_the_throttle(self, mock_monotonic):
        mock_monotonic.return_value = 1000.0
        api, session = self._make_api(freshness_probe_ttl=0)
        session.post.return_value = _mock_response(
            200, json_data={"rows": [["2024-01-01", 42]]}
        )

        api.get_topics_last_activity_time(7)
        api.get_topics_last_activity_time(7)

        # No memoisation: every render probes
        self.assertEqual(session.post.call_count, 2)

    @unittest.mock.patch("canonicalwebteam.discourse.models.time.monotonic")
    def test_failed_probe_is_not_memoised(self, mock_monotonic):
        mock_monotonic.return_value = 1000.0
        api, session = self._make_api(freshness_probe_ttl=60)
        # First probe errors, second succeeds; the failure must not latch
        session.post.side_effect = [
            _mock_response(500),
            _mock_response(200, json_data={"rows": [["2024-01-01", 42]]}),
        ]

        with self.assertRaises(requests.exceptions.HTTPError):
            api.get_topics_last_activity_time(7)
        result = api.get_topics_last_activity_time(7)

        self.assertEqual(result, [["2024-01-01", 42]])
        self.assertEqual(session.post.call_count, 2)


if __name__ == "__main__":
    unittest.main()

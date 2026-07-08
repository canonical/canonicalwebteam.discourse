# Standard library
import unittest
from unittest.mock import Mock

# Packages
import requests

# Local
from canonicalwebteam.discourse.models import DiscourseAPI


def _response(json_data, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


def _make_api(session, authenticated_reads=True):
    return DiscourseAPI(
        base_url="https://discourse.example.com",
        session=session,
        api_key="key",
        api_username="user",
        authenticated_reads=authenticated_reads,
    )


class TestAuthenticatedReadsDefault(unittest.TestCase):
    """
    Default behaviour is unchanged: credentials are attached to the
    session, so every request is authenticated.
    """

    def test_default_sets_session_headers(self):
        session = requests.Session()
        _make_api(session)

        self.assertEqual(session.headers.get("Api-Key"), "key")
        self.assertEqual(session.headers.get("Api-Username"), "user")


class TestAnonymousReads(unittest.TestCase):
    """
    With authenticated_reads=False, public GET endpoints are anonymous
    (they don't count against the shared admin API quota and become
    proxy-cacheable) while Data Explorer requests stay authenticated.
    """

    def test_session_headers_are_not_modified(self):
        session = requests.Session()
        _make_api(session, authenticated_reads=False)

        self.assertNotIn("Api-Key", session.headers)
        self.assertNotIn("Api-Username", session.headers)

    def test_get_topic_sends_no_auth_headers(self):
        session = Mock()
        session.get.return_value = _response({"id": 5})
        api = _make_api(session, authenticated_reads=False)

        api.get_topic(5)

        self.assertNotIn("headers", session.get.call_args.kwargs)

    def test_get_topics_authenticates_the_data_explorer_call(self):
        session = Mock()
        session.post.return_value = _response({"rows": [["cooked"]]})
        api = _make_api(session, authenticated_reads=False)

        api.get_topics([1, 2])

        headers = session.post.call_args.kwargs["headers"]
        self.assertEqual(headers.get("Api-Key"), "key")
        self.assertEqual(headers.get("Api-Username"), "user")

    def test_topic_list_by_category_authenticates(self):
        session = Mock()
        session.post.return_value = _response(
            {"columns": ["id"], "rows": [[1]]}
        )
        api = _make_api(session, authenticated_reads=False)

        api.get_topic_list_by_category(5)

        headers = session.post.call_args.kwargs["headers"]
        self.assertEqual(headers.get("Api-Key"), "key")

    def test_engage_pages_by_param_authenticates(self):
        session = Mock()
        session.post.return_value = _response(
            {"success": True, "rows": [["row"]]}
        )
        api = _make_api(session, authenticated_reads=False)

        api.get_engage_pages_by_param(category_id=51, key="path", value="/x")

        headers = session.post.call_args.kwargs["headers"]
        self.assertEqual(headers.get("Api-Key"), "key")

    def test_engage_pages_by_tag_authenticates(self):
        session = Mock()
        session.post.return_value = _response(
            {"success": True, "rows": [["row"]]}
        )
        api = _make_api(session, authenticated_reads=False)

        api.get_engage_pages_by_tag(category_id=51, tag="events")

        headers = session.post.call_args.kwargs["headers"]
        self.assertEqual(headers.get("Api-Key"), "key")

    def test_activity_probes_authenticate(self):
        session = Mock()
        session.post.return_value = _response({"rows": [[1, "2026-07-08"]]})
        api = _make_api(session, authenticated_reads=False)

        api.get_topics_last_activity_time(1)
        headers = session.post.call_args.kwargs["headers"]
        self.assertEqual(headers.get("Api-Key"), "key")

        api.get_categories_last_activity_time(1)
        headers = session.post.call_args.kwargs["headers"]
        self.assertEqual(headers.get("Api-Key"), "key")


if __name__ == "__main__":
    unittest.main()

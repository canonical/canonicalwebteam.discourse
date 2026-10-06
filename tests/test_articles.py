import json
import unittest

import httpretty
import requests

from canonicalwebteam.discourse import Articles, DiscourseAPI, ResponseCache

BASE_URL = "https://discourse.example.com"
TAG_URL = f"{BASE_URL}/tag/developer-diaries.json"


def _topic(topic_id, slug, created_at, tags, user_id=1, **extra):
    return {
        "id": topic_id,
        "title": slug.replace("-", " ").title(),
        "slug": slug,
        "created_at": created_at,
        "tags": tags,
        "image_url": f"https://example.com/{slug}.png",
        "like_count": 20,
        "op_like_count": 3,
        "visible": True,
        "archetype": "regular",
        "posters": [
            {"description": "Frequent Poster", "user_id": 2},
            {"description": "Original Poster", "user_id": user_id},
        ],
        **extra,
    }


USERS = [
    {
        "id": 1,
        "username": "jdoe",
        "name": "Jane Doe",
        "avatar_template": "/user_avatar/example/jdoe/{size}/1.png",
    },
    {
        "id": 2,
        "username": "nameless",
        "name": "",
        "avatar_template": "/user_avatar/example/x/{size}/2.png",
    },
]

TAG_PAGES = {
    "0": {
        "users": USERS,
        "topic_list": {
            "more_topics_url": "/tag/developer-diaries?page=1",
            "topics": [
                _topic(
                    11, "older", "2025-01-01T10:00:00.000Z", ["blog", "rocks"]
                ),
                _topic(
                    12,
                    "newest",
                    "2026-06-30T10:00:00.000Z",
                    ["developer-diaries", "Snaps", "featured"],
                    user_id=2,
                ),
                _topic(
                    13,
                    "unlisted",
                    "2026-07-01T10:00:00.000Z",
                    ["rocks"],
                    visible=False,
                ),
            ],
        },
    },
    "1": {
        "users": USERS,
        "topic_list": {
            "topics": [
                _topic(14, "middle", "2026-01-01T10:00:00.000Z", ["charms"]),
                _topic(15, "excluded", "2026-02-01T10:00:00.000Z", []),
            ],
        },
    },
}

COOKED = (
    "<p>First   paragraph with <a href='/t/other/99'>a link</a>.</p>"
    '<h2><a name="p-1-intro-1" class="anchor" href="#p-1-intro-1"></a>'
    "<strong>Intro</strong></h2>"
    "<p>one two three four</p>"
    "<h3>Details</h3>"
    "<pre><code>these words are code and not read</code></pre>"
    "<h3>Details</h3>"
    "<h2>Outro</h2>"
)


def _tag_page(request, uri, response_headers):
    page = request.querystring.get("page", ["0"])[0]
    return [200, response_headers, json.dumps(TAG_PAGES[page])]


class TestArticles(unittest.TestCase):
    def setUp(self):
        httpretty.enable()
        httpretty.register_uri(httpretty.GET, TAG_URL, body=_tag_page)
        httpretty.register_uri(
            httpretty.GET,
            f"{BASE_URL}/t/12.json",
            body=json.dumps(
                {
                    **TAG_PAGES["0"]["topic_list"]["topics"][1],
                    "post_stream": {
                        "posts": [
                            {
                                "cooked": COOKED,
                                "username": "jdoe",
                                "name": "Jane Doe",
                                "avatar_template": USERS[0]["avatar_template"],
                                "updated_at": "2026-07-01T10:00:00.000Z",
                                "actions_summary": [
                                    {"id": 6, "count": 1},
                                    {"id": 2, "count": 9},
                                ],
                            }
                        ]
                    },
                }
            ),
        )
        httpretty.register_uri(
            httpretty.GET, f"{BASE_URL}/t/14.json", status=404
        )

        self.api = DiscourseAPI(
            base_url=f"{BASE_URL}/", session=requests.Session()
        )
        self.articles = Articles(
            api=self.api,
            tag="developer-diaries",
            url_prefix="/community/developer-diaries",
            hidden_tags=["blog", "Featured"],
            exclude_topics=[15],
            words_per_minute=1,
        )

    def tearDown(self):
        httpretty.disable()
        httpretty.reset()

    def test_index_lists_visible_topics_across_pages_newest_first(self):
        articles, total = self.articles.get_index()

        self.assertEqual(total, 3)
        self.assertEqual(
            [article["slug"] for article in articles],
            ["newest", "middle", "older"],
        )

    def test_index_summary_fields(self):
        articles, _ = self.articles.get_index()
        newest, _, older = articles

        self.assertEqual(newest["path"], "/community/developer-diaries/newest")
        self.assertEqual(newest["image"], "https://example.com/newest.png")
        self.assertEqual(newest["tags"], ["Snaps"])
        self.assertEqual(older["tags"], ["rocks"])
        self.assertEqual(newest["likes"], 3)
        self.assertEqual(newest["created"].year, 2026)
        self.assertEqual(newest["forum_url"], f"{BASE_URL}/t/newest/12")
        # Falls back to the username when the user has no name
        self.assertEqual(newest["author"]["name"], "nameless")
        self.assertEqual(
            older["author"],
            {
                "name": "Jane Doe",
                "username": "jdoe",
                "avatar_url": f"{BASE_URL}/user_avatar/example/jdoe/96/1.png",
                "url": f"{BASE_URL}/u/jdoe",
            },
        )

    def test_index_limit_and_offset(self):
        articles, total = self.articles.get_index(limit=1, offset=1)

        self.assertEqual(total, 3)
        self.assertEqual([article["slug"] for article in articles], ["middle"])

    def test_index_tag_filter_matches_any_tag_case_insensitively(self):
        articles, total = self.articles.get_index(tags=["snaps", "CHARMS"])

        self.assertEqual(total, 2)
        self.assertEqual(
            [article["slug"] for article in articles], ["newest", "middle"]
        )

    def test_index_tag_filter_matches_hidden_tags(self):
        articles, _ = self.articles.get_index(tags="featured")

        self.assertEqual([article["slug"] for article in articles], ["newest"])

    def test_max_pages_caps_the_listing(self):
        self.articles.max_pages = 1

        _, total = self.articles.get_index()

        self.assertEqual(total, 2)

    def test_get_article(self):
        article = self.articles.get_article("newest")

        self.assertEqual(article["id"], 12)
        self.assertEqual(article["title"], "Newest")
        self.assertEqual(article["tags"], ["Snaps"])
        self.assertEqual(article["likes"], 9)
        self.assertEqual(article["author"]["name"], "Jane Doe")
        self.assertEqual(article["updated"].month, 7)
        self.assertEqual(article["excerpt"], "First paragraph with a link.")

    def test_get_article_navigation_from_headings(self):
        article = self.articles.get_article("newest")

        self.assertEqual(
            article["navigation"],
            [
                {
                    "id": "p-1-intro",
                    "text": "Intro",
                    "children": [
                        {"id": "details", "text": "Details", "children": []},
                        {
                            "id": "details-2",
                            "text": "Details",
                            "children": [],
                        },
                    ],
                },
                {"id": "outro", "text": "Outro", "children": []},
            ],
        )
        self.assertIn('<h2 id="p-1-intro">', article["body_html"])
        self.assertIn('<h3 id="details-2">', article["body_html"])
        self.assertNotIn('name="p-1-intro', article["body_html"])

    def test_get_article_read_time_skips_code(self):
        article = self.articles.get_article("newest")

        # 13 words of prose at 1 word per minute; the code is skipped
        self.assertEqual(article["read_time"], 13)

    def test_get_article_unknown_slug(self):
        self.assertIsNone(self.articles.get_article("not-an-article"))

    def test_get_article_hidden_or_excluded_topic(self):
        self.assertIsNone(self.articles.get_article("unlisted"))
        self.assertIsNone(self.articles.get_article("excluded"))

    def test_get_article_deleted_topic(self):
        self.assertIsNone(self.articles.get_article("middle"))


class TestGetTopicListByTag(unittest.TestCase):
    def setUp(self):
        httpretty.enable()
        httpretty.register_uri(httpretty.GET, TAG_URL, body=_tag_page)

    def tearDown(self):
        httpretty.disable()
        httpretty.reset()

    def test_requests_the_given_page(self):
        api = DiscourseAPI(base_url=BASE_URL, session=requests.Session())

        response = api.get_topic_list_by_tag("developer-diaries", page=1)

        self.assertEqual(response, TAG_PAGES["1"])
        self.assertEqual(httpretty.last_request().querystring, {"page": ["1"]})

    def test_pages_are_cached_separately(self):
        api = DiscourseAPI(
            base_url=BASE_URL,
            session=requests.Session(),
            cache=ResponseCache(),
        )

        api.get_topic_list_by_tag("developer-diaries", page=0)
        api.get_topic_list_by_tag("developer-diaries", page=0)
        api.get_topic_list_by_tag("developer-diaries", page=1)

        self.assertEqual(len(httpretty.latest_requests()), 2)
